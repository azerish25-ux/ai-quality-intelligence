"""Audit retained decisions by family without inferring an unobserved failure cause.

Evaluation-only. Scoring verifies the saved pipeline output first; this command
neither reruns inference nor reads a label into the ordinary application. An old
record without instrumentation is not silently called a missing-input failure.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.campaign_contract import bounded_read, canonical, digest

GAPS = {'publication_rejection', 'missing_or_invalid_observations',
        'contradictory_observations', 'unresolved_evidence_or_capability'}
NEXT_CHECK = {
    'publication_rejection': 'Inspect rejected claims, execution binding and publication predicates.',
    'missing_or_invalid_observations': 'Compare original producer artifacts with normalized observations; do not assume which stage lost evidence.',
    'contradictory_observations': 'Inspect competing observations and scope before changing classification.',
    'unresolved_evidence_or_capability': 'Review observable evidence and parser/predicate coverage; no automatic root-cause attribution.',
    'legacy_uninstrumented': 'Replay as regression with diagnostic instrumentation, then compare original and normalized artifacts.',
    'supported_decision': 'Retain claim/evidence regression; this is not independent generalization evidence.',
}


def summarize(metrics: dict, scored: list[dict], replay: dict, *, analysis_field: str = "analysis") -> dict:
    """Bounded audit projection of independently scored records; no raw excerpts."""
    if analysis_field not in {'analysis', 'published'}:
        raise ValueError('Unsupported explicit replay analysis envelope')
    cases = replay.get('cases')
    if not isinstance(cases, list) or len(cases) > 1000:
        raise ValueError('Invalid or oversized replay cases')
    by_id = {p['case_id']: p for p in cases}
    if len(by_id) != len(cases) or len(scored) != len(cases) or set(by_id) != {r['case_id'] for r in scored}:
        raise ValueError('Scored/replayed case identities differ')
    groups = defaultdict(list)
    rows = []
    for row in scored:
        case_id = row['case_id']
        analysis = by_id[case_id][analysis_field]
        predicted = analysis['category']
        scored_prediction = row.get('predicted', row.get('modes', {}).get('full_deterministic'))
        if predicted != scored_prediction:
            raise ValueError('Scored/published category differs')
        validation = analysis.get('validation_results', {})
        if not isinstance(validation, dict):
            raise ValueError('Malformed diagnostic metadata')
        gap = validation.get('diagnostic_gap')
        if gap is not None and gap not in GAPS:
            raise ValueError('Unknown diagnostic gap: do not guess its meaning')
        stage = gap or ('legacy_uninstrumented' if predicted == 'insufficient_evidence' and 'diagnostic_gap' not in validation
                        else 'unresolved_evidence_or_capability' if predicted == 'insufficient_evidence' else 'supported_decision')
        findings = validation.get('diagnostic_findings', [])
        if not isinstance(findings, list) or len(findings) > 1000:
            raise ValueError('Malformed or oversized diagnostic findings')
        family = row.get('scenario_family_id', row.get('family_group'))
        if not isinstance(family, str) or not 1 <= len(family) <= 240:
            raise ValueError('Missing family identity')
        result = dict(case_id=case_id, scenario_family_id=family, split=row['split'], source_kind=row['source_kind'],
            expected_category=row['expected_category'], predicted_category=predicted,
            mismatch=predicted != row['expected_category'], diagnostic_stage=stage,
            recorded_findings=len(findings), published_claim_count=len(analysis.get('claims', [])),
            artifact_adjudication_required=stage != 'supported_decision', next_check=NEXT_CHECK[stage])
        rows.append(result)
        groups[(family, row['split'])].append(result)
    return dict(version='diagnostic-gap-audit-v1', measured_source_revision=metrics['source_revision'],
        scope='Retained pipeline-output audit; no new inference, label adjudication or held-out claim.',
        case_count=len(rows), mismatches=sum(r['mismatch'] for r in rows),
        stage_counts=dict(sorted(Counter(r['diagnostic_stage'] for r in rows).items())),
        families=[dict(scenario_family_id=family, split=split, cases=len(items),
                       mismatches=sum(r['mismatch'] for r in items),
                       stages=dict(sorted(Counter(r['diagnostic_stage'] for r in items).items())))
                  for (family, split), items in sorted(groups.items())],
        cases=rows, limitations=[
            'Diagnostic metadata localizes a reported boundary; it does not prove whether evidence was absent at the producer or lost during normalization.',
            'Agent-authored labels and family groupings still need observable-evidence adjudication.',
            'Inspected test cases are regression evidence, never a newly held-out result.',
            'Raw artifacts, secrets, reviewer notes and arbitrary diagnostic text are not copied into this projection.'])


def run(corpus: Path, replay_root: Path, *, kind: str) -> dict:
    # Existing scorers independently check immutable input and published evidence.
    if kind == 'benchmark':
        from evaluation.benchmark_harness import evaluate
        metrics, scored = evaluate(corpus, replay_root)
    elif kind == 'development':
        from evaluation.campaign_harness import evaluate
        metrics, scored = evaluate(corpus, replay_root, enforce_minimums=False, score_split='development')
    else:
        raise ValueError('Unsupported audit source')
    data = bounded_read(replay_root/'predictions.json', 32*1024*1024)
    result = summarize(metrics, scored, json.loads(data), analysis_field='published' if kind == 'benchmark' else 'analysis')
    result['replay_sha256'] = digest(data)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--kind', choices=['benchmark', 'development'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(args.corpus.resolve()) or output.is_relative_to(args.replay.resolve()):
        raise ValueError('Audit output must be separate from immutable corpus and replay')
    result = run(args.corpus, args.replay, kind=args.kind)
    with output.open('xb') as target:
        target.write(canonical(result))
    print(json.dumps({k: result[k] for k in ('case_count', 'mismatches', 'stage_counts')}, indent=2))


if __name__ == '__main__':
    main()
