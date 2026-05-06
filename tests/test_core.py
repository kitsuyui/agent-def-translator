from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent_def_translator import (
    DefinitionError,
    Target,
    check_drift,
    generate,
    load_definition,
    render,
    validate_definitions,
)


def write_sample(root: Path) -> Path:
    definitions_dir = root / "agents"
    prompt_dir = root / "prompts"
    definitions_dir.mkdir()
    prompt_dir.mkdir()
    (prompt_dir / "sample.claude.md").write_text(
        "Claude appendix",
        encoding="utf-8",
    )
    spec = definitions_dir / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            '''
            name = "sample"
            description = "Sample agent"
            instructions = """
            Base instructions
            """

            [targets.claude]
            tools = ["Read", "Grep"]
            permission_mode = "plan"
            prompt_append_file = "../prompts/sample.claude.md"

            [targets.codex]
            model = "gpt-5.4-mini"
            sandbox_mode = "read-only"

            [targets.copilot]
            tools = ["search", "fetch"]
            target = "vscode"
            ''',
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return spec


def test_render_all_targets(tmp_path: Path) -> None:
    spec = write_sample(tmp_path)
    definition = load_definition(spec, root_dir=tmp_path / "agents")

    claude = render(definition, Target.CLAUDE)
    codex = render(definition, Target.CODEX)
    copilot = render(definition, Target.COPILOT)

    assert "Claude appendix" in claude
    assert 'sandbox_mode = "read-only"' in codex
    assert 'target: "vscode"' in copilot


def test_render_uses_prompt_override_and_hides_prompt_controls(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "Sample"
            instructions = "Base instructions"

            [targets.codex]
            prompt_override = "Codex only"
            prompt_append = "Appendix"
            sandbox_mode = "read-only"
            [targets.codex.experimental]
            enabled = true
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    rendered = render(load_definition(spec), Target.CODEX)

    assert 'developer_instructions = "Codex only\\n\\nAppendix"' in rendered
    assert 'sandbox_mode = "read-only"' in rendered
    assert "[experimental]" in rendered
    assert "prompt_override" not in rendered
    assert "prompt_append" not in rendered


def test_generate_and_drift_check(tmp_path: Path) -> None:
    write_sample(tmp_path)
    output_dir = tmp_path / "generated"

    artifacts = generate(
        definitions_dir=tmp_path / "agents",
        output_dir=output_dir,
    )

    assert len(artifacts) == 3
    assert (output_dir / "claude" / "agents" / "sample.md").exists()
    assert (output_dir / "codex" / "agents" / "sample.toml").exists()
    assert (output_dir / "copilot" / "agents" / "sample.agent.md").exists()
    assert (
        check_drift(
            definitions_dir=tmp_path / "agents",
            output_dir=output_dir,
        )
        == []
    )

    generated = output_dir / "codex" / "agents" / "sample.toml"
    generated.write_text("stale", encoding="utf-8")

    assert check_drift(
        definitions_dir=tmp_path / "agents",
        output_dir=output_dir,
    ) == [generated]


def test_validate_definitions_renders_prompt_append_files(
    tmp_path: Path,
) -> None:
    write_sample(tmp_path)

    definitions = validate_definitions(tmp_path / "agents")

    assert [definition.name for definition in definitions] == ["sample"]


def test_legacy_target_tables_are_accepted(tmp_path: Path) -> None:
    spec = tmp_path / "legacy.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "legacy"
            description = "Legacy shape"
            instructions = "Base instructions"

            [vscode]
            tools = ["search"]
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    definition = load_definition(spec)

    assert definition.targets[Target.COPILOT]["tools"] == ["search"]


def test_filename_must_match_definition_name(tmp_path: Path) -> None:
    spec = tmp_path / "wrong-file.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "Sample"
            instructions = "Base instructions"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match="filename stem must match name"):
        load_definition(spec)


def test_target_table_must_be_table(tmp_path: Path) -> None:
    spec = tmp_path / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "Sample"
            instructions = "Base instructions"
            [targets]
            claude = "bad"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match=r"\[targets.claude\]"):
        load_definition(spec)


def test_prompt_append_controls_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "Sample"
            instructions = "Base instructions"

            [targets.claude]
            prompt_append = "inline"
            prompt_append_file = "appendix.md"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match="mutually exclusive"):
        render(load_definition(spec), Target.CLAUDE)


def test_unknown_top_level_field_fails(tmp_path: Path) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "bad"
            description = "Bad"
            instructions = "Base instructions"
            unexpected = true
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError):
        load_definition(spec)


def test_missing_prompt_append_file_fails(tmp_path: Path) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "bad"
            description = "Bad"
            instructions = "Base instructions"

            [targets.claude]
            prompt_append_file = "missing.md"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    definition = load_definition(spec, root_dir=tmp_path)

    with pytest.raises(DefinitionError):
        render(definition, Target.CLAUDE)
