from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_def_translator.core import (
    DefinitionError,
    Target,
    check_drift,
    generate,
    validate_definitions,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent-def-translator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate",
        help="Validate agent definition TOML files.",
    )
    validate.add_argument("--definitions-dir", required=True)
    validate.add_argument(
        "--target",
        action="append",
        choices=[target.value for target in Target],
    )

    translate = subparsers.add_parser(
        "translate",
        help="Generate platform-native agent files.",
    )
    translate.add_argument("--definitions-dir", required=True)
    translate.add_argument("--output-dir", required=True)
    translate.add_argument(
        "--target",
        action="append",
        choices=[target.value for target in Target],
    )

    diff = subparsers.add_parser(
        "diff",
        help="Check whether generated files are up to date.",
    )
    diff.add_argument("--definitions-dir", required=True)
    diff.add_argument("--output-dir", required=True)
    diff.add_argument(
        "--target",
        action="append",
        choices=[target.value for target in Target],
    )

    return parser.parse_args(argv)


def _targets(values: list[str] | None) -> tuple[Target, ...]:
    if values is None:
        return tuple(Target)
    return tuple(Target.parse(value) for value in values)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "validate":
            definitions = validate_definitions(
                Path(args.definitions_dir),
                targets=_targets(args.target),
            )
            for definition in definitions:
                print(definition.source_path.as_posix())
            return 0

        if args.command == "translate":
            artifacts = generate(
                definitions_dir=Path(args.definitions_dir),
                output_dir=Path(args.output_dir),
                targets=_targets(args.target),
            )
            for artifact in artifacts:
                print(artifact.output_path.as_posix())
            return 0

        if args.command == "diff":
            drifted = check_drift(
                definitions_dir=Path(args.definitions_dir),
                output_dir=Path(args.output_dir),
                targets=_targets(args.target),
            )
            for path in drifted:
                print(path.as_posix())
            return 1 if drifted else 0
    except DefinitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
