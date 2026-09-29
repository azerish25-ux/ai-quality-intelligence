"""Independently verify retained diagnostic development evidence, not fresh execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from evaluation.campaign_harness import evaluate
from evaluation.verify_snapshot import unpack_snapshot

REPORT = ROOT / 'reports/diagnostic-development-v1'
REPORT_FILES = {'metrics.json', 'report.md', 'predictions.jsonl'}
MAX_BYTES = 2 * 1024 * 1024


def bounded(path: Path, limit: int = MAX_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Unsafe or oversized retained diagnostic file')
    return path.read_bytes()


def verify_snapshot(report: Path = REPORT) -> dict:
    retained = json.loads(bounded(report / 'retention.json', 16384))
    if set(retained['report_sha256']) != REPORT_FILES:
        raise ValueError('Incomplete or unexpected retained report')
    expected_source = retained['tested_source_revision']
    if not re.fullmatch(r'[0-9a-f]{40}', expected_source):
        raise ValueError('Missing exact tested revision')
    for name, expected in retained['report_sha256'].items():
        if hashlib.sha256(bounded(report / name)).hexdigest() != expected:
            raise ValueError('Retained diagnostic report digest mismatch')
    expected_metrics = json.loads(bounded(report / 'metrics.json'))
    compressed = bounded(report / 'execution.zip.xz')
    if hashlib.sha256(compressed).hexdigest() != retained['snapshot']['sha256']:
        raise ValueError('Compressed diagnostic snapshot digest mismatch')
    decoder = lzma.LZMADecompressor(memlimit=32 * 1024 * 1024)
    data = decoder.decompress(compressed, max_length=MAX_BYTES + 1)
    if len(data) > MAX_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError('Diagnostic snapshot expansion or trailing-data limit')
    with tempfile.TemporaryDirectory(prefix='failurelens-diagnostic-snapshot-') as work:
        archive = Path(work) / 'snapshot.zip'
        archive.write_bytes(data)
        target = Path(work) / 'data'
        unpack_snapshot(archive, target, retained['snapshot']['zip_sha256'], allow_input_bundles=True)
        metrics, rows = evaluate(target / 'corpus', target / 'replay', enforce_minimums=False, score_split='development')
        if metrics != expected_metrics:
            raise ValueError('Rescored diagnostic metrics differ from retained results')
        for name in REPORT_FILES:
            if bounded(target / 'report' / name) != bounded(report / name):
                raise ValueError('Retained report differs from originating artifact')
        provenance = json.loads(bounded(target / 'corpus/execution-provenance.json'))
        receipts = provenance['oracle_receipts']
        if (metrics['source_revision'] != expected_source or metrics['source_worktree_dirty']
                or metrics['database_dialect'] != 'postgresql'
                or not all(metrics['integrity_acceptance'].values())
                or provenance['failurelens_revision'] != expected_source or provenance['source_worktree_dirty']
                or provenance['executed_pairs'] != 12 or provenance['executed_families'] != 3
                or len(receipts) != 12 or not all(r['control_passed'] and r['intervention_failed'] for r in receipts)):
            raise ValueError('Missing exact-source PostgreSQL, paired execution or integrity evidence')
        if (len(rows) != 32 or metrics['evaluation_scope'] != 'development_contract_measurement'
                or metrics['held_out_acceptance'] or metrics['full_m6_complete']
                or metrics['generalization_claim_allowed'] or metrics['unknown_family_test_cases'] != 0
                or metrics['source_counts']['ledgerguard_executed'] != 12 or metrics['source_counts']['synthetic'] != 20):
            raise ValueError('Diagnostic development scope was misrepresented')
    return dict(tested_source_revision=expected_source, case_count=len(rows),
                product_recall=metrics['product_defect_recall'], dangerous_dismissal=metrics['dangerous_dismissal'],
                full_m6_complete=False, held_out_acceptance=False,
                verification_scope='Retained bytes and independent rescoring; not fresh companion, PostgreSQL or browser execution.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=REPORT)
    print(json.dumps(verify_snapshot(parser.parse_args().report), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
