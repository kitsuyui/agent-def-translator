from __future__ import annotations

import json
import re
import sys
import tempfile
import warnings
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
PLUGIN_ROOT_FIELDS = frozenset(
    {
        "name",
        "description",
        "version",
        "author",
        "repository",
        "homepage",
        "license",
        "keywords",
        "components",
        "interface",
        "marketplace",
        "targets",
    },
)
PLUGIN_COMPONENT_FIELDS = frozenset(
    {
        "subagents",
        "skills",
        "mcp",
        "resources_dir",
        "require_subagents",
        "require_skills",
        "require_mcp",
        "require_resources",
    },
)
PLUGIN_INTERFACE_FIELDS = frozenset(
    {
        "display_name",
        "short_description",
        "long_description",
        "developer_name",
        "category",
        "capabilities",
        "website_url",
    },
)
PLUGIN_MARKETPLACE_FIELDS = frozenset(
    {
        "name",
        "display_name",
        "source_path",
        "installation",
        "authentication",
        "category",
    },
)
PLUGIN_TARGET_CONTROL_FIELDS = frozenset({"enabled"})
PLUGIN_TARGET_FIELDS = frozenset(
    {
        "name",
        "description",
        "version",
        "author",
        "repository",
        "homepage",
        "license",
        "keywords",
        "components",
        "interface",
        "marketplace",
        *PLUGIN_TARGET_CONTROL_FIELDS,
    },
)


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
    mode: int | None = None


@dataclass(frozen=True, slots=True)
class McpConfigDefinition:
    name: str
    description: str
    transport: str
    config: dict[str, Any]
    targets: dict[Target, dict[str, Any]]
    source_path: Path
    root_dir: Path


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    name: str
    description: str
    version: str
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


