from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from scripts import quality_checks as quality


def canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@pytest.fixture
def multipart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    scanner = {
        "version": "1.5.0",
        "plugins_used": [{"name": "KeywordDetector"}],
        "filters_used": [],
    }
    candidates = []
    entries = []
    for number in range(4):
        name = f"fixture-{number}.py"
        value = f"review-fixture-value-{number}"
        source = f'value = "{value}"\n'
        (tmp_path / name).write_text(source)
        candidate = {
            "file": name,
            "detector": "Secret Keyword",
            "value_sha256": digest(value.encode()),
            "file_sha256": digest(source.encode()),
            "line": 1,
            "occurrences": [
                {"line": 1, "context_sha256": digest(source.strip().encode())}
            ],
        }
        candidates.append(candidate)
        entries.append(
            {
                **{key: item for key, item in candidate.items() if key != "line"},
                "review_id": f"fixture-review-{number}",
                "classification": "intentional_fake_credential",
                "reason": "Purpose-built inert review fixture with no external account.",
                "evidence": f"{name}:1",
                "reviewed_by": "test fixture",
                "reviewed_on": "2026-09-30",
                "review_reference": "synthetic-review-test",
            }
        )
    logical = {"schema_version": 1, "scanner": scanner, "entries": entries}
    paths = []
    parts = []
    for number, batch in enumerate((entries[:2], entries[2:]), 1):
        name = f"{quality.REVIEW_PARTS_DIR}/part-{number:04}.json"
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = canonical({"schema_version": 1, "entries": batch})
        path.write_bytes(body)
        paths.append(path)
        parts.append({"path": name, "entry_count": len(batch), "sha256": digest(body)})
    index = {
        "schema_version": 2,
        "scanner": scanner,
        "entry_count": len(entries),
        "logical_sha256": digest(canonical(logical)),
        "parts": parts,
    }
    index_path = tmp_path / quality.SECRET_REVIEW_FILE
    index_path.write_bytes(canonical(index))
    monkeypatch.setattr(quality, "secret_occurrences", lambda *args: candidates)
    monkeypatch.setattr(quality, "signed_url_findings", lambda *args: [])
    return {
        "root": tmp_path,
        "original": canonical(logical),
        "index": index,
        "index_path": index_path,
        "parts": paths,
        "candidates": candidates,
        "files": [
            quality.SECRET_REVIEW_FILE,
            *(p["path"] for p in parts),
            *(e["file"] for e in entries),
        ],
        "raw": json.dumps({**scanner, "results": {}}),
    }


def scan(fixture: dict[str, Any]) -> dict[str, Any]:
    return quality.reviewed_secret_findings(
        fixture["raw"], fixture["files"], fixture["root"]
    )


def save_index(fixture: dict[str, Any]) -> None:
    fixture["index_path"].write_bytes(canonical(fixture["index"]))


def reconcile_index(fixture: dict[str, Any], *, logical_digest: bool = True) -> None:
    entries = []
    for declaration, path in zip(
        fixture["index"]["parts"], fixture["parts"], strict=True
    ):
        content = json.loads(path.read_bytes())
        declaration["sha256"] = digest(path.read_bytes())
        declaration["entry_count"] = len(content["entries"])
        entries.extend(content["entries"])
    fixture["index"]["entry_count"] = len(entries)
    if logical_digest:
        fixture["index"]["logical_sha256"] = digest(
            canonical(
                {
                    "schema_version": 1,
                    "scanner": fixture["index"]["scanner"],
                    "entries": entries,
                }
            )
        )
    save_index(fixture)


def add_metadata(fixture: dict[str, Any], name: str, number: int, value: str) -> None:
    fixture["candidates"].append(
        {
            "file": name,
            "line": number,
            "detector": "Hex High Entropy String",
            "value_sha256": digest(value.encode()),
            "occurrences": [{"line": number, "context_sha256": "unused-in-policy"}],
        }
    )


def test_parts_preserve_exact_original_logical_bytes_and_all_source_findings(multipart):
    logical, documents = quality.load_review_policy(
        multipart["root"], multipart["files"]
    )
    assert canonical(logical) == multipart["original"]
    assert len(documents) == 3
    result = scan(multipart)
    assert (
        result["raw_candidate_count"] == result["reviewed_source_candidate_count"] == 4
    )
    assert result["unresolved_candidate_count"] == 0
    assert result["review_policy_errors"] == []
    assert len(result["findings"]) == 4
    assert all(item["review_status"] == "reviewed" for item in result["findings"])


