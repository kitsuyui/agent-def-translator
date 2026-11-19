import os
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
    assert not (PROJECT_ROOT / ".tmp" / "e2e-smoke").exists()


@pytest.mark.parametrize(
    ("script", "work_root_environment"),
    [
        ("scripts/e2e-smoke.sh", "E2E_WORK_ROOT"),
        ("scripts/e2e-model-live.sh", "E2E_MODEL_LIVE_WORK_ROOT"),
    ],
)
def test_e2e_scripts_clean_work_root_after_failure(
    tmp_path: Path,
    script: str,
    work_root_environment: str,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env sh\nexit 1\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    work_root = tmp_path / "work-root"
    environment = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        work_root_environment: str(work_root),
    }
    bash = shutil.which("bash")
    assert bash is not None

    result = subprocess.run(  # noqa: S603
        (bash, script),
        cwd=PROJECT_ROOT,
        check=False,
        env=environment,
    )

    assert result.returncode != 0
    assert not work_root.exists()


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
