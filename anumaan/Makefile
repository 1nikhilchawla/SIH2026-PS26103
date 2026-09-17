# ANUMAAN makefile - works on Windows (PowerShell) and POSIX shells.
#
# Targets:
#   make setup         create .venv + install requirements
#   make test          offline test suite (stdlib + bs4 only)
#   make list          list every report found (no download)
#   make harvest       download reports since FY 2019-20 (polite, resumable)
#   make parse FILE=X  parse a single PDF (defaults to every PDF under data/raw/)
#   make parse-all     parse every PDF under data/raw/
#   make panel         build the project-month panel
#   make train         train the T1 model + produce results/*
#   make clean         delete generated artefacts under data/interim/ and results/

# ---- platform detection -----------------------------------------------------
ifeq ($(OS),Windows_NT)
  VENV_PY := .venv\Scripts\python.exe
  VENV_PIP := .venv\Scripts\pip.exe
  RM := mavis-trash
  RMDIR := mavis-trash
  SEP := \\
else
  VENV_PY := .venv/bin/python
  VENV_PIP := .venv/bin/pip
  RM := rm -f
  RMDIR := rm -rf
  SEP := /
endif

# ---- python-version-driven requirements -------------------------------------
# Brief pins Python 3.11 for the production stack; this dev machine runs 3.14
# which has no wheels for some pinned versions. requirements-py314.txt is a
# deliberate, documented fallback - see P1 notes in results/judge-qa.md.
SETUP_PY := $(VENV_PY)
REQ_FILE := requirements.txt
ifneq (,$(wildcard .venv/))
  PY_VER := $(shell $(VENV_PY) -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>nul)
  ifeq ($(PY_VER),3.14)
    REQ_FILE := requirements-py314.txt
  endif
  ifeq ($(PY_VER),3.13)
    REQ_FILE := requirements-py314.txt
  endif
endif

.PHONY: help setup test test-nodeps verify-test list harvest parse parse-all panel train synth demo clean

help:
	@echo "make setup         - create .venv and install $(REQ_FILE)"
	@echo "make test          - run the offline test suite (no network)"
	@echo "make test-nodeps   - same tests without pytest"
	@echo "make verify-test   - same tests, with heavy deps blocked (P1 acceptance)"
	@echo "make list          - list every report found (no download)"
	@echo "make harvest       - download reports since FY 2019-20"
	@echo "make parse FILE=X  - parse a single PDF"
	@echo "make parse-all     - parse every PDF under data/raw/"
	@echo "make synth         - generate a synthetic Flash-Report-shaped panel"
	@echo "make train         - train the T1 model and write results/*"
	@echo "make demo          - synth + train + build the three-screen demo"
	@echo "make clean         - remove generated artefacts"

setup:
	@if not exist .venv ($(SETUP_PY) -m venv .venv)
	python -m venv .venv 2>nul || python3 -m venv .venv
	$(VENV_PY) -m pip install -U pip
	$(VENV_PY) -m pip install -r $(REQ_FILE)
	@echo "Installed $(REQ_FILE). Activate with: source .venv/bin/activate (POSIX) or .venv\Scripts\activate (Windows)."

test:
	$(VENV_PY) -m pytest -q tests/

test-nodeps:
	$(VENV_PY) tests/run_tests.py

# P1 acceptance: prove `make test` does not pull heavy deps (pdfplumber,
# pandas, sklearn, lightgbm, fastapi, requests, yaml, ...) at any point.
verify-test:
	$(VENV_PY) scripts/verify_test_target_standalone.py

list:
	$(VENV_PY) scripts/harvest_paimana.py --list-only

harvest:
	$(VENV_PY) scripts/harvest_paimana.py --since-fy 2019-20

# Single-file parse - FILE is required.
parse:
ifndef FILE
	$(error usage: make parse FILE=data/raw/<path-to-one>.pdf)
endif
	$(VENV_PY) scripts/parse_report.py --file "$(FILE)"

parse-all:
	$(VENV_PY) scripts/parse_report.py --all

# Stages 2+ are wired here but currently stub. Their scripts/ will be added
# in P4 (panel) and P5 (train).
panel:
	$(VENV_PY) scripts/build_panel.py

train:
	$(VENV_PY) scripts/train_t1.py

# Demo pipeline: synthetic panel -> trainer -> three static HTML pages.
# Re-running is idempotent; every number on every page is regenerated.
synth:
	$(VENV_PY) scripts/synth_panel.py --out data/synthetic/panel.csv --seed 42

demo: synth train
	$(VENV_PY) scripts/build_demo.py --panel data/synthetic/panel.csv \
	    --results results --out demo
	@echo ""
	@echo "Demo built. Serve it locally with:"
	@echo "  $(VENV_PY) -m http.server 8765 --directory demo"

clean:
	-$(RMDIR) data/interim 2>nul
	-$(RM) data/interim/.gitkeep 2>nul
	-$(RMDIR) results 2>nul
	-$(RM) results/.gitkeep 2>nul
	@echo "interim + results cleared (raw/ is never touched)"