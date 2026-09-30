"""Validate retained HTTP/PostgreSQL evidence without claiming a fresh execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from evaluation.fullstack_harness import bounded_json, evaluate
from evaluation.verify_snapshot import unpack_snapshot

SNAPSHOT = ROOT / "corpus/ledgerguard-fullstack-v1/execution.zip.xz"
REPORT = ROOT / "reports/ledgerguard-fullstack-v1"
REPORT_FILES = {"metrics.json", "report.md", "predictions.jsonl"}


def verify_snapshot(archive: Path = SNAPSHOT, report: Path = REPORT) -> dict:
    retained = bounded_json(report / "retention.json")
    if set(retained["report_sha256"]) != REPORT_FILES:
        raise ValueError("Incomplete or unexpected retained report")
    for name, expected in retained["report_sha256"].items():
        path = report / name
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise ValueError("Unsafe retained report")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Retained report digest mismatch")
    expected_metrics = bounded_json(report / "metrics.json")
    with tempfile.TemporaryDirectory(prefix="failurelens-fullstack-snapshot-") as work:
        target = Path(work) / "data"
        if archive.is_symlink() or archive.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Unsafe or oversized compressed snapshot")
        compressed = archive.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != retained["snapshot"]["sha256"]:
            raise ValueError("Compressed snapshot digest mismatch")
        decoder = lzma.LZMADecompressor(memlimit=32 * 1024 * 1024)
        data = decoder.decompress(compressed, max_length=2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
            raise ValueError("Compressed snapshot expansion or trailing-data limit")
        unpacked_zip = Path(work) / "snapshot.zip"
        unpacked_zip.write_bytes(data)
        unpack_snapshot(
            unpacked_zip,
            target,
            retained["snapshot"]["zip_sha256"],
            allow_input_bundles=True,
        )
        metrics, rows = evaluate(target / "corpus", target / "replay")
        if metrics != expected_metrics:
            raise ValueError("Rescored metrics differ from retained executed results")
        for name in REPORT_FILES:
            if (target / "report" / name).read_bytes() != (report / name).read_bytes():
                raise ValueError(
                    "Retained report differs from the original CI artifact"
                )
        if (
            metrics["source_revision"] != retained["tested_source_revision"]
            or not re.fullmatch(r"[0-9a-f]{40}", metrics["source_revision"])
            or metrics["evaluation_scope"] != "http_postgresql_fault_proxy"
            or metrics["database_dialect"] != "postgresql"
            or not all(metrics["integrity_acceptance"].values())
        ):
            raise ValueError(
                "Snapshot lacks exact-source PostgreSQL/integrity acceptance"
            )
    return {
        "tested_source_revision": metrics["source_revision"],
        "case_count": len(rows),
        "family_count": metrics["family_count"],
        "dangerous_dismissal": metrics["dangerous_dismissal"],
        "control_abstentions": metrics["control_abstentions"],
        "quality_targets": metrics["quality_targets"],
        "verification_scope": "Retained artifact integrity and independent rescoring, not a fresh HTTP, PostgreSQL or browser execution.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=SNAPSHOT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    print(
        json.dumps(verify_snapshot(args.archive, args.report), sort_keys=True, indent=2)
    )


if __name__ == "__main__":
    main()
