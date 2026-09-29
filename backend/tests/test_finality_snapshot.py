"""Retained real execution is independently rescored, never called a fresh run."""
from copy import deepcopy
import io
import json
import lzma
from pathlib import Path
import shutil
import zipfile

import pytest

from evaluation.verify_finality_snapshot import REPORT, validate_execution, verify_snapshot


@pytest.fixture
def records():
    retained = json.loads((REPORT / 'retention.json').read_bytes())
    with zipfile.ZipFile(io.BytesIO(lzma.decompress((REPORT / 'execution.zip.xz').read_bytes()))) as archive:
        metrics = json.loads(archive.read('report/metrics.json'))
        rows = [json.loads(line) for line in archive.read('report/predictions.jsonl').splitlines()]
        provenance = json.loads(archive.read('corpus/execution-provenance.json'))
    return metrics, rows, provenance, retained


def test_real_retained_snapshot_rescores_and_exports_exact_safe_evidence(tmp_path):
    destination = tmp_path / 'verified'
    result = verify_snapshot(extract_to=destination)
    assert result['tested_source_revision'] == 'b7327b437d8fc4cb009918d1d4d31b6bf36f508a'
    assert result['database_dialect'] == 'postgresql'
    assert result['executed_pairs'] == 4 and result['executed_families'] == 1
    assert result['case_count'] == 8 and result['synthetic_cases'] == 4
    assert result['held_out_acceptance'] is False and result['full_m6_complete'] is False
    assert 'not fresh' in result['verification_scope']
    assert len(list((destination / 'replay/safe-evidence').rglob('*.json'))) == 16
    assert (destination / 'report/report.md').read_bytes() == (REPORT / 'report.md').read_bytes()
    with pytest.raises(ValueError, match='already exist'):
        verify_snapshot(extract_to=destination)
    assert (destination / 'report/metrics.json').is_file()


@pytest.mark.parametrize('mutation', ('dirty', 'sqlite', 'wrong_sha', 'heldout', 'completed_m6',
                                      'fake_executed_count', 'missing_receipt', 'duplicate_receipt',
                                      'invalid_role', 'boolean_variant', 'fake_oracle', 'wrong_balance'))
def test_retained_truth_and_oracles_cannot_be_replaced_with_success_flags(records, mutation):
    metrics, rows, provenance, retained = deepcopy(records)
    if mutation == 'dirty': metrics['source_worktree_dirty'] = True
    if mutation == 'sqlite': metrics['database_dialect'] = 'sqlite'
    if mutation == 'wrong_sha': provenance['failurelens_revision'] = '0' * 40
    if mutation == 'heldout': metrics['held_out_acceptance'] = True
    if mutation == 'completed_m6': metrics['full_m6_complete'] = True
    if mutation == 'fake_executed_count': metrics['source_counts']['ledgerguard_executed'] = 8
    if mutation == 'missing_receipt': provenance['oracle_receipts'].pop()
    if mutation == 'duplicate_receipt': provenance['oracle_receipts'][1] = deepcopy(provenance['oracle_receipts'][0])
    if mutation == 'invalid_role': provenance['oracle_receipts'][0]['role'] = 'passed'
    if mutation == 'boolean_variant': provenance['oracle_receipts'][0]['variant'] = True
    if mutation == 'fake_oracle': provenance['oracle_receipts'][0]['oracle']['committed_transfers'] = 1
    if mutation == 'wrong_balance': provenance['oracle_receipts'][0]['after']['balances'][0]['posted_minor'] += 1
    with pytest.raises(ValueError):
        validate_execution(metrics, rows, provenance, retained)


@pytest.mark.parametrize('mutation', ('compressed_bytes', 'visible_report', 'inventory', 'symlink'))
def test_corrupted_retention_is_rejected_before_export(tmp_path, mutation):
    report = tmp_path / 'report'
    shutil.copytree(REPORT, report)
    path = report / 'execution.zip.xz'
    if mutation == 'compressed_bytes':
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
    if mutation == 'visible_report': (report / 'report.md').write_text('Everything passed.\n')
    if mutation == 'inventory':
        metadata = json.loads((report / 'retention.json').read_bytes())
        metadata['file_sha256'].pop('report/metrics.json')
        (report / 'retention.json').write_text(json.dumps(metadata))
    if mutation == 'symlink':
        path.unlink(); path.symlink_to(REPORT / 'execution.zip.xz')
    destination = tmp_path / 'not-exported'
    with pytest.raises(ValueError):
        verify_snapshot(report, extract_to=destination)
    assert not destination.exists()
