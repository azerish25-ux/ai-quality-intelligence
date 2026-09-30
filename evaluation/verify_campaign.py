"""Verify and unpack the immutable campaign. This does not execute the application."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.campaign_contract import audit, bounded_read
from evaluation.generate_campaign import unpack

ARCHIVE = ROOT / "evaluation/corpus/diverse-v1/corpus.json.xz"
RETENTION = ARCHIVE.with_name("retention.json")


def verify(output: Path, archive: Path = ARCHIVE, retention: Path = RETENTION) -> dict:
    metadata = json.loads(bounded_read(retention, 64 * 1024))
    if metadata.get("version") != "campaign-retention-v1":
        raise ValueError("Unknown campaign retention version")
    unpack(archive, output, metadata["archive_sha256"])
    inventory = audit(output)[0]
    if (
        inventory["freeze_sha256"] != metadata["freeze_sha256"]
        or inventory["public_manifest_sha256"] != metadata["public_manifest_sha256"]
    ):
        raise ValueError("Retained campaign metadata differs")
    return {
        **inventory,
        "verification_scope": "Frozen bytes only; no fresh companion or inference execution.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), indent=2))


if __name__ == "__main__":
    main()
