"""0.5.2 synthetic source-ID regressions. No real issuers, keys or network calls.

The original incident's response text was NOT retained. These fixtures reproduce
its exact validation paths/types, not the unseen provider body or factual content.
"""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main
from app.outlook import (CatalystDocument, RiskDocument, OUTLOOK_VERSION,
                         normalize_source_labels, outlook_request_body, parse_outlook)
from app.outlook_diagnostics import safe_diagnostic
from app.research import ResearchError, ResearchService
from test_outlook import context, document, raw, source


def long_document(scope='catalysts', count=5):
    d = document(scope)
    # Same first 30 characters: naïve truncation would collapse distinct sources.
    ids = ['synthetic_document_identifier_shared_prefix_' + str(i) + '_reference_for_report' for i in range(count)]
    d['sources'] = [source(sid, 'https://issuer.example/source/' + str(i)) for i, sid in enumerate(ids)]
    d['identity']['source_ids'] = ids[:2]
    for index, entry in enumerate(d['coverage']):
        entry['source_ids'] = [ids[index % count]]
    d[scope][0]['source_ids'] = ids[:]
    if scope == 'catalysts':
        d[scope][0]['date_source_ids'] = ids[-2:]
    return d


def replace_first_id(d, new):
    old = d['sources'][0]['id']
    def walk(x):
        if isinstance(x, dict):
            return {k: ([new if r == old else r for r in v] if k in {'source_ids', 'date_source_ids'} and isinstance(v, list) else walk(v)) for k, v in x.items()}
        if isinstance(x, list):return [walk(v) for v in x]
        return x
    out = walk(d)
    out['sources'][0]['id'] = new
    return out


