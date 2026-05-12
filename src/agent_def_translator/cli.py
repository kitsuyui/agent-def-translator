from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_def_translator.core import (
    DefinitionError,
    Target,
    check_drift,
    check_mcp_config_drift,
    check_plugin_drift,
    check_skill_drift,
    generate,
    generate_mcp_configs,
    generate_plugins,
    generate_skills,
    validate_definitions,
    validate_mcp_config_definitions,
    validate_plugin_definitions,
    validate_skill_definitions,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent-def-translator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subagent = subparsers.add_parser(
        "subagent",
        help="Work with subagent definition files.",
    )
    subagent_subparsers = subagent.add_subparsers(
        dest="resource_command",
        required=True,
    )
    subagent_validate = subagent_subparsers.add_parser(
        "validate",
        help="Validate subagent definition TOML files.",
    )
    _add_definition_args(subagent_validate, output=False)
    subagent_translate = subagent_subparsers.add_parser(
        "translate",
        help="Generate platform-native subagent files.",
    )
    _add_definition_args(subagent_translate, output=True)
    subagent_diff = subagent_subparsers.add_parser(
        "diff",
        help="Check whether generated subagent files are up to date.",
    )
    _add_definition_args(subagent_diff, output=True)

    agent = subparsers.add_parser(
        "agent",
        help="Deprecated alias for subagent.",
    )
    agent_subparsers = agent.add_subparsers(
        dest="resource_command",
        required=True,
    )
    agent_validate = agent_subparsers.add_parser(
        "validate",
        help="Deprecated alias for subagent validate.",
    )
    _add_definition_args(agent_validate, output=False)
    agent_translate = agent_subparsers.add_parser(
        "translate",
        help="Deprecated alias for subagent translate.",
    )
    _add_definition_args(agent_translate, output=True)
    agent_diff = agent_subparsers.add_parser(
        "diff",
        help="Deprecated alias for subagent diff.",
    )
    _add_definition_args(agent_diff, output=True)

    skill = subparsers.add_parser(
        "skill",
        help="Work with skill definition files.",
    )
    skill_subparsers = skill.add_subparsers(
        dest="resource_command",
        required=True,
    )
    skill_translate = skill_subparsers.add_parser(
        "translate",
        help="Generate platform-native skill files.",
    )
    _add_definition_args(skill_translate, output=True)
    skill_validate = skill_subparsers.add_parser(
        "validate",
        help="Validate skill definition TOML files.",
    )
    _add_definition_args(skill_validate, output=False)
    skill_diff = skill_subparsers.add_parser(
        "diff",
        help="Check whether generated skill files are up to date.",
    )
    _add_definition_args(skill_diff, output=True)

    mcp = subparsers.add_parser(
        "mcp",
        help="Work with MCP config definition files.",
    )
    mcp_subparsers = mcp.add_subparsers(
        dest="resource_command",
        required=True,
    )
    mcp_validate = mcp_subparsers.add_parser(
        "validate",
        help="Validate MCP config definition TOML files.",
    )
    _add_definition_args(mcp_validate, output=False)
    mcp_translate = mcp_subparsers.add_parser(
        "translate",
        help="Generate platform-native MCP config files.",
    )
    _add_definition_args(mcp_translate, output=True)
    mcp_diff = mcp_subparsers.add_parser(
        "diff",
        help="Check whether generated MCP config files are up to date.",
    )
    _add_definition_args(mcp_diff, output=True)

    plugin = subparsers.add_parser(
        "plugin",
        help="Work with plugin bundle definition files.",
    )
    plugin_subparsers = plugin.add_subparsers(
        dest="resource_command",
        required=True,
    )
    plugin_validate = plugin_subparsers.add_parser(
        "validate",
        help="Validate plugin bundle definition TOML files.",
    )
    _add_definition_args(plugin_validate, output=False)
    plugin_translate = plugin_subparsers.add_parser(
        "translate",
        help="Generate platform-native plugin bundles.",
    )
    _add_definition_args(plugin_translate, output=True)
    plugin_diff = plugin_subparsers.add_parser(
        "diff",
        help="Check whether generated plugin bundles are up to date.",
    )
    _add_definition_args(plugin_diff, output=True)

    validate = subparsers.add_parser(
        "validate",
        help="Deprecated alias for subagent validate.",
    )
    _add_definition_args(validate, output=False)

    validate_agents = subparsers.add_parser(
        "validate-agents",
        help="Deprecated alias for subagent validate.",
    )
    _add_definition_args(validate_agents, output=False)

    translate = subparsers.add_parser(
        "translate",
        help="Deprecated alias for subagent translate.",
    )
    _add_definition_args(translate, output=True)

    translate_agents = subparsers.add_parser(
        "translate-agents",
        help="Deprecated alias for subagent translate.",
    )
    _add_definition_args(translate_agents, output=True)

    diff = subparsers.add_parser(
        "diff",
        help="Deprecated alias for subagent diff.",
    )
    _add_definition_args(diff, output=True)

    diff_agents = subparsers.add_parser(
        "diff-agents",
        help="Deprecated alias for subagent diff.",
    )
    _add_definition_args(diff_agents, output=True)

    return parser.parse_args(argv)


def _add_definition_args(
    parser: argparse.ArgumentParser,
    *,
    output: bool,
) -> None:
    parser.add_argument("--definitions-dir", required=True)
    if output:
        parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--target",
        action="append",
        choices=[target.value for target in Target],
    )


