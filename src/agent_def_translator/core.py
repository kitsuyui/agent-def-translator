from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
PROMPT_FIELDS = frozenset(
    {"prompt_override", "prompt_append", "prompt_append_file"},
)
ROOT_FIELDS = frozenset({"name", "description", "instructions", "targets"})
LEGACY_TARGET_FIELDS = frozenset({"claude", "codex", "vscode", "copilot"})
SKILL_ROOT_FIELDS = frozenset(
    {
        "name",
        "description",
        "instructions",
        "source_dir",
        "license",
        "compatibility",
        "metadata",
        "allowed_tools",
        "argument_hint",
        "user_invocable",
        "disable_model_invocation",
        "context",
        "targets",
    },
)
SKILL_TARGET_CONTROL_FIELDS = frozenset({"enabled"})
SKILL_TARGET_FIELDS = frozenset(
    {
        "name",
        "description",
        "instructions",
        "license",
        "compatibility",
        "metadata",
        "allowed_tools",
        "argument_hint",
        "user_invocable",
        "disable_model_invocation",
        "context",
        "agent",
        "model",
        "effort",
        "hooks",
        "paths",
        "shell",
        "display_name",
        "short_description",
        "icon_small",
        "icon_large",
        "brand_color",
        "default_prompt",
        "allow_implicit_invocation",
        "dependencies",
        *SKILL_TARGET_CONTROL_FIELDS,
    },
)
SKILL_COMMON_FRONTMATTER_FIELDS = {
    "license": "license",
    "compatibility": "compatibility",
    "metadata": "metadata",
    "allowed_tools": "allowed-tools",
    "argument_hint": "argument-hint",
    "user_invocable": "user-invocable",
    "disable_model_invocation": "disable-model-invocation",
    "context": "context",
}
SKILL_CLAUDE_EXTRA_FRONTMATTER_FIELDS = {
    "agent": "agent",
    "model": "model",
    "effort": "effort",
    "hooks": "hooks",
    "paths": "paths",
    "shell": "shell",
}
SKILL_CODEX_FRONTMATTER_FIELDS = {
    "license": "license",
    "compatibility": "compatibility",
    "metadata": "metadata",
    "allowed_tools": "allowed-tools",
}
SKILL_CODEX_INTERFACE_FIELDS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}
MCP_ROOT_FIELDS = frozenset(
    {
        "name",
        "description",
        "transport",
        "url",
        "command",
        "args",
        "env",
        "headers",
        "tools",
        "bearer_token_env_var",
        "targets",
    },
)
MCP_TARGET_CONTROL_FIELDS = frozenset({"enabled", "server_name"})
MCP_TARGET_FIELDS = frozenset(
    {
        "url",
        "command",
        "args",
        "env",
        "headers",
        "tools",
        "bearer_token_env_var",
        *MCP_TARGET_CONTROL_FIELDS,
    },
)
MCP_TRANSPORTS = frozenset({"stdio", "http", "sse"})


class DefinitionError(ValueError):
    """Raised when a definition cannot be translated."""


