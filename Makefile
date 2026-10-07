.DEFAULT_GOAL := help

PYTHON ?= python3
VENV := .venv
PY := $(VENV)/bin/python

.PHONY: help install samples demo test serve up

help:
	@echo "make demo      Run the offline demo (CSV, SQLite, dry-run emails)"
	@echo "make serve     Open the dashboard at http://127.0.0.1:8741"
	@echo "make test      Run the unit tests"
	@echo "make samples   Rebuild fictional PDFs so dates are relative to today"
	@echo "make up        docker compose up --build"

$(PY):
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

install: $(PY)

samples: $(PY)
	$(PY) scripts/generate_samples.py

demo: $(PY) samples
	DEMO_MODE=true LLM_PROVIDER=mock REMINDER_DRY_RUN=true $(PY) -m doc_extractor demo

test: $(PY)
	$(PY) -m pytest

serve: $(PY) samples
	DEMO_MODE=true LLM_PROVIDER=mock REMINDER_DRY_RUN=true \
	PROCESS_SAMPLES_ON_START=true WATCH_ENABLED=true SCHEDULER_ENABLED=true \
	$(PY) -m doc_extractor serve --host 0.0.0.0 --port 8741

up:
	docker compose up --build
