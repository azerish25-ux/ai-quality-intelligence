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


def test_embedded_authorization_and_sensitive_mapping_fields_are_redacted() -> None:
    from failurelens.redaction import redact_sensitive_field

    embedded = redact_text(
        "request failed; Authorization: Bearer top-secret-bearer-value; retrying"
    )
    assert "top-secret-bearer-value" not in embedded.text
    assert "authorization" in embedded.classes
    assert embedded.text.endswith("; retrying")

    token = redact_sensitive_field("access_token", "top-secret-bearer-value")
    email = redact_sensitive_field("customer_email", "customer@example.com")
    ordinary = redact_sensitive_field("amount", "29.00")
    assert token is not None and "top-secret-bearer-value" not in token.text
    assert token.classes == ("api_key",)
    assert email is not None and "customer@example.com" not in email.text
    assert email.classes == ("email",)
    assert ordinary is None


def test_phone_redaction_preserves_digest_tokens_but_not_sensitive_fields() -> None:
    from failurelens.redaction import redact_sensitive_field

    # Regression: digit runs in a random request digest must retain their identity.
    digest = "a" * 24 + "4165550123" + "b" * 30
    assert len(digest) == 64
    assert redact_text(digest).text == digest
    for field in ("phone", "customer_phone", "access_token", "password"):
        restricted = redact_sensitive_field(field, digest)
        assert restricted is not None and digest not in restricted.text
    for phone in ("4165550123", "+1 416 555 0123", "(416) 555-0123", "416.555.0123"):
        result = redact_text(f"phone: {phone}; response=500")
        assert phone not in result.text and "phone" in result.classes
        assert "response=500" in result.text
    assert digest not in redact_text("Authorization: Bearer " + digest).text
