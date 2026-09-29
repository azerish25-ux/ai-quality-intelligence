"""Integrity regressions over retained execution, not new LedgerGuard executions."""
import hashlib
import io
import json
import lzma
from pathlib import Path
import shutil
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.fullstack_harness import SUBSTANTIVE, digest, evaluate
from evaluation.verify_fullstack_snapshot import SNAPSHOT as ARCHIVE, REPORT, verify_snapshot as verify_fullstack_snapshot
from evaluation.verify_snapshot import unpack_snapshot


def extracted(tmp_path):
    retained = json.loads((REPORT / 'retention.json').read_bytes())
    archive = tmp_path / 'original.zip'
    archive.write_bytes(lzma.decompress(ARCHIVE.read_bytes(), memlimit=32 * 1024 * 1024))
    target = tmp_path / 'original'
    unpack_snapshot(archive, target, retained['snapshot']['zip_sha256'], allow_input_bundles=True)
    return target


def test_retained_http_postgresql_snapshot_rescores_independently():
    result = verify_fullstack_snapshot()
    assert result['case_count'] == 8 and result['family_count'] == 1
    assert result['control_abstentions'] == 4
    assert result['dangerous_dismissal']['numerator'] == 0
    assert 'not a fresh' in result['verification_scope']


@pytest.mark.parametrize('fault', ['claim_text', 'empty_claims', 'input_role', 'repetitions'])
def test_saved_outputs_cannot_forge_supported_claims_or_roles(tmp_path, fault):
    root = extracted(tmp_path)
    path = root / 'replay/predictions.json'
    values = json.loads(path.read_bytes())
    case = values['cases'][0]
    analysis = case['role_analyses']['observation'][0]
    if fault == 'claim_text':
        analysis['claims'][0]['text'] = 'LedgerGuard itself caused this defect and is safe to release.'
    elif fault == 'empty_claims':
        analysis['claims'] = []
    elif fault == 'input_role':
        case['inputs'][0]['role'] = 'observation'
    else:
        case['repeat_digests']['observation'] = [['0' * 64] * 5]
    if fault in {'claim_text', 'empty_claims'}:
        # A forger can recompute hashes; independent semantic checks must still reject it.
        case['repeat_digests']['observation'] = [[digest(json.dumps({key: analysis[key] for key in SUBSTANTIVE}, sort_keys=True).encode())] * 5]
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        evaluate(root / 'corpus', root / 'replay')


@pytest.mark.parametrize('fault', ['bytes', 'symlink', 'expansion', 'trailing', 'report'])
def test_snapshot_rejects_changed_or_unsafe_content(tmp_path, fault):
    report = tmp_path / 'report'
    shutil.copytree(REPORT, report)
    archive = tmp_path / 'execution.zip.xz'
    archive.write_bytes(ARCHIVE.read_bytes())
    metadata = json.loads((report / 'retention.json').read_bytes())
    if fault == 'bytes':
        archive.write_bytes(archive.read_bytes()[:-1] + b'!')
    elif fault == 'symlink':
        archive.unlink()
        archive.symlink_to(ARCHIVE)
    elif fault == 'expansion':
        archive.write_bytes(lzma.compress(b'x' * (2 * 1024 * 1024 + 1)))
        metadata['snapshot']['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    elif fault == 'trailing':
        archive.write_bytes(archive.read_bytes() + b'ignored suffix')
        metadata['snapshot']['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    else:
        (report / 'metrics.json').write_text('{}')
    (report / 'retention.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        verify_fullstack_snapshot(archive, report)


@pytest.mark.parametrize('name', ['corpus/inputs/c-one/../../escape.zip', 'replay/unauthorized.zip'])
def test_nested_bundle_permission_does_not_relax_path_checks(tmp_path, name):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as stream:
        stream.writestr(name, b'not an authorized bundle')
    archive = tmp_path / 'malicious.zip'
    archive.write_bytes(out.getvalue())
    with pytest.raises(ValueError, match='unsafe snapshot entry'):
        unpack_snapshot(archive, tmp_path / 'unpack', hashlib.sha256(out.getvalue()).hexdigest(), allow_input_bundles=True)
