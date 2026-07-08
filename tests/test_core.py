from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Literal, cast

import pytest

import agent_def_translator._common as common
from agent_def_translator import (
    DefinitionError,
    McpConfigDefinition,
    PluginDefinition,
    SkillDefinition,
    Target,
    check_drift,
    check_mcp_config_drift,
    check_plugin_drift,
    check_skill_drift,
    generate,
    generate_mcp_configs,
    generate_plugins,
    generate_skills,
    load_definition,
    load_mcp_config_definition,
    load_plugin_definition,
    load_skill_definition,
    mcp_output_path,
    output_path,
    plugin_manifest_output_path,
    plugin_root_path,
    render,
    render_mcp_config,
    render_plugin_manifest,
    render_skill,
    skill_output_path,
    validate_definitions,
    validate_mcp_config_definitions,
    validate_plugin_definitions,
    validate_skill_definitions,
)
from agent_def_translator._common import GeneratedArtifact


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


def test_target_is_not_str_subclass() -> None:
    assert Target.CLAUDE != "claude"
    assert not isinstance(Target.CLAUDE, str)


def test_subagent_public_helpers_accept_raw_target_names(
    tmp_path: Path,
) -> None:
    spec = write_sample(tmp_path)
    definition = load_definition(spec, root_dir=tmp_path / "agents")

    assert "Claude appendix" in render(definition, "claude")
    assert output_path(tmp_path, "sample", "claude") == (
        tmp_path / "claude" / "agents" / "sample.md"
    )

    artifacts = generate(
        definitions_dir=tmp_path / "agents",
        output_dir=tmp_path / "generated",
        targets=("claude", "codex", "copilot"),
        write=False,
    )

    assert [artifact.target for artifact in artifacts] == [
        Target.CLAUDE,
        Target.CODEX,
        Target.COPILOT,
    ]


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


def test_yaml_nested_mapping_order_is_deterministic(tmp_path: Path) -> None:
    spec = tmp_path / "sample.toml"
    first_payload = """
        name = "sample"
        description = "Sample"
        instructions = "Base instructions"

        [targets.copilot]
        target = "vscode"

        [targets.copilot.metadata]
        zeta = "last"
        alpha = "first"
        items = [{ zeta = "last", alpha = "first" }]
    """
    second_payload = """
        name = "sample"
        description = "Sample"
        instructions = "Base instructions"

        [targets.copilot]
        target = "vscode"

        [targets.copilot.metadata]
        alpha = "first"
        zeta = "last"
        items = [{ alpha = "first", zeta = "last" }]
    """

    spec.write_text(
        textwrap.dedent(first_payload).strip() + "\n",
        encoding="utf-8",
    )
    first = render(load_definition(spec), Target.COPILOT)
    spec.write_text(
        textwrap.dedent(second_payload).strip() + "\n",
        encoding="utf-8",
    )
    second = render(load_definition(spec), Target.COPILOT)

    assert first == second
    assert first.index("  alpha:") < first.index("  zeta:")
    assert first.index("      alpha:") < first.index("      zeta:")


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


def test_write_artifact_cleans_tmp_file_on_baseexception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Path] = []

    class ArtificialInterrupt(BaseException):
        pass

    class InterruptingTempFile:
        def __init__(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> None:
            directory = cast(str | Path, _kwargs["dir"])
            suffix = cast(str, _kwargs["suffix"])
            self.path = Path(directory) / f"artifact{suffix}"
            self.path.write_bytes(b"")
            self.name = str(self.path)
            created.append(self.path)

        def __enter__(self) -> InterruptingTempFile:
            return self

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> Literal[False]:
            return False

        def write(self, _content: bytes) -> int:
            raise ArtificialInterrupt

    monkeypatch.setattr(
        common.tempfile,
        "NamedTemporaryFile",
        InterruptingTempFile,
    )

    artifact = GeneratedArtifact(
        target=Target.CODEX,
        source_path=tmp_path / "source.toml",
        output_path=tmp_path / "generated.toml",
        content="content",
    )

    with pytest.raises(ArtificialInterrupt):
        common._write_artifact(artifact)

    assert created == [tmp_path / "artifact.tmp"]
    assert not created[0].exists()
    assert not artifact.output_path.exists()


def test_write_artifacts_batch_cleans_tmp_files_on_baseexception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Path] = []

    class ArtificialInterrupt(BaseException):
        pass

    class InterruptingSecondTempFile:
        def __init__(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> None:
            directory = cast(str | Path, _kwargs["dir"])
            suffix = cast(str, _kwargs["suffix"])
            self.index = len(created)
            self.path = Path(directory) / f"artifact-{self.index}{suffix}"
            self.path.write_bytes(b"")
            self.name = str(self.path)
            created.append(self.path)

        def __enter__(self) -> InterruptingSecondTempFile:
            return self

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> Literal[False]:
            return False

        def write(self, content: bytes) -> int:
            if self.index == 1:
                raise ArtificialInterrupt
            self.path.write_bytes(content)
            return len(content)

    monkeypatch.setattr(
        common.tempfile,
        "NamedTemporaryFile",
        InterruptingSecondTempFile,
    )

    artifacts = [
        GeneratedArtifact(
            target=Target.CODEX,
            source_path=tmp_path / "source-one.toml",
            output_path=tmp_path / "generated-one.toml",
            content="one",
        ),
        GeneratedArtifact(
            target=Target.CLAUDE,
            source_path=tmp_path / "source-two.toml",
            output_path=tmp_path / "generated-two.md",
            content="two",
        ),
    ]

    with pytest.raises(ArtificialInterrupt):
        common._write_artifacts_batch(artifacts)

    assert created == [
        tmp_path / "artifact-0.tmp",
        tmp_path / "artifact-1.tmp",
    ]
    assert all(not path.exists() for path in created)
    assert all(not artifact.output_path.exists() for artifact in artifacts)


def test_validate_definitions_renders_prompt_append_files(
    tmp_path: Path,
) -> None:
    write_sample(tmp_path)

    definitions = validate_definitions(tmp_path / "agents")

    assert [definition.name for definition in definitions] == ["sample"]


def test_legacy_target_tables_are_accepted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    captured = capsys.readouterr()
    assert "[vscode]" in captured.err
    assert "no earlier than agent-def-translator 1.0.0" in captured.err


def test_legacy_and_targets_conflict_is_rejected(tmp_path: Path) -> None:
    spec = tmp_path / "conflict.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "conflict"
            description = "Conflict shape"
            instructions = "Base instructions"

            [targets.claude]
            tools = ["Read"]

            [claude]
            tools = ["Bash"]
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match="configured twice"):
        load_definition(spec)


