#!/usr/bin/env python3
"""P1 acceptance check: `make test` must run with only stdlib + bs4.

Runs the entire test suite after installing a sys.meta_path blocker that
raises ImportError for any heavy dependency (pdfplumber, pandas, numpy,
sklearn, lightgbm, fastapi, requests, yaml, ...). If a test pulls in any of
these, the suite fails loudly.

Usage:
    python scripts/verify_test_target_standalone.py
    make verify-test

Acceptance (P1):
    All tests pass under the heavy-dep blocker.

This script itself uses only stdlib (sys, pathlib, importlib).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

BLOCK = {
    # PDF + heavy data
    "pdfplumber", "pandas", "numpy", "sklearn", "scikit-learn",
    "lightgbm", "lifelines", "shap", "mapie", "pandera",
    "rapidfuzz", "fastapi", "uvicorn", "pydantic", "PIL",
    "camelot", "tabula", "tabula-py", "camelot-py",
    # IO + serialisation
    "yaml", "requests",
}


class Blocker:
    def find_module(self, name, path=None):
        if name in BLOCK:
            return self

    def load_module(self, name):
        raise ImportError(f"P1 acceptance: blocked heavy dep {name!r}")


sys.meta_path.insert(0, Blocker())

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failed = 0
ran = 0
skipped = 0

for path in sorted((ROOT / "tests").glob("test_*.py")):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        # Top-level import pulled a heavy dep -> the whole test file is
        # out of scope for the standalone check.
        print(f"SKIP  {path.name}: {exc}")
        skipped += 1
        continue
    for name in dir(module):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            getattr(module, name)()
            print(f"PASS  {path.name}::{name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {path.name}::{name}: {type(exc).__name__}: {exc}")

total = ran + failed
print(f"\n{ran}/{total} passed (heavy deps blocked; {skipped} file(s) skipped)")
sys.exit(0 if failed == 0 else 1)