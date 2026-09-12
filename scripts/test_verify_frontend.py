"""Offline export-guard regression tests; temporary synthetic assets, not a Next build."""
from __future__ import annotations
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from verify_frontend import (BUILD_ID, REQUIRED_FEATURE_IDS, FORBIDDEN, VERSION,
                             plain_js, validate_export, validate_source)

ROOT = Path(__file__).resolve().parents[1]


class EscapeTests(unittest.TestCase):
    def test_original_hex_middle_dot_failure_is_reproduced(self):
        encoded = r'"\uc0c1\uc2b9\xb7\ud558\ub77d \uc870\uac74 \uc870\uc0ac"'
        old = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), encoded)
        self.assertNotIn('상승·하락 조건 조사', old)
        self.assertIn('상승·하락 조건 조사', plain_js(encoded))

    def test_hex_upper_and_lower(self):
        self.assertEqual(plain_js(r'상승\xB7하락/상승\xb7하락'), '상승·하락/상승·하락')

    def test_literal_utf8_not_corrupted(self):
        text = '상승·하락 조건 조사 · 유료 1회'
        self.assertEqual(plain_js(text), text)

    def test_four_digit_unicode(self):
        self.assertEqual(plain_js(r'\uc0c1\uC2B9\u00b7\ud558\ub77d'), '상승·하락')

    def test_braced_unicode(self):
        self.assertEqual(plain_js(r'\u{c0c1}\u{c2b9}\u{B7}\u{d558}\u{b77d}'), '상승·하락')

    def test_codepoint_range(self):
        self.assertEqual(plain_js(r'\u{1f7e2}'), '🟢')
        self.assertEqual(plain_js(r'\u{110000}'), r'\u{110000}')

    def test_doubled_backslash_not_redecoded(self):
        self.assertEqual(plain_js(r'\\xb7'), r'\\xb7')
        self.assertEqual(plain_js(r'\\u00b7'), r'\\u00b7')

    def test_no_recursive_decode(self):
        self.assertEqual(plain_js(r'\x5cxb7'), r'\xb7')

    def test_malformed_escapes_unchanged(self):
        text = r'\xGG \uXYZZ \u{badxxx} \u{1234567}'
        self.assertEqual(plain_js(text), text)

    @unittest.skipUnless(shutil.which('node'), 'Node is unavailable')
    def test_real_node_string_equivalence(self):
        code = r'''console.log(JSON.stringify(["상승·하락 조건 조사", "상승\xb7하락 조건 조사", "상승\u00b7하락 조건 조사", "상승\u{b7}하락 조건 조사"]));'''
        values = json.loads(subprocess.check_output(['node', '-e', code], text=True, encoding='utf-8'))
        self.assertTrue(all(v == '상승·하락 조건 조사' for v in values))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / 'frontend', self.root / 'frontend',
                        ignore=shutil.ignore_patterns('node_modules', '.next', 'out', '__pycache__', '.env*', '.git', '.backups', '.cache', '*.log'))
        out = self.root / 'frontend/out'
        for name in ('index.html', 'advanced/index.html'):
            p = out / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'<html><body>{BUILD_ID}<script src="/_next/static/main.js"></script></body></html>', encoding='utf-8')
        self.js = out / '_next/static/main.js'
        self.js.parent.mkdir(parents=True)
        self.js.write_text('window.SYNTHETIC_FIXTURE=' + json.dumps([BUILD_ID, *REQUIRED_FEATURE_IDS]) + ';', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_valid(self):
        validate_source(self.root)

    def test_stamp_then_reverify(self):
        info = validate_export(self.root, stamp=True)
        self.assertEqual(info['feature_ids'], list(REQUIRED_FEATURE_IDS))
        self.assertEqual(info, validate_export(self.root))

    def test_hex_label_does_not_fail_feature_check(self):
        with self.js.open('a', encoding='utf-8') as out:
            out.write(r';window.LABEL="상승\xb7하락 조건 조사";')
        validate_export(self.root, stamp=True)

    def test_compiled_features_work_with_escaped_letters(self):
        self.js.write_text(self.js.read_text().replace('sd-stock', r'\x73d-stock'), encoding='utf-8')
        validate_export(self.root, stamp=True)

    def test_missing_action_rejected(self):
        self.js.write_text(self.js.read_text().replace('sd-stock-drivers-action', 'missing-feature'), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'sd-stock-drivers-action'):
            validate_export(self.root, stamp=True)

    def test_missing_event_condition_rejected(self):
        self.js.write_text(self.js.read_text().replace('sd-event-downside-condition', 'missing-feature'), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'sd-event-downside-condition'):
            validate_export(self.root, stamp=True)

    def test_old_html_rejected(self):
        (self.root / 'frontend/out/index.html').write_text('SD-110-DRIVERS-DILUTION')
        with self.assertRaisesRegex(RuntimeError, 'Old HTML'):
            validate_export(self.root, stamp=True)

    def test_old_javascript_rejected(self):
        self.js.write_text(self.js.read_text().replace(BUILD_ID, 'SD-110-DRIVERS-DILUTION'))
        with self.assertRaisesRegex(RuntimeError, 'UI feature identifiers'):
            validate_export(self.root, stamp=True)

    def test_missing_javascript_rejected(self):
        self.js.unlink()
        with self.assertRaisesRegex(RuntimeError, 'no JavaScript'):
            validate_export(self.root, stamp=True)

    def test_escaped_removed_valuation_rejected(self):
        for encoded in [r'가정\xb7자료 설정', r'가정\u00b7자료 설정', r'가정\u{b7}자료 설정']:
            with self.subTest(encoded=encoded):
                original = self.js.read_text(encoding='utf-8')
                self.js.write_text(original + ';var old="' + encoded + '";', encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'Old valuation'):
                    validate_export(self.root, stamp=True)
                self.js.write_text(original, encoding='utf-8')

    def test_removed_api_rejected(self):
        self.js.write_text(self.js.read_text() + '"/api/v1/decision/calculate"')
        with self.assertRaisesRegex(RuntimeError, 'Old valuation'):
            validate_export(self.root, stamp=True)

    def test_missing_source_action_rejected(self):
        p = self.root / 'frontend/components/StockWatch.jsx'
        p.write_text(p.read_text(encoding='utf-8').replace('sd-dilution-scan-action', 'absent'), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Stock Watch UI'):
            validate_export(self.root, stamp=True)

    def test_disconnected_component_rejected(self):
        p = self.root / 'frontend/app/page.jsx'
        p.write_text(p.read_text(encoding='utf-8').replace('<StockWatch ', '<section '), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'not connected'):
            validate_source(self.root)

    def test_changed_source_rejected_after_stamp(self):
        validate_export(self.root, stamp=True)
        p = self.root / 'frontend/app/page.jsx'
        p.write_text(p.read_text(encoding='utf-8') + '\n// changed source', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Source changed'):
            validate_export(self.root)

    def test_changed_export_rejected_after_stamp(self):
        validate_export(self.root, stamp=True)
        self.js.write_text(self.js.read_text() + '\n// changed exported bytes')
        with self.assertRaisesRegex(RuntimeError, 'Export differs'):
            validate_export(self.root)

    def test_missing_manifest_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'manifest missing'):
            validate_export(self.root)

    def test_bad_manifest_version_rejected(self):
        info = validate_export(self.root, stamp=True)
        info['version'] = '1.1.0'
        (self.root / 'frontend/out/build-info.json').write_text(json.dumps(info), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'manifest version'):
            validate_export(self.root)

    def test_bad_manifest_feature_ids_rejected(self):
        info = validate_export(self.root, stamp=True)
        info['feature_ids'] = []
        (self.root / 'frontend/out/build-info.json').write_text(json.dumps(info), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'feature checks'):
            validate_export(self.root)


if __name__ == '__main__':
    unittest.main()
