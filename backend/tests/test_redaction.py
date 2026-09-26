from failurelens.redaction import redact_text


def test_redacts_declared_sensitive_classes_and_preserves_evidence() -> None:
    source = "Authorization: Bearer super-secret-token\nemail=alice@example.com\namount=29.00 status=500"
    result = redact_text(source)
    assert "super-secret-token" not in result.text
    assert "alice@example.com" not in result.text
    assert "amount=29.00" in result.text
    assert "status=500" in result.text
    assert set(result.classes) == {"authorization", "email"}


def test_terminal_escape_is_removed() -> None:
    result = redact_text("before\x1b[31mred\x1b[0mafter")
    assert "\x1b" not in result.text
    assert "CONTROL_SEQUENCE_REMOVED" in result.text
