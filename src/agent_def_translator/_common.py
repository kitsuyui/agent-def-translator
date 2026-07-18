from __future__ import annotations

import contextlib
import ctypes
import errno
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Generator, Iterator
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover
    _fcntl = None  # type: ignore[assignment]

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_YAML_SAFE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
LEGACY_TARGET_FIELDS = frozenset({"claude", "codex", "vscode", "copilot"})

MAX_BUNDLE_FILE_COUNT = 1000
MAX_BUNDLE_FILE_BYTES = 10 * 1024 * 1024
DEPRECATION_REMOVAL_NOTICE = (
    "scheduled for removal no earlier than agent-def-translator 1.0.0"
)
_AT_FDCWD = -100
_RENAME_EXCHANGE = 0x2
_libc = ctypes.CDLL(None, use_errno=True)


class DefinitionError(ValueError):
    """Raised when a definition cannot be translated."""


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise DefinitionError(f"{path}: {e}") from e


class Target(Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"

    @classmethod
    def parse(cls, value: Target | str) -> Target:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            choices = ", ".join(item.value for item in cls)
            msg = f"unsupported target: {value}. Expected one of: {choices}"
            raise DefinitionError(msg)
        # "vscode" is accepted as a compatibility alias for COPILOT.
        normalized = value.strip().lower()
        if normalized == "vscode":
            return cls.COPILOT
        try:
            return cls(normalized)
        except ValueError as exc:
            choices = ", ".join(item.value for item in cls)
            msg = f"unsupported target: {value}. Expected one of: {choices}"
            raise DefinitionError(msg) from exc


def coerce_targets(values: tuple[Target | str, ...]) -> tuple[Target, ...]:
    return tuple(Target.parse(value) for value in values)


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
        print(
            f"Warning: {path}: legacy top-level target tables ({joined}) are "
            f"deprecated and {DEPRECATION_REMOVAL_NOTICE}; "
            "use [targets.<target>] instead.",
            file=sys.stderr,
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


def _resolve_relative_path(
    *,
    base_dir: Path,
    field_name: str,
    source_path: Path,
    value: str,
    containment_dir: Path | None = None,
) -> Path:
    if Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        msg = f"{source_path}: {field_name} must be a relative path"
        raise DefinitionError(msg)
    resolved = (base_dir / value).resolve()
    root = (containment_dir or base_dir).resolve()
    if resolved != root and root not in resolved.parents:
        msg = f"{source_path}: {field_name} must stay within {root}"
        raise DefinitionError(msg)
    return resolved


def _iter_bundle_files(source_root: Path) -> Iterator[Path]:
    """Yield regular files under source_root, rejecting symlinks."""
    resolved_root = source_root.resolve()
    for path in sorted(source_root.rglob("*")):
        if path.is_symlink():
            raise DefinitionError(
                f"{path}: symlinks are not allowed in bundle directories",
            )
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved_root not in resolved.parents:
            raise DefinitionError(
                f"{path}: resolved path escapes bundle root {resolved_root}",
            )
        yield path


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


def _yaml_key(key: str) -> str:
    if _YAML_SAFE_KEY_RE.fullmatch(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _yaml_lines(key: str, value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    safe_key = _yaml_key(key)
    if isinstance(value, dict):
        lines = [f"{prefix}{safe_key}:"]
        for child_key, child_value in _sorted_mapping_items(value):
            lines.extend(_yaml_lines(str(child_key), child_value, indent + 2))
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}{safe_key}: []"]
        lines = [f"{prefix}{safe_key}:"]
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
    return [f"{prefix}{safe_key}: {_render_yaml_scalar(value)}"]


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
        _chmod_artifact(artifact, path=tmp_path)
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
    except BaseException:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def _swap_paths_atomic(left: Path, right: Path) -> None:
    left_bytes = os.fsencode(left)
    right_bytes = os.fsencode(right)
    if sys.platform.startswith("linux"):
        renameat2 = getattr(_libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(
                errno.ENOTSUP,
                "atomic directory swap is not supported on this platform",
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            _AT_FDCWD,
            left_bytes,
            _AT_FDCWD,
            right_bytes,
            _RENAME_EXCHANGE,
        )
    elif sys.platform == "darwin":
        renamex_np = getattr(_libc, "renamex_np", None)
        if renamex_np is None:
            raise OSError(
                errno.ENOTSUP,
                "atomic directory swap is not supported on this platform",
            )
        renamex_np.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(left_bytes, right_bytes, _RENAME_EXCHANGE)
    else:
        raise OSError(
            errno.ENOTSUP,
            "atomic directory swap is not supported on this platform",
        )
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(left))


def _write_artifacts_batch_via_output_dir_snapshot(
    artifacts: list[GeneratedArtifact],
    output_dir: Path,
) -> None:
    staged_root = Path(
        tempfile.mkdtemp(
            dir=output_dir.parent,
            prefix=f".{output_dir.name}.",
            suffix=".staging",
        ),
    )
    swapped = False
    try:
        if output_dir.exists():
            shutil.copytree(output_dir, staged_root, dirs_exist_ok=True)
        staged_artifacts = [
            replace(
                artifact,
                output_path=staged_root
                / artifact.output_path.relative_to(output_dir),
            )
            for artifact in artifacts
        ]
        _write_artifacts_batch(staged_artifacts)
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
        _swap_paths_atomic(staged_root, output_dir)
        swapped = True
        shutil.rmtree(staged_root)
    except ValueError as exc:
        msg = "artifact output_path must stay within output_dir"
        raise OSError(msg) from exc
    finally:
        if not swapped:
            shutil.rmtree(staged_root, ignore_errors=True)


@contextlib.contextmanager
def _output_dir_write_lock(output_dir: Path) -> Generator[None, None, None]:
    """Hold an exclusive cross-process write lock on output_dir.

    Uses fcntl.flock on POSIX. A no-op on platforms without fcntl (Windows).
    """
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.translate.lock"
    if _fcntl is None:  # pragma: no cover
        yield
        return
    with lock_path.open("w") as lf:
        _fcntl.flock(lf, _fcntl.LOCK_EX)
        try:
            yield
        finally:
            _fcntl.flock(lf, _fcntl.LOCK_UN)


def _write_artifacts_batch(
    artifacts: list[GeneratedArtifact],
    output_dir: Path | None = None,
) -> None:
    """Write artifacts with a minimized partial-state window.

    Phase 1 (slow): write all content to temp files in the same directories
    as the final paths so rename is atomic on POSIX.
    Phase 2 (fast): rename all temp files to their final paths.

    On failure during phase 1, any created temp files are removed.
    When output_dir is provided, an exclusive cross-process file lock is held
    for the duration so concurrent translate runs cannot interleave writes.
    """
    if output_dir is not None:
        with _output_dir_write_lock(output_dir):
            _write_artifacts_batch_via_output_dir_snapshot(
                artifacts,
                output_dir,
            )
        return
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
                _chmod_artifact(artifact, path=tmp)
                tmp.replace(artifact.output_path)
                tmp_paths[i] = None
    except BaseException:
        for tmp in tmp_paths:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        raise


def _artifact_mode_has_drift(artifact: GeneratedArtifact) -> bool:
    if artifact.mode is None:
        return False
    return (artifact.output_path.stat().st_mode & 0o777) != artifact.mode


def _chmod_artifact(
    artifact: GeneratedArtifact,
    path: Path | None = None,
) -> None:
    if artifact.mode is None:
        return
    target = path if path is not None else artifact.output_path
    try:
        target.chmod(artifact.mode)
    except OSError as exc:
        msg = (
            f"failed to chmod {artifact.output_path}"
            f" (target={artifact.target.value},"
            f" source={artifact.source_path},"
            f" mode={oct(artifact.mode)}): {exc}"
        )
        raise OSError(msg) from exc
