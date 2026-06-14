from __future__ import annotations

from pathlib import Path

import pytest

from agent_def_translator.cli import main

_ACTIVE_COMMANDS = ("subagent", "skill", "mcp", "plugin")
_DEPRECATED_COMMANDS = (
    "agent",
    "validate",
    "validate-agents",
    "translate",
    "translate-agents",
    "diff",
    "diff-agents",
)


def test_cli_help_shows_only_active_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "{subagent,skill,mcp,plugin}" in help_text
    for cmd in _ACTIVE_COMMANDS:
        assert cmd in help_text
    # Deprecated commands must not appear as listed subcommands.
    # Leading spaces avoid matching "agent" inside "agent-def-translator".
    for cmd in _DEPRECATED_COMMANDS:
        assert f"    {cmd}" not in help_text
    assert "Deprecated" not in help_text


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
    assert "no earlier than agent-def-translator 1.0.0" in captured.err
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


def test_cli_plugin_validate_translate_and_diff(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    (generated / "claude" / "agents").mkdir(parents=True)
    (generated / "claude" / "agents" / "hello.md").write_text(
        "hello agent\n",
        encoding="utf-8",
    )
    (generated / "claude" / "skills" / "hello").mkdir(parents=True)
    (generated / "claude" / "skills" / "hello" / "SKILL.md").write_text(
        "hello skill\n",
        encoding="utf-8",
    )
    (generated / "claude" / "mcp").mkdir(parents=True)
    (generated / "claude" / "mcp" / "hello.json").write_text(
        '{"mcpServers": {"hello": {"type": "http", "url": "https://example.com"}}}\n',
        encoding="utf-8",
    )

    definitions_dir = tmp_path / "plugins"
    definitions_dir.mkdir()
    (definitions_dir / "hello-bundle.toml").write_text(
        "\n".join(
            [
                'name = "hello-bundle"',
                'description = "Bundle hello components."',
                'version = "0.1.0"',
                'author = "Example Maintainer"',
                "",
                "[components]",
                "subagents = true",
                "skills = true",
                "mcp = true",
                "",
                "[targets.codex]",
                "enabled = false",
                "",
                "[targets.copilot]",
                "enabled = false",
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        main(["plugin", "validate", "--definitions-dir", str(definitions_dir)])
        == 0
    )
    translate_args = [
        "plugin",
        "translate",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(generated),
    ]
    diff_args = [
        "plugin",
        "diff",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(generated),
    ]
    assert main(translate_args) == 0
    assert main(diff_args) == 0

    manifest = (
        generated
        / "claude"
        / "plugins"
        / "hello-bundle"
        / ".claude-plugin"
        / "plugin.json"
    )
    assert manifest.exists()
    manifest.write_text("stale", encoding="utf-8")

    assert main(diff_args) == 1


def test_cli_toml_syntax_error_exits_with_code_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    (definitions_dir / "bad.toml").write_text(
        "this is not valid toml ===\n",
        encoding="utf-8",
    )
    result = main(
        ["subagent", "validate", "--definitions-dir", str(definitions_dir)],
    )
    assert result == 2
    assert "error:" in capsys.readouterr().err
