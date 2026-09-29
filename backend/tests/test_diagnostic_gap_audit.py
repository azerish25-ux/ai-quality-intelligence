"""Audit metadata never invents a producer/normalizer/capability root cause."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from evaluation.diagnostic_gap_audit import summarize, run


def fixture(gap=None, legacy=False):
    metadata = {} if legacy else dict(diagnostic_gap=gap, diagnostic_findings=[])
    rows = [dict(case_id='c-'+'a'*20, predicted='insufficient_evidence', expected_category='product_defect',
                 scenario_family_id='example', split='test', source_kind='synthetic')]
    replay = dict(cases=[dict(case_id=rows[0]['case_id'], analysis=dict(category='insufficient_evidence',
                           claims=[], validation_results=metadata))])
    return dict(source_revision='b'*40), rows, replay


@pytest.mark.parametrize('gap,stage', [(None,'unresolved_evidence_or_capability'),
    ('publication_rejection','publication_rejection'), ('missing_or_invalid_observations','missing_or_invalid_observations'),
    ('contradictory_observations','contradictory_observations')])
def test_recorded_boundary_is_not_promoted_to_hidden_root_cause(gap,stage):
    result=summarize(*fixture(gap))
    assert result['case_count']==result['mismatches']==1
    assert result['stage_counts']=={stage:1}
    assert result['cases'][0]['artifact_adjudication_required']
    assert 'root_cause' not in result['cases'][0]


def test_legacy_records_are_uninstrumented_not_automatically_missing_evidence():
    result=summarize(*fixture(legacy=True))
    assert result['stage_counts']=={'legacy_uninstrumented':1}


@pytest.mark.parametrize('bad', ['unknown_stage','duplicate','category','findings'])
def test_invalid_audit_records_fail_closed(bad):
    metrics,rows,replay=fixture()
    if bad=='unknown_stage': replay['cases'][0]['analysis']['validation_results']['diagnostic_gap']='guess'
    if bad=='duplicate': replay['cases']*=2
    if bad=='category': rows[0]['predicted']='product_defect'
    if bad=='findings': replay['cases'][0]['analysis']['validation_results']['diagnostic_findings']='text'
    with pytest.raises(ValueError): summarize(metrics,rows,replay)


def test_arbitrary_diagnostic_text_is_not_exported():
    metrics,rows,replay=fixture('contradictory_observations')
    replay['cases'][0]['analysis']['validation_results']['diagnostic_findings']=[dict(reason='secret-canary-unsafe', contract='x')]
    result=summarize(metrics,rows,replay)
    assert result['cases'][0]['recorded_findings']==1
    assert 'secret-canary-unsafe' not in json.dumps(result)


def test_invalid_kind_never_runs_inference(tmp_path):
    with pytest.raises(ValueError): run(tmp_path, tmp_path, kind='untrusted')


def test_workflow_keeps_exact_source_scope_and_guardrails():
    root=Path(__file__).resolve().parents[2]
    workflow=(root/'.github/workflows/rollback-evaluation.yml').read_text()
    assert 'contents: read' in workflow and 'contents: write' not in workflow
    assert 'pull_request_target' not in workflow
    assert '--confirm-disposable-stack' in workflow
    assert "ref: 13bdd62c924a3230825b6d9304f449f887c8e7fe" in workflow
    assert "assert all(metrics['integrity_acceptance'].values()) and not metrics['errors']" in workflow
    assert "assert metrics['source_revision']==os.environ['GITHUB_SHA']" in workflow
    assert '--development-only' in workflow and '--enforce-quality' not in workflow
    assert "metrics['held_out_acceptance'] is False" in workflow
    assert 'playwright.finality.config.ts' in workflow
    config=(root/'frontend/playwright.finality.config.ts').read_text()
    assert 'retries: 0' in config
