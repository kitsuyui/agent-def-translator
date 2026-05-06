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

## Test Selection

E2E and live tests are implemented as pytest tests with custom markers. The
default test/check workflow does not run them because they are skipped unless
the corresponding pytest option is passed.

The marker hierarchy is:

- `e2e`: repository-level smoke tests that invoke generated CLI artifacts
- `live`: E2E tests that inspect installed Claude Code, Codex, or GitHub
  Copilot CLI surfaces
- `model_live`: live tests that call external model APIs

Run the deterministic E2E smoke test:

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

To run opt-in live checks that call installed agent CLIs with short model
prompts:

```bash
uv run poe e2e-model-live
```

This path is intentionally outside `test`, `check`, and `e2e`. It generates
temporary subagent, skill, and MCP config definitions, installs the generated
artifacts into disposable project/config directories, and then asks available
Claude Code, Codex, and GitHub Copilot CLIs to recognize them. Use
`ADT_E2E_CLAUDE_MODEL`, `ADT_E2E_CODEX_MODEL`, or `ADT_E2E_COPILOT_MODEL` to
override the default low-cost model names.

Claude Code and GitHub Copilot CLI expose direct non-interactive custom-agent
selection, so this suite calls those generated subagents through the model.
Codex `exec` does not currently expose an equivalent custom-agent selector, so
the suite verifies the generated Codex subagent artifact and uses Codex for the
generated skill model-call path plus MCP config listing.

To run unit tests plus every E2E/live path:

```bash
uv run poe test-full
```

The raw pytest equivalents are available when a narrower selection is useful:

```bash
uv run pytest -m "e2e and not live" --run-e2e
uv run pytest -m "live and not model_live" --run-e2e --run-live
uv run pytest -m model_live --run-e2e --run-live --run-model-live
```

## Examples

The repository intentionally does not vendor real workflow skills from private
or project-specific skill sets. Skill examples are limited to tiny fixtures,
such as `examples/skills/hello/SKILL.md` and
`examples/skill-definitions/hello.toml`, so the package stays focused on
definition translation rather than distributing an opinionated skill library.
MCP examples follow the same rule and use generic public config fixtures.
