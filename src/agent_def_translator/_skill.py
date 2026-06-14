from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_def_translator._common import (
    DefinitionError,
    GeneratedArtifact,
    Target,
    _artifact_has_drift,
    _is_string_list,
    _is_yaml_value,
    _load_target_configs,
    _load_toml,
    _write_artifacts_batch,
    _yaml_lines,
)

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_MAX_BUNDLE_FILE_COUNT = 1000
_MAX_BUNDLE_FILE_BYTES = 10 * 1024 * 1024
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


def load_skill_definition(
    path: Path,
    *,
    root_dir: Path | None = None,
) -> SkillDefinition:
    root = root_dir or path.parent
    payload = _load_toml(path)
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
        if target_config.get("enabled", True) is not False:
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
        _write_artifacts_batch(artifacts)
    return artifacts


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
    file_count = 0
    for path in sorted(definition.bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        file_count += 1
        if file_count > _MAX_BUNDLE_FILE_COUNT:
            raise DefinitionError(
                f"{definition.bundle_dir}: bundle has too many files"
                f" (max {_MAX_BUNDLE_FILE_COUNT})",
            )
        file_size = path.stat().st_size
        if file_size > _MAX_BUNDLE_FILE_BYTES:
            raise DefinitionError(
                f"{path}: bundle file too large"
                f" ({file_size} bytes, max {_MAX_BUNDLE_FILE_BYTES})",
            )
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


def _validate_invocation_policy_coherence(
    path: Path,
    config: dict[str, Any],
) -> None:
    if (
        config.get("allow_implicit_invocation") is True
        and config.get("disable_model_invocation") is True
    ):
        raise DefinitionError(
            f"{path}: allow_implicit_invocation=true conflicts with"
            " disable_model_invocation=true; implicit invocation cannot be"
            " allowed when model invocation is disabled",
        )


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
    _validate_invocation_policy_coherence(path, config)

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


def _generated_skill_comment(definition: SkillDefinition) -> str:
    try:
        source = definition.source_path.relative_to(definition.root_dir)
    except ValueError:
        source = definition.source_path
    return f"Generated from {source.as_posix()} by agent-def-translator."


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
