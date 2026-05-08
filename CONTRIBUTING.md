# Contributing

Thank you for taking the time to improve agent-def-translator.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```sh
uv sync
```

## Checks

Run formatting before opening a pull request:

```sh
uv run poe format
```

Run lint and type checks:

```sh
uv run poe check
```

Run the test suite:

```sh
uv run poe test
```

Generate the coverage XML report when checking coverage-related changes:

```sh
uv run poe coverage-xml
```

Optional end-to-end smoke checks are available for changes that affect generated
agent artifacts or CLI behavior:

```sh
uv run poe e2e
```

If the external Claude Code, OpenAI Codex, or GitHub Copilot CLIs are installed,
you can also inspect their live help surfaces:

```sh
uv run poe e2e-live
```

## Pull requests

Before opening a pull request, please make sure that:

- the change is focused on one topic;
- relevant checks pass locally;
- README or CLI examples are updated when behavior changes;
- generated artifacts remain disposable outputs rather than source of truth.

When reporting a failing check, include the command you ran and the relevant
error output.
