from datetime import UTC, datetime, timedelta

from failurelens.jobs import claim_next, complete, fail
from failurelens.models import Job, JobState
from failurelens.service import create_project


def test_job_claim_completion_and_retry(session) -> None:
    project = create_project(session, "jobs-project", "Jobs")
    first = Job(project_id=project.id, kind="noop", payload={})
    session.add(first)
    session.commit()
    claimed = claim_next(session, "worker-1", 30)
    assert claimed and claimed.state is JobState.running
    complete(session, claimed)
    assert claimed.state is JobState.succeeded

    second = Job(
        project_id=project.id,
        kind="unsupported",
        payload={},
        max_attempts=1,
        available_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    session.add(second)
    session.commit()
    claimed = claim_next(session, "worker-2", 30)
    assert claimed
    fail(session, claimed, "boom")
    assert claimed.state is JobState.dead_lettered
