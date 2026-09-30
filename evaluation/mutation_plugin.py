"""Opt-in, subprocess-only pytest instrumentation. Never imported by runtime code."""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
from dataclasses import replace
from functools import wraps
from pathlib import Path

import pytest

from evaluation.mutation_cases import BY_ID

ROOT = Path(__file__).resolve().parents[1]
STATE: dict = {}


def pytest_addoption(parser):
    group = parser.getgroup("synthetic-safeguard-mutations")
    group.addoption("--safeguard-case", choices=tuple(BY_ID))
    group.addoption("--safeguard-mode", choices=("baseline", "mutant"))
    group.addoption("--safeguard-result")
    group.addoption("--safeguard-nonce")


def _deny_network(*args, **kwargs):
    raise RuntimeError("external networking is disabled in synthetic safeguard probes")


def _replace_aliases(original, replacement):
    # conftest imports the API before configure. Replace its imported aliases too;
    # test modules collected later then import the same instrumented function.
    for name, module in tuple(sys.modules.items()):
        if name == "failurelens" or name.startswith("failurelens."):
            for attribute, value in tuple(vars(module).items()):
                if value is original:
                    setattr(module, attribute, replacement)


def _install(case):
    module = importlib.import_module(case.module)
    expected = ROOT / "backend/src" / (case.module.replace(".", "/") + ".py")
    if Path(module.__file__).resolve() != expected:
        raise RuntimeError("runtime module is not from the measured checkout")
    owner = module
    path = case.target.split(".")
    for attribute in path[:-1]:
        owner = getattr(owner, attribute)
    original = getattr(owner, path[-1])
    STATE["runtime_source"] = str(expected.relative_to(ROOT))
    if STATE["mode"] == "baseline":
        return

    @wraps(original)
    def altered(*args, **kwargs):
        STATE["mutation_calls"] += 1
        if case.id == "authorization":
            from failurelens.models import ProjectRole

            return ProjectRole.administrator
        if case.id == "redaction":
            return original(*args, **kwargs)
        if case.id == "missing-citation":
            values, accepted_ids = args
            if (
                isinstance(values, list)
                and values
                and accepted_ids
                and not set(values) & accepted_ids
            ):
                STATE["effect_calls"] += 1
                return tuple(sorted(accepted_ids)[: len(values)])
            return original(*args, **kwargs)
        if case.id == "retry-as-run":
            result = original(*args, **kwargs)
            count = sum(item["attempt_count"] for item in result["observations"])
            if count != result["sample_sizes"]["independent_runs"]:
                STATE["effect_calls"] += 1
                result["sample_sizes"]["independent_runs"] = count
            return result
        if case.id == "timeout-to-flake":
            from failurelens.models import Category

            result = original(*args, **kwargs)
            if "timeout" in str(kwargs.get("exception_type", "")).casefold():
                STATE["effect_calls"] += 1
                return replace(
                    result, category=Category.known_flake, abstention_reason=None
                )
            return result
        if case.id == "missing-shard":
            expected_count, received_count, completeness = original(*args, **kwargs)
            if completeness != "complete":
                STATE["effect_calls"] += 1
            return expected_count, received_count, "complete"
        if case.id == "stale-report":
            # The original still performs its real HTTP-client lookup against the
            # existing MockTransport fixture; no GitHub connection is made.
            original(*args, **kwargs)
            STATE["effect_calls"] += 1
            return "a" * 40  # synthetic tested revision in the existing fixture
        raise RuntimeError("unregistered mutation")

    if case.id == "redaction":
        patterns = module._PATTERNS
        reduced = tuple(pair for pair in patterns if pair[0] != "authorization")
        if len(reduced) != len(patterns) - 1:
            raise RuntimeError(
                "authorization redaction mutation no longer matches source"
            )
        module._PATTERNS = reduced
    if owner is module:
        _replace_aliases(original, altered)
    else:
        setattr(owner, path[-1], altered)
    STATE["mutation_applied"] = True


def pytest_configure(config):
    if os.environ.get("FAILURELENS_SYNTHETIC_MUTATIONS") != "1":
        raise pytest.UsageError(
            "synthetic mutation plugin requires explicit runner opt-in"
        )
    case_id = config.getoption("safeguard_case")
    destination = config.getoption("safeguard_result")
    if (
        not case_id
        or not destination
        or not config.getoption("safeguard_mode")
        or not config.getoption("safeguard_nonce")
    ):
        raise pytest.UsageError("all safeguard runner arguments are required")
    result_path = Path(destination).resolve()
    if result_path.is_relative_to(ROOT) or result_path.exists():
        raise pytest.UsageError("child results must be fresh and outside the checkout")
    STATE.update(
        case_id=case_id,
        mode=config.getoption("safeguard_mode"),
        nonce=config.getoption("safeguard_nonce"),
        result_path=str(result_path),
        collected=[],
        collection_errors=0,
        phases=[],
        mutation_applied=False,
        mutation_calls=0,
        effect_calls=0,
    )
    socket.create_connection = _deny_network
    socket.socket.connect = _deny_network
    socket.socket.connect_ex = _deny_network
    _install(BY_ID[case_id])


def pytest_collection_finish(session):
    STATE["collected"] = [item.nodeid for item in session.items]


def pytest_collectreport(report):
    if report.failed:
        STATE["collection_errors"] += 1


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    phase = {"test_id": report.nodeid, "when": report.when, "outcome": report.outcome}
    if call.excinfo is not None:
        phase["exception_type"] = call.excinfo.type.__name__
        last = call.excinfo.traceback[-1]
        source = Path(str(last.path)).resolve()
        phase["assertion_in_test"] = (
            call.excinfo.type is AssertionError
            and source == Path(str(item.path)).resolve()
        )
        if source.is_relative_to(ROOT):
            phase["failure_source"] = str(source.relative_to(ROOT))
            phase["failure_line"] = last.lineno + 1
    STATE["phases"].append(phase)


def pytest_sessionfinish(session, exitstatus):
    STATE["exit_code"] = int(exitstatus)
    # These mutations take effect on every call rather than a conditional branch.
    if STATE["case_id"] in {"authorization", "redaction"}:
        STATE["effect_calls"] = STATE["mutation_calls"]
    payload = {key: value for key, value in STATE.items() if key != "result_path"}
    with Path(STATE["result_path"]).open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
