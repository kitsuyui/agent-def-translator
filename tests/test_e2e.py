import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> None:
    subprocess.run(  # noqa: S603
        args,
        cwd=PROJECT_ROOT,
        check=True,
    )


@pytest.mark.e2e
def test_e2e_smoke() -> None:
    run_script("bash", "scripts/e2e-smoke.sh")


@pytest.mark.e2e
def test_build_without_git_metadata_fails_before_publish(
    tmp_path: Path,
) -> None:
    repo_copy = tmp_path / "repo-copy"
    shutil.copytree(
        PROJECT_ROOT,
        repo_copy,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".pytest_cache",
            "__pycache__",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    uv = shutil.which("uv")
    assert uv is not None

    result = subprocess.run(  # noqa: S603
        (uv, "build"),
        cwd=repo_copy,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unable to detect version" in result.stderr
    assert "fallback_version" not in (repo_copy / "pyproject.toml").read_text(
        encoding="utf-8",
    )


@pytest.mark.e2e
@pytest.mark.live
def test_e2e_live_cli_surfaces() -> None:
    run_script("bash", "scripts/e2e-smoke.sh", "--live")


@pytest.mark.e2e
@pytest.mark.live
@pytest.mark.model_live
def test_e2e_model_live() -> None:
    run_script("bash", "scripts/e2e-model-live.sh")
