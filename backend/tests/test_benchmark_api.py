import json
import pytest
from failurelens.config import get_settings


def test_benchmark_endpoint_reports_not_loaded(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FAILURELENS_BENCHMARK_EVALUATION_METRICS_PATH", str(tmp_path / "missing.json"))
    get_settings.cache_clear()
    response = client.get("/api/v1/evaluations/benchmark")
    assert response.status_code == 200
    assert response.json()["status"] == "not_loaded"


def test_benchmark_endpoint_preserves_failures_zeros_and_unknowns(client, tmp_path, monkeypatch):
    path = tmp_path / "metrics.json"
    data = {"evaluation_scope": "frozen_five_category_benchmark", "split": "test", "macro_f1": None,
            "product_defect_recall": 0, "quality_targets": {"recall": False}, "source_revision": "a"*40}
    path.write_text(json.dumps(data))
    monkeypatch.setenv("FAILURELENS_BENCHMARK_EVALUATION_METRICS_PATH", str(path)); get_settings.cache_clear()
    response = client.get("/api/v1/evaluations/benchmark")
    assert response.status_code == 200
    assert response.json()["metrics"] == data


@pytest.mark.parametrize("kind", ["oversized", "malformed", "wrong_scope", "wrong_split", "directory", "symlink", "nonfinite"])
def test_benchmark_endpoint_fails_closed_without_exposing_paths(client, tmp_path, monkeypatch, kind):
    path = tmp_path / "private-report.json"
    if kind == "oversized": path.write_bytes(b"x"*(2*1024*1024+1))
    elif kind == "malformed": path.write_bytes(b"not json")
    elif kind == "wrong_scope": path.write_text('{"evaluation_scope":"http_postgresql_fault_proxy","split":"test"}')
    elif kind == "wrong_split": path.write_text('{"evaluation_scope":"frozen_five_category_benchmark","split":"development"}')
    elif kind == "directory": path.mkdir()
    elif kind == "nonfinite": path.write_text('{"evaluation_scope":"frozen_five_category_benchmark","split":"test","macro_f1":NaN}')
    elif kind == "symlink": path.symlink_to(tmp_path / "absent-target")
    monkeypatch.setenv("FAILURELENS_BENCHMARK_EVALUATION_METRICS_PATH", str(path)); get_settings.cache_clear()
    response = client.get("/api/v1/evaluations/benchmark")
    assert response.status_code == 503
    assert "private-report" not in response.text
    assert str(tmp_path) not in response.text
