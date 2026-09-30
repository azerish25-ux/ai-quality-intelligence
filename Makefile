SHELL := /bin/bash
PYTHON ?= python

.PHONY: bootstrap demo test test-e2e evaluate security-test verify up down

bootstrap:
	$(PYTHON) -m pip install --require-hashes -r backend/requirements.lock
	$(PYTHON) -m pip install --no-deps -e './backend[dev]'
	cd frontend && npm install --no-audit --no-fund

demo:
	PYTHONPATH=backend/src FAILURELENS_DATABASE_URL=sqlite+pysqlite:///./failurelens.db $(PYTHON) -m failurelens.cli demo

test:
	cd backend && PYTHONPATH=src pytest --cov=failurelens --cov-report=term-missing

test-e2e:
	cd frontend && npm run test:e2e

evaluate:
	$(PYTHON) evaluation/generate_corpus.py
	$(PYTHON) evaluation/generate_clustering_corpus.py
	$(PYTHON) evaluation/generate_impact_corpus.py
	$(PYTHON) evaluation/generate_performance_corpus.py
	$(PYTHON) evaluation/generate_infrastructure_corpus.py
	PYTHONPATH=backend/src $(PYTHON) evaluation/harness.py --split test --output evaluation/reports/latest
	PYTHONPATH=backend/src $(PYTHON) evaluation/clustering_harness.py --output evaluation/reports/latest
	PYTHONPATH=backend/src $(PYTHON) evaluation/impact_harness.py --output evaluation/reports/latest
	PYTHONPATH=backend/src $(PYTHON) evaluation/performance_harness.py --output evaluation/reports/latest
	PYTHONPATH=backend/src $(PYTHON) evaluation/infrastructure_harness.py --output evaluation/reports/latest

security-test:
	cd backend && PYTHONPATH=src pytest -q tests/test_redaction.py tests/test_ingestion.py tests/test_analysis.py tests/test_clustering.py tests/test_history.py tests/test_infrastructure.py tests/test_impact.py tests/test_performance.py

verify:
	./scripts/verify.sh

up:
	docker compose up --build

down:
	docker compose down
