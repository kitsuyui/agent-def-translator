from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_def_translator._common import (
    MAX_BUNDLE_FILE_BYTES,
    MAX_BUNDLE_FILE_COUNT,
    NAME_PATTERN,
    DefinitionError,
    GeneratedArtifact,
    Target,
    _artifact_has_drift,
    _is_json_value,
    _is_string_list,
    _load_target_configs,
    _load_toml,
    _resolve_relative_path,
    _write_artifacts_batch,
)

_MAX_COPY_TREE_FILE_COUNT = 1000
_MAX_COPY_TREE_FILE_BYTES = 10 * 1024 * 1024

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


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    name: str
    description: str
    version: str
    config: dict[str, Any]
    targets: dict[Target, dict[str, Any]]
    source_path: Path
    root_dir: Path


def load_plugin_definition(
    path: Path,
    *,
    root_dir: Path | None = None,
) -> PluginDefinition:
    root = root_dir or path.parent
    payload = _load_toml(path)
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
        if target_config.get("enabled", True) is not False:
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


def generate_plugins(
    *,
    definitions_dir: Path,
    output_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
    write: bool = True,
) -> list[GeneratedArtifact]:
    definitions = list(load_plugin_definitions(definitions_dir))
    if Target.CODEX in targets:
        codex_plugins = [
            d for d in definitions if _plugin_target_enabled(d, Target.CODEX)
        ]
        if len(codex_plugins) > 1:
            names = ", ".join(d.name for d in codex_plugins)
            msg = (
                f"{definitions_dir}: multiple Codex-enabled plugins: "
                f"{names}. All write to the same codex/marketplace.json"
                " and would silently overwrite each other. "
                "Enable Codex for at most one plugin per directory."
            )
            raise DefinitionError(msg)
    artifacts: list[GeneratedArtifact] = []
    for definition in definitions:
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
        _write_artifacts_batch(artifacts)
    return artifacts


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
        source_root = _resolve_relative_path(
            base_dir=definition.root_dir,
            field_name="components.resources_dir",
            source_path=definition.source_path,
            value=resources_dir,
        )
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
    file_count = 0
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        file_count += 1
        if file_count > MAX_BUNDLE_FILE_COUNT:
            raise DefinitionError(
                f"{source_root}: directory has too many files"
                f" (max {MAX_BUNDLE_FILE_COUNT})",
            )
        file_size = path.stat().st_size
        if file_size > MAX_BUNDLE_FILE_BYTES:
            raise DefinitionError(
                f"{path}: file too large"
                f" ({file_size} bytes, max {MAX_BUNDLE_FILE_BYTES})",
            )
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
    file_count = 0
    for path in sorted(source_root.glob("*.json")):
        file_count += 1
        if file_count > _MAX_COPY_TREE_FILE_COUNT:
            raise DefinitionError(
                f"{source_root}: too many MCP fragment files"
                f" (max {_MAX_COPY_TREE_FILE_COUNT})",
            )
        file_size = path.stat().st_size
        if file_size > _MAX_COPY_TREE_FILE_BYTES:
            raise DefinitionError(
                f"{path}: MCP fragment file too large"
                f" ({file_size} bytes, max {_MAX_COPY_TREE_FILE_BYTES})",
            )
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise DefinitionError(f"{path}: {e}") from e
        servers = fragment.get("mcpServers")
        if not isinstance(servers, dict):
            continue
        payload["mcpServers"].update(servers)
    return payload


def _merge_codex_mcp_fragments(source_root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"mcpServers": {}}
    file_count = 0
    for path in sorted(source_root.glob("*.toml")):
        file_count += 1
        if file_count > _MAX_COPY_TREE_FILE_COUNT:
            raise DefinitionError(
                f"{source_root}: too many MCP fragment files"
                f" (max {_MAX_COPY_TREE_FILE_COUNT})",
            )
        file_size = path.stat().st_size
        if file_size > _MAX_COPY_TREE_FILE_BYTES:
            raise DefinitionError(
                f"{path}: MCP fragment file too large"
                f" ({file_size} bytes, max {_MAX_COPY_TREE_FILE_BYTES})",
            )
        fragment = _load_toml(path)
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
