"""Verify retained PostgreSQL finality evidence; never claim a fresh execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from evaluation.campaign_harness import evaluate
from evaluation.diagnostic_gap_audit import run as audit_gaps
from evaluation.verify_diagnostic_snapshot import bounded
from evaluation.verify_snapshot import unpack_snapshot
from integrations.ledgerguard.rollback_oracle import verify_observation

REPORT = ROOT / 'reports/transaction-finality-postgresql-v1'
MAX_BYTES = 2 * 1024 * 1024


def validate_execution(metrics: dict, rows: list, provenance: dict, retained: dict) -> None:
    """Recompute every control/intervention oracle, not just its stored PASS flag."""
    source = retained['tested_source_revision']
    if (metrics['source_revision'] != source or metrics['source_tree'] != retained['tested_source_tree']
            or metrics['source_worktree_dirty'] is not False or metrics['database_dialect'] != 'postgresql'
            or provenance['failurelens_revision'] != source or provenance['source_worktree_dirty'] is not False
            or provenance['ledgerguard_revision'] != retained['ledgerguard_revision']
            or not all(metrics['integrity_acceptance'].values())):
        raise ValueError('Missing exact-source PostgreSQL integrity evidence')
    if (len(rows) != 8 or metrics['case_count'] != 8 or metrics['family_count'] != 1
            or metrics['source_counts'] != {'ledgerguard_executed': 4, 'synthetic': 4, 'other_executed': 0}
            or metrics['evaluation_scope'] != 'development_contract_measurement'
            or any(metrics[k] is not False for k in ('held_out_acceptance', 'full_m6_complete', 'generalization_claim_allowed'))
            or metrics['unknown_family_test_cases'] != 0 or metrics['repeated_analysis_count'] != 5
            or metrics['claim_checks']['published'] != 4 or metrics['claim_checks']['supported'] != 4
            or metrics['product_defect_recall'] != 1 or metrics['errors']
            or provenance['executed_pairs'] != 4 or provenance['executed_families'] != 1
            or provenance['synthetic_cases'] != 4):
        raise ValueError('Transaction-finality development scope was misrepresented')
    receipts = provenance['oracle_receipts']
    if len(receipts) != 8:
        raise ValueError('Missing paired SQL/receipt evidence')
    pairs = {}
    for receipt in receipts:
        role, variant = receipt['role'], receipt['variant']
        if role not in {'control', 'observation'} or type(variant) is not int or variant not in range(4):
            raise ValueError('Invalid control/intervention identity')
        key = (role, variant)
        if key in pairs:
            raise ValueError('Duplicate control/intervention identity')
        expected = int(role == 'observation')
        actual = verify_observation(receipt['before'], receipt['after'], command=receipt['command'],
                                    response=receipt['response'], expected_effects=expected)
        if actual != receipt['oracle']:
            raise ValueError('Retained oracle differs from independent recomputation')
        pairs[key] = receipt
    for variant in range(4):
        if pairs['control', variant]['command'] != pairs['observation', variant]['command']:
            raise ValueError('Control and intervention monetary intent differ')


def verify_snapshot(report: Path = REPORT, *, extract_to: Path | None = None) -> dict:
    if extract_to is not None and (extract_to.exists() or extract_to.is_symlink()):
        raise ValueError('Extraction destination must not already exist')
    retained = json.loads(bounded(report / 'retention.json', 32768))
    if retained['schema_version'] != 'retained-finality-postgresql-v1':
        raise ValueError('Unsupported retained finality schema')
    compressed = bounded(report / 'execution.zip.xz')
    if hashlib.sha256(compressed).hexdigest() != retained['snapshot']['sha256']:
        raise ValueError('Retained finality snapshot digest mismatch')
    decoder = lzma.LZMADecompressor(memlimit=32 * 1024 * 1024)
    data = decoder.decompress(compressed, max_length=MAX_BYTES + 1)
    if len(data) > MAX_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError('Snapshot expansion or trailing-data limit')
    with tempfile.TemporaryDirectory(prefix='failurelens-finality-snapshot-') as work:
        archive, target = Path(work) / 'snapshot.zip', Path(work) / 'data'
        archive.write_bytes(data)
        unpack_snapshot(archive, target, retained['snapshot']['zip_sha256'], allow_input_bundles=True)
        actual_files = {p.relative_to(target).as_posix(): hashlib.sha256(bounded(p)).hexdigest()
                        for p in target.rglob('*') if p.is_file()}
        if actual_files != retained['file_sha256']:
            raise ValueError('Retained file inventory or digest mismatch')
        if bounded(report / 'report.md') != bounded(target / 'report/report.md'):
            raise ValueError('Visible report differs from retained execution')
        metrics, rows = evaluate(target / 'corpus', target / 'replay', enforce_minimums=False, score_split='development')
        if metrics != json.loads(bounded(target / 'report/metrics.json')):
            raise ValueError('Independent rescoring differs from retained metrics')
        provenance = json.loads(bounded(target / 'corpus/execution-provenance.json'))
        validate_execution(metrics, rows, provenance, retained)
        if audit_gaps(target / 'corpus', target / 'replay', kind='development') != json.loads(bounded(target / 'report/diagnostic-gaps.json')):
            raise ValueError('Diagnostic-gap audit differs from retained observations')
        if extract_to is not None:
            # copytree refuses overwrite, including a path created after the initial check.
            shutil.copytree(target, extract_to)
    return dict(tested_source_revision=metrics['source_revision'], database_dialect='postgresql',
                case_count=len(rows), executed_pairs=4, executed_families=1, synthetic_cases=4,
                published_supported_claims=4, held_out_acceptance=False, full_m6_complete=False,
                verification_scope='Retained bytes, independently recomputed oracles and rescoring; not fresh companion, PostgreSQL or browser execution.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=REPORT)
    parser.add_argument('--extract-to', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_snapshot(args.report, extract_to=args.extract_to), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
