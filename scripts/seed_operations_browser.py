"""Disposable API-backed browser fixture; never enabled in application startup."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from failurelens.config import get_settings
from failurelens.db import SessionLocal
from failurelens.models import Evidence, Failure, utcnow
from failurelens.retention import policy_for
from failurelens.schemas import IngestionRequest
from failurelens.service import analyze_and_persist, create_project, ingest_normalized
from sqlalchemy import select


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-disposable-database", action="store_true", required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not get_settings().demo_mode:
        raise SystemExit("Browser fixture generation requires explicit demo mode.")
    fixtures = {}
    for browser in ("chromium-desktop", "firefox-desktop", "webkit-desktop"):
        for attempt in (0, 1):
            with SessionLocal() as session:
                project = create_project(
                    session,
                    f"m53-{uuid4().hex}",
                    f"M5.3 disposable {browser} {attempt}",
                )
                policy = policy_for(session, project.id)
                policy.source_days = policy.evidence_days = 365
                session.commit()
                run = ingest_normalized(
                    session,
                    project,
                    IngestionRequest.model_validate(
                        {
                            "external_id": "retention-old-run",
                            "observations": [
                                {
                                    "test_identity": "retention-old-payment",
                                    "outcome": "failed",
                                    "message": "duplicate transfer committed and ledger became unbalanced",
                                    "details": {"data_integrity_violation": True},
                                }
                            ],
                        }
                    ),
                )
                failure = session.scalar(
                    select(Failure).where(Failure.run_id == run.id)
                )
                analyze_and_persist(session, failure)
                run.created_at = utcnow() - timedelta(days=100)
                session.commit()
                evidence = session.scalar(
                    select(Evidence).where(Evidence.run_id == run.id)
                )
                fixtures[f"{browser}:{attempt}"] = {
                    "project_id": project.id,
                    "run_id": run.id,
                    "failure_id": failure.id,
                    "evidence_id": evidence.id,
                }
                # Put the investigation outside the legacy recent-runs window.
                for number in range(101):
                    ingest_normalized(
                        session,
                        project,
                        IngestionRequest.model_validate(
                            {
                                "external_id": f"newer-{number}",
                                "observations": [
                                    {
                                        "test_identity": "passing-control",
                                        "outcome": "passed",
                                    }
                                ],
                            }
                        ),
                    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixtures, indent=2) + "\n")
    print(f"Created {len(fixtures)} isolated fixtures at {args.output}")


if __name__ == "__main__":
    main()
