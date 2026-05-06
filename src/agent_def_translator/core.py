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
PROMPT_FIELDS = frozenset(
    {"prompt_override", "prompt_append", "prompt_append_file"},
)
ROOT_FIELDS = frozenset({"name", "description", "instructions", "targets"})
LEGACY_TARGET_FIELDS = frozenset({"claude", "codex", "vscode", "copilot"})


class DefinitionError(ValueError):
    """Raised when an agent definition cannot be translated."""


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
class GeneratedArtifact:
    target: Target
    source_path: Path
    output_path: Path
    content: str


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


def validate_definitions(
    definitions_dir: Path,
    targets: tuple[Target, ...] = tuple(Target),
) -> list[AgentDefinition]:
    definitions = load_definitions(definitions_dir)
    for definition in definitions:
        for target in targets:
            render(definition, target)
    return definitions


def render(definition: AgentDefinition, target: Target) -> str:
    if target == Target.CLAUDE:
        return _render_claude(definition)
    if target == Target.CODEX:
        return _render_codex(definition)
    if target == Target.COPILOT:
        return _render_copilot(definition)
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
                path.write_text(content, encoding="utf-8")
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


def output_path(output_dir: Path, name: str, target: Target) -> Path:
    if target == Target.CLAUDE:
        return output_dir / "claude" / "agents" / f"{name}.md"
    if target == Target.CODEX:
        return output_dir / "codex" / "agents" / f"{name}.toml"
    if target == Target.COPILOT:
        return output_dir / "copilot" / "agents" / f"{name}.agent.md"
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
    return artifact.output_path.read_text(encoding="utf-8") != artifact.content