@pytest.mark.parametrize("field", ["sha256", "logical_sha256"])
def test_index_digests_are_metadata_only_after_recomputation(multipart, field):
    index = multipart["index"]
    value = index["parts"][0][field] if field == "sha256" else index[field]
    line = next(
        i
        for i, text in enumerate(multipart["index_path"].read_text().splitlines(), 1)
        if f'"{field}": "{value}"' in text
    )
    add_metadata(multipart, quality.SECRET_REVIEW_FILE, line, value)
    result = scan(multipart)
    assert result["reviewed_policy_candidate_count"] == 1
    assert result["raw_policy_candidate_count"] == 1
    assert result["unresolved_candidate_count"] == 0
    index["parts"][0]["sha256"] = "0" * 64
    save_index(multipart)
    failed = scan(multipart)
    assert failed["reviewed_candidate_count"] == 0
    assert failed["unresolved_candidate_count"] == 5


def test_metadata_approval_binds_file_line_and_value(multipart):
    source = multipart["parts"][0]
    value = json.loads(source.read_text())["entries"][0]["file_sha256"]
    line = next(
        i
        for i, text in enumerate(source.read_text().splitlines(), 1)
        if f'"file_sha256": "{value}"' in text
    )
    name = source.relative_to(multipart["root"]).as_posix()
    add_metadata(multipart, name, line, value)
    assert scan(multipart)["unresolved_candidate_count"] == 0
    candidate = multipart["candidates"][-1]
    candidate["file"] = multipart["index"]["parts"][1]["path"]
    assert scan(multipart)["unresolved_candidate_count"] == 1
    candidate["file"] = name
    candidate["occurrences"][0]["line"] += 1
    assert scan(multipart)["unresolved_candidate_count"] == 1
    candidate["occurrences"][0]["line"] -= 1
    candidate["value_sha256"] = digest(b"unrelated-value")
    assert scan(multipart)["unresolved_candidate_count"] == 1


def test_arbitrary_part_reason_digest_stays_unresolved(multipart):
    path = multipart["parts"][0]
    part = json.loads(path.read_text())
    value = part["entries"][0]["file_sha256"]
    part["entries"][0]["reason"] = value
    path.write_bytes(canonical(part))
    reconcile_index(multipart)
    line = next(
        i
        for i, text in enumerate(path.read_text().splitlines(), 1)
        if f'"reason": "{value}"' in text
    )
    add_metadata(multipart, path.relative_to(multipart["root"]).as_posix(), line, value)
    result = scan(multipart)
    assert result["review_policy_errors"] == []
    assert result["unresolved_candidate_count"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "unscanned",
        "phantom_inventory",
        "duplicate_path",
        "reordered_parts",
        "absolute",
        "traversal",
        "alias",
        "count",
        "bool_count",
        "total_count",
        "bool_total",
        "digest",
        "logical",
        "unknown",
        "empty",
        "too_many",
    ],
)
def test_invalid_part_inventory_or_manifest_disables_every_review(multipart, mutation):
    index = multipart["index"]
    if mutation == "missing":
        multipart["parts"][0].unlink()
    elif mutation == "extra":
        (multipart["parts"][0].parent / "unexpected.json").write_text("{}\n")
    elif mutation == "unscanned":
        multipart["files"].remove(index["parts"][0]["path"])
    elif mutation == "phantom_inventory":
        multipart["files"].append(quality.REVIEW_PARTS_DIR + "/extra.json")
    elif mutation == "duplicate_path":
        index["parts"][1]["path"] = index["parts"][0]["path"]
    elif mutation == "reordered_parts":
        index["parts"].reverse()
    elif mutation in {"absolute", "traversal", "alias"}:
        index["parts"][0]["path"] = {
            "absolute": "/etc/passwd",
            "traversal": "../part-0001.json",
            "alias": quality.REVIEW_PARTS_DIR + "/./part-0001.json",
        }[mutation]
    elif mutation in {"count", "bool_count"}:
        index["parts"][0]["entry_count"] = 1 if mutation == "count" else True
    elif mutation in {"total_count", "bool_total"}:
        index["entry_count"] = 3 if mutation == "total_count" else True
    elif mutation == "digest":
        index["parts"][0]["sha256"] = "0" * 64
    elif mutation == "logical":
        index["logical_sha256"] = "0" * 64
    elif mutation == "unknown":
        index["ignored"] = True
    elif mutation == "empty":
        index["parts"] = []
    else:
        index["parts"] *= quality.MAX_REVIEW_PARTS
    save_index(multipart)
    result = scan(multipart)
    assert result["review_policy_errors"]
    assert result["reviewed_candidate_count"] == 0
    assert result["raw_candidate_count"] == result["unresolved_candidate_count"] == 4


