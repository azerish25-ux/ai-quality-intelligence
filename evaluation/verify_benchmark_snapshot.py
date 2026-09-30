"""Verify and independently rescore retained M6.3 bytes, without fresh execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.benchmark_harness import evaluate


def extract_snapshot(archive: Path, destination: Path) -> None:
    if archive.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Snapshot compressed size exceeds policy")
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        names = [item.filename for item in infos]
        if (
            len(infos) > 5000
            or len(names) != len(set(names))
            or sum(i.file_size for i in infos) > 64 * 1024 * 1024
        ):
            raise ValueError("Snapshot is oversized or contains duplicate paths")
        for item in infos:
            path = PurePosixPath(item.filename)
            if (
                not path.parts
                or path.is_absolute()
                or ".." in path.parts
                or str(path) != item.filename
                or "\\" in item.filename
                or item.flag_bits & 1
                or stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG}
                or item.file_size > 32 * 1024 * 1024
                or path.parts[0] not in {"predictions.json", "safe-evidence", "reports"}
            ):
                raise ValueError("Unsafe snapshot path or member")
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            # Never extract over an existing target or follow a pre-existing link.
            if target.exists() or any(
                p.is_symlink() for p in target.parents if p.is_relative_to(destination)
            ):
                raise ValueError("Snapshot destination is not empty or safe")
            with source.open(item) as stream, target.open("xb") as output:
                remaining = item.file_size
                while remaining:
                    block = stream.read(min(65536, remaining))
                    if not block:
                        raise ValueError("Snapshot member is truncated")
                    output.write(block)
                    remaining -= len(block)
                if stream.read(1):
                    raise ValueError("Snapshot member exceeds declared bounds")


def verify(corpus: Path, report: Path) -> dict:
    metadata = json.loads((report / "retention.json").read_bytes())
    archive = report / "execution.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["snapshot_sha256"]:
        raise ValueError("Retained snapshot digest differs")
    expected_bytes = (report / "metrics.json").read_bytes()
    if hashlib.sha256(expected_bytes).hexdigest() != metadata["metrics_sha256"]:
        raise ValueError("Retained metric digest differs")
    with tempfile.TemporaryDirectory(prefix="failurelens-benchmark-verify-") as name:
        root = Path(name)
        extract_snapshot(archive, root)
        actual, _ = evaluate(corpus, root)
    if actual != json.loads(expected_bytes):
        raise ValueError("Independent rescore differs from the retained measurement")
    return {
        "status": "verified",
        "tested_source": actual["source_revision"],
        "case_count": actual["case_count"],
        "scope": "Retained bytes and independent rescoring only; no fresh API/worker or LedgerGuard execution.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, default=ROOT / "evaluation/corpus/benchmark-v1"
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "evaluation/reports/benchmark-v1"
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.corpus.resolve(), args.report.resolve()), indent=2))


if __name__ == "__main__":
    main()