def _targets(values: list[str] | None) -> tuple[Target, ...]:
    if values is None:
        return tuple(Target)
    return tuple(Target.parse(value) for value in values)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        command = _normalized_command(args)
        _warn_deprecated_command(args, command)
        return _run_command(args, command)
    except DefinitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"io-error: {exc}", file=sys.stderr)
        return 3


def _normalized_command(args: argparse.Namespace) -> tuple[str, str]:
    aliases = {
        "validate": ("subagent", "validate"),
        "validate-agents": ("subagent", "validate"),
        "translate": ("subagent", "translate"),
        "translate-agents": ("subagent", "translate"),
        "diff": ("subagent", "diff"),
        "diff-agents": ("subagent", "diff"),
    }
    if args.command in aliases:
        return aliases[args.command]
    if args.command == "agent":
        return ("subagent", args.resource_command)
    if args.command in {"subagent", "skill", "mcp", "plugin"}:
        return (args.command, args.resource_command)
    raise AssertionError(f"unhandled command: {args.command}")


def _warn_deprecated_command(
    args: argparse.Namespace,
    command: tuple[str, str],
) -> None:
    replacements = {
        "validate": "subagent validate",
        "validate-agents": "subagent validate",
        "translate": "subagent translate",
        "translate-agents": "subagent translate",
        "diff": "subagent diff",
        "diff-agents": "subagent diff",
    }
    replacement = replacements.get(args.command)
    if args.command == "agent":
        replacement = f"subagent {command[1]}"
    if replacement is None:
        return
    print(
        "warning: this command is deprecated; "
        f"use 'agent-def-translator {replacement}' instead.",
        file=sys.stderr,
    )


def _run_command(
    args: argparse.Namespace,
    command: tuple[str, str],
) -> int:
    handlers = {
        ("subagent", "validate"): _run_subagent_validate,
        ("subagent", "translate"): _run_subagent_translate,
        ("subagent", "diff"): _run_subagent_diff,
        ("skill", "validate"): _run_skill_validate,
        ("skill", "translate"): _run_skill_translate,
        ("skill", "diff"): _run_skill_diff,
        ("mcp", "validate"): _run_mcp_validate,
        ("mcp", "translate"): _run_mcp_translate,
        ("mcp", "diff"): _run_mcp_diff,
        ("plugin", "validate"): _run_plugin_validate,
        ("plugin", "translate"): _run_plugin_translate,
        ("plugin", "diff"): _run_plugin_diff,
    }
    try:
        handler = handlers[command]
    except KeyError as exc:
        raise AssertionError(f"unhandled command: {command}") from exc
    return handler(args)


def _run_subagent_validate(args: argparse.Namespace) -> int:
    definitions = validate_definitions(
        Path(args.definitions_dir),
        targets=_targets(args.target),
    )
    for definition in definitions:
        print(definition.source_path.as_posix())
    return 0


def _run_subagent_translate(args: argparse.Namespace) -> int:
    artifacts = generate(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for artifact in artifacts:
        print(artifact.output_path.as_posix())
    return 0


def _run_subagent_diff(args: argparse.Namespace) -> int:
    drifted = check_drift(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for path in drifted:
        print(path.as_posix())
    return 1 if drifted else 0


def _run_skill_translate(args: argparse.Namespace) -> int:
    artifacts = generate_skills(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for artifact in artifacts:
        print(artifact.output_path.as_posix())
    return 0


def _run_skill_validate(args: argparse.Namespace) -> int:
    definitions = validate_skill_definitions(
        Path(args.definitions_dir),
        targets=_targets(args.target),
    )
    for definition in definitions:
        print(definition.source_path.as_posix())
    return 0


def _run_skill_diff(args: argparse.Namespace) -> int:
    drifted = check_skill_drift(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for path in drifted:
        print(path.as_posix())
    return 1 if drifted else 0


def _run_mcp_validate(args: argparse.Namespace) -> int:
    definitions = validate_mcp_config_definitions(
        Path(args.definitions_dir),
        targets=_targets(args.target),
    )
    for definition in definitions:
        print(definition.source_path.as_posix())
    return 0


def _run_mcp_translate(args: argparse.Namespace) -> int:
    artifacts = generate_mcp_configs(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for artifact in artifacts:
        print(artifact.output_path.as_posix())
    return 0


def _run_mcp_diff(args: argparse.Namespace) -> int:
    drifted = check_mcp_config_drift(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for path in drifted:
        print(path.as_posix())
    return 1 if drifted else 0


def _run_plugin_validate(args: argparse.Namespace) -> int:
    definitions = validate_plugin_definitions(
        Path(args.definitions_dir),
        targets=_targets(args.target),
    )
    for definition in definitions:
        print(definition.source_path.as_posix())
    return 0


def _run_plugin_translate(args: argparse.Namespace) -> int:
    artifacts = generate_plugins(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for artifact in artifacts:
        print(artifact.output_path.as_posix())
    return 0


def _run_plugin_diff(args: argparse.Namespace) -> int:
    drifted = check_plugin_drift(
        definitions_dir=Path(args.definitions_dir),
        output_dir=Path(args.output_dir),
        targets=_targets(args.target),
    )
    for path in drifted:
        print(path.as_posix())
    return 1 if drifted else 0


if __name__ == "__main__":
    raise SystemExit(main())
