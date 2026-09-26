SHELL := /bin/bash
PYTHON ?= python

.PHONY: bootstrap demo test test-e2e evaluate security-test verify up down

bootstrap:
	$(PYTHON) -m pip install -e './backend[dev]'
	cd frontend && npm install --no-audit --no-fund

demo:
	PYTHONPATH=backend/src FAILURELENS_DATABASE_URL=sqlite+pysqlite:///./failurelens.db $(PYTHON) -m failurelens.cli demo

test:
	cd backend && PYTHONPATH=src pytest --cov=failurelens --cov-report=term-missing

test-e2e:
	@echo "Browser E2E requires the Docker stack and is not implemented in this initial vertical slice." >&2
	@exit 2

evaluate:
	$(PYTHON) evaluation/generate_corpus.py
	PYTHONPATH=backend/src $(PYTHON) evaluation/harness.py --split test --output evaluation/reports/latest

security-test:
	cd backend && PYTHONPATH=src pytest -q tests/test_redaction.py tests/test_ingestion.py tests/test_analysis.py

verify:
	./scripts/verify.sh

up:
	docker compose up --build

down:
	docker compose down