def load_plugin_definition(
    path: Path,
    *,
    root_dir: Path | None = None,
) -> PluginDefinition:
    root = root_dir or path.parent
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = sorted(set(payload) - PLUGIN_ROOT_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        raise DefinitionError(f"{path}: unknown top-level fields: {fields}")

    for field in ("name", "description", "version"):
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

    config = {
        key: value
        for key, value in payload.items()
        if key not in {"name", "description", "version", "targets"}
    }
    _validate_plugin_config(path, config)
    targets = _load_target_configs(path, payload)
    for target, target_config in targets.items():
        _validate_plugin_target_config(path, target, target_config)
        _validate_plugin_config(
            path,
            _plugin_render_config(config, target_config),
        )
    return PluginDefinition(
        name=name,
        description=payload["description"].strip(),
        version=payload["version"].strip(),
        config=config,
        targets=targets,
        source_path=path,
        root_dir=root,
    )


def load_plugin_definitions(definitions_dir: Path) -> list[PluginDefinition]:
    if not definitions_dir.is_dir():
        msg = f"definitions directory not found: {definitions_dir}"
        raise DefinitionError(msg)
    definitions = [
        load_plugin_definition(path, root_dir=definitions_dir)
        for path in sorted(definitions_dir.glob("*.toml"))
    ]
    _reject_duplicate_plugin_names(definitions)
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


def validate_plugin_definitions(
    definitions_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[PluginDefinition]:
    definitions = load_plugin_definitions(definitions_dir)
    for definition in definitions:
        for target in targets:
            if _plugin_target_enabled(definition, target):
                render_plugin_manifest(definition, target)
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


def render_plugin_manifest(
    definition: PluginDefinition,
    target: Target,
) -> str:
    target_config = definition.targets.get(target, {})
    if not _plugin_target_enabled(definition, target):
        msg = f"{definition.source_path}: target disabled: {target.value}"
        raise DefinitionError(msg)
    config = _plugin_render_config(definition.config, target_config)
    if target == Target.CLAUDE:
        payload = _plugin_common_manifest(definition, config)
        return _json_plugin_manifest(definition, payload)
    if target == Target.CODEX:
        payload = _plugin_common_manifest(definition, config)
        components = _plugin_components(config)
        if components.get("skills") is True:
            payload["skills"] = "./skills/"
        interface = _plugin_codex_interface(definition, config)
        if interface:
            payload["interface"] = interface
        return _json_plugin_manifest(definition, payload)
    if target == Target.COPILOT:
        payload = _plugin_common_manifest(definition, config)
        components = _plugin_components(config)
        if components.get("subagents") is True:
            payload["agents"] = "./agents/"
        if components.get("skills") is True:
            payload["skills"] = "./skills/"
        return _json_plugin_manifest(definition, payload)
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


def generate_plugins(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
    write: bool = True,
) -> list[GeneratedArtifact]:
    artifacts: list[GeneratedArtifact] = []
    for definition in load_plugin_definitions(definitions_dir):
        for target in targets:
            if not _plugin_target_enabled(definition, target):
                continue
            manifest = GeneratedArtifact(
                target=target,
                source_path=definition.source_path,
                output_path=plugin_manifest_output_path(
                    output_dir,
                    definition.name,
                    target,
                ),
                content=render_plugin_manifest(definition, target),
            )
            target_artifacts = [
                manifest,
                *_plugin_bundle_artifacts(definition, output_dir, target),
            ]
            if target == Target.CODEX:
                target_artifacts.append(
                    GeneratedArtifact(
                        target=target,
                        source_path=definition.source_path,
                        output_path=plugin_marketplace_output_path(output_dir),
                        content=_render_codex_marketplace(
                            definition,
                            definition.targets.get(target, {}),
                        ),
                    ),
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


def check_plugin_drift(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[Path]:
    artifacts = generate_plugins(
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


def plugin_root_path(output_dir: Path, name: str, target: Target) -> Path:
    if target == Target.CLAUDE:
        return output_dir / "claude" / "plugins" / name
    if target == Target.CODEX:
        return output_dir / "codex" / "plugins" / name
    if target == Target.COPILOT:
        return output_dir / "copilot" / "plugins" / name
    raise DefinitionError(f"unsupported target: {target}")


def plugin_manifest_output_path(
    output_dir: Path,
    name: str,
    target: Target,
) -> Path:
    root = plugin_root_path(output_dir, name, target)
    if target == Target.CLAUDE:
        return root / ".claude-plugin" / "plugin.json"
    if target == Target.CODEX:
        return root / ".codex-plugin" / "plugin.json"
    if target == Target.COPILOT:
        return root / "plugin.json"
    raise DefinitionError(f"unsupported target: {target}")


def plugin_marketplace_output_path(output_dir: Path) -> Path:
    return output_dir / "codex" / "marketplace.json"


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
    target_sources: dict[Target, str] = {}
    for key, value in targets_payload.items():
        target = Target.parse(str(key))
        if not isinstance(value, dict):
            raise DefinitionError(f"{path}: [targets.{key}] must be a table")
        configs[target] = dict(value)
        target_sources[target] = f"[targets.{key}]"

    legacy_used: list[str] = []
    for legacy_key in sorted(LEGACY_TARGET_FIELDS):
        if legacy_key not in payload:
            continue
        target = Target.parse(legacy_key)
        value = payload[legacy_key]
        if not isinstance(value, dict):
            raise DefinitionError(f"{path}: [{legacy_key}] must be a table")
        if target in configs:
            existing = target_sources[target]
            msg = (
                f"{path}: target {target.value!r} is configured twice: "
                f"{existing} and [{legacy_key}]. Use only [targets.<target>]."
            )
            raise DefinitionError(msg)
        configs[target] = dict(value)
        target_sources[target] = f"[{legacy_key}]"
        legacy_used.append(legacy_key)

    if legacy_used:
        joined = ", ".join(f"[{key}]" for key in legacy_used)
        warnings.warn(
            (
                f"{path}: legacy top-level target tables ({joined}) are "
                f"deprecated; use [targets.<target>] instead."
            ),
            DeprecationWarning,
            stacklevel=2,
        )

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


def _reject_duplicate_plugin_names(
    definitions: list[PluginDefinition],
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
                mode=path.stat().st_mode & 0o777,
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


def _plugin_target_enabled(
    definition: PluginDefinition,
    target: Target,
) -> bool:
    enabled = definition.targets.get(target, {}).get("enabled", True)
    if not isinstance(enabled, bool):
        msg = f"{definition.source_path}: enabled must be a boolean"
        raise DefinitionError(msg)
    return enabled


def _plugin_render_config(
    base: dict[str, Any],
    target_config: dict[str, Any],
) -> dict[str, Any]:
    config = {
        **base,
        **{
            key: value
            for key, value in target_config.items()
            if key not in PLUGIN_TARGET_CONTROL_FIELDS
        },
    }
    if "components" in base or "components" in target_config:
        config["components"] = {
            **_plugin_component_table(base),
            **_plugin_component_table(target_config),
        }
    if "interface" in base or "interface" in target_config:
        config["interface"] = {
            **_plugin_table(base, "interface"),
            **_plugin_table(target_config, "interface"),
        }
    if "marketplace" in base or "marketplace" in target_config:
        config["marketplace"] = {
            **_plugin_table(base, "marketplace"),
            **_plugin_table(target_config, "marketplace"),
        }
    return config


def _validate_plugin_config(path: Path, config: dict[str, Any]) -> None:
    for key in (
        "name",
        "description",
        "version",
        "author",
        "repository",
        "homepage",
        "license",
    ):
        value = config.get(key)
        if value is not None and not isinstance(value, str):
            raise DefinitionError(f"{path}: {key} must be a string")
    keywords = config.get("keywords")
    if keywords is not None and not _is_string_list(keywords):
        raise DefinitionError(f"{path}: keywords must be a list of strings")
    _validate_plugin_components(path, config.get("components"))
    _validate_plugin_interface(path, config.get("interface"))
    _validate_plugin_marketplace(path, config.get("marketplace"))


def _validate_plugin_components(path: Path, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise DefinitionError(f"{path}: [components] must be a table")
    unknown = sorted(set(value) - PLUGIN_COMPONENT_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        raise DefinitionError(
            f"{path}: [components] unknown fields: {fields}",
        )
    for key in (
        "subagents",
        "skills",
        "mcp",
        "require_subagents",
        "require_skills",
        "require_mcp",
        "require_resources",
    ):
        component_value = value.get(key)
        if component_value is not None and not isinstance(
            component_value,
            bool,
        ):
            raise DefinitionError(
                f"{path}: components.{key} must be a boolean",
            )
    resources_dir = value.get("resources_dir")
    if resources_dir is not None and not isinstance(resources_dir, str):
        raise DefinitionError(
            f"{path}: components.resources_dir must be a string",
        )


def _validate_plugin_interface(path: Path, value: Any) -> None:
    if value is None:
        return
    _validate_plugin_named_table(
        path,
        "interface",
        value,
        PLUGIN_INTERFACE_FIELDS,
    )
    for key in (
        "display_name",
        "short_description",
        "long_description",
        "developer_name",
        "category",
        "website_url",
    ):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise DefinitionError(f"{path}: interface.{key} must be a string")
    capabilities = value.get("capabilities")
    if capabilities is not None and not _is_string_list(capabilities):
        raise DefinitionError(
            f"{path}: interface.capabilities must be a list of strings",
        )


def _validate_plugin_marketplace(path: Path, value: Any) -> None:
    if value is None:
        return
    _validate_plugin_named_table(
        path,
        "marketplace",
        value,
        PLUGIN_MARKETPLACE_FIELDS,
    )
    for key in PLUGIN_MARKETPLACE_FIELDS:
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise DefinitionError(
                f"{path}: marketplace.{key} must be a string",
            )


def _validate_plugin_named_table(
    path: Path,
    name: str,
    value: Any,
    allowed_fields: frozenset[str],
) -> None:
    if not isinstance(value, dict):
        raise DefinitionError(f"{path}: [{name}] must be a table")
    unknown = sorted(set(value) - allowed_fields)
    if unknown:
        fields = ", ".join(unknown)
        raise DefinitionError(f"{path}: [{name}] unknown fields: {fields}")


def _validate_plugin_target_config(
    path: Path,
    target: Target,
    config: dict[str, Any],
) -> None:
    unknown = sorted(set(config) - PLUGIN_TARGET_FIELDS)
    if unknown:
        fields = ", ".join(unknown)
        msg = f"{path}: [targets.{target.value}] unknown fields: {fields}"
        raise DefinitionError(msg)


def _plugin_components(config: dict[str, Any]) -> dict[str, Any]:
    components = config.get("components")
    if components is None:
        return {"subagents": True, "skills": True, "mcp": True}
    return _plugin_component_table(config)


def _plugin_component_table(config: dict[str, Any]) -> dict[str, Any]:
    components = config.get("components")
    if not isinstance(components, dict):
        return {}
    return dict(components)


def _plugin_table(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _plugin_common_manifest(
    definition: PluginDefinition,
    config: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": str(config.get("name", definition.name)),
        "version": str(config.get("version", definition.version)),
        "description": str(config.get("description", definition.description)),
    }
    author = config.get("author")
    if author is not None:
        payload["author"] = {"name": author}
    for key in ("repository", "homepage", "license", "keywords"):
        value = config.get(key)
        if value is not None:
            payload[key] = value
    return payload


def _plugin_codex_interface(
    definition: PluginDefinition,
    config: dict[str, Any],
) -> dict[str, Any]:
    interface = _plugin_table(config, "interface")
    payload: dict[str, Any] = {}
    field_map = {
        "display_name": "displayName",
        "short_description": "shortDescription",
        "long_description": "longDescription",
        "developer_name": "developerName",
        "category": "category",
        "capabilities": "capabilities",
        "website_url": "websiteURL",
    }
    for source_key, rendered_key in field_map.items():
        if source_key in interface:
            payload[rendered_key] = interface[source_key]
    payload.setdefault("displayName", definition.name)
    payload.setdefault("shortDescription", definition.description)
    payload.setdefault("longDescription", definition.description)
    if "author" in config:
        payload.setdefault("developerName", config["author"])
    payload.setdefault("category", "Productivity")
    return payload


def _json_plugin_manifest(
    definition: PluginDefinition,
    payload: dict[str, Any],
) -> str:
    if not _is_json_value(payload):
        msg = f"{definition.source_path}: plugin manifest must be JSON-safe"
        raise DefinitionError(msg)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _generated_plugin_comment(definition: PluginDefinition) -> str:
    try:
        source = definition.source_path.relative_to(definition.root_dir)
    except ValueError:
        source = definition.source_path
    return f"Generated from {source.as_posix()} by agent-def-translator."


def _plugin_bundle_artifacts(
    definition: PluginDefinition,
    output_dir: Path,
    target: Target,
) -> list[GeneratedArtifact]:
    target_config = definition.targets.get(target, {})
    config = _plugin_render_config(definition.config, target_config)
    components = _plugin_components(config)
    plugin_root = plugin_root_path(output_dir, definition.name, target)
    artifacts: list[GeneratedArtifact] = []
    if components.get("subagents") is True:
        artifacts.extend(
            _copy_tree_artifacts(
                target=target,
                source_root=output_dir / target.value / "agents",
                output_root=plugin_root / "agents",
                required=_plugin_component_required(
                    components,
                    "subagents",
                ),
            ),
        )
    if components.get("skills") is True:
        artifacts.extend(
            _copy_tree_artifacts(
                target=target,
                source_root=output_dir / target.value / "skills",
                output_root=plugin_root / "skills",
                required=_plugin_component_required(components, "skills"),
            ),
        )
    if components.get("mcp") is True:
        artifact = _plugin_mcp_artifact(
            definition,
            output_dir,
            target,
            required=_plugin_component_required(components, "mcp"),
        )
        if artifact is not None:
            artifacts.append(artifact)

    resources_dir = components.get("resources_dir")
    if isinstance(resources_dir, str) and resources_dir.strip():
        source_root = definition.root_dir / resources_dir
        artifacts.extend(
            _copy_tree_artifacts(
                target=target,
                source_root=source_root,
                output_root=plugin_root,
                required=_plugin_component_required(components, "resources"),
            ),
        )
    return artifacts


def _plugin_component_required(
    components: dict[str, Any],
    name: str,
) -> bool:
    value = components.get(f"require_{name}", True)
    return bool(value)


def _copy_tree_artifacts(
    *,
    target: Target,
    source_root: Path,
    output_root: Path,
    required: bool = True,
) -> list[GeneratedArtifact]:
    if not source_root.is_dir():
        if not required:
            return []
        msg = f"component directory not found: {source_root}"
        raise DefinitionError(msg)
    artifacts: list[GeneratedArtifact] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        artifacts.append(
            GeneratedArtifact(
                target=target,
                source_path=path,
                output_path=output_root / path.relative_to(source_root),
                content=path.read_bytes(),
                mode=path.stat().st_mode & 0o777,
            ),
        )
    return artifacts


def _plugin_mcp_artifact(
    definition: PluginDefinition,
    output_dir: Path,
    target: Target,
    *,
    required: bool = True,
) -> GeneratedArtifact | None:
    source_root = output_dir / target.value / "mcp"
    if not source_root.is_dir():
        if not required:
            return None
        msg = f"component directory not found: {source_root}"
        raise DefinitionError(msg)
    if target == Target.CODEX:
        payload = _merge_codex_mcp_fragments(source_root)
    else:
        payload = _merge_json_mcp_fragments(source_root)
    if not payload.get("mcpServers"):
        if not required:
            return None
        msg = f"no MCP servers found in: {source_root}"
        raise DefinitionError(msg)
    payload = {
        "$comment": _generated_plugin_comment(definition),
        **payload,
    }
    return GeneratedArtifact(
        target=target,
        source_path=definition.source_path,
        output_path=plugin_root_path(output_dir, definition.name, target)
        / ".mcp.json",
        content=json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _merge_json_mcp_fragments(source_root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"mcpServers": {}}
    for path in sorted(source_root.glob("*.json")):
        fragment = json.loads(path.read_text(encoding="utf-8"))
        servers = fragment.get("mcpServers")
        if not isinstance(servers, dict):
            continue
        payload["mcpServers"].update(servers)
    return payload


def _merge_codex_mcp_fragments(source_root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"mcpServers": {}}
    for path in sorted(source_root.glob("*.toml")):
        fragment = tomllib.loads(path.read_text(encoding="utf-8"))
        servers = fragment.get("mcp_servers")
        if not isinstance(servers, dict):
            continue
        payload["mcpServers"].update(servers)
    return payload


def _render_codex_marketplace(
    definition: PluginDefinition,
    target_config: dict[str, Any],
) -> str:
    config = _plugin_render_config(definition.config, target_config)
    marketplace = _plugin_table(config, "marketplace")
    interface = {
        "displayName": marketplace.get(
            "display_name",
            f"{definition.name} Local Plugins",
        ),
    }
    payload = {
        "name": marketplace.get("name", f"{definition.name}-local"),
        "interface": interface,
        "plugins": [
            {
                "name": str(config.get("name", definition.name)),
                "source": {
                    "source": "local",
                    "path": marketplace.get(
                        "source_path",
                        f"./plugins/{definition.name}",
                    ),
                },
                "policy": {
                    "installation": marketplace.get(
                        "installation",
                        "AVAILABLE",
                    ),
                    "authentication": marketplace.get(
                        "authentication",
                        "ON_INSTALL",
                    ),
                },
                "category": marketplace.get("category", "Productivity"),
            },
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, str | bool | int | float):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in value.items()
        )
    return False


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
        for child_key, child_value in _sorted_mapping_items(value):
            lines.extend(_yaml_lines(str(child_key), child_value, indent + 2))
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}{key}: []"]
        lines = [f"{prefix}{key}:"]
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}  -")
                for child_key, child_value in _sorted_mapping_items(item):
                    lines.extend(
                        _yaml_lines(str(child_key), child_value, indent + 6),
                    )
            elif isinstance(item, list):
                raise DefinitionError("nested YAML lists are not supported")
            else:
                lines.append(f"{prefix}  - {_render_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{key}: {_render_yaml_scalar(value)}"]


def _sorted_mapping_items(
    payload: dict[Any, Any],
) -> list[tuple[Any, Any]]:
    return sorted(payload.items(), key=lambda item: str(item[0]))


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
        content_drifted = artifact.output_path.read_bytes() != artifact.content
    else:
        content_drifted = (
            artifact.output_path.read_text(encoding="utf-8")
            != artifact.content
        )
    if content_drifted:
        return True
    return _artifact_mode_has_drift(artifact)


def _write_artifact(artifact: GeneratedArtifact) -> None:
    content = (
        artifact.content
        if isinstance(artifact.content, bytes)
        else artifact.content.encode("utf-8")
    )
    parent = artifact.output_path.parent
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            dir=parent,
            suffix=".tmp",
        ) as f:
            tmp_path = Path(f.name)
            f.write(content)
        tmp_path.replace(artifact.output_path)
        tmp_path = None
    except OSError as exc:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        msg = (
            f"failed to write {artifact.output_path}"
            f" (target={artifact.target.value},"
            f" source={artifact.source_path}): {exc}"
        )
        raise OSError(msg) from exc
    _chmod_artifact(artifact)


def _artifact_mode_has_drift(artifact: GeneratedArtifact) -> bool:
    if artifact.mode is None:
        return False
    return (artifact.output_path.stat().st_mode & 0o777) != artifact.mode


def _chmod_artifact(artifact: GeneratedArtifact) -> None:
    if artifact.mode is None:
        return
    try:
        artifact.output_path.chmod(artifact.mode)
    except OSError as exc:
        msg = (
            f"failed to chmod {artifact.output_path}"
            f" (target={artifact.target.value},"
            f" source={artifact.source_path},"
            f" mode={oct(artifact.mode)}): {exc}"
        )
        raise OSError(msg) from exc
