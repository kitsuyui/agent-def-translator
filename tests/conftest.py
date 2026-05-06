from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="run E2E tests that invoke repository scripts",
    )
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run live E2E tests that inspect installed external CLIs",
    )
    parser.addoption(
        "--run-model-live",
        action="store_true",
        default=False,
        help="run live E2E tests that call external model APIs",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    skip_e2e = pytest.mark.skip(
        reason="need --run-e2e option to run",
    )
    skip_live = pytest.mark.skip(
        reason="need --run-live option to run",
    )
    skip_model_live = pytest.mark.skip(
        reason="need --run-model-live option to run",
    )

    run_e2e = config.getoption("--run-e2e")
    run_live = config.getoption("--run-live")
    run_model_live = config.getoption("--run-model-live")

    for item in items:
        keywords = item.keywords
        if "model_live" in keywords and not run_model_live:
            item.add_marker(skip_model_live)
        if "live" in keywords and not run_live:
            item.add_marker(skip_live)
        if "e2e" in keywords and not run_e2e:
            item.add_marker(skip_e2e)
