from failurelens.fingerprint import make_fingerprint, normalize_message


def test_nuisance_values_normalize_without_erasing_status() -> None:
    first = "2026-01-01T10:00:00Z request 550e8400-e29b-41d4-a716-446655440000 failed at api.py:51 with HTTP 401"
    second = "2026-02-02T11:22:33Z request 4b65a4ce-4559-4ea9-9a8c-4fd45c895bbb failed at api.py:90 with HTTP 401"
    assert normalize_message(first) == normalize_message(second)
    changed = second.replace("401", "500")
    assert normalize_message(first) != normalize_message(changed)


def test_fingerprint_is_deterministic() -> None:
    a, features_a = make_fingerprint("boom at file.py:12", "RuntimeError", {"http_status": 500})
    b, features_b = make_fingerprint("boom at file.py:99", "RuntimeError", {"http_status": 500})
    assert a == b
    assert features_a == features_b
