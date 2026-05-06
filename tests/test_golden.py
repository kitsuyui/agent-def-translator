from __future__ import annotations

from pathlib import Path

from agent_def_translator import Target, load_definition, render

FIXTURES = Path(__file__).parent / "fixtures"


def test_generated_artifacts_match_golden_files() -> None:
    definition_path = FIXTURES / "agents" / "repo-explorer.toml"
    definition = load_definition(
        definition_path,
        root_dir=FIXTURES / "agents",
    )
    expectations = {
        Target.CLAUDE: FIXTURES / "golden" / "repo-explorer.claude.md",
        Target.CODEX: FIXTURES / "golden" / "repo-explorer.codex.toml",
        Target.COPILOT: FIXTURES / "golden" / "repo-explorer.copilot.agent.md",
    }

    for target, expected_path in expectations.items():
        assert render(definition, target) == expected_path.read_text(
            encoding="utf-8",
        )