@pytest.mark.parametrize(
    "mutation",
    [
        "reorder",
        "duplicate",
        "review_id",
        "unknown",
        "schema",
        "empty_reason",
        "self",
        "source_guard",
        "scanner",
    ],
)
def test_part_content_is_revalidated_after_its_digest_is_updated(multipart, mutation):
    path = multipart["parts"][0]
    part = json.loads(path.read_text())
    if mutation == "reorder":
        part["entries"].reverse()
    elif mutation == "duplicate":
        part["entries"].append(copy.deepcopy(part["entries"][0]))
    elif mutation == "review_id":
        part["entries"][1]["review_id"] = part["entries"][0]["review_id"]
    elif mutation == "unknown":
        part["extra"] = True
    elif mutation == "schema":
        part["schema_version"] = True
    elif mutation == "empty_reason":
        part["entries"][0]["reason"] = " "
    elif mutation == "self":
        part["entries"][0]["file"] = path.relative_to(multipart["root"]).as_posix()
    elif mutation == "source_guard":
        part["entries"][0]["file_sha256"] = "0" * 64
    else:
        multipart["index"]["scanner"]["version"] = "different"
    path.write_bytes(canonical(part))
    reconcile_index(multipart, logical_digest=mutation != "reorder")
    result = scan(multipart)
    assert result["review_policy_errors"]
    if mutation == "reorder":
        assert result["review_policy_errors"] == [
            "secret-review-logical-digest-mismatch"
        ]
    assert result["reviewed_candidate_count"] == 0
    assert result["unresolved_candidate_count"] == 4


@pytest.mark.parametrize(
    "location", ["index", "part", "part_directory", "parent_directory"]
)
def test_symlinks_cannot_redirect_policy_reads(multipart, location):
    if location == "index":
        path = multipart["index_path"]
    elif location == "part":
        path = multipart["parts"][0]
    elif location == "part_directory":
        path = multipart["parts"][0].parent
    else:
        path = multipart["index_path"].parent
    saved = multipart["root"] / "preserved-policy-target"
    path.rename(saved)
    path.symlink_to(saved, target_is_directory=saved.is_dir())
    result = scan(multipart)
    assert result["reviewed_candidate_count"] == 0
    assert result["review_policy_errors"]


@pytest.mark.parametrize("location", ["index", "part"])
def test_named_pipes_fail_without_blocking(multipart, location):
    path = multipart["index_path"] if location == "index" else multipart["parts"][0]
    path.unlink()
    os.mkfifo(path)
    result = scan(multipart)
    assert result["review_policy_errors"] == ["nonregular-secret-review-file"]
    assert result["reviewed_candidate_count"] == 0


@pytest.mark.parametrize("location", ["index", "part"])
@pytest.mark.parametrize("mutation", ["duplicate_key", "noncanonical", "nesting"])
def test_part_and_index_parsing_remain_strict(multipart, location, mutation):
    path = multipart["index_path"] if location == "index" else multipart["parts"][0]
    content = json.loads(path.read_text())
    if mutation == "duplicate_key":
        path.write_text('{"schema_version":1,"schema_version":2}')
    elif mutation == "noncanonical":
        path.write_text(json.dumps(content))
    else:
        path.write_text("[" * 20 + "]" * 20)
    result = scan(multipart)
    assert result["review_policy_errors"]
    assert result["reviewed_candidate_count"] == 0


@pytest.mark.parametrize("limit", ["part_bytes", "total_bytes", "entries", "parts"])
def test_multipart_resource_limits_fail_closed(multipart, monkeypatch, limit):
    if limit == "part_bytes":
        maximum = max(path.stat().st_size for path in multipart["parts"])
        monkeypatch.setattr(quality, "MAX_REVIEW_PART_BYTES", maximum - 1)
    elif limit == "total_bytes":
        total = sum(
            path.stat().st_size
            for path in [multipart["index_path"], *multipart["parts"]]
        )
        monkeypatch.setattr(quality, "MAX_REVIEW_BYTES", total - 1)
    elif limit == "entries":
        monkeypatch.setattr(quality, "MAX_REVIEW_ENTRIES", 3)
    else:
        monkeypatch.setattr(quality, "MAX_REVIEW_PARTS", 1)
    result = scan(multipart)
    assert result["review_policy_errors"]
    assert result["reviewed_candidate_count"] == 0


def test_orphan_parts_cannot_silently_become_no_policy(multipart):
    multipart["index_path"].unlink()
    assert scan(multipart)["review_policy_errors"] == ["orphan-secret-review-parts"]
    multipart["index_path"].write_bytes(multipart["original"])
    assert scan(multipart)["review_policy_errors"] == ["orphan-secret-review-parts"]
