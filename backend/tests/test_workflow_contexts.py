import subprocess
from pathlib import Path

import pytest

from scripts import quality_checks as quality


def test_workflow_job_environments_do_not_use_runner_context() -> None:
    """GitHub evaluates job env before allocating a runner (contexts reference)."""
    import re

    import yaml

    for path in (quality.ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        environments = [workflow.get("env", {})]
        environments.extend(job.get("env", {}) for job in workflow["jobs"].values())
        for environment in environments:
            for value in environment.values():
                assert not re.search(r"\$\{\{[^}]*\brunner[.\[]", value), path.name


@pytest.mark.parametrize("job_name", ["checks", "npm-audit"])
def test_quality_cache_paths_are_exported_from_allocated_runner(
    tmp_path: Path, job_name: str
) -> None:
    import yaml

    workflow = yaml.load(
        (quality.ROOT / ".github/workflows/quality-security.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    first_step = workflow["jobs"][job_name]["steps"][0]
    environment_file = tmp_path / "runner environment"
    allocated_temp = tmp_path / "runner temp with spaces"
    result = subprocess.run(
        ["bash", "-eu", "-c", first_step["run"]],
        env={"RUNNER_TEMP": str(allocated_temp), "GITHUB_ENV": str(environment_file)},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    exported = dict(
        line.split("=", 1) for line in environment_file.read_text().splitlines()
    )
    expected = {
        "PIP_CACHE_DIR": "quality-pip-cache",
        "XDG_CACHE_HOME": "quality-cache",
        "NPM_CONFIG_CACHE": "quality-npm-cache",
    }
    if job_name == "checks":
        expected["UV_CACHE_DIR"] = "quality-uv-cache"
    assert exported == {
        key: str(allocated_temp / leaf) for key, leaf in expected.items()
    }
