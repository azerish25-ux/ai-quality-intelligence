"""Authenticated safe-artifact routes; never serve restricted source storage."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .auth import Principal, current_principal, record_audit_event, require_project_role
from . import binary_evidence as binary
from .binary_schemas import (BinaryDecisionCreate, BinaryEvidencePage, BinaryEvidenceRead,
    ImageComparisonCreate, ImageComparisonRead, ScreenshotReview)
from .config import get_settings
from .db import get_session
from . import models as m
from .image_codec import ImageCodecError, decode_image

router = APIRouter(prefix="/api/v1", tags=["safe evidence"])


@router.get("/runs/{run_id}/binary-evidence", response_model=BinaryEvidencePage)
def list_binary(run_id: str, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                principal: Principal = Depends(current_principal), session: Session = Depends(get_session)):
    run = session.get(m.Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    require_project_role(session, principal, run.project_id)
    query = select(m.BinaryEvidence).where(m.BinaryEvidence.run_id == run.id, m.BinaryEvidence.project_id == run.project_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(m.BinaryEvidence.input_id).limit(limit).offset(offset))
    return BinaryEvidencePage(items=[binary.to_schema(session, row) for row in rows], total=total, offset=offset, limit=limit)


@router.get("/binary-evidence/{input_id}", response_model=BinaryEvidenceRead)
def get_binary(input_id: str, decision_offset: int = Query(0, ge=0),
               principal: Principal = Depends(current_principal), session: Session = Depends(get_session)):
    return binary.to_schema(session, binary.get_state(session, principal, input_id), decision_offset=decision_offset)


@router.post("/binary-evidence/{input_id}/screenshot-reviews", response_model=BinaryEvidenceRead, status_code=201)
async def review_image(input_id: str, request: Request, principal: Principal = Depends(current_principal),
                       session: Session = Depends(get_session)):
    # Authorize before buffering any untrusted body. Metadata belongs in the body,
    # not URLs or filenames that routinely appear in access logs.
    state = binary.get_state(session, principal, input_id)
    require_project_role(session, principal, state.project_id, m.ProjectRole.reviewer)
    if request.headers.get("content-type", "").split(";")[0] != "application/vnd.failurelens.image-review":
        raise HTTPException(415, "Expected the bounded image-review protocol")
    settings = get_settings()
    maximum = settings.max_file_bytes + 16_385

    async def receive() -> bytearray:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > maximum:
                raise binary._error("limit_exceeded", "Image review upload is too large", 413)
            data.extend(chunk)
        return data

    try:
        body = await asyncio.wait_for(receive(), timeout=30)
    except asyncio.TimeoutError as exc:
        raise binary._error("upload_timeout", "Image review upload exceeded its deadline", 408) from exc
    newline = body.find(b"\n")
    if newline < 0 or newline > 16_384:
        raise binary._error("invalid_review_header", "Image review metadata is missing or too large")
    try:
        options = ScreenshotReview.model_validate_json(bytes(body[:newline]))
    except ValidationError as exc:
        # Do not echo raw options, reasons or pixel content in diagnostics.
        raise binary._error("invalid_review_header", "Image review metadata failed validation") from exc
    content = bytes(body[newline + 1:])
    if len(content) > settings.max_file_bytes:
        raise binary._error("limit_exceeded", "Image exceeds file limit", 413)
    return await run_in_threadpool(binary.review_screenshot, session, principal, input_id, options, content, settings)


@router.post("/binary-evidence/{input_id}/decisions", response_model=BinaryEvidenceRead)
def decide_binary(input_id: str, options: BinaryDecisionCreate, principal: Principal = Depends(current_principal),
                  session: Session = Depends(get_session)):
    return binary.decide(session, principal, input_id, options)


@router.get("/binary-evidence/{input_id}/trace-events")
def trace_events(input_id: str, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                 principal: Principal = Depends(current_principal), session: Session = Depends(get_session)):
    state = binary.get_state(session, principal, input_id)
    if state.current_derivative_id is None:
        raise binary._error("artifact_restricted", "No approved trace index is available", 403)
    derivative, content = binary.read_derivative(session, principal, state.current_derivative_id)
    if derivative.kind != "safe-trace-index-v2":
        raise binary._error("not_trace", "Input is not a supported trace")
    index = json.loads(content)
    events = index["events"]
    return {"derivative_id": derivative.id, "digest": derivative.digest, "summary": index["summary"],
            "events": [{**item, "index": offset + i, "pointer": f"/events/{offset + i}"}
                       for i, item in enumerate(events[offset:offset + limit])],
            "total": len(events), "offset": offset, "limit": limit}


def _range(value: str, size: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", value)
    if not match or not any(match.groups()):
        raise HTTPException(416, "Only a single byte range is supported", headers={"Content-Range": f"bytes */{size}"})
    a, b = match.groups()
    start = int(a) if a else max(0, size - int(b))
    end = min(size - 1, int(b)) if a and b else size - 1
    if start >= size or start > end or (not a and int(b) == 0):
        raise HTTPException(416, "Unsatisfiable range", headers={"Content-Range": f"bytes */{size}"})
    return start, end


@router.get("/artifact-derivatives/{derivative_id}/content")
def derivative_content(derivative_id: str, request: Request, download: bool = False, preview: bool = False,
                       principal: Principal = Depends(current_principal), session: Session = Depends(get_session)):
    derivative, content = binary.read_derivative(session, principal, derivative_id)
    media_type = derivative.media_type
    if preview:
        if media_type != "image/png":
            raise binary._error("preview_not_image", "Image previews require approved PNG evidence")
        try:
            _, content = decode_image(content, get_settings(), encode=True, preview_size=1280)
        except ImageCodecError as exc:
            raise binary._error(exc.code, "Preview generation failed safely", 409) from exc
    suffix = "png" if media_type == "image/png" else "txt" if media_type == "text/plain" else "json"
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
               "Cross-Origin-Resource-Policy": "same-origin", "Referrer-Policy": "no-referrer",
               "Content-Security-Policy": "sandbox; default-src 'none'; frame-ancestors 'none'",
               "Content-Disposition": f'{"attachment" if download else "inline"}; filename="evidence-{derivative.id}.{suffix}"',
               "ETag": f'"{hashlib.sha256(content).hexdigest()}"', "X-Artifact-Digest": derivative.digest,
               "Accept-Ranges": "bytes"}
    response_status = 200
    if request.headers.get("range"):
        total = len(content)
        start, end = _range(request.headers["range"], total)
        content = content[start:end + 1]
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        response_status = 206
    record_audit_event(session, principal, project_id=derivative.project_id, action="artifact.safe_download" if download else "artifact.safe_preview",
        resource_type="run", resource_id=derivative.run_id, details={"derivative_id": derivative.id, "digest": derivative.digest})
    session.commit()
    return Response(content=content, status_code=response_status, media_type=media_type, headers=headers)


@router.post("/image-comparisons", response_model=ImageComparisonRead)
def image_comparison(options: ImageComparisonCreate, principal: Principal = Depends(current_principal),
                     session: Session = Depends(get_session)):
    return binary.compare_images(session, principal, options.expected_derivative_id, options.actual_derivative_id)
