"""HTTP replay must preserve durable binary results without resurrecting originals."""
from failurelens import models as m
from failurelens.config import get_settings
from failurelens.jobs import process_next
from failurelens.retention import _scrub_run
from test_binary_evidence import bundle_bytes, ingest


def test_http_replay_of_discarded_binary_original_is_idempotent_and_conflicts_still_clean_up(client, session):
    project_id, _, _, _ = ingest(client, session)
    bundle, _ = bundle_bytes()
    # Source bytes are intentionally not retained. Capture a new external-ID
    # upload and replay that same buffer after durable processing.
    url = f"/api/v1/projects/{project_id}/ingestions"
    params = {"external_id": "replay-binary", "filename": "replay.zip"}
    queued = client.post(url, params=params, content=bundle, headers={"content-type": "application/zip"})
    assert queued.status_code == 202
    assert process_next(session, "replay-worker", settings=get_settings())
    result = queued.json()
    source = session.get(m.Ingestion, result["id"])
    assert source.source_expired_at is not None
    source_path = get_settings().artifact_root/source.storage_path
    assert not source_path.exists()
    replay = client.post(url, params=params, content=bundle, headers={"content-type": "application/zip"})
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == result["id"] and replay.json()["state"] == "partial"
    assert not source_path.exists()
    conflict = client.post(url, params={**params, "branch": "changed"}, content=bundle,
                           headers={"content-type": "application/zip"})
    assert conflict.status_code == 409 and not source_path.exists()
    run = session.get(m.Run, source.run_id)
    _scrub_run(session, run, 1); session.commit()
    expired = client.post(url, params=params, content=bundle, headers={"content-type": "application/zip"})
    assert expired.status_code == 409 and not source_path.exists()
