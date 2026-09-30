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

# Fresh external reports; consume frozen inputs without regenerating them.
evaluate:
	"$(PYTHON)" scripts/local_verify.py evaluate $(VERIFY_ARGS)

# Current authorization, evidence, capability and publication trust boundaries.
# Synthetic/SQLite and mock transports only; real producers/PostgreSQL remain in CI.
SECURITY_TESTS := auth redaction ingestion ingestion_m2_adapters durable_ingestion \
	analysis service evidence_validation binary_evidence trace_safety \
	adversarial_boundaries history history_reuse clustering infrastructure impact \
	performance contract_evidence domain_evidence transaction_evidence \
	transaction_finality github_report github_snapshot github_publication \
	providers provider_config provider_accounting provider_credential_echo \
	provider_deployment_fixture provider_ledger provider_output_bounds provider_proxy \
	provider_retention provider_workflow project_redaction image_process_boundary \
	binary_impact_boundaries runtime_boundary_diagnostics publication_predicate_types \
	github_action github_action_config github_evidence github_publication_api \
	github_publication_revisions github_publication_service github_report_sections \
	workflow_contexts compose_topology operations telemetry mutation_safeguards

security-test:
	"$(PYTHON)" scripts/local_verify.py security $(VERIFY_ARGS) --tests $(addprefix backend/tests/test_,$(addsuffix .py,$(SECURITY_TESTS)))

# Opt-in and an explicit fresh destination remain required even through Make.
# Example: make safeguard-mutations MUTATION_ARGS='--confirm-synthetic-mutations --output /tmp/safeguards.json'
safeguard-mutations:
	PYTHONPATH=backend/src:. $(PYTHON) -m evaluation.mutation_runner $(MUTATION_ARGS)

verify:
	PYTHON="$(PYTHON)" ./scripts/verify.sh $(VERIFY_ARGS)

up:
	docker compose up --build

down:
	docker compose down
