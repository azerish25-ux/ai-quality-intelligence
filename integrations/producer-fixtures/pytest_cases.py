"""Disposable producer conformance scenarios, not LedgerGuard evaluation cases."""
import pytest


def test_pass():
    assert 2 + 2 == 4


def test_failure():
    print("synthetic contact fixture-person@example.com")
    assert 2 + 2 == 5, "controlled assertion intervention"


@pytest.mark.skip(reason="controlled skipped fixture")
def test_skip():
    pass


@pytest.mark.xfail(reason="known controlled fixture", strict=True)
def test_expected_failure():
    assert False


@pytest.mark.parametrize("value", [1, 2])
def test_parameterized(value):
    assert value > 0
