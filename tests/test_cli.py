from __future__ import annotations

from pathlib import Path

import pytest

from agent_def_translator.cli import main


def test_cli_subagent_validate_and_translate(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    (definitions_dir / "sample.toml").write_text(
        "\n".join(
            [
                'name = "sample"',
                'description = "Sample"',
                'instructions = "Base instructions"',
                "",
                "[targets.codex]",
                'sandbox_mode = "read-only"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "generated"

    assert (
        main(
            [
                "subagent",
                "validate",
                "--definitions-dir",
                str(definitions_dir),
            ],
        )
        == 0
    )
    translate_args = [
        "subagent",
        "translate",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    diff_args = [
        "subagent",
        "diff",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    assert main(translate_args) == 0
    assert main(diff_args) == 0

    generated = output_dir / "codex" / "agents" / "sample.toml"
    generated.write_text("stale", encoding="utf-8")

    assert main(diff_args) == 1


def test_cli_validate_renders_selected_targets(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    (definitions_dir / "sample.toml").write_text(
        "\n".join(
            [
                'name = "sample"',
                'description = "Sample"',
                'instructions = "Base instructions"',
                "",
                "[targets.claude]",
                'prompt_append_file = "missing.md"',
                "",
                "[targets.codex]",
                'sandbox_mode = "read-only"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    base_args = [
        "subagent",
        "validate",
        "--definitions-dir",
        str(definitions_dir),
    ]

    assert main([*base_args, "--target", "codex"]) == 0
    assert main([*base_args, "--target", "claude"]) == 2


def test_cli_translate_subagent_resource(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    (definitions_dir / "sample.toml").write_text(
        "\n".join(
            [
                'name = "sample"',
                'description = "Sample"',
                'instructions = "Base instructions"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "generated"

    assert (
        main(
            [
                "subagent",
                "translate",
                "--definitions-dir",
                str(definitions_dir),
                "--output-dir",
                str(output_dir),
            ],
        )
        == 0
    )

    assert (output_dir / "codex" / "agents" / "sample.toml").exists()


@pytest.mark.parametrize(
    ("args", "replacement"),
    [
        (["translate"], "subagent translate"),
        (["translate-agents"], "subagent translate"),
        (["agent", "translate"], "subagent translate"),
    ],
)
def test_cli_deprecated_subagent_aliases_warn(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    replacement: str,
) -> None:
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    (definitions_dir / "sample.toml").write_text(
        "\n".join(
            [
                'name = "sample"',
                'description = "Sample"',
                'instructions = "Base instructions"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "generated"

    assert (
        main(
            [
                *args,
                "--definitions-dir",
                str(definitions_dir),
                "--output-dir",
                str(output_dir),
            ],
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "deprecated" in captured.err
    assert replacement in captured.err


def test_cli_skill_validate_translate_and_diff(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "skills"
    definitions_dir.mkdir()
    (definitions_dir / "hello.toml").write_text(
        "\n".join(
            [
                'name = "hello"',
                'description = "Say hello."',
                'instructions = "Reply with a greeting."',
                "",
                "[targets.codex]",
                'display_name = "Hello"',
                "allow_implicit_invocation = true",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "generated"

    assert (
        main(["skill", "validate", "--definitions-dir", str(definitions_dir)])
        == 0
    )
    translate_args = [
        "skill",
        "translate",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    diff_args = [
        "skill",
        "diff",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    assert main(translate_args) == 0
    assert main(diff_args) == 0

    generated = output_dir / "codex" / "skills" / "hello" / "SKILL.md"
    assert generated.exists()
    generated.write_text("stale", encoding="utf-8")

    assert main(diff_args) == 1


def test_cli_mcp_validate_translate_and_diff(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "mcp"
    definitions_dir.mkdir()
    (definitions_dir / "openai-docs.toml").write_text(
        "\n".join(
            [
                'name = "openai-docs"',
                'description = "OpenAI documentation MCP server."',
                'transport = "http"',
                'url = "https://developers.openai.com/mcp"',
                "",
                "[targets.codex]",
                'server_name = "openaiDeveloperDocs"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "generated"

    assert (
        main(["mcp", "validate", "--definitions-dir", str(definitions_dir)])
        == 0
    )
    translate_args = [
        "mcp",
        "translate",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    diff_args = [
        "mcp",
        "diff",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    assert main(translate_args) == 0
    assert main(diff_args) == 0

    generated = output_dir / "codex" / "mcp" / "openai-docs.toml"
    assert generated.exists()
    generated.write_text("stale", encoding="utf-8")

    assert main(diff_args) == 1
