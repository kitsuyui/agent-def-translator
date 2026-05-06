# Development

Use `uv` for local development.

## Setup

```bash
uv sync
```

## Tests

Run the default test suite:

```bash
uv run poe test
```

Run static checks:

```bash
uv run poe check
```

Run coverage:

```bash
uv run poe coverage-xml
```

## E2E Smoke Tests

E2E smoke tests are available, but they are not part of the default test/check
workflow.

```bash
uv run poe e2e
```

To also inspect installed external CLI help surfaces when available:

```bash
uv run poe e2e-live
```

Live mode also checks installed Claude Code, Codex, and GitHub Copilot CLI MCP
config surfaces when those commands are available. It uses temporary
homes/config directories and does not call model APIs.

## Examples

The repository intentionally does not vendor real workflow skills from private
or project-specific skill sets. Skill examples are limited to tiny fixtures,
such as `examples/skills/hello/SKILL.md`, so the package stays focused on
definition translation rather than distributing an opinionated skill library.
MCP examples follow the same rule and use generic public config fixtures.
