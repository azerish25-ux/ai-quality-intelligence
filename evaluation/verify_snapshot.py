"""Verify and independently rescore the compact, retained CI execution snapshot."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from evaluation.artifact_contract import load_manifest, read_artifact
from evaluation.executed_harness import evaluate

SNAPSHOT = ROOT / "corpus/ledgerguard-component-v1/execution.zip"
REPORT = ROOT / "reports/ledgerguard-component-v1-7405d923"


def unpack_snapshot(
    archive: Path,
    destination: Path,
    expected_digest: str,
    *,
    allow_input_bundles: bool = False,
) -> None:
    """Only extract bounded regular data files into a newly created private directory."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("invalid archive digest")
    if archive.is_symlink() or archive.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("unsafe or oversized snapshot")
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise ValueError("snapshot digest mismatch")
    if destination.exists():
        raise ValueError("snapshot destination must not already exist")
    destination.mkdir(mode=0o700, parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        infos = source.infolist()
        if (
            not 1 <= len(infos) <= 1000
            or sum(i.file_size for i in infos) > 4 * 1024 * 1024
        ):
            raise ValueError("snapshot expansion limit exceeded")
        seen: set[str] = set()
        for info in infos:
            path = PurePosixPath(info.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or str(path) != info.filename
                or info.is_dir()
                or path.parts[0]
                not in {"corpus", "replay", "report", "legacy-audit.json"}
                or (
                    path.suffix not in {".json", ".jsonl", ".xml", ".md"}
                    and not (
                        allow_input_bundles
                        and path.suffix == ".zip"
                        and len(path.parts) == 4
                        and path.parts[:2] == ("corpus", "inputs")
                    )
                )
                or stat.S_IFMT(info.external_attr >> 16) not in {0, stat.S_IFREG}
                or info.filename in seen
                or info.file_size > 1024 * 1024
                or info.file_size > max(1, info.compress_size) * 100
            ):
                raise ValueError("unsafe snapshot entry")
            seen.add(info.filename)
            content = source.read(info)
            if len(content) != info.file_size:
                raise ValueError("snapshot entry length mismatch")
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open("xb") as stream:
                stream.write(content)


def verify_snapshot(archive: Path = SNAPSHOT, report: Path = REPORT) -> dict:
    retained = json.loads((report / "retention.json").read_bytes())
    expected_metrics = json.loads((report / "metrics.json").read_bytes())
    for name, digest in retained["report_sha256"].items():
        if name not in {"metrics.json", "report.md", "predictions.jsonl"}:
            raise ValueError("unexpected retained report")
        if hashlib.sha256((report / name).read_bytes()).hexdigest() != digest:
            raise ValueError("retained report digest mismatch")
    with tempfile.TemporaryDirectory(prefix="failurelens-snapshot-") as work:
        target = Path(work) / "data"
        unpack_snapshot(archive, target, retained["artifact"]["sha256"])
        manifest = load_manifest(target / "corpus/inputs")
        for case in manifest.cases:
            for reference in case.inputs:
                read_artifact(target / "corpus/inputs", reference)
        policy = json.loads(
            (ROOT / "policies/ledgerguard-component-v1.json").read_bytes()
        )
        metrics, rows = evaluate(target / "corpus", target / "replay", policy)
        if metrics != expected_metrics:
            raise ValueError("rescored metrics differ from the retained actual results")
        for name in retained["report_sha256"]:
            if (target / "report" / name).read_bytes() != (report / name).read_bytes():
                raise ValueError(
                    "retained report does not match originating CI artifact"
                )
        if (
            metrics["source_revision"] != retained["tested_source_revision"]
            or metrics["source_worktree_dirty"]
        ):
            raise ValueError("source revision or dirty-tree provenance mismatch")
        if metrics["database_dialect"] != "postgresql" or not all(
            metrics["integrity_acceptance"].values()
        ):
            raise ValueError("snapshot lacks PostgreSQL/integrity acceptance")
    return {
        "case_count": len(rows),
        "family_count": metrics["family_count"],
        "dangerous_dismissal": metrics["dangerous_dismissal"],
        "quality_targets": metrics["quality_targets"],
        "tested_source_revision": metrics["source_revision"],
        "verification_scope": "retained artifact validation and deterministic rescoring; not a fresh LedgerGuard or PostgreSQL execution",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=SNAPSHOT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    print(
        json.dumps(verify_snapshot(args.archive, args.report), indent=2, sort_keys=True)
    )


if __name__ == "__main__":
    main()
