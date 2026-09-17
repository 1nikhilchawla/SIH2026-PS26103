#!/usr/bin/env python3
"""Minimal test runner for environments without pytest.

Usage:  python3 tests/run_tests.py
Exits non-zero if any test fails, so it works in CI too.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import traceback


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    failed = 0
    ran = 0

    for path in sorted((root / "tests").glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in dir(module):
            if not name.startswith("test_"):
                continue
            ran += 1
            try:
                getattr(module, name)()
                print(f"PASS  {path.name}::{name}")
            except Exception:
                failed += 1
                print(f"FAIL  {path.name}::{name}")
                traceback.print_exc()

    print(f"\n{ran - failed}/{ran} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
