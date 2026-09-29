"""Retained development evidence must stay byte-exact and independently rescorable."""
from pathlib import Path
import json
import hashlib
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.verify_diagnostic_snapshot import REPORT, verify_snapshot


def test_retained_diagnostic_snapshot_independently_rescores():
    result = verify_snapshot()
    assert result['case_count'] == 32
    assert result['product_recall'] == 1
    assert result['dangerous_dismissal']['numerator'] == 0
    assert result['held_out_acceptance'] is False
    assert result['full_m6_complete'] is False


@pytest.mark.parametrize('name', ['metrics.json', 'report.md', 'predictions.jsonl', 'execution.zip.xz'])
def test_retained_diagnostic_tampering_is_rejected(tmp_path, name):
    target = tmp_path / 'retained'
    shutil.copytree(REPORT, target)
    with (target / name).open('ab') as stream:
        stream.write(b'altered')
    with pytest.raises(ValueError, match='digest mismatch'):
        verify_snapshot(target)


def test_retained_diagnostic_trailing_stream_rejected_even_with_updated_digest(tmp_path):
    target = tmp_path / 'retained'
    shutil.copytree(REPORT, target)
    archive = target / 'execution.zip.xz'
    archive.write_bytes(archive.read_bytes() + b'trailing data')
    meta = json.loads((target / 'retention.json').read_bytes())
    meta['snapshot']['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (target / 'retention.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='trailing-data'):
        verify_snapshot(target)


def test_retained_diagnostic_report_symlink_rejected(tmp_path):
    target = tmp_path / 'retained'
    shutil.copytree(REPORT, target)
    (target / 'metrics.json').unlink()
    (target / 'metrics.json').symlink_to(REPORT / 'metrics.json')
    with pytest.raises(ValueError, match='Unsafe'):
        verify_snapshot(target)
