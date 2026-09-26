from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from .api import app  # noqa: F401
from .db import SessionLocal, initialize_database
from .demo import seed_demo
from .github_report import render_markdown
from .ingestion import parse_junit_xml, parse_playwright_json
from .models import Analysis, Failure, Project, Run
from .schemas import IngestionRequest, TestObservation
from .service import analyze_and_persist, create_project, ingest_normalized


def _load_report(path: Path) -> list[TestObservation]:
    content = path.read_bytes()
    if path.suffix.lower() == ".xml":
        parsed = parse_junit_xml(content)
    elif path.suffix.lower() == ".json":
        parsed = parse_playwright_json(content)
    else:
        raise SystemExit("unsupported input: expected .xml or .json")
    return [TestObservation(
        test_identity=o.test_identity,
        suite=o.suite,
        source_path=o.source_path,
        browser=o.browser,
        attempt=o.attempt,
        outcome=o.outcome,
        duration_ms=o.duration_ms,
        message=o.message,
        exception_type=o.exception_type,
        details=o.details,
    ) for o in parsed]


def main() -> None:
    parser = argparse.ArgumentParser(prog="failurelens")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("demo")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("report", type=Path)
    ingest.add_argument("--project", required=True)
    ingest.add_argument("--external-id", required=True)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--run", required=True)

    report = sub.add_parser("report")
    report.add_argument("--run", required=True)
    report.add_argument("--format", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args()
    initialize_database()
    with SessionLocal() as session:
        if args.command == "doctor":
            session.execute(select(1))
            print(json.dumps({"database": "ok", "deterministic_mode": True, "external_model_required": False}))
        elif args.command == "demo":
            print(json.dumps(seed_demo(session), indent=2))
        elif args.command == "ingest":
            project = session.scalar(select(Project).where(Project.slug == args.project)) or create_project(session, args.project, args.project)
            request = IngestionRequest(external_id=args.external_id, framework="auto", observations=_load_report(args.report))
            run = ingest_normalized(session, project, request)
            print(json.dumps({"run_id": run.id, "status": run.status.value, "received_inputs": run.received_inputs}))
        elif args.command == "analyze":
            failures = session.scalars(select(Failure).where(Failure.run_id == args.run)).all()
            results = [analyze_and_persist(session, failure) for failure in failures]
            print(json.dumps({"analyzed": len(results), "analysis_ids": [item.id for item in results]}))
        elif args.command == "report":
            run = session.get(Run, args.run)
            if not run:
                raise SystemExit("run not found")
            analyses = session.scalars(select(Analysis).join(Failure).where(Failure.run_id == run.id)).all()
            if args.format == "markdown":
                print(render_markdown(run, list(analyses)), end="")
            else:
                print(json.dumps({"run_id": run.id, "analyses": [{"id": a.id, "category": a.category.value, "summary": a.summary} for a in analyses]}, indent=2))


if __name__ == "__main__":
    main()
