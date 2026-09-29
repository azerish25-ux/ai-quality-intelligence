"""Execution-oracle and replay regressions; all fixtures here are synthetic."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from evaluation.campaign_contract import audit
from evaluation.campaign_harness import evaluate
from integrations.ledgerguard import rollback
from integrations.ledgerguard.rollback_oracle import verify_observation

ROOT = Path(__file__).resolve().parents[2]
SOURCE, DEST = rollback.SOURCE, rollback.DEST
RESPONSE = dict(status=422, code='TRANSFER_REJECTED')
COMMAND = dict(source_id=SOURCE, destination_id=DEST, amount_minor=7, currency='CAD')


def measured(effects=True):
    before = dict(balances=[dict(account_id=SOURCE, posted_minor=100), dict(account_id=DEST, posted_minor=50)], effects=[], entries=[])
    after = deepcopy(before)
    if effects:
        journal = '00000000-0000-0000-0000-000000000200'
        after['balances'][0]['posted_minor'] = 93
        after['balances'][1]['posted_minor'] = 57
        after['effects'] = [dict(id='00000000-0000-0000-0000-000000000100', source_id=SOURCE, destination_id=DEST,
                                 amount_minor=7, currency='CAD', journal_id=journal)]
        after['entries'] = [dict(journal_id=journal, account_id=SOURCE, side='DEBIT', amount_minor=7),
                            dict(journal_id=journal, account_id=DEST, side='CREDIT', amount_minor=7)]
    return before, after


@pytest.mark.parametrize('effects', [True, False])
def test_oracle_requires_actual_snapshot_relation(effects):
    result = verify_observation(*measured(effects), command=COMMAND, response=RESPONSE, expected_effects=int(effects))
    assert result['expectation_met']
    assert result['committed_transfers'] == int(effects)
    assert result['debit_minor'] == result['credit_minor'] == 7 * int(effects)
    assert result['no_effects_after_rejection'] is (not effects)


@pytest.mark.parametrize('case', ['empty_intervention', 'wrong_balance', 'missing_credit', 'extra_entry', 'wrong_transfer_amount',
    'wrong_currency', 'missing_account', 'duplicate_account', 'boolean_amount', 'negative_amount',
    'wrong_account', 'duplicate_transfer', 'unknown_field', 'oversized', 'invalid_uuid'])
def test_oracle_cannot_certify_an_expected_exception_without_matching_sql(case):
    before, after = measured()
    if case == 'empty_intervention': after = deepcopy(before)
    if case == 'wrong_balance': after['balances'][1]['posted_minor'] = 50
    if case == 'missing_credit': after['entries'].pop()
    if case == 'extra_entry': after['entries'].append(deepcopy(after['entries'][0]))
    if case == 'wrong_transfer_amount': after['effects'][0]['amount_minor'] = 8
    if case == 'wrong_currency': after['effects'][0]['currency'] = 'USD'
    if case == 'missing_account': after['balances'].pop()
    if case == 'duplicate_account': after['balances'].append(deepcopy(after['balances'][0]))
    if case == 'boolean_amount': after['balances'][0]['posted_minor'] = True
    if case == 'negative_amount': after['entries'][0]['amount_minor'] = -7
    if case == 'wrong_account': after['effects'][0]['source_id'] = DEST
    if case == 'duplicate_transfer': after['effects'].append(deepcopy(after['effects'][0]))
    if case == 'unknown_field': after['effects'][0]['oracle'] = 'PASS'
    if case == 'oversized': after['entries'] *= 513
    if case == 'invalid_uuid': after['entries'][0]['journal_id'] = 'not-a-uuid'
    with pytest.raises(ValueError):
        verify_observation(before, after, command=COMMAND, response=RESPONSE, expected_effects=1)


@pytest.mark.parametrize('case', ['deleted', 'changed', 'journal_deleted', 'journal_duplicated', 'reused_journal'])
def test_historical_effects_cannot_be_removed_or_reused(case):
    _, before = measured()
    after = deepcopy(before)
    if case == 'deleted': after['effects'] = []
    if case == 'changed': after['effects'][0]['amount_minor'] = 8
    if case == 'journal_deleted': after['entries'].pop()
    if case == 'journal_duplicated': after['entries'].append(deepcopy(after['entries'][0]))
    if case == 'reused_journal':
        after['effects'].append({**after['effects'][0], 'id': '00000000-0000-0000-0000-000000000101'})
    with pytest.raises(ValueError):
        verify_observation(before, after, command=COMMAND, response=RESPONSE, expected_effects=int(case == 'reused_journal'))


@pytest.mark.parametrize('response', [dict(status=503, code='OUTCOME_UNKNOWN'), dict(status=422, code='OTHER'),
                                    dict(status=True, code='TRANSFER_REJECTED'), {}])
def test_only_matching_business_rejection_is_eligible(response):
    with pytest.raises(ValueError):
        verify_observation(*measured(), command=COMMAND, response=response, expected_effects=1)


@pytest.mark.parametrize('expectation', [True, '1', 2, -1])
def test_execution_expectation_is_strict(expectation):
    with pytest.raises(ValueError):
        verify_observation(*measured(), command=COMMAND, response=RESPONSE, expected_effects=expectation)


def test_producer_observations_are_derived_without_oracle_answers():
    before, after = measured()
    value = rollback.observation(before, after, amount=7, request_id='a'*64, response=RESPONSE, semantics_digest='b'*64)
    m = value['measurement']
    assert m['new_transfer_count'] == 1 and m['new_journal_entry_count'] == 2
    assert m['new_debit_minor'] == m['new_credit_minor'] == 7
    assert m['after_source_minor'] == 93 and m['after_destination_minor'] == 57
    assert not {'oracle', 'expected_category', 'fault_enabled', 'expected_effects'} & set(m)


def test_mutation_is_fail_closed_and_injects_in_correct_order(monkeypatch):
    # This minimal fixture tests byte replacement only, not companion execution.
    sample = b'void fixture() {\n' + rollback.HOOK + b'                c.commit();\n}\n'
    blob = hashlib.sha1(b'blob ' + str(len(sample)).encode() + b'\0' + sample).hexdigest()
    with pytest.raises(ValueError): rollback.mutate_command(sample, early_commit=False)
    monkeypatch.setattr(rollback, 'COMMAND_BLOB', blob)
    control = rollback.mutate_command(sample, early_commit=False)
    fault = rollback.mutate_command(sample, early_commit=True)
    assert control.index(b'throw new SQLException') < control.index(b'c.commit();')
    assert fault.index(b'c.commit();') < fault.index(b'throw new SQLException')
    assert control.count(b'c.commit();') == 1 and fault.count(b'c.commit();') == 2
    assert b'if ("TRANSFER".equals(operation))' in control
    with pytest.raises(ValueError): rollback.mutate_command(sample+b'\n', early_commit=True)


def test_no_docker_never_silently_becomes_synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr(rollback.shutil, 'which', lambda name: None)
    with pytest.raises(RuntimeError, match='no synthetic fallback'):
        rollback.run(tmp_path/'source', tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_corpus_is_small_development_slice_not_heldout_or_fresh_execution(tmp_path):
    root = tmp_path/'corpus'
    inventory = rollback.build_synthetic(root)
    assert inventory['case_count'] == 8 and inventory['family_count'] == 1
    assert inventory['source_counts'] == {'synthetic': 8}
    assert inventory['split_counts'] == {'development': 8}
    _, labels, public = audit(root, enforce_minimums=False)
    assert all(l.reused_development for l in labels)
    assert len([c for c in public.cases if c.control]) == 4
    assert {l.expected_category for l in labels} == {'product_defect', 'insufficient_evidence'}
    with pytest.raises(ValueError): audit(root)
    with pytest.raises(ValueError): rollback.build_synthetic(root)
    frozen = json.loads((root/'freeze.json').read_bytes())
    assert 'integrations/ledgerguard/rollback.py' in frozen['harness_files']
    assert 'response-semantics.json' in frozen['files']


@pytest.fixture(scope='module')
def development(tmp_path_factory):
    root = tmp_path_factory.mktemp('finality-replay')
    corpus = root/'corpus'; rollback.build_synthetic(corpus)
    env = {**os.environ, 'FAILURELENS_DATABASE_URL': f'sqlite+pysqlite:///{root}/db.sqlite',
           'FAILURELENS_ARTIFACT_ROOT': str(root/'private'), 'FAILURELENS_DEMO_MODE': 'true'}
    p = subprocess.run([sys.executable, str(ROOT/'evaluation/replay_campaign.py'), '--inputs', str(corpus/'inputs'),
                        '--output', str(root/'replay'), '--confirm-disposable-database'], cwd=ROOT, env=env,
                        capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout+p.stderr
    return corpus, root/'replay'


def test_full_api_worker_replay_resolves_citations_without_label_leakage(development):
    metrics, rows = evaluate(*development, enforce_minimums=False, score_split='development')
    assert len(rows) == 8 and not metrics['errors']
    assert metrics['claim_checks']['published'] == metrics['claim_checks']['supported'] == 4
    assert all(metrics['integrity_acceptance'].values())
    assert metrics['citation_checks']['resolved']['rate'] == 1
    assert metrics['repeated_analysis_count'] == 5
    assert metrics['source_counts'] == {'ledgerguard_executed': 0, 'synthetic': 8, 'other_executed': 0}
    assert metrics['database_dialect'] == 'sqlite'
    assert metrics['evaluation_scope'] == 'development_contract_measurement'
    assert not metrics['held_out_acceptance'] and not metrics['full_m6_complete']
    assert metrics['unknown_family_test_cases'] == 0


def test_empty_test_partition_cannot_be_presented_as_heldout(development):
    with pytest.raises(ValueError, match='empty'):
        evaluate(*development, enforce_minimums=False, score_split='test')