class Target(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"

    @classmethod
    def parse(cls, value: str) -> Target:
        normalized = value.strip().lower()
        if normalized == "vscode":
            return cls.COPILOT
        try:
            return cls(normalized)
        except ValueError as exc:
            choices = ", ".join(item.value for item in cls)
            msg = f"unsupported target: {value}. Expected one of: {choices}"
            raise DefinitionError(msg) from exc


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    name: str
    description: str
    instructions: str
    targets: dict[Target, dict[str, Any]]
    source_path: Path
    root_dir: Path


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    description: str
    instructions: str
    config: dict[str, Any]
    targets: dict[Target, dict[str, Any]]
    source_path: Path
    root_dir: Path
    bundle_dir: Path | None


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    target: Target
    source_path: Path
    output_path: Path
    content: str | bytes


@dataclass(frozen=True, slots=True)
class McpConfigDefinition:
    name: str
    description: str
    transport: str
    config: dict[str, Any]
    targets: dict[Target, dict[str, Any]]
    source_path: Path
    root_dir: Path


def load_definition(
    path: Path,
    *,
    root_dir: Path | None = None,
) -> AgentDefinition:
    root = root_dir or path.parent
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = sorted(set(payload) - ROOT_FIELDS - LEGACY_TARGET_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        raise DefinitionError(f"{path}: unknown top-level fields: {fields}")

    for field in ("name", "description", "instructions"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            msg = f"{path}: {field} must be a non-empty string"
            raise DefinitionError(msg)

    name = payload["name"].strip()
    if not NAME_PATTERN.fullmatch(name):
        msg = f"{path}: name must match {NAME_PATTERN.pattern}"
        raise DefinitionError(msg)
    if path.stem != name:
        msg = f"{path}: filename stem must match name: {name}"
        raise DefinitionError(msg)

    targets = _load_target_configs(path, payload)
    return AgentDefinition(
        name=name,
        description=payload["description"].strip(),
        instructions=payload["instructions"].strip(),
        targets=targets,
        source_path=path,
        root_dir=root,
    )


def load_definitions(definitions_dir: Path) -> list[AgentDefinition]:
    if not definitions_dir.is_dir():
        msg = f"definitions directory not found: {definitions_dir}"
        raise DefinitionError(msg)
    definitions = [
        load_definition(path, root_dir=definitions_dir)
        for path in sorted(definitions_dir.glob("*.toml"))
    ]
    _reject_duplicate_names(definitions)
    return definitions


def load_skill_definition(
    path: Path,
    *,
    root_dir: Path | None = None,
) -> SkillDefinition:
    root = root_dir or path.parent
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = sorted(set(payload) - SKILL_ROOT_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        raise DefinitionError(f"{path}: unknown top-level fields: {fields}")

    for field in ("name", "description", "instructions"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            msg = f"{path}: {field} must be a non-empty string"
            raise DefinitionError(msg)

    name = payload["name"].strip()
    _validate_skill_name(path, name)
    if path.stem != name:
        msg = f"{path}: filename stem must match name: {name}"
        raise DefinitionError(msg)

    config = {
        key: value
        for key, value in payload.items()
        if key not in {"name", "description", "instructions", "targets"}
    }
    _validate_skill_config(path, config)
    bundle_dir = _skill_bundle_dir(path, root, name, config)
    targets = _load_target_configs(path, payload)
    for target, target_config in targets.items():
        _validate_skill_target_config(path, target, target_config)
        _validate_skill_config(
            path,
            _skill_render_config(config, target_config),
        )
    return SkillDefinition(
        name=name,
        description=payload["description"].strip(),
        instructions=payload["instructions"].strip(),
        config=config,
        targets=targets,
        source_path=path,
        root_dir=root,
        bundle_dir=bundle_dir,
    )


def load_skill_definitions(definitions_dir: Path) -> list[SkillDefinition]:
    if not definitions_dir.is_dir():
        msg = f"definitions directory not found: {definitions_dir}"
        raise DefinitionError(msg)
    definitions = [
        load_skill_definition(path, root_dir=definitions_dir)
        for path in sorted(definitions_dir.glob("*.toml"))
    ]
    _reject_duplicate_skill_names(definitions)
    return definitions


def load_mcp_config_definition(
    path: Path,
    *,
    root_dir: Path | None = None,
) -> McpConfigDefinition:
    root = root_dir or path.parent
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = sorted(set(payload) - MCP_ROOT_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        raise DefinitionError(f"{path}: unknown top-level fields: {fields}")

    for field in ("name", "description", "transport"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            msg = f"{path}: {field} must be a non-empty string"
            raise DefinitionError(msg)

    name = payload["name"].strip()
    if not NAME_PATTERN.fullmatch(name):
        msg = f"{path}: name must match {NAME_PATTERN.pattern}"
        raise DefinitionError(msg)
    if path.stem != name:
        msg = f"{path}: filename stem must match name: {name}"
        raise DefinitionError(msg)

    transport = payload["transport"].strip().lower()
    if transport not in MCP_TRANSPORTS:
        choices = ", ".join(sorted(MCP_TRANSPORTS))
        raise DefinitionError(
            f"{path}: transport must be one of: {choices}",
        )

    config = {
        key: value
        for key, value in payload.items()
        if key not in {"name", "description", "transport", "targets"}
    }
    _validate_mcp_transport_shape(path, transport, config)
    _validate_mcp_config(path, config)
    targets = _load_target_configs(path, payload)
    for target, target_config in targets.items():
        _validate_mcp_target_config(path, target, target_config)
        rendered_config = _mcp_render_config(config, target_config)
        _validate_mcp_transport_shape(path, transport, rendered_config)
        _validate_mcp_config(path, rendered_config)
    return McpConfigDefinition(
        name=name,
        description=payload["description"].strip(),
        transport=transport,
        config=config,
        targets=targets,
        source_path=path,
        root_dir=root,
    )


def load_mcp_config_definitions(
    definitions_dir: Path,
) -> list[McpConfigDefinition]:
    if not definitions_dir.is_dir():
        msg = f"definitions directory not found: {definitions_dir}"
        raise DefinitionError(msg)
    definitions = [
        load_mcp_config_definition(path, root_dir=definitions_dir)
        for path in sorted(definitions_dir.glob("*.toml"))
    ]
    _reject_duplicate_mcp_names(definitions)
    return definitions


def validate_definitions(
    definitions_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[AgentDefinition]:
    definitions = load_definitions(definitions_dir)
    for definition in definitions:
        for target in targets:
            render(definition, target)
    return definitions


def validate_mcp_config_definitions(
    definitions_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[McpConfigDefinition]:
    definitions = load_mcp_config_definitions(definitions_dir)
    for definition in definitions:
        for target in targets:
            if _mcp_target_enabled(definition, target):
                render_mcp_config(definition, target)
    return definitions


def validate_skill_definitions(
    definitions_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[SkillDefinition]:
    definitions = load_skill_definitions(definitions_dir)
    for definition in definitions:
        for target in targets:
            if _skill_target_enabled(definition, target):
                render_skill(definition, target)
    return definitions


def render(definition: AgentDefinition, target: Target) -> str:
    if target == Target.CLAUDE:
        return _render_claude(definition)
    if target == Target.CODEX:
        return _render_codex(definition)
    if target == Target.COPILOT:
        return _render_copilot(definition)
    raise DefinitionError(f"unsupported target: {target}")


def render_skill(
    definition: SkillDefinition,
    target: Target,
) -> str:
    target_config = definition.targets.get(target, {})
    if not _skill_target_enabled(definition, target):
        msg = f"{definition.source_path}: target disabled: {target.value}"
        raise DefinitionError(msg)
    if target == Target.CLAUDE:
        return _render_skill_claude(definition, target_config)
    if target == Target.CODEX:
        return _render_skill_codex(definition, target_config)
    if target == Target.COPILOT:
        return _render_skill_copilot(definition, target_config)
    raise DefinitionError(f"unsupported target: {target}")


def render_mcp_config(
    definition: McpConfigDefinition,
    target: Target,
) -> str:
    target_config = definition.targets.get(target, {})
    if not _mcp_target_enabled(definition, target):
        msg = f"{definition.source_path}: target disabled: {target.value}"
        raise DefinitionError(msg)
    if target == Target.CLAUDE:
        return _render_mcp_claude(definition, target_config)
    if target == Target.CODEX:
        return _render_mcp_codex(definition, target_config)
    if target == Target.COPILOT:
        return _render_mcp_copilot(definition, target_config)
    raise DefinitionError(f"unsupported target: {target}")


def generate(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
    write: bool = True,
) -> list[GeneratedArtifact]:
    artifacts: list[GeneratedArtifact] = []
    for definition in load_definitions(definitions_dir):
        for target in targets:
            content = render(definition, target)
            path = output_path(output_dir, definition.name, target)
            artifact = GeneratedArtifact(
                target=target,
                source_path=definition.source_path,
                output_path=path,
                content=content,
            )
            artifacts.append(artifact)
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_artifact(artifact)
    return artifacts


def generate_skills(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
    write: bool = True,
) -> list[GeneratedArtifact]:
    artifacts: list[GeneratedArtifact] = []
    for definition in load_skill_definitions(definitions_dir):
        for target in targets:
            if not _skill_target_enabled(definition, target):
                continue
            content = render_skill(definition, target)
            path = skill_output_path(output_dir, definition.name, target)
            target_artifacts = [
                GeneratedArtifact(
                    target=target,
                    source_path=definition.source_path,
                    output_path=path,
                    content=content,
                ),
            ]
            if target == Target.CODEX:
                openai_yaml = _render_skill_codex_openai_yaml(definition)
                if openai_yaml is not None:
                    target_artifacts.append(
                        GeneratedArtifact(
                            target=target,
                            source_path=definition.source_path,
                            output_path=skill_codex_openai_yaml_path(
                                output_dir,
                                definition.name,
                            ),
                            content=openai_yaml,
                        ),
                    )
            target_artifacts.extend(
                _skill_bundle_artifacts(definition, output_dir, target),
            )
            artifacts.extend(target_artifacts)
            if write:
                for artifact in target_artifacts:
                    artifact.output_path.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    _write_artifact(artifact)
    return artifacts


def generate_mcp_configs(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
    write: bool = True,
) -> list[GeneratedArtifact]:
    artifacts: list[GeneratedArtifact] = []
    for definition in load_mcp_config_definitions(definitions_dir):
        for target in targets:
            if not _mcp_target_enabled(definition, target):
                continue
            content = render_mcp_config(definition, target)
            path = mcp_output_path(output_dir, definition.name, target)
            artifact = GeneratedArtifact(
                target=target,
                source_path=definition.source_path,
                output_path=path,
                content=content,
            )
            artifacts.append(artifact)
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_artifact(artifact)
    return artifacts


def check_drift(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[Path]:
    artifacts = generate(
        definitions_dir=definitions_dir,
        output_dir=output_dir,
        targets=targets,
        write=False,
    )
    return [
        artifact.output_path
        for artifact in artifacts
        if _artifact_has_drift(artifact)
    ]


def check_skill_drift(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[Path]:
    artifacts = generate_skills(
        definitions_dir=definitions_dir,
        output_dir=output_dir,
        targets=targets,
        write=False,
    )
    return [
        artifact.output_path
        for artifact in artifacts
        if _artifact_has_drift(artifact)
    ]


def check_mcp_config_drift(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[Path]:
    artifacts = generate_mcp_configs(
        definitions_dir=definitions_dir,
        output_dir=output_dir,
        targets=targets,
        write=False,
    )
    return [
        artifact.output_path
        for artifact in artifacts
        if _artifact_has_drift(artifact)
    ]


def output_path(output_dir: Path, name: str, target: Target) -> Path:
    if target == Target.CLAUDE:
        return output_dir / "claude" / "agents" / f"{name}.md"
    if target == Target.CODEX:
        return output_dir / "codex" / "agents" / f"{name}.toml"
    if target == Target.COPILOT:
        return output_dir / "copilot" / "agents" / f"{name}.agent.md"
    raise DefinitionError(f"unsupported target: {target}")


def skill_output_path(output_dir: Path, name: str, target: Target) -> Path:
    if target == Target.CLAUDE:
        return output_dir / "claude" / "skills" / name / "SKILL.md"
    if target == Target.CODEX:
        return output_dir / "codex" / "skills" / name / "SKILL.md"
    if target == Target.COPILOT:
        return output_dir / "copilot" / "skills" / name / "SKILL.md"
    raise DefinitionError(f"unsupported target: {target}")


def skill_codex_openai_yaml_path(output_dir: Path, name: str) -> Path:
    return output_dir / "codex" / "skills" / name / "agents" / "openai.yaml"


def mcp_output_path(output_dir: Path, name: str, target: Target) -> Path:
    if target == Target.CODEX:
        return output_dir / "codex" / "mcp" / f"{name}.toml"
    if target == Target.CLAUDE:
        return output_dir / "claude" / "mcp" / f"{name}.json"
    if target == Target.COPILOT:
        return output_dir / "copilot" / "mcp" / f"{name}.json"
    raise DefinitionError(f"unsupported target: {target}")


def _load_target_configs(
    path: Path,
    payload: dict[str, Any],
) -> dict[Target, dict[str, Any]]:
    targets_payload = payload.get("targets", {})
    if targets_payload is None:
        targets_payload = {}
    if not isinstance(targets_payload, dict):
        raise DefinitionError(f"{path}: [targets] must be a table")

    configs: dict[Target, dict[str, Any]] = {}
    for key, value in targets_payload.items():
        target = Target.parse(str(key))
        if not isinstance(value, dict):
            raise DefinitionError(f"{path}: [targets.{key}] must be a table")
        configs[target] = dict(value)

    for legacy_key in sorted(LEGACY_TARGET_FIELDS):
        if legacy_key not in payload:
            continue
        target = Target.parse(legacy_key)
        value = payload[legacy_key]
        if not isinstance(value, dict):
            raise DefinitionError(f"{path}: [{legacy_key}] must be a table")
        configs.setdefault(target, dict(value))

    return configs


def _reject_duplicate_names(definitions: list[AgentDefinition]) -> None:
    seen: dict[str, Path] = {}
    for definition in definitions:
        existing = seen.get(definition.name)
        if existing is not None:
            msg = (
                f"{definition.source_path}: duplicate definition name "
                f"{definition.name!r}; already defined in {existing}"
            )
            raise DefinitionError(msg)
        seen[definition.name] = definition.source_path


def _reject_duplicate_skill_names(
    definitions: list[SkillDefinition],
) -> None:
    seen: dict[str, Path] = {}
    for definition in definitions:
        existing = seen.get(definition.name)
        if existing is not None:
            msg = (
                f"{definition.source_path}: duplicate definition name "
                f"{definition.name!r}; already defined in {existing}"
            )
            raise DefinitionError(msg)
        seen[definition.name] = definition.source_path


def _reject_duplicate_mcp_names(
    definitions: list[McpConfigDefinition],
) -> None:
    seen: dict[str, Path] = {}
    for definition in definitions:
        existing = seen.get(definition.name)
        if existing is not None:
            msg = (
                f"{definition.source_path}: duplicate definition name "
                f"{definition.name!r}; already defined in {existing}"
            )
            raise DefinitionError(msg)
        seen[definition.name] = definition.source_path


def _compose_prompt(definition: AgentDefinition, target: Target) -> str:
    config = definition.targets.get(target, {})
    override = config.get("prompt_override")
    append = config.get("prompt_append")
    append_file = config.get("prompt_append_file")

    if override is not None and not isinstance(override, str):
        msg = f"{definition.source_path}: prompt_override must be a string"
        raise DefinitionError(msg)
    if append is not None and not isinstance(append, str):
        msg = f"{definition.source_path}: prompt_append must be a string"
        raise DefinitionError(msg)
    if append_file is not None and not isinstance(append_file, str):
        msg = f"{definition.source_path}: prompt_append_file must be a string"
        raise DefinitionError(msg)
    if append is not None and append_file is not None:
        msg = (
            f"{definition.source_path}: prompt_append and prompt_append_file "
            "are mutually exclusive"
        )
        raise DefinitionError(msg)

    prompt = (
        override if override is not None else definition.instructions
    ).strip()
    if append_file is not None:
        file_path = (definition.root_dir / append_file).resolve()
        try:
            append = file_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            msg = (
                f"{definition.source_path}: prompt_append_file not found: "
                f"{file_path}"
            )
            raise DefinitionError(msg) from exc
    if append:
        prompt = f"{prompt}\n\n{append.strip()}"
    return prompt


def _target_config(
    definition: AgentDefinition,
    target: Target,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in definition.targets.get(target, {}).items()
        if key not in PROMPT_FIELDS
    }


def _source_comment(definition: AgentDefinition) -> str:
    try:
        source = definition.source_path.relative_to(definition.root_dir)
    except ValueError:
        source = definition.source_path
    return source.as_posix()


def _render_claude(definition: AgentDefinition) -> str:
    config = _target_config(definition, Target.CLAUDE)
    frontmatter = {
        "name": definition.name,
        "description": definition.description,
        **config,
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        normalized = _normalize_claude_value(key, value)
        lines.extend(_yaml_lines(str(key), normalized))
    comment = _generated_comment(definition)
    lines.extend(
        [
            "---",
            "",
            f"<!-- {comment} -->",
            "",
            _compose_prompt(definition, Target.CLAUDE),
            "",
        ],
    )
    return "\n".join(lines)


def _render_codex(definition: AgentDefinition) -> str:
    payload = {
        "name": definition.name,
        "description": definition.description,
        "developer_instructions": _compose_prompt(definition, Target.CODEX),
        **_target_config(definition, Target.CODEX),
    }
    lines = [f"# {_generated_comment(definition)}"]
    _write_toml_table(lines, [], payload)
    return "\n".join(lines) + "\n"


def _render_copilot(definition: AgentDefinition) -> str:
    frontmatter = {
        "name": definition.name,
        "description": definition.description,
        **_target_config(definition, Target.COPILOT),
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.extend(_yaml_lines(str(key), value))
    comment = _generated_comment(definition)
    lines.extend(
        [
            "---",
            "",
            f"<!-- {comment} -->",
            "",
            _compose_prompt(definition, Target.COPILOT),
            "",
        ],
    )
    return "\n".join(lines)


def _normalize_claude_value(key: str, value: Any) -> Any:
    if key in {"tools", "disallowedTools", "allowedTools"} and isinstance(
        value,
        list,
    ):
        return ", ".join(str(item) for item in value)
    return value


def _generated_comment(definition: AgentDefinition) -> str:
    source = _source_comment(definition)
    return f"Generated from {source} by agent-def-translator."


def _generated_skill_comment(definition: SkillDefinition) -> str:
    try:
        source = definition.source_path.relative_to(definition.root_dir)
    except ValueError:
        source = definition.source_path
    return f"Generated from {source.as_posix()} by agent-def-translator."


def _validate_skill_name(path: Path, name: str) -> None:
    if not SKILL_NAME_PATTERN.fullmatch(name) or "--" in name:
        msg = (
            f"{path}: name must use lowercase letters, numbers, and single "
            "hyphens; it must be 1-64 characters and match the filename stem"
        )
        raise DefinitionError(msg)


def _skill_target_enabled(
    definition: SkillDefinition,
    target: Target,
) -> bool:
    enabled = definition.targets.get(target, {}).get("enabled", True)
    if not isinstance(enabled, bool):
        msg = f"{definition.source_path}: enabled must be a boolean"
        raise DefinitionError(msg)
    return enabled


def _skill_bundle_dir(
    path: Path,
    root_dir: Path,
    name: str,
    config: dict[str, Any],
) -> Path | None:
    source_dir = config.get("source_dir")
    if source_dir is None:
        candidate = root_dir / name
        return candidate if candidate.is_dir() else None
    if not isinstance(source_dir, str) or not source_dir.strip():
        raise DefinitionError(f"{path}: source_dir must be a string")
    bundle_dir = root_dir / source_dir
    if not bundle_dir.is_dir():
        raise DefinitionError(f"{path}: source_dir not found: {bundle_dir}")
    return bundle_dir


def _skill_bundle_artifacts(
    definition: SkillDefinition,
    output_dir: Path,
    target: Target,
) -> list[GeneratedArtifact]:
    if definition.bundle_dir is None:
        return []

    skill_dir = skill_output_path(output_dir, definition.name, target).parent
    artifacts: list[GeneratedArtifact] = []
    for path in sorted(definition.bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(definition.bundle_dir)
        if relative_path == Path("SKILL.md"):
            continue
        if relative_path == Path("agents") / "openai.yaml":
            continue
        artifacts.append(
            GeneratedArtifact(
                target=target,
                source_path=path,
                output_path=skill_dir / relative_path,
                content=path.read_bytes(),
            ),
        )
    return artifacts


def _skill_render_config(
    base: dict[str, Any],
    target_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        **base,
        **{
            key: value
            for key, value in target_config.items()
            if key not in SKILL_TARGET_CONTROL_FIELDS
        },
    }


def _validate_skill_config(path: Path, config: dict[str, Any]) -> None:
    for key in (
        "name",
        "description",
        "instructions",
        "source_dir",
        "license",
        "compatibility",
        "argument_hint",
        "context",
        "agent",
        "model",
        "effort",
        "shell",
        "display_name",
        "short_description",
        "icon_small",
        "icon_large",
        "brand_color",
        "default_prompt",
    ):
        value = config.get(key)
        if value is not None and not isinstance(value, str):
            raise DefinitionError(f"{path}: {key} must be a string")

    for key in ("user_invocable", "disable_model_invocation"):
        value = config.get(key)
        if value is not None and not isinstance(value, bool):
            raise DefinitionError(f"{path}: {key} must be a boolean")
    value = config.get("allow_implicit_invocation")
    if value is not None and not isinstance(value, bool):
        raise DefinitionError(
            f"{path}: allow_implicit_invocation must be a boolean",
        )

    for key in ("allowed_tools", "paths"):
        value = config.get(key)
        if value is not None and not _is_string_list(value):
            raise DefinitionError(f"{path}: {key} must be a list of strings")

    for key in ("metadata", "hooks", "dependencies"):
        value = config.get(key)
        if value is not None and not _is_yaml_value(value):
            raise DefinitionError(
                f"{path}: {key} must contain YAML-compatible values",
            )


def _validate_skill_target_config(
    path: Path,
    target: Target,
    config: dict[str, Any],
) -> None:
    unknown = sorted(set(config) - SKILL_TARGET_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        msg = f"{path}: [targets.{target.value}] unknown fields: {fields}"
        raise DefinitionError(msg)


def _is_yaml_value(value: Any) -> bool:
    if isinstance(value, str | bool | int):
        return True
    if isinstance(value, list):
        return all(_is_yaml_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_yaml_value(item)
            for key, item in value.items()
        )
    return False


def _render_skill_claude(
    definition: SkillDefinition,
    target_config: dict[str, Any],
) -> str:
    config = _skill_render_config(definition.config, target_config)
    return _render_skill_markdown(
        definition,
        config,
        {
            **SKILL_COMMON_FRONTMATTER_FIELDS,
            **SKILL_CLAUDE_EXTRA_FRONTMATTER_FIELDS,
        },
    )


def _render_skill_codex(
    definition: SkillDefinition,
    target_config: dict[str, Any],
) -> str:
    config = _skill_render_config(definition.config, target_config)
    return _render_skill_markdown(
        definition,
        config,
        SKILL_CODEX_FRONTMATTER_FIELDS,
    )


def _render_skill_copilot(
    definition: SkillDefinition,
    target_config: dict[str, Any],
) -> str:
    config = _skill_render_config(definition.config, target_config)
    return _render_skill_markdown(
        definition,
        config,
        SKILL_COMMON_FRONTMATTER_FIELDS,
    )


def _render_skill_markdown(
    definition: SkillDefinition,
    config: dict[str, Any],
    field_map: dict[str, str],
) -> str:
    frontmatter = {
        "name": str(config.get("name", definition.name)).strip(),
        "description": str(
            config.get("description", definition.description),
        ).strip(),
    }
    for source_key, rendered_key in field_map.items():
        if source_key in config:
            frontmatter[rendered_key] = config[source_key]

    lines = ["---"]
    for key, value in frontmatter.items():
        lines.extend(_yaml_lines(str(key), value))
    body = str(config.get("instructions", definition.instructions)).strip()
    lines.extend(
        [
            "---",
            "",
            f"<!-- {_generated_skill_comment(definition)} -->",
            "",
            body,
            "",
        ],
    )
    return "\n".join(lines)


def _render_skill_codex_openai_yaml(
    definition: SkillDefinition,
) -> str | None:
    target_config = definition.targets.get(Target.CODEX, {})
    config = _skill_render_config(definition.config, target_config)
    payload: dict[str, Any] = {}
    interface = {
        key: config[key]
        for key in sorted(SKILL_CODEX_INTERFACE_FIELDS)
        if key in config
    }
    if interface:
        payload["interface"] = interface

    if "allow_implicit_invocation" in config:
        allow_implicit = config["allow_implicit_invocation"]
    elif config.get("disable_model_invocation") is True:
        allow_implicit = False
    else:
        allow_implicit = None
    if allow_implicit is not None:
        payload["policy"] = {"allow_implicit_invocation": allow_implicit}

    dependencies = config.get("dependencies")
    if dependencies:
        payload["dependencies"] = dependencies

    if not payload:
        return None

    lines = [f"# {_generated_skill_comment(definition)}"]
    for index, (key, value) in enumerate(payload.items()):
        lines.extend(_yaml_lines(key, value))
        if index != len(payload) - 1:
            lines.append("")
    return "\n".join(lines) + "\n"


def _generated_mcp_comment(definition: McpConfigDefinition) -> str:
    try:
        source = definition.source_path.relative_to(definition.root_dir)
    except ValueError:
        source = definition.source_path
    return f"Generated from {source.as_posix()} by agent-def-translator."


def _mcp_target_enabled(
    definition: McpConfigDefinition,
    target: Target,
) -> bool:
    enabled = definition.targets.get(target, {}).get("enabled", True)
    if not isinstance(enabled, bool):
        msg = f"{definition.source_path}: enabled must be a boolean"
        raise DefinitionError(msg)
    return enabled


def _mcp_server_name(
    definition: McpConfigDefinition,
    target_config: dict[str, Any],
) -> str:
    value = target_config.get("server_name", definition.name)
    if not isinstance(value, str) or not value.strip():
        msg = (
            f"{definition.source_path}: server_name must be a non-empty string"
        )
        raise DefinitionError(msg)
    return value.strip()


def _mcp_render_config(
    base: dict[str, Any],
    target_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        **base,
        **{
            key: value
            for key, value in target_config.items()
            if key not in MCP_TARGET_CONTROL_FIELDS
        },
    }


def _validate_mcp_transport_shape(
    path: Path,
    transport: str,
    config: dict[str, Any],
) -> None:
    if transport in {"http", "sse"}:
        if not isinstance(config.get("url"), str) or not config["url"].strip():
            raise DefinitionError(f"{path}: url is required for {transport}")
        if "command" in config:
            raise DefinitionError(
                f"{path}: command is only valid for stdio transport",
            )
    if transport == "stdio":
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise DefinitionError(f"{path}: command is required for stdio")
        if "url" in config:
            raise DefinitionError(
                f"{path}: url is only valid for http or sse transport",
            )


def _validate_mcp_config(path: Path, config: dict[str, Any]) -> None:
    optional_strings = ("url", "command", "bearer_token_env_var")
    for key in optional_strings:
        value = config.get(key)
        if value is not None and not isinstance(value, str):
            raise DefinitionError(f"{path}: {key} must be a string")
    for key in ("args", "tools"):
        value = config.get(key)
        if value is not None and not _is_string_list(value):
            raise DefinitionError(f"{path}: {key} must be a list of strings")
    for key in ("env", "headers"):
        value = config.get(key)
        if value is not None and not _is_string_dict(value):
            raise DefinitionError(
                f"{path}: {key} must be a table of string values",
            )


def _validate_mcp_target_config(
    path: Path,
    target: Target,
    config: dict[str, Any],
) -> None:
    unknown = sorted(set(config) - MCP_TARGET_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        msg = f"{path}: [targets.{target.value}] unknown fields: {fields}"
        raise DefinitionError(msg)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) for item in value
    )


def _is_string_dict(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    )


def _render_mcp_codex(
    definition: McpConfigDefinition,
    target_config: dict[str, Any],
) -> str:
    config = _mcp_render_config(definition.config, target_config)
    transport = str(config.get("transport", definition.transport))
    payload: dict[str, Any] = {}
    if transport in {"http", "sse"}:
        payload["url"] = config["url"]
        token_env = config.get("bearer_token_env_var")
        if token_env is not None:
            payload["bearer_token_env_var"] = token_env
    elif transport == "stdio":
        payload["command"] = config["command"]
        if config.get("args"):
            payload["args"] = config["args"]
        if config.get("env"):
            payload["env"] = config["env"]
    else:
        raise DefinitionError(f"unsupported MCP transport: {transport}")

    server_name = _mcp_server_name(definition, target_config)
    lines = [f"# {_generated_mcp_comment(definition)}"]
    _write_toml_table(lines, ["mcp_servers", server_name], payload)
    return "\n".join(lines) + "\n"


def _render_mcp_claude(
    definition: McpConfigDefinition,
    target_config: dict[str, Any],
) -> str:
    config = _mcp_render_config(definition.config, target_config)
    server = _json_mcp_server(config, definition.transport, claude=True)
    return _json_mcp_fragment(definition, target_config, server)


def _render_mcp_copilot(
    definition: McpConfigDefinition,
    target_config: dict[str, Any],
) -> str:
    config = _mcp_render_config(definition.config, target_config)
    server = _json_mcp_server(config, definition.transport, claude=False)
    if "tools" not in server:
        server["tools"] = ["*"]
    return _json_mcp_fragment(definition, target_config, server)


def _json_mcp_server(
    config: dict[str, Any],
    default_transport: str,
    *,
    claude: bool,
) -> dict[str, Any]:
    transport = str(config.get("transport", default_transport))
    if transport in {"http", "sse"}:
        server: dict[str, Any] = {
            "type": transport,
            "url": config["url"],
        }
        if config.get("headers"):
            server["headers"] = config["headers"]
        if config.get("tools") and not claude:
            server["tools"] = config["tools"]
        return server
    if transport == "stdio":
        server = {
            "type": "stdio" if claude else "local",
            "command": config["command"],
        }
        if config.get("args"):
            server["args"] = config["args"]
        if config.get("env"):
            server["env"] = config["env"]
        if config.get("tools") and not claude:
            server["tools"] = config["tools"]
        return server
    raise DefinitionError(f"unsupported MCP transport: {transport}")


def _json_mcp_fragment(
    definition: McpConfigDefinition,
    target_config: dict[str, Any],
    server: dict[str, Any],
) -> str:
    server_name = _mcp_server_name(definition, target_config)
    payload = {
        "$comment": _generated_mcp_comment(definition),
        "mcpServers": {server_name: server},
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _render_yaml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    msg = f"unsupported YAML scalar type: {type(value).__name__}"
    raise DefinitionError(msg)


def _yaml_lines(key: str, value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines = [f"{prefix}{key}:"]
        for child_key, child_value in value.items():
            lines.extend(_yaml_lines(str(child_key), child_value, indent + 2))
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}{key}: []"]
        lines = [f"{prefix}{key}:"]
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}  -")
                for child_key, child_value in item.items():
                    lines.extend(
                        _yaml_lines(str(child_key), child_value, indent + 6),
                    )
            elif isinstance(item, list):
                raise DefinitionError("nested YAML lists are not supported")
            else:
                lines.append(f"{prefix}  - {_render_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{key}: {_render_yaml_scalar(value)}"]


def _toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    msg = f"unsupported TOML scalar type: {type(value).__name__}"
    raise DefinitionError(msg)


def _write_toml_table(
    lines: list[str],
    path_parts: list[str],
    payload: dict[str, Any],
) -> None:
    scalar_items: list[tuple[str, Any]] = []
    child_tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            child_tables.append((str(key), value))
        else:
            scalar_items.append((str(key), value))

    if path_parts:
        lines.append(f"[{'.'.join(path_parts)}]")
    for key, value in scalar_items:
        if isinstance(value, list):
            rendered = ", ".join(_toml_scalar(item) for item in value)
            lines.append(f"{key} = [{rendered}]")
        else:
            lines.append(f"{key} = {_toml_scalar(value)}")
    if scalar_items and child_tables:
        lines.append("")
    for index, (key, value) in enumerate(child_tables):
        _write_toml_table(lines, [*path_parts, key], value)
        if index != len(child_tables) - 1:
            lines.append("")


def _artifact_has_drift(artifact: GeneratedArtifact) -> bool:
    if not artifact.output_path.exists():
        return True
    if isinstance(artifact.content, bytes):
        return artifact.output_path.read_bytes() != artifact.content
    return artifact.output_path.read_text(encoding="utf-8") != artifact.content


def _write_artifact(artifact: GeneratedArtifact) -> None:
    if isinstance(artifact.content, bytes):
        artifact.output_path.write_bytes(artifact.content)
        return
    artifact.output_path.write_text(artifact.content, encoding="utf-8")
