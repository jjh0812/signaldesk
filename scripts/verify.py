"""Offline unit/API tests: no calls to Yahoo, OpenAI, or a broker."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
suite = unittest.defaultTestLoader.discover(str(ROOT / "backend" / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(f"\nBACKEND TESTS: {'PASS' if result.wasSuccessful() else 'FAIL'} ({result.testsRun} tests)")
raise SystemExit(0 if result.wasSuccessful() else 1)
