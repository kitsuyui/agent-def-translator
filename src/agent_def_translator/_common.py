from __future__ import annotations

import json
import re
import tempfile
import warnings
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
LEGACY_TARGET_FIELDS = frozenset({"claude", "codex", "vscode", "copilot"})


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
class GeneratedArtifact:
    target: Target
    source_path: Path
    output_path: Path
    content: str | bytes
    mode: int | None = None


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


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) for item in value
    )


def _is_string_dict(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    )


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


def _write_artifacts_batch(artifacts: list[GeneratedArtifact]) -> None:
    """Write artifacts with a minimized partial-state window.

    Phase 1 (slow): write all content to temp files in the same directories
    as the final paths so rename is atomic on POSIX.
    Phase 2 (fast): rename all temp files to their final paths.

    On failure during phase 1, any created temp files are removed.
    """
    for artifact in artifacts:
        artifact.output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_paths: list[Path | None] = [None] * len(artifacts)
    try:
        for i, artifact in enumerate(artifacts):
            content = (
                artifact.content
                if isinstance(artifact.content, bytes)
                else artifact.content.encode("utf-8")
            )
            with tempfile.NamedTemporaryFile(
                delete=False,
                dir=artifact.output_path.parent,
                suffix=".tmp",
            ) as f:
                tmp_paths[i] = Path(f.name)
                f.write(content)
        for i, artifact in enumerate(artifacts):
            tmp = tmp_paths[i]
            if tmp is not None:
                tmp.replace(artifact.output_path)
                tmp_paths[i] = None
            _chmod_artifact(artifact)
    except OSError:
        for tmp in tmp_paths:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        raise


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