class SourceLabelRegressionTests(unittest.TestCase):
    def parsed(self, d=None, scope='catalysts', **kwargs):
        return parse_outlook(raw(d if d is not None else long_document(scope), scope=scope, **kwargs), scope, context())

    def test_reproduces_exact_five_reported_length_errors_before_normalization(self):
        with self.assertRaises(ValidationError) as e:
            CatalystDocument.model_validate(long_document())
        errors = e.exception.errors(include_url=False, include_input=False)
        self.assertEqual([(x['loc'], x['type']) for x in errors],
                         [(('sources', i, 'id'), 'string_too_long') for i in range(5)])

    def test_five_long_ids_accepted_and_every_source_link_preserved(self):
        d = long_document(); r = self.parsed(d)
        self.assertEqual(len(r['sources']), 5)
        self.assertEqual(len(r['items']), 1)
        self.assertEqual(r['response_processing']['normalized_source_ids'], 5)
        self.assertEqual(r['response_processing']['source_reference_rewrites'], 13)
        for before, after in zip(d['sources'], r['sources']):
            self.assertEqual(before['url'], after['url'])
            self.assertEqual(before['title'], after['title'])
            self.assertLessEqual(len(after['id']), 30)
        by_id = {s['id']: s['url'] for s in r['sources']}
        self.assertEqual([by_id[x] for x in r['items'][0]['source_ids']], [s['url'] for s in d['sources']])
        self.assertEqual([by_id[x] for x in r['items'][0]['date_source_ids']], [s['url'] for s in d['sources'][-2:]])
        self.assertEqual([by_id[x] for x in r['identity']['source_ids']], [s['url'] for s in d['sources'][:2]])
        for i, c in enumerate(r['coverage']):
            self.assertEqual(by_id[c['source_ids'][0]], d['sources'][i]['url'])

    def test_risk_references_rekeyed_and_loss_warning_retained(self):
        d = long_document('risks'); r = self.parsed(d, 'risks')
        self.assertEqual(len(r['items'][0]['source_ids']), 5)
        self.assertEqual(r['items'][0]['fact'], d['risks'][0]['fact'])
        self.assertIn('확정 손실과 다릅니다', r['items'][0]['mandatory_amount_notice'])

    def test_shared_first_thirty_characters_do_not_collide(self):
        d = long_document(); self.assertEqual(len({s['id'][:30] for s in d['sources']}), 1)
        self.assertEqual(len({s['id'] for s in self.parsed(d)['sources']}), 5)

    def test_short_existing_label_cannot_collide_with_new_alias(self):
        d = long_document(); d['sources'].append(source('sdsrc1', 'https://issuer.example/short'))
        r = self.parsed(d); self.assertEqual(len({s['id'] for s in r['sources']}), 6)
        by_id = {s['id']: s['url'] for s in r['sources']}
        self.assertEqual(by_id['sdsrc1'], 'https://issuer.example/short')

    def test_dangling_short_reference_never_accidentally_becomes_linked(self):
        d = long_document(); d['catalysts'][0]['source_ids'] = ['sdsrc1']
        r = self.parsed(d)
        self.assertNotIn('sdsrc1', {s['id'] for s in r['sources']})
        self.assertEqual(r['items'], []); self.assertEqual(r['excluded_item_count'], 1)

    def test_unknown_long_reference_not_guessed_by_prefix(self):
        d = long_document(); d['catalysts'][0]['source_ids'] = [d['sources'][0]['id'] + '_DIFFERENT']
        self.assertEqual(self.parsed(d)['items'], [])

    def test_reference_matching_is_case_sensitive(self):
        d = long_document(); d['catalysts'][0]['source_ids'] = [d['sources'][0]['id'].upper()]
        self.assertEqual(self.parsed(d)['items'], [])

    def test_missing_date_reference_still_downgrades_timing(self):
        d = long_document(); d['catalysts'][0]['date_source_ids'] = ['sdsrc1']
        c = self.parsed(d)['items'][0]
        self.assertEqual(c['timing'], 'UNCONFIRMED'); self.assertIsNone(c['event_date'])

    def test_duplicate_original_long_ids_still_rejected(self):
        d = long_document(); d['sources'][1]['id'] = d['sources'][0]['id']
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertEqual(e.exception.code, 'OUTLOOK_SOURCE_IDS')

    def test_duplicate_original_even_when_first_url_untrusted_still_rejected(self):
        d = long_document(); d['sources'][1]['id'] = d['sources'][0]['id']; d['sources'][0]['url'] = 'https://unlinked.example/a'
        with self.assertRaises(ResearchError) as e:self.parsed(d, tool_urls=[s['url'] for s in d['sources'][1:]])
        self.assertEqual(e.exception.code, 'OUTLOOK_SOURCE_IDS')

    def test_limits_thirty_thirtyone_and_fourthousand(self):
        for length in (30, 31, 4096):
            with self.subTest(length=length):
                d = replace_first_id(document(), 'x' * length); r = self.parsed(d)
                self.assertEqual(len(r['items']), 1)
                self.assertEqual(r['response_processing']['normalized_source_ids'], int(length > 30))
                if length == 30:self.assertEqual(r['sources'][0]['id'], 'x' * length)

    def test_huge_id_rejected_without_echoing_value(self):
        d = replace_first_id(document(), 'PRIVATE_SENTINEL_' + 'x' * 4096)
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertEqual(e.exception.code, 'OUTLOOK_SOURCE_IDS')
        self.assertNotIn('PRIVATE_SENTINEL', e.exception.message)

    def test_missing_null_number_list_ids_not_coerced(self):
        for value in (None, 3, ['s1'], {'id': 's1'}):
            with self.subTest(value=value):
                d = long_document(); d['sources'][0]['id'] = value
                with self.assertRaises(ResearchError) as e:self.parsed(d)
                self.assertEqual(e.exception.code, 'OUTLOOK_SCHEMA')
        d = long_document(); del d['sources'][0]['id']
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertIn('sources.0.id:missing', e.exception.message)

    def test_blank_ids_not_invented(self):
        for value in ('', '   ', '\t\n'):
            with self.subTest(value=repr(value)):
                d = replace_first_id(document(), value)
                with self.assertRaises(ResearchError) as e:self.parsed(d)
                self.assertEqual(e.exception.code, 'OUTLOOK_SOURCE_IDS')

    def test_opaque_unicode_and_url_identifiers_are_exactly_rekeyed(self):
        for label in ('공식자료의긴식별자' * 20, 'https://issuer.example/reports/long/document/id-not-url-field'):
            with self.subTest(label=label):
                d = replace_first_id(document(), label); r = self.parsed(d)
                self.assertEqual(r['items'][0]['source_ids'], [r['sources'][0]['id']])
                self.assertEqual(r['sources'][0]['url'], d['sources'][0]['url'])

    def test_all_fact_date_title_url_strings_unchanged_even_if_equal_to_id(self):
        d = long_document(); label = d['sources'][0]['id']
        d['catalysts'][0]['fact'] = label; d['sources'][0]['title'] = label; d['unresolved'] = [label]
        out, _ = normalize_source_labels(d, 'catalysts')
        stripped = copy.deepcopy(out)
        back = {s['id']: before['id'] for s, before in zip(out['sources'], d['sources'])}
        def restore(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in {'source_ids', 'date_source_ids'} and isinstance(v, list):x[k] = [back.get(r, r) for r in v]
                    else:restore(v)
            elif isinstance(x, list):
                for v in x:restore(v)
        restore(stripped)
        for s in stripped['sources']:s['id'] = back[s['id']]
        self.assertEqual(stripped, d)

    def test_raw_response_and_input_document_not_mutated(self):
        d = long_document(); before = copy.deepcopy(d)
        normalize_source_labels(d, 'catalysts'); self.assertEqual(d, before)
        envelope = raw(d); saved = copy.deepcopy(envelope)
        parse_outlook(envelope, 'catalysts', context()); self.assertEqual(envelope, saved)

    def test_short_legacy_ids_unchanged(self):
        d = document(); out, stats = normalize_source_labels(d, 'catalysts')
        self.assertEqual(out, d); self.assertEqual(stats['normalized_source_ids'], 0)

    def test_invalid_reference_types_still_fail_schema(self):
        for value in ('s1', None, [42], [{'bad': 'type'}]):
            with self.subTest(value=value):
                d = long_document(); d['catalysts'][0]['source_ids'] = value
                with self.assertRaises(ResearchError) as e:self.parsed(d)
                self.assertEqual(e.exception.code, 'OUTLOOK_SCHEMA')

    def test_missing_field_and_overlong_research_prose_not_repaired(self):
        d = long_document(); del d['catalysts'][0]['watch']
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertIn('watch:missing', e.exception.message)
        d = long_document(); d['catalysts'][0]['fact'] = 'x' * 400
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertIn('fact:string_too_long', e.exception.message)
        self.assertEqual(e.exception.outlook_diagnostics['normalized_source_ids'], 5)

    def test_no_source_or_list_cardinality_forgiveness(self):
        d = long_document(); d['sources'] = [source('id' + str(i)) for i in range(25)]
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertEqual(e.exception.code, 'OUTLOOK_SCHEMA')

    def test_bad_date_ticker_and_provenance_checks_still_run(self):
        d = long_document(); d['catalysts'][0]['event_date'] = '2026-08-01'
        self.assertEqual(self.parsed(d)['items'], [])
        d = long_document(); d['symbol'] = 'OTHER'
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertEqual(e.exception.code, 'OUTLOOK_SYMBOL')
        with self.assertRaises(ResearchError) as e:self.parsed(tool_urls=['https://unrelated.example/source'])
        self.assertEqual(e.exception.code, 'OUTLOOK_IDENTITY')

    def test_future_publications_and_unsafe_urls_still_excluded(self):
        d = long_document()
        for s in d['sources']:s['published_date'] = '2027-01-01'
        with self.assertRaises(ResearchError) as e:self.parsed(d)
        self.assertEqual(e.exception.code, 'OUTLOOK_IDENTITY')
        d = long_document()
        for s in d['sources']:s['url'] = 'http://127.0.0.1/private'
        with self.assertRaises(ResearchError):self.parsed(d)

    def test_no_response_retry_or_budget_increase_in_request_shape(self):
        for scope in ('catalysts', 'risks'):
            b = outlook_request_body(context(), scope, 'gpt-5-mini')
            self.assertEqual(b['max_tool_calls'], 6); self.assertEqual(b['max_output_tokens'], 10000)
            self.assertTrue(b['text']['format']['strict']); self.assertFalse(b['store'])
            self.assertIn('short UNIQUE LOCAL labels s1, s2, s3', b['instructions'])
            self.assertEqual(b['text']['format']['schema']['$defs']['Source']['properties']['id']['maxLength'], 30)

    def test_safe_diagnostic_counts_only_not_id_contents(self):
        d = long_document(); d['catalysts'][0]['fact'] = 'x' * 400; envelope = raw(d)
        with self.assertRaises(ResearchError) as e:parse_outlook(envelope, 'catalysts', context())
        diag = safe_diagnostic(envelope, e.exception, 'catalysts')
        self.assertEqual(diag['normalized_source_ids'], 5)
        self.assertNotIn(d['sources'][0]['id'], json.dumps(diag)); self.assertNotIn('https:', json.dumps(diag))


class SourceLabelAPIRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root / '.env.signaldesk').write_text('OPENAI_API_KEY=sk-offline-fixture-' + 'x' * 30)
        self.service = ResearchService(self.root)
        self.ctx = patch.object(self.service, 'outlook_context', return_value=context()); self.ctx.start()
        self.service_patch = patch.object(main, 'research', self.service); self.service_patch.start()
        self.client = TestClient(main.app)
        self.headers = {'X-SignalDesk-AI': self.service.csrf_token}

    def tearDown(self):
        self.client.close(); self.service_patch.stop(); self.ctx.stop(); self.tmp.cleanup()

    def post(self, scope='catalysts', consent=True):
        return self.client.post('/api/v1/ai/outlook/analyze', headers=self.headers,
                                json={'snapshot_id': 'x' * 24, 'scope': scope, 'allow_paid': consent})

    def test_five_long_ids_full_endpoint_returns_200_with_one_mocked_call(self):
        with patch('app.research.call_openai', return_value=raw(long_document())) as call:
            res = self.post(); self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(len(res.json()['items']), 1); self.assertEqual(call.call_count, 1)
            self.assertEqual(res.json()['parser_version'], '0.5.2')
            self.assertEqual(res.json()['response_processing']['normalized_source_ids'], 5)
            self.assertFalse(self.service.status()['busy'])

    def test_risks_endpoint_200_and_each_scope_requires_only_one_call(self):
        with patch('app.research.call_openai', side_effect=[raw(long_document()), raw(long_document('risks'), scope='risks')]) as call:
            self.assertEqual(self.post().status_code, 200)
            self.assertEqual(self.post('risks').status_code, 200)
            self.assertEqual(call.call_count, 2)

    def test_cached_result_and_status_make_no_additional_provider_call(self):
        with patch('app.research.call_openai', return_value=raw(long_document())) as call:
            first = self.post(); second = self.post()
            self.assertEqual(first.status_code, 200); self.assertEqual(second.status_code, 200)
            self.assertTrue(second.json()['cache_hit']); self.assertEqual(call.call_count, 1)
            self.assertEqual(self.client.get('/api/v1/ai/status').status_code, 200)
            self.assertEqual(call.call_count, 1); self.assertEqual(OUTLOOK_VERSION, 'outlook-v0.5.0')

    def test_missing_consent_sends_no_provider_call(self):
        with patch('app.research.call_openai') as call:
            self.assertEqual(self.post(consent=False).status_code, 400); call.assert_not_called()

    def test_other_invalid_result_not_retried_and_not_cached(self):
        d = long_document(); del d['catalysts'][0]['watch']
        with patch('app.research.call_openai', return_value=raw(d)) as call, redirect_stdout(io.StringIO()):
            res = self.post(); self.assertEqual(res.status_code, 502)
            self.assertEqual(res.json()['error']['code'], 'OUTLOOK_SCHEMA'); self.assertEqual(call.call_count, 1)
            self.assertFalse(self.service.status()['busy'])
            self.assertIsNone(self.service.cached_outlook('x' * 24)['reports']['catalysts'])
            self.assertNotIn('sk-offline', res.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
