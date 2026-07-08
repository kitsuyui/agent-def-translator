from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_def_translator._common import (
    NAME_PATTERN,
    DefinitionError,
    GeneratedArtifact,
    Target,
    _artifact_has_drift,
    _is_string_dict,
    _is_string_list,
    _load_target_configs,
    _load_toml,
    _write_artifacts_batch,
    _write_toml_table,
    coerce_targets,
)

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


@dataclass(frozen=True, slots=True)
class McpConfigDefinition:
    name: str
    description: str
    transport: str
    config: dict[str, Any]
    targets: dict[Target, dict[str, Any]]
    source_path: Path
    root_dir: Path


def load_mcp_config_definition(
    path: Path,
    *,
    root_dir: Path | None = None,
) -> McpConfigDefinition:
    root = root_dir or path.parent
    payload = _load_toml(path)
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
        if target_config.get("enabled", True) is not False:
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


def validate_mcp_config_definitions(
    definitions_dir: Path,
    targets: tuple[Target | str, ...] = tuple(Target),
) -> list[McpConfigDefinition]:
    definitions = load_mcp_config_definitions(definitions_dir)
    targets = coerce_targets(targets)
    for definition in definitions:
        for target in targets:
            if _mcp_target_enabled(definition, target):
                render_mcp_config(definition, target)
    return definitions


def render_mcp_config(
    definition: McpConfigDefinition,
    target: Target | str,
) -> str:
    target = Target.parse(target)
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


def generate_mcp_configs(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target | str, ...] = tuple(Target),
    write: bool = True,
) -> list[GeneratedArtifact]:
    targets = coerce_targets(targets)
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
        _write_artifacts_batch(artifacts)
    return artifacts


def check_mcp_config_drift(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target | str, ...] = tuple(Target),
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


def mcp_output_path(output_dir: Path, name: str, target: Target | str) -> Path:
    target = Target.parse(target)
    if target == Target.CODEX:
        return output_dir / "codex" / "mcp" / f"{name}.toml"
    if target == Target.CLAUDE:
        return output_dir / "claude" / "mcp" / f"{name}.json"
    if target == Target.COPILOT:
        return output_dir / "copilot" / "mcp" / f"{name}.json"
    raise DefinitionError(f"unsupported target: {target}")


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
    tools = config.get("tools")
    if transport in {"http", "sse"}:
        server: dict[str, Any] = {
            "type": transport,
            "url": config["url"],
        }
        if config.get("headers"):
            server["headers"] = config["headers"]
        if not claude and "tools" in config and tools is not None:
            server["tools"] = tools
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
        if not claude and "tools" in config and tools is not None:
            server["tools"] = tools
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
