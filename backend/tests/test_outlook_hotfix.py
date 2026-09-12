"""0.5.1 regression fixtures: no network, no real issuer claims, no paid requests."""
from __future__ import annotations
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

from test_outlook import context, raw, document
from test_price_context import snapshot
from app.outlook import parse_outlook, OUTLOOK_VERSION, OUTLOOK_PARSER_VERSION
from app.outlook_diagnostics import record_failure, safe_diagnostic
from app.research import ResearchError, ResearchService


def message(text='공식 자료를 찾아보겠습니다.', phase='commentary', status='completed'):
    m={'type':'message','role':'assistant','status':status,'content':[{'type':'output_text','text':text,'annotations':[]}]}
    if phase is not None:m['phase']=phase
    return m


def with_commentary(scope='catalysts'):
    r=raw(scope=scope);r['output'].insert(0,message());r['output'][-1]['phase']='final_answer'
    return r


class OutlookFinalSelectionTests(unittest.TestCase):
    def test_progress_plus_final_json_is_not_concatenated(self):
        r=parse_outlook(with_commentary(),'catalysts',context())
        self.assertEqual(len(r['items']),1);self.assertEqual(r['parser_version'],'0.5.2')
        self.assertEqual(r['response_processing']['ignored_messages'],1)
    def test_risks_progress_plus_final_supported(self):
        r=parse_outlook(with_commentary('risks'),'risks',context());self.assertEqual(len(r['items']),1)
    def test_unphased_progress_before_search_is_ignored(self):
        r=raw();r['output'].insert(0,message(phase=None))
        self.assertEqual(len(parse_outlook(r,'catalysts',context())['items']),1)
    def test_unphased_progress_after_search_uses_last_answer_only(self):
        r=raw();r['output'].insert(1,message(phase=None))
        self.assertEqual(len(parse_outlook(r,'catalysts',context())['items']),1)
    def test_final_body_text_parts_join_without_newline_insertion(self):
        r=raw();p=r['output'][-1]['content'][0];text=p['text'];mid=text.index('Example')+3
        r['output'][-1]['content']=[{**p,'text':text[:mid]},{**p,'text':text[mid:]}]
        self.assertEqual(parse_outlook(r,'catalysts',context())['identity']['name'],'Example Company (Synthetic)')
    def test_trailing_commentary_does_not_replace_final(self):
        r=with_commentary();r['output'].append(message('표시를 마칩니다.'))
        self.assertEqual(len(parse_outlook(r,'catalysts',context())['items']),1)
    def test_only_commentary_is_not_report(self):
        r=raw();r['output'][-1]['phase']='commentary'
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_NO_FINAL')
    def test_no_final_after_last_tool_is_not_stale_report(self):
        r=raw();r['output'].append(copy.deepcopy(r['output'][0]))
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_NO_FINAL')
    def test_two_explicit_finals_rejected(self):
        r=with_commentary();r['output'].append(copy.deepcopy(r['output'][-1]))
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_AMBIGUOUS_FINAL')
    def test_later_malformed_final_does_not_use_earlier_valid_draft(self):
        r=raw();r['output'].append(message('truncated {',phase=None))
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_JSON')
    def test_unlabeled_answer_after_explicit_final_is_ambiguous(self):
        r=with_commentary();r['output'].append(message('{}',phase=None))
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_AMBIGUOUS_FINAL')
    def test_partial_message_rejected_even_if_envelope_complete(self):
        r=raw();r['output'][-1]['status']='incomplete'
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'AI_INCOMPLETE')
    def test_bom_only_removed(self):
        r=raw();r['output'][-1]['content'][0]['text']='\ufeff'+r['output'][-1]['content'][0]['text']
        self.assertEqual(len(parse_outlook(r,'catalysts',context())['items']),1)
    def test_whole_json_code_fence_unwrapped_without_changing_fields(self):
        r=raw();p=r['output'][-1]['content'][0];p['text']='```json\n'+p['text']+'\n```'
        a=parse_outlook(r,'catalysts',context());self.assertEqual(a['items'][0]['fact'],document()['catalysts'][0]['fact'])
    def test_preamble_in_same_final_message_still_rejected(self):
        r=raw();p=r['output'][-1]['content'][0];p['text']='Here is the answer:\n'+p['text']
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_JSON')
    def test_no_substring_extraction_of_json_from_prose(self):
        r=raw();r['output'][-1]['content'][0]['text']='prose {} trailing'
        with self.assertRaises(ResearchError):parse_outlook(r,'catalysts',context())
    def test_no_missing_bracket_repair(self):
        r=raw();p=r['output'][-1]['content'][0];p['text']=p['text'][:-1]
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_JSON')
    def test_root_shape_error_distinct_from_json_error(self):
        r=raw();r['output'][-1]['content'][0]['text']='[]'
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_SCHEMA')
    def test_field_length_error_reports_path_not_value(self):
        d=document();d['catalysts'][0]['fact']='PRIVATE_SENTINEL'*100
        with self.assertRaises(ResearchError) as e:parse_outlook(raw(d),'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_SCHEMA');self.assertIn('catalysts.0.fact',e.exception.message)
        self.assertNotIn('PRIVATE_SENTINEL',str(e.exception.outlook_diagnostics))
    def test_missing_field_is_not_fabricated(self):
        d=document();del d['catalysts'][0]['event_date']
        with self.assertRaises(ResearchError) as e:parse_outlook(raw(d),'catalysts',context())
        self.assertIn('event_date:missing',e.exception.message)
    def test_unknown_extra_key_name_not_leaked(self):
        d=document();d['sk-PRIVATE_SECRET']=123
        with self.assertRaises(ResearchError) as e:parse_outlook(raw(d),'catalysts',context())
        self.assertNotIn('PRIVATE_SECRET',e.exception.message);self.assertIn('?:extra_forbidden',e.exception.message)
    def test_refusal_blocks_old_valid_draft(self):
        r=raw();r['output'].append({'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'PRIVATE_REFUSAL'}]})
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'AI_REFUSAL');self.assertNotIn('PRIVATE_REFUSAL',e.exception.message)
    def test_top_incomplete_reports_token_limit_without_increasing_budget(self):
        r=raw();r.update(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.outlook_diagnostics['incomplete_reason'],'max_output_tokens')
    def test_empty_final_does_not_use_previous_answer(self):
        r=raw();r['output'].append(message('',phase=None))
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_NO_FINAL')
    def test_split_documents_not_concatenated_or_first_selected(self):
        r=raw();p=r['output'][-1]['content'][0];r['output'][-1]['content'].append(copy.deepcopy(p))
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_JSON')
    def test_non_dict_top_response_safe_error(self):
        with self.assertRaises(ResearchError) as e:parse_outlook([], 'catalysts', context())
        self.assertEqual(e.exception.code,'OUTLOOK_RESPONSE_SHAPE')
    def test_malformed_tool_action_is_safe_error(self):
        r=raw();r['output'][0]['action']='invalid'
        with self.assertRaises(ResearchError) as e:parse_outlook(r,'catalysts',context())
        self.assertEqual(e.exception.code,'OUTLOOK_RESPONSE_SHAPE')
    def test_queries_scalar_not_iterated_as_characters(self):
        r=raw();r['output'][0]['action']['queries']='secret_scalar'
        self.assertEqual(parse_outlook(r,'catalysts',context())['queries'],[])
    def test_successful_cache_version_unchanged(self):
        self.assertEqual(OUTLOOK_VERSION,'outlook-v0.5.0');self.assertEqual(OUTLOOK_PARSER_VERSION,'0.5.2')


class OutlookDiagnosticsTests(unittest.TestCase):
    def test_no_key_output_text_urls_or_input_saved(self):
        r=raw();r.update(api_key='PRIVATE_KEY',input='PRIVATE_PROMPT')
        r['output'].insert(0,message('PRIVATE_ASSISTANT_TEXT'))
        e=ResearchError('OUTLOOK_JSON','PRIVATE_ERROR');e.outlook_diagnostics={'unknown':'PRIVATE_EXTRA'}
        with tempfile.TemporaryDirectory() as t,redirect_stdout(io.StringIO()) as stdout:
            d=record_failure(Path(t),r,e,'catalysts')
            text=(Path(t)/'logs/outlook-last-diagnostic.json').read_text()+stdout.getvalue()
            for x in ['PRIVATE_','issuer.example','EXM','SYNTHETIC']:self.assertNotIn(x,text)
            self.assertTrue(d['saved_locally'])
    def test_overwrites_one_diagnostic_without_growing_archive(self):
        with tempfile.TemporaryDirectory() as t,redirect_stdout(io.StringIO()):
            for _ in range(3):record_failure(Path(t),raw(),ResearchError('OUTLOOK_JSON','x'),'risks')
            self.assertEqual(len(list((Path(t)/'logs').iterdir())),1)
    def test_diagnostic_io_failure_does_not_mask_error(self):
        with tempfile.TemporaryDirectory() as t,redirect_stdout(io.StringIO()):
            (Path(t)/'logs').write_text('not a directory')
            self.assertFalse(record_failure(Path(t),raw(),ResearchError('OUTLOOK_JSON','x'),'risks')['saved_locally'])
    def test_diagnostic_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as t,redirect_stdout(io.StringIO()):
            root=Path(t)/'root';root.mkdir();outside=Path(t)/'outside';outside.mkdir()
            try:(root/'logs').symlink_to(outside,target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest('Symlinks unavailable')
            self.assertFalse(record_failure(root,raw(),ResearchError('OUTLOOK_JSON','x'),'risks')['saved_locally'])
            self.assertEqual(list(outside.iterdir()),[])
    def test_issue_sanitizer_rejects_extra_diagnostic_fields(self):
        e=ResearchError('OUTLOOK_SCHEMA','secret');e.outlook_diagnostics={'issues':[{'path':'sources.0.PRIVATE','type':'PRIVATE_TYPE','input':'PRIVATE_TEXT'}], 'prompt':'PRIVATE_PROMPT'}
        d=safe_diagnostic(raw(),e,'risks');s=json.dumps(d)
        self.assertNotIn('PRIVATE',s);self.assertEqual(d['issues'][0]['path'],'sources.0.?')


class OutlookHotfixServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-fixture-'+'x'*30)
        self.service=ResearchService(self.root);d=snapshot();d['symbol']='EXM';d['price_context']['symbol']='EXM'
        self.token=self.service.snapshots.add(d)
        self.ctx=patch.object(self.service,'outlook_context',return_value=context());self.ctx.start()
    def tearDown(self):self.ctx.stop();self.tmp.cleanup()
    def invoke(self,scope='catalysts',consent=True,refresh=False):
        return self.service.analyze_outlook(self.token,scope,consent,refresh)
    def test_progress_response_uses_exactly_one_provider_call(self):
        with patch('app.research.call_openai',return_value=with_commentary()) as call:
            r=self.invoke();self.assertEqual(call.call_count,1);self.assertEqual(r['parser_version'],'0.5.2')
    def test_new_error_does_not_retry_or_switch_models(self):
        r=raw();r['output'][-1]['content'][0]['text']='bad JSON'
        with patch('app.research.call_openai',return_value=r) as call,redirect_stdout(io.StringIO()):
            with self.assertRaises(ResearchError) as e:self.invoke()
            self.assertEqual(call.call_count,1);self.assertIn('OUTLOOK_JSON',e.exception.message)
        with self.service._db() as db:self.assertEqual(db.execute('SELECT SUM(n) FROM attempts').fetchone()[0],1)
    def test_diagnostic_and_status_inspection_never_calls_provider(self):
        with patch('app.research.call_openai') as call:
            self.service.cached_outlook(self.token);s=self.service.status();call.assert_not_called()
            self.assertEqual(s['outlook_parser_version'],'0.5.2')
    def test_one_scope_failure_retains_other_cached_result(self):
        bad=raw(scope='risks');bad['output'][-1]['content'][0]['text']='bad'
        with patch('app.research.call_openai',side_effect=[with_commentary(),bad]),redirect_stdout(io.StringIO()):
            self.invoke()
            with self.assertRaises(ResearchError):self.invoke('risks')
        c=self.service.cached_outlook(self.token)['reports'];self.assertIsNotNone(c['catalysts']);self.assertIsNone(c['risks'])
    def test_same_scope_refresh_failure_preserves_success(self):
        bad=raw();bad['output'][-1]['content'][0]['text']='bad'
        with patch('app.research.call_openai',side_effect=[with_commentary(),bad]),redirect_stdout(io.StringIO()):
            self.invoke()
            with self.assertRaises(ResearchError):self.invoke(refresh=True)
        self.assertIsNotNone(self.service.cached_outlook(self.token)['reports']['catalysts'])
    def test_success_is_cached_and_second_read_is_free(self):
        with patch('app.research.call_openai',return_value=with_commentary()) as call:
            self.invoke();self.assertTrue(self.invoke(consent=False)['cache_hit']);self.assertEqual(call.call_count,1)
    def test_failure_diagnostics_have_no_local_api_key(self):
        bad=raw();bad['output'][-1]['content'][0]['text']='bad'
        with patch('app.research.call_openai',return_value=bad),redirect_stdout(io.StringIO()):
            with self.assertRaises(ResearchError):self.invoke()
        txt=(self.root/'logs/outlook-last-diagnostic.json').read_text()
        self.assertNotIn('sk-fixture',txt);self.assertNotIn('Authorization',txt)
    def test_legacy_successful_cache_is_reused_without_paid_call(self):
        key=self.service.cache_key(context(),'gpt-5-mini','outlook-v0.5.0:catalysts')
        import time
        with self.service._db() as db:
            db.execute('INSERT INTO cache(cache_key,expires,payload) VALUES(?,?,?)',(key,time.time()+3600,json.dumps({'scope':'catalysts','saved':'legacy'})))
        with patch('app.research.call_openai') as call:
            self.assertEqual(self.invoke(consent=False)['saved'],'legacy');call.assert_not_called()

class OutlookHotfixAPITests(unittest.TestCase):
    def test_api_accepts_valid_final_after_commentary(self):
        from fastapi.testclient import TestClient
        import app.main as main
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-fixture-'+'x'*30)
            service=ResearchService(root)
            with patch.object(main,'research',service),patch.object(service,'outlook_context',return_value=context()),patch('app.research.call_openai',return_value=with_commentary()) as call:
                res=TestClient(main.app).post('/api/v1/ai/outlook/analyze',headers={'X-SignalDesk-AI':service.csrf_token},json={'snapshot_id':'x'*24,'scope':'catalysts','allow_paid':True})
                self.assertEqual(res.status_code,200);self.assertEqual(res.json()['parser_version'],'0.5.2');self.assertEqual(call.call_count,1)
    def test_api_error_includes_safe_schema_hint(self):
        from fastapi.testclient import TestClient
        import app.main as main
        d=document();del d['catalysts'][0]['watch']
        with tempfile.TemporaryDirectory() as t,redirect_stdout(io.StringIO()):
            root=Path(t);(root/'.env.signaldesk').write_text('OPENAI_API_KEY=sk-fixture-'+'x'*30)
            service=ResearchService(root)
            with patch.object(main,'research',service),patch.object(service,'outlook_context',return_value=context()),patch('app.research.call_openai',return_value=raw(d)) as call:
                res=TestClient(main.app).post('/api/v1/ai/outlook/analyze',headers={'X-SignalDesk-AI':service.csrf_token},json={'snapshot_id':'x'*24,'scope':'catalysts','allow_paid':True})
                self.assertEqual(res.status_code,502);self.assertEqual(res.json()['error']['code'],'OUTLOOK_SCHEMA')
                self.assertIn('catalysts.0.watch:missing',res.json()['error']['message']);self.assertEqual(call.call_count,1)
                self.assertFalse(service.status()['busy']);self.assertNotIn('sk-fixture',res.text)
    def test_health_reports_hotfix_version_without_key(self):
        from fastapi.testclient import TestClient
        import app.main as main
        res=TestClient(main.app).get('/api/health')
        self.assertEqual(res.json()['version'],'0.6.2');self.assertNotIn('api_key',res.text)
