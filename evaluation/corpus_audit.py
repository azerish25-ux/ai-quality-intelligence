"""Audit the legacy generator without rewriting its historical corpus or scores."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def audit_legacy(cases: list[dict]) -> dict:
    # This conservative key describes the five templates in generator-v1, not
    # an automatic universal root-cause adjudication algorithm.
    groups: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        key = str(case.get("root_cause") or "unknown-timeout-observation-template")
        groups[key].append(case)
    leakage = [
        {
            "mechanism": key,
            "splits": sorted({c["split"] for c in rows}),
            "case_count": len(rows),
        }
        for key, rows in sorted(groups.items())
        if len({c["split"] for c in rows}) > 1
    ]
    return {
        "audit_version": "legacy-generator-v1-mechanism-audit",
        "case_count": len(cases),
        "declared_family_ids": len({c["scenario_family_id"] for c in cases}),
        "conservative_mechanism_count": len(groups),
        "cross_split_mechanisms": leakage,
        "source_counts": {
            kind: sum(c["source_kind"] == kind for c in cases)
            for kind in ("synthetic", "ledgerguard_executed", "other_executed")
        },
        "generalization_claim_allowed": False,
        "classification": "legacy rule-regression fixture, not independent held-out families",
        "limitations": [
            "Mechanisms are grouped by reviewed generator-v1 root-cause templates; different family IDs do not establish diversity.",
            "Historical metrics and fixtures are retained unchanged. This audit does not create new independent cases.",
        ],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus/cases.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.corpus.read_bytes()
    report = audit_legacy(
        [json.loads(line) for line in raw.splitlines() if line.strip()]
    )
    report["corpus_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
