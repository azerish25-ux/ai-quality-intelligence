"""Retained real evidence is rescored; malicious variants below are test-only mutations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.executed_harness import evaluate
from evaluation.verify_snapshot import REPORT, SNAPSHOT, unpack_snapshot, verify_snapshot


def test_retained_postgresql_execution_rescores_without_hiding_failed_target():
    result = verify_snapshot()
    assert result['case_count'] == 60 and result['family_count'] == 15
    assert result['dangerous_dismissal']['numerator'] == 0
    assert result['dangerous_dismissal']['denominator'] == 60
    assert result['quality_targets']['product_recall_gte_90_percent'] is False


def test_snapshot_checks_archive_digest_before_extraction(tmp_path):
    archive = tmp_path / 'changed.zip'; archive.write_bytes(SNAPSHOT.read_bytes() + b'changed')
    digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='digest'): unpack_snapshot(archive, tmp_path / 'data', digest)
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('name', ['../outside.json', '/tmp/outside.json', 'corpus/../outside.xml', 'corpus//data.json', 'corpus/code.py', 'unknown/data.json'])
def test_snapshot_rejects_unsafe_archive_paths(tmp_path, name):
    archive = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(archive, 'w') as source: source.writestr(name, '{}')
    with pytest.raises(ValueError, match='unsafe'): unpack_snapshot(archive, tmp_path / 'data', hashlib.sha256(archive.read_bytes()).hexdigest())


@pytest.mark.parametrize('mode', [stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO])
def test_snapshot_accepts_only_regular_data_files(tmp_path, mode):
    archive = tmp_path / 'unsafe.zip'; entry = zipfile.ZipInfo('corpus/file.json'); entry.external_attr = (mode | 0o600) << 16
    with zipfile.ZipFile(archive, 'w') as source: source.writestr(entry, 'data')
    with pytest.raises(ValueError, match='unsafe'): unpack_snapshot(archive, tmp_path / 'data', hashlib.sha256(archive.read_bytes()).hexdigest())


def test_snapshot_refuses_existing_destination(tmp_path):
    target = tmp_path / 'existing'; target.mkdir(); (target / 'preserve').write_text('unrelated')
    with pytest.raises(ValueError, match='already exist'):
        unpack_snapshot(SNAPSHOT, target, hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest())
    assert (target / 'preserve').read_text() == 'unrelated'


@pytest.fixture
def replay_copy(tmp_path):
    target = tmp_path / 'data'
    unpack_snapshot(SNAPSHOT, target, hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest())
    policy = json.loads((ROOT / 'evaluation/policies/ledgerguard-component-v1.json').read_text())
    return target, policy


@pytest.mark.parametrize('field,value', [('case_count', 59), ('repeats', 0), ('repeats', True), ('schema_version', 'unknown')])
def test_scorer_rejects_tampered_replay_metadata(replay_copy, field, value):
    root, policy = replay_copy; p = root / 'replay/predictions.json'; data = json.loads(p.read_text()); data[field] = value; p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='count or version'): evaluate(root / 'corpus', root / 'replay', policy)


def test_scorer_cannot_inflate_repeat_count(replay_copy):
    root, policy = replay_copy; p = root / 'replay/predictions.json'; data = json.loads(p.read_text()); data['cases'][0]['repeat_count'] = 1; p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='repetition'): evaluate(root / 'corpus', root / 'replay', policy)


def test_scorer_requires_distinct_control_and_intervention(replay_copy):
    root, policy = replay_copy; p = root / 'replay/predictions.json'; data = json.loads(p.read_text()); data['cases'][0]['inputs'][0]['role'] = 'observation'; p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='control/observation'): evaluate(root / 'corpus', root / 'replay', policy)


@pytest.mark.parametrize('field', ['family_count', 'control_passes', 'intervention_failures'])
def test_scorer_rejects_inflated_provenance_counts(replay_copy, field):
    root, policy = replay_copy; p = root / 'corpus/provenance.json'; data = json.loads(p.read_text()); data[field] += 1; p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='counts differ'): evaluate(root / 'corpus', root / 'replay', policy)


def test_scorer_revalidates_the_actual_producer_bytes(replay_copy):
    root, policy = replay_copy; p = next((root / 'corpus/inputs').glob('*/observation.xml')); p.write_bytes(p.read_bytes().replace(b'Expected', b'Changed!'))
    with pytest.raises(ValueError, match='digest'): evaluate(root / 'corpus', root / 'replay', policy)


def test_retained_report_cannot_be_silently_replaced(tmp_path):
    report = tmp_path / 'report'; shutil.copytree(REPORT, report)
    p = report / 'metrics.json'; data = json.loads(p.read_text()); data['product_defect_recall'] = 1.0; p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='report digest'): verify_snapshot(SNAPSHOT, report)
