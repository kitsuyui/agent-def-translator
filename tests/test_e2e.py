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
@pytest.mark.live
def test_e2e_live_cli_surfaces() -> None:
    run_script("bash", "scripts/e2e-smoke.sh", "--live")


@pytest.mark.e2e
@pytest.mark.live
@pytest.mark.model_live
def test_e2e_model_live() -> None:
    run_script("bash", "scripts/e2e-model-live.sh")