def test_legacy_alias_and_targets_conflict_is_rejected(tmp_path: Path) -> None:
    spec = tmp_path / "conflict-alias.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "conflict-alias"
            description = "Conflict via vscode alias"
            instructions = "Base instructions"

            [targets.copilot]
            tools = ["search"]

            [vscode]
            tools = ["fetch"]
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match="configured twice"):
        load_definition(spec)


def test_new_targets_syntax_emits_no_deprecation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = tmp_path / "modern.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "modern"
            description = "Modern shape"
            instructions = "Base instructions"

            [targets.claude]
            tools = ["Read"]
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    load_definition(spec)

    captured = capsys.readouterr()
    assert "deprecated" not in captured.err


@pytest.mark.parametrize(
    "tool_key",
    ["tools", "allowedTools", "disallowedTools"],
)
def test_claude_empty_tool_lists_render_as_yaml_lists(
    tmp_path: Path,
    tool_key: str,
) -> None:
    spec = tmp_path / "empty-tools.toml"
    spec.write_text(
        textwrap.dedent(
            f"""
            name = "empty-tools"
            description = "Empty tool list"
            instructions = "Base instructions"

            [targets.claude]
            {tool_key} = []
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    rendered = render(load_definition(spec), Target.CLAUDE)

    assert f"{tool_key}: []" in rendered
    assert f'{tool_key}: ""' not in rendered


def test_subagent_output_path_is_publicly_exported(tmp_path: Path) -> None:
    from agent_def_translator import output_path

    expected = tmp_path / "claude" / "agents" / "sample.md"
    assert output_path(tmp_path, "sample", Target.CLAUDE) == expected


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


@pytest.mark.parametrize(
    "path_kind",
    ["absolute", "windows_absolute", "parent"],
)
def test_prompt_append_file_rejects_paths_outside_project_root(
    tmp_path: Path,
    path_kind: str,
) -> None:
    if path_kind == "absolute":
        prompt_append_file = str((tmp_path / "appendix.md").resolve())
    elif path_kind == "windows_absolute":
        prompt_append_file = "C:/outside/appendix.md"
    else:
        prompt_append_file = "../../appendix.md"
    spec = tmp_path / "agents" / "bad.toml"
    spec.parent.mkdir()
    spec.write_text(
        textwrap.dedent(
            f"""
            name = "bad"
            description = "Bad"
            instructions = "Base instructions"

            [targets.claude]
            prompt_append_file = "{prompt_append_file}"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    definition = load_definition(spec, root_dir=tmp_path / "agents")

    with pytest.raises(
        DefinitionError,
        match=r"prompt_append_file must (be a relative path|stay within)",
    ):
        render(definition, Target.CLAUDE)


def write_mcp_sample(root: Path) -> Path:
    definitions_dir = root / "mcp"
    definitions_dir.mkdir()
    spec = definitions_dir / "openai-docs.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "openai-docs"
            description = "OpenAI documentation MCP server."
            transport = "http"
            url = "https://developers.openai.com/mcp"
            tools = ["search"]

            [targets.codex]
            server_name = "openaiDeveloperDocs"

            [targets.claude]
            server_name = "openaiDeveloperDocs"

            [targets.copilot]
            server_name = "openaiDeveloperDocs"
            tools = ["*"]
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return spec


def write_skill_sample(root: Path) -> Path:
    definitions_dir = root / "skills"
    definitions_dir.mkdir()
    bundle_dir = definitions_dir / "hello"
    (bundle_dir / "scripts").mkdir(parents=True)
    (bundle_dir / "references").mkdir()
    (bundle_dir / "assets").mkdir()
    (bundle_dir / "templates").mkdir()
    (bundle_dir / "scripts" / "hello.sh").write_text(
        "#!/usr/bin/env sh\necho hello\n",
        encoding="utf-8",
    )
    (bundle_dir / "scripts" / "hello.sh").chmod(0o755)
    (bundle_dir / "references" / "usage.md").write_text(
        "# Usage\n",
        encoding="utf-8",
    )
    (bundle_dir / "runbook.md").write_text(
        "# Runbook\n",
        encoding="utf-8",
    )
    (bundle_dir / "templates" / "greeting.txt").write_text(
        "Hello, {name}\n",
        encoding="utf-8",
    )
    (bundle_dir / "assets" / "sample.bin").write_bytes(b"\x00hello\xff")
    spec = definitions_dir / "hello.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "hello"
            description = "Say hello when the user asks for a greeting."
            instructions = "Reply with one short greeting."
            source_dir = "hello"
            user_invocable = true
            disable_model_invocation = false
            allowed_tools = []

            [targets.claude]
            context = "fork"
            agent = "general-purpose"

            [targets.codex]
            display_name = "Hello"
            short_description = "Say hello."
            allow_implicit_invocation = true
            [targets.codex.dependencies]
            tools = ["shell"]

            [targets.copilot]
            user_invocable = false
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return spec


def test_render_skill_all_targets(tmp_path: Path) -> None:
    spec = write_skill_sample(tmp_path)
    definition = load_skill_definition(spec, root_dir=tmp_path / "skills")

    assert isinstance(definition, SkillDefinition)
    claude = render_skill(definition, Target.CLAUDE)
    codex = render_skill(definition, Target.CODEX)
    copilot = render_skill(definition, Target.COPILOT)

    assert 'name: "hello"' in claude
    assert 'context: "fork"' in claude
    assert 'agent: "general-purpose"' in claude
    assert "display_name" not in codex
    assert "user-invocable: false" in copilot
    assert "Reply with one short greeting." in copilot


def test_skill_public_helpers_accept_raw_target_names(
    tmp_path: Path,
) -> None:
    spec = write_skill_sample(tmp_path)
    definition = load_skill_definition(spec, root_dir=tmp_path / "skills")

    assert 'context: "fork"' in render_skill(definition, "claude")
    assert skill_output_path(tmp_path, "hello", "codex") == (
        tmp_path / "codex" / "skills" / "hello" / "SKILL.md"
    )


@pytest.mark.parametrize(
    "path_kind",
    ["absolute", "windows_absolute", "parent"],
)
def test_skill_source_dir_rejects_paths_outside_definitions_dir(
    tmp_path: Path,
    path_kind: str,
) -> None:
    if path_kind == "absolute":
        source_dir = str((tmp_path / "skill-bundle").resolve())
    elif path_kind == "windows_absolute":
        source_dir = "C:/outside/skill-bundle"
    else:
        source_dir = "../bundle"
    spec = tmp_path / "skills" / "bad.toml"
    spec.parent.mkdir()
    spec.write_text(
        textwrap.dedent(
            f"""
            name = "bad"
            description = "Bad skill."
            instructions = "Do the thing."
            source_dir = "{source_dir}"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DefinitionError,
        match=r"source_dir must (be a relative path|stay within)",
    ):
        load_skill_definition(spec, root_dir=tmp_path / "skills")


def test_skill_codex_interface_fields_are_immutable() -> None:
    from agent_def_translator import _skill

    assert isinstance(_skill.SKILL_CODEX_INTERFACE_FIELDS, frozenset)


def test_generate_skills_and_drift_check(tmp_path: Path) -> None:
    write_skill_sample(tmp_path)
    output_dir = tmp_path / "generated"

    artifacts = generate_skills(
        definitions_dir=tmp_path / "skills",
        output_dir=output_dir,
    )

    assert len(artifacts) == 19
    assert (output_dir / "claude" / "skills" / "hello" / "SKILL.md").exists()
    assert (
        output_dir / "claude" / "skills" / "hello" / "scripts" / "hello.sh"
    ).exists()
    assert (
        output_dir / "claude" / "skills" / "hello" / "references" / "usage.md"
    ).exists()
    assert (output_dir / "claude" / "skills" / "hello" / "runbook.md").exists()
    assert (
        output_dir
        / "claude"
        / "skills"
        / "hello"
        / "templates"
        / "greeting.txt"
    ).exists()
    assert (
        output_dir / "claude" / "skills" / "hello" / "assets" / "sample.bin"
    ).read_bytes() == b"\x00hello\xff"
    assert (output_dir / "codex" / "skills" / "hello" / "SKILL.md").exists()
    assert (
        output_dir / "codex" / "skills" / "hello" / "agents" / "openai.yaml"
    ).exists()
    assert (output_dir / "copilot" / "skills" / "hello" / "SKILL.md").exists()
    assert (
        check_skill_drift(
            definitions_dir=tmp_path / "skills",
            output_dir=output_dir,
        )
        == []
    )

    generated = output_dir / "claude" / "skills" / "hello" / "SKILL.md"
    generated.write_text("stale", encoding="utf-8")

    assert check_skill_drift(
        definitions_dir=tmp_path / "skills",
        output_dir=output_dir,
    ) == [generated]


def test_validate_skill_definitions(tmp_path: Path) -> None:
    write_skill_sample(tmp_path)

    definitions = validate_skill_definitions(tmp_path / "skills")

    assert [definition.name for definition in definitions] == ["hello"]


def test_skill_target_rejects_unknown_fields(tmp_path: Path) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "bad"
            description = "Bad skill."
            instructions = "Do the thing."

            [targets.claude]
            typo = "value"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match=r"unknown fields: typo"):
        load_skill_definition(spec)


def test_skill_conflicting_invocation_policy_via_target_is_rejected(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "bad"
            description = "Bad skill."
            instructions = "Do the thing."
            disable_model_invocation = true

            [targets.codex]
            allow_implicit_invocation = true
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match="conflicts with"):
        load_skill_definition(spec)


def test_skill_disabled_target_skips_render_validation(
    tmp_path: Path,
) -> None:
    # The disabled claude target sets `allowed_tools` to a string instead of a
    # list, which would fail _validate_skill_config. The loader must skip
    # render validation for disabled targets.
    spec = tmp_path / "quarantine.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "quarantine"
            description = "Skill under quarantine."
            instructions = "Base instructions."

            [targets.claude]
            enabled = false
            allowed_tools = "not-a-list"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    definition = load_skill_definition(spec)
    assert definition.targets[Target.CLAUDE].get("enabled") is False


def test_skill_name_must_use_portable_shape(tmp_path: Path) -> None:
    spec = tmp_path / "Bad_Name.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "Bad_Name"
            description = "Bad skill."
            instructions = "Do the thing."
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match="lowercase"):
        load_skill_definition(spec)


def test_render_mcp_config_all_targets(tmp_path: Path) -> None:
    spec = write_mcp_sample(tmp_path)
    definition = load_mcp_config_definition(spec, root_dir=tmp_path / "mcp")

    assert isinstance(definition, McpConfigDefinition)
    codex = render_mcp_config(definition, Target.CODEX)
    claude = render_mcp_config(definition, Target.CLAUDE)
    copilot = render_mcp_config(definition, Target.COPILOT)

    assert "[mcp_servers.openaiDeveloperDocs]" in codex
    assert 'url = "https://developers.openai.com/mcp"' in codex
    assert '"type": "http"' in claude
    assert '"openaiDeveloperDocs"' in claude
    assert '"tools": [' in copilot


def test_mcp_public_helpers_accept_raw_target_names(tmp_path: Path) -> None:
    spec = write_mcp_sample(tmp_path)
    definition = load_mcp_config_definition(spec, root_dir=tmp_path / "mcp")

    assert "[mcp_servers.openaiDeveloperDocs]" in render_mcp_config(
        definition,
        "codex",
    )
    assert mcp_output_path(tmp_path, "openai-docs", "claude") == (
        tmp_path / "claude" / "mcp" / "openai-docs.json"
    )


def test_render_mcp_stdio_config(tmp_path: Path) -> None:
    spec = tmp_path / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "Local sample server."
            transport = "stdio"
            command = "node"
            args = ["server.js", "--flag"]
            [env]
            FOO = "bar"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    definition = load_mcp_config_definition(spec)

    codex = render_mcp_config(definition, Target.CODEX)
    copilot = render_mcp_config(definition, Target.COPILOT)

    assert 'command = "node"' in codex
    assert 'args = ["server.js", "--flag"]' in codex
    assert "[mcp_servers.sample.env]" in codex
    assert '"type": "local"' in copilot
    assert '"FOO": "bar"' in copilot


def test_render_mcp_copilot_preserves_explicit_empty_tools_for_http(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "HTTP sample server."
            transport = "http"
            url = "https://example.com/mcp"

            [targets.copilot]
            tools = []
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    definition = load_mcp_config_definition(spec)

    copilot = json.loads(render_mcp_config(definition, Target.COPILOT))
    server = copilot["mcpServers"]["sample"]

    assert server["tools"] == []


def test_render_mcp_copilot_preserves_explicit_empty_tools_for_stdio(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "Local sample server."
            transport = "stdio"
            command = "node"

            [targets.copilot]
            tools = []
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    definition = load_mcp_config_definition(spec)

    copilot = json.loads(render_mcp_config(definition, Target.COPILOT))
    server = copilot["mcpServers"]["sample"]

    assert server["tools"] == []


def test_render_mcp_copilot_defaults_tools_to_wildcard_when_omitted(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "sample.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "HTTP sample server."
            transport = "http"
            url = "https://example.com/mcp"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    definition = load_mcp_config_definition(spec)

    copilot = json.loads(render_mcp_config(definition, Target.COPILOT))
    server = copilot["mcpServers"]["sample"]

    assert server["tools"] == ["*"]


def test_generate_mcp_configs_and_drift_check(tmp_path: Path) -> None:
    write_mcp_sample(tmp_path)
    output_dir = tmp_path / "generated"

    artifacts = generate_mcp_configs(
        definitions_dir=tmp_path / "mcp",
        output_dir=output_dir,
    )

    assert len(artifacts) == 3
    assert (output_dir / "claude" / "mcp" / "openai-docs.json").exists()
    assert (output_dir / "codex" / "mcp" / "openai-docs.toml").exists()
    assert (output_dir / "copilot" / "mcp" / "openai-docs.json").exists()
    assert (
        check_mcp_config_drift(
            definitions_dir=tmp_path / "mcp",
            output_dir=output_dir,
        )
        == []
    )

    generated = output_dir / "codex" / "mcp" / "openai-docs.toml"
    generated.write_text("stale", encoding="utf-8")

    assert check_mcp_config_drift(
        definitions_dir=tmp_path / "mcp",
        output_dir=output_dir,
    ) == [generated]


def test_validate_mcp_config_definitions(tmp_path: Path) -> None:
    write_mcp_sample(tmp_path)

    definitions = validate_mcp_config_definitions(tmp_path / "mcp")

    assert [definition.name for definition in definitions] == ["openai-docs"]


def test_mcp_transport_requires_matching_connection_fields(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "bad"
            description = "Bad MCP definition."
            transport = "http"
            command = "node"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match="url is required"):
        load_mcp_config_definition(spec)


def test_mcp_target_rejects_unknown_fields(tmp_path: Path) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "bad"
            description = "Bad MCP definition."
            transport = "http"
            url = "https://example.com/mcp"

            [targets.codex]
            typo = "value"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match=r"unknown fields: typo"):
        load_mcp_config_definition(spec)


def test_mcp_disabled_target_skips_render_validation(
    tmp_path: Path,
) -> None:
    # The disabled claude target overrides `command` with an empty string,
    # which would fail _validate_mcp_transport_shape (stdio requires a
    # non-empty command). The loader must skip render validation for disabled
    # targets so the file can be loaded while the target is quarantined.
    spec = tmp_path / "quarantine.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "quarantine"
            description = "MCP config under quarantine."
            transport = "stdio"
            command = "mycmd"

            [targets.claude]
            enabled = false
            command = ""
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    definition = load_mcp_config_definition(spec)
    assert definition.targets[Target.CLAUDE].get("enabled") is False


def write_plugin_sample(root: Path) -> Path:
    definitions_dir = root / "plugins"
    definitions_dir.mkdir()
    (definitions_dir / "runtime").mkdir()
    (definitions_dir / "runtime" / "README.md").write_text(
        "# Runtime\n",
        encoding="utf-8",
    )
    (definitions_dir / "runtime" / "run.sh").write_text(
        "#!/usr/bin/env sh\necho runtime\n",
        encoding="utf-8",
    )
    (definitions_dir / "runtime" / "run.sh").chmod(0o755)
    spec = definitions_dir / "hello-bundle.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "hello-bundle"
            description = "Bundle generated hello components."
            version = "0.1.0"
            author = "Example Maintainer"
            repository = "https://example.com/hello-bundle"
            homepage = "https://example.com/hello-bundle"
            license = "MIT"
            keywords = ["agents", "skills", "mcp"]

            [components]
            subagents = true
            skills = true
            mcp = true
            resources_dir = "runtime"

            [interface]
            display_name = "Hello Bundle"
            short_description = "Generated hello components."
            long_description = "A tiny plugin bundle for examples."
            developer_name = "Example Maintainer"
            category = "Productivity"
            capabilities = ["Read"]
            website_url = "https://example.com/hello-bundle"

            [marketplace]
            name = "hello-local"
            display_name = "Hello Local Plugins"
            source_path = "./plugins/hello-bundle"
            installation = "AVAILABLE"
            authentication = "ON_INSTALL"
            category = "Productivity"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return spec


def test_render_plugin_manifest_all_targets(tmp_path: Path) -> None:
    spec = write_plugin_sample(tmp_path)
    definition = load_plugin_definition(spec, root_dir=tmp_path / "plugins")

    assert isinstance(definition, PluginDefinition)
    claude = json.loads(render_plugin_manifest(definition, Target.CLAUDE))
    codex = json.loads(render_plugin_manifest(definition, Target.CODEX))
    copilot = json.loads(render_plugin_manifest(definition, Target.COPILOT))

    assert claude["name"] == "hello-bundle"
    assert claude["author"] == {"name": "Example Maintainer"}
    assert codex["skills"] == "./skills/"
    assert codex["interface"]["displayName"] == "Hello Bundle"
    assert copilot["agents"] == "./agents/"
    assert copilot["skills"] == "./skills/"


def test_plugin_public_helpers_accept_raw_target_names(
    tmp_path: Path,
) -> None:
    spec = write_plugin_sample(tmp_path)
    definition = load_plugin_definition(spec, root_dir=tmp_path / "plugins")

    assert render_plugin_manifest(definition, "copilot").endswith("\n")
    assert plugin_root_path(tmp_path, "hello-bundle", "claude") == (
        tmp_path / "claude" / "plugins" / "hello-bundle"
    )
    assert plugin_manifest_output_path(
        tmp_path,
        "hello-bundle",
        "codex",
    ) == (
        tmp_path
        / "codex"
        / "plugins"
        / "hello-bundle"
        / ".codex-plugin"
        / "plugin.json"
    )


@pytest.mark.parametrize(
    "path_kind",
    ["absolute", "windows_absolute", "parent"],
)
def test_plugin_resources_dir_rejects_paths_outside_definitions_dir(
    tmp_path: Path,
    path_kind: str,
) -> None:
    if path_kind == "absolute":
        resources_dir = str((tmp_path / "plugin-runtime").resolve())
    elif path_kind == "windows_absolute":
        resources_dir = "C:/outside/plugin-runtime"
    else:
        resources_dir = "../runtime"
    definitions_dir = tmp_path / "plugins"
    definitions_dir.mkdir()
    spec = definitions_dir / "bad-bundle.toml"
    spec.write_text(
        textwrap.dedent(
            f"""
            name = "bad-bundle"
            description = "Bad bundle."
            version = "0.1.0"

            [components]
            resources_dir = "{resources_dir}"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        DefinitionError,
        match=r"components.resources_dir must "
        r"(be a relative path|stay within)",
    ):
        generate_plugins(definitions_dir=definitions_dir, output_dir=tmp_path)


def test_generate_plugins_and_drift_check(tmp_path: Path) -> None:
    write_sample(tmp_path)
    write_skill_sample(tmp_path)
    write_mcp_sample(tmp_path)
    write_plugin_sample(tmp_path)
    output_dir = tmp_path / "generated"
    generate(definitions_dir=tmp_path / "agents", output_dir=output_dir)
    generate_skills(definitions_dir=tmp_path / "skills", output_dir=output_dir)
    generate_mcp_configs(
        definitions_dir=tmp_path / "mcp",
        output_dir=output_dir,
    )

    artifacts = generate_plugins(
        definitions_dir=tmp_path / "plugins",
        output_dir=output_dir,
    )

    assert len(artifacts) == 35
    claude_root = output_dir / "claude" / "plugins" / "hello-bundle"
    codex_root = output_dir / "codex" / "plugins" / "hello-bundle"
    copilot_root = output_dir / "copilot" / "plugins" / "hello-bundle"
    assert (claude_root / ".claude-plugin" / "plugin.json").exists()
    assert (codex_root / ".codex-plugin" / "plugin.json").exists()
    assert (copilot_root / "plugin.json").exists()
    assert (claude_root / "agents" / "sample.md").exists()
    assert (codex_root / "skills" / "hello" / "SKILL.md").exists()
    assert (
        copilot_root / "skills" / "hello" / "assets" / "sample.bin"
    ).exists()
    assert (claude_root / ".mcp.json").exists()
    assert (codex_root / ".mcp.json").exists()
    assert (copilot_root / ".mcp.json").exists()
    assert (codex_root / "README.md").read_text(
        encoding="utf-8",
    ) == "# Runtime\n"
    assert ((codex_root / "run.sh").stat().st_mode & 0o777) == 0o755
    assert (
        (claude_root / "skills" / "hello" / "scripts" / "hello.sh")
        .stat()
        .st_mode
        & 0o777
    ) == 0o755
    marketplace = json.loads(
        (output_dir / "codex" / "marketplace.json").read_text(
            encoding="utf-8",
        ),
    )
    assert marketplace["name"] == "hello-local"
    assert (
        marketplace["plugins"][0]["source"]["path"] == "./plugins/hello-bundle"
    )
    assert (
        check_plugin_drift(
            definitions_dir=tmp_path / "plugins",
            output_dir=output_dir,
        )
        == []
    )

    generated = codex_root / ".codex-plugin" / "plugin.json"
    generated.write_text("stale", encoding="utf-8")

    assert check_plugin_drift(
        definitions_dir=tmp_path / "plugins",
        output_dir=output_dir,
    ) == [generated]

    script = codex_root / "run.sh"
    script.chmod(0o644)

    assert check_plugin_drift(
        definitions_dir=tmp_path / "plugins",
        output_dir=output_dir,
    ) == [generated, script]


def test_generate_plugins_can_skip_missing_optional_components(
    tmp_path: Path,
) -> None:
    definitions_dir = tmp_path / "plugins"
    definitions_dir.mkdir()
    spec = definitions_dir / "optional-bundle.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "optional-bundle"
            description = "Bundle optional components when present."
            version = "0.1.0"

            [components]
            subagents = true
            skills = true
            mcp = true
            resources_dir = "missing-runtime"
            require_subagents = false
            require_skills = false
            require_mcp = false
            require_resources = false
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    artifacts = generate_plugins(
        definitions_dir=definitions_dir,
        output_dir=tmp_path / "generated",
    )

    assert [
        artifact.output_path.relative_to(tmp_path / "generated").as_posix()
        for artifact in artifacts
    ] == [
        "claude/plugins/optional-bundle/.claude-plugin/plugin.json",
        "codex/plugins/optional-bundle/.codex-plugin/plugin.json",
        "codex/marketplace.json",
        "copilot/plugins/optional-bundle/plugin.json",
    ]


def test_validate_plugin_definitions(tmp_path: Path) -> None:
    write_plugin_sample(tmp_path)

    definitions = validate_plugin_definitions(tmp_path / "plugins")

    assert [definition.name for definition in definitions] == ["hello-bundle"]


def test_plugin_target_rejects_unknown_fields(tmp_path: Path) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "bad"
            description = "Bad plugin."
            version = "0.1.0"

            [targets.codex]
            typo = "value"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match=r"unknown fields: typo"):
        load_plugin_definition(spec)


def test_plugin_disabled_target_skips_render_validation(
    tmp_path: Path,
) -> None:
    # The disabled codex target sets `keywords` to a string instead of a list,
    # which would fail _validate_plugin_config. The loader must skip render
    # validation for disabled targets.
    spec = tmp_path / "quarantine.toml"
    spec.write_text(
        textwrap.dedent(
            """
            name = "quarantine"
            description = "Plugin under quarantine."
            version = "0.1.0"

            [targets.codex]
            enabled = false
            keywords = "not-a-list"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    definition = load_plugin_definition(spec)
    assert definition.targets[Target.CODEX].get("enabled") is False


def test_generate_plugins_rejects_multiple_codex_plugins(
    tmp_path: Path,
) -> None:
    definitions_dir = tmp_path / "plugins"
    definitions_dir.mkdir()
    plugin_toml = (
        textwrap.dedent(
            """
        name = "{name}"
        description = "Plugin {name}."
        version = "0.1.0"
        author = "Test"
        repository = "https://example.com/{name}"
        homepage = "https://example.com/{name}"
        license = "MIT"

        [components]

        [interface]
        display_name = "{name}"
        short_description = "Test plugin."
        long_description = "Test plugin."
        developer_name = "Test"
        category = "Productivity"
        capabilities = []
        website_url = "https://example.com/{name}"

        [marketplace]
        name = "{name}-local"

        [targets.codex]
        """,
        ).strip()
        + "\n"
    )
    (definitions_dir / "plugin-a.toml").write_text(
        plugin_toml.format(name="plugin-a"),
        encoding="utf-8",
    )
    (definitions_dir / "plugin-b.toml").write_text(
        plugin_toml.format(name="plugin-b"),
        encoding="utf-8",
    )

    with pytest.raises(DefinitionError, match=r"multiple Codex-enabled"):
        generate_plugins(
            definitions_dir=definitions_dir,
            output_dir=tmp_path / "out",
        )


def test_skill_bundle_rejects_too_many_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_def_translator import _skill

    monkeypatch.setattr(_skill, "MAX_BUNDLE_FILE_COUNT", 2)
    write_skill_sample(tmp_path)
    # The sample bundle already has 5 files; with limit=2 it should reject.
    with pytest.raises(DefinitionError, match="too many files"):
        generate_skills(
            definitions_dir=tmp_path / "skills",
            output_dir=tmp_path / "out",
        )


def test_skill_bundle_rejects_oversized_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_def_translator import _skill

    monkeypatch.setattr(_skill, "MAX_BUNDLE_FILE_BYTES", 10)
    write_skill_sample(tmp_path)
    # The sample bundle contains files larger than 10 bytes.
    with pytest.raises(DefinitionError, match="too large"):
        generate_skills(
            definitions_dir=tmp_path / "skills",
            output_dir=tmp_path / "out",
        )


def test_write_artifact_chmod_failure_leaves_no_final_path(
    tmp_path: Path,
) -> None:
    """chmod failure before rename must not leave a file at the final path."""
    import unittest.mock

    from agent_def_translator._common import (
        GeneratedArtifact,
        Target,
        _write_artifact,
    )

    output = tmp_path / "out.sh"
    artifact = GeneratedArtifact(
        target=Target.CLAUDE,
        source_path=tmp_path / "src.toml",
        output_path=output,
        content=b"#!/bin/sh\necho hi\n",
        mode=0o755,
    )

    with (
        unittest.mock.patch.object(
            Path,
            "chmod",
            side_effect=OSError("permission denied"),
        ),
        pytest.raises(OSError),
    ):
        _write_artifact(artifact)

    # Final path must not exist; tmp cleaned up inside the except handler.
    assert not output.exists(), "final path must not be left when chmod fails"


def test_write_artifacts_batch_chmod_failure_leaves_no_final_paths(
    tmp_path: Path,
) -> None:
    """chmod failure mid-batch must not leave any file at a final path."""
    import unittest.mock

    from agent_def_translator._common import (
        GeneratedArtifact,
        Target,
        _write_artifacts_batch,
    )

    artifacts = [
        GeneratedArtifact(
            target=Target.CLAUDE,
            source_path=tmp_path / "src.toml",
            output_path=tmp_path / f"out{i}.sh",
            content=b"#!/bin/sh\n",
            mode=0o755,
        )
        for i in range(3)
    ]

    with (
        unittest.mock.patch.object(
            Path,
            "chmod",
            side_effect=OSError("permission denied"),
        ),
        pytest.raises(OSError),
    ):
        _write_artifacts_batch(artifacts)

    for artifact in artifacts:
        assert not artifact.output_path.exists(), (
            f"{artifact.output_path} must not exist after chmod failure"
        )


def test_yaml_key_safe_and_unsafe() -> None:
    from agent_def_translator._common import _yaml_key

    # Safe keys: no quoting needed
    assert _yaml_key("name") == "name"
    assert _yaml_key("allowed-tools") == "allowed-tools"
    assert _yaml_key("permission_mode") == "permission_mode"
    assert _yaml_key("_private") == "_private"
    assert _yaml_key("v1.0") == "v1.0"

    # Unsafe keys: must be double-quoted
    assert _yaml_key("foo: bar") == '"foo: bar"'
    assert _yaml_key("key\ninjection") == '"key\\ninjection"'
    assert _yaml_key("key#comment") == '"key#comment"'
    assert _yaml_key("1start") == '"1start"'


def test_yaml_key_injection_is_blocked(tmp_path: Path) -> None:
    """TOML quoted key with ':' must not break YAML frontmatter."""
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    spec = definitions_dir / "sample.toml"
    # TOML allows quoted keys with arbitrary strings; the colon here would
    # break YAML if the key were embedded without quoting.
    spec.write_text(
        textwrap.dedent(
            """
            name = "sample"
            description = "Sample agent"
            instructions = "Instructions"

            [targets.claude]
            "foo: injected" = "value"
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    definition = load_definition(spec, root_dir=definitions_dir)
    output = render(definition, Target.CLAUDE)
    # The key must appear double-quoted in the YAML output
    assert '"foo: injected": "value"' in output
    # The raw unquoted form must not appear as a YAML mapping key
    assert "\nfoo: injected" not in output


def test_load_definition_toml_syntax_error_raises_definition_error(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text("this is not valid toml ===\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match=str(spec)):
        load_definition(spec)


def test_load_mcp_config_definition_toml_syntax_error_raises_definition_error(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text("this is not valid toml ===\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match=str(spec)):
        load_mcp_config_definition(spec)


def test_load_plugin_definition_toml_syntax_error_raises_definition_error(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text("this is not valid toml ===\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match=str(spec)):
        load_plugin_definition(spec)


def test_load_skill_definition_toml_syntax_error_raises_definition_error(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "bad.toml"
    spec.write_text("this is not valid toml ===\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match=str(spec)):
        load_skill_definition(spec)


def test_mcp_json_fragment_merge_rejects_too_many_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_def_translator import _plugin

    monkeypatch.setattr(_plugin, "_MAX_COPY_TREE_FILE_COUNT", 2)
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    for i in range(3):
        (mcp_dir / f"fragment{i}.json").write_text(
            '{"mcpServers": {}}',
            encoding="utf-8",
        )
    with pytest.raises(DefinitionError, match="too many MCP fragment files"):
        _plugin._merge_json_mcp_fragments(mcp_dir)


def test_mcp_json_fragment_merge_rejects_oversized_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_def_translator import _plugin

    monkeypatch.setattr(_plugin, "_MAX_COPY_TREE_FILE_BYTES", 10)
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "fragment.json").write_text(
        '{"mcpServers": {"large": {}}}',
        encoding="utf-8",
    )
    with pytest.raises(DefinitionError, match="too large"):
        _plugin._merge_json_mcp_fragments(mcp_dir)


def test_mcp_toml_fragment_merge_rejects_too_many_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_def_translator import _plugin

    monkeypatch.setattr(_plugin, "_MAX_COPY_TREE_FILE_COUNT", 2)
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    for i in range(3):
        (mcp_dir / f"fragment{i}.toml").write_text(
            "[mcp_servers]\n",
            encoding="utf-8",
        )
    with pytest.raises(DefinitionError, match="too many MCP fragment files"):
        _plugin._merge_codex_mcp_fragments(mcp_dir)


def test_mcp_toml_fragment_merge_rejects_oversized_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_def_translator import _plugin

    monkeypatch.setattr(_plugin, "_MAX_COPY_TREE_FILE_BYTES", 10)
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "fragment.toml").write_text(
        "[mcp_servers.large]\nurl = 'https://example.com/mcp'\n",
        encoding="utf-8",
    )
    with pytest.raises(DefinitionError, match="too large"):
        _plugin._merge_codex_mcp_fragments(mcp_dir)


def test_skill_bundle_rejects_symlinked_file(tmp_path: Path) -> None:
    import sys

    if sys.platform == "win32":
        pytest.skip("symlinks require elevated privileges on Windows")
    write_skill_sample(tmp_path)
    bundle_dir = tmp_path / "skills" / "hello"
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (bundle_dir / "leak.txt").symlink_to(secret)
    with pytest.raises(DefinitionError, match="symlinks are not allowed"):
        generate_skills(
            definitions_dir=tmp_path / "skills",
            output_dir=tmp_path / "out",
        )


def test_plugin_resources_dir_rejects_symlinked_file(tmp_path: Path) -> None:
    import sys

    if sys.platform == "win32":
        pytest.skip("symlinks require elevated privileges on Windows")
    write_sample(tmp_path)
    write_skill_sample(tmp_path)
    write_mcp_sample(tmp_path)
    write_plugin_sample(tmp_path)
    output_dir = tmp_path / "out"
    generate(definitions_dir=tmp_path / "agents", output_dir=output_dir)
    generate_skills(definitions_dir=tmp_path / "skills", output_dir=output_dir)
    generate_mcp_configs(
        definitions_dir=tmp_path / "mcp",
        output_dir=output_dir,
    )
    resources_dir = tmp_path / "plugins" / "runtime"
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (resources_dir / "leak.txt").symlink_to(secret)
    with pytest.raises(DefinitionError, match="symlinks are not allowed"):
        generate_plugins(
            definitions_dir=tmp_path / "plugins",
            output_dir=output_dir,
        )
