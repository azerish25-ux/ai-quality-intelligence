SHELL := /bin/bash
PYTHON ?= python

.PHONY: bootstrap demo test test-e2e evaluate security-test safeguard-mutations verify up down

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

# Current authorization, evidence, capability and publication trust boundaries.
# Synthetic/SQLite and mock transports only; real producers/PostgreSQL remain in CI.
SECURITY_TESTS := auth redaction ingestion ingestion_m2_adapters durable_ingestion \
	analysis service evidence_validation binary_evidence trace_safety \
	adversarial_boundaries history history_reuse clustering infrastructure impact \
	performance contract_evidence domain_evidence transaction_evidence \
	transaction_finality github_report github_snapshot github_publication \
	providers operations telemetry mutation_safeguards

security-test:
	PYTHONPATH=backend/src:. $(PYTHON) -m pytest -q $(addprefix backend/tests/test_,$(addsuffix .py,$(SECURITY_TESTS)))

# Opt-in and an explicit fresh destination remain required even through Make.
# Example: make safeguard-mutations MUTATION_ARGS='--confirm-synthetic-mutations --output /tmp/safeguards.json'
safeguard-mutations:
	PYTHONPATH=backend/src:. $(PYTHON) -m evaluation.mutation_runner $(MUTATION_ARGS)

verify:
	./scripts/verify.sh

up:
	docker compose up --build

down:
	docker compose down
