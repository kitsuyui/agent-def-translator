# agent-def-translator

Maintain coding-agent role definitions once, then generate platform-native
agent files for Claude Code, OpenAI Codex, and GitHub Copilot.

## Status

This project is currently alpha software. The core translation model is usable,
but the canonical definition shape and target-specific output formats may change
before a stable release.

This project intentionally does not run agents, manage sessions, resume tasks,
or provide an orchestration runtime. It only translates definition files into
deterministic platform artifacts.

## Install

```bash
uv sync
```

## Agent Spec

Write canonical role definitions as TOML:

```toml
name = "repo-explorer"
description = "Read repository context and summarize relevant files."
instructions = """
Inspect the repository rules, locate the relevant files, and report concise
findings with file paths. Do not edit files.
"""

[targets.claude]
tools = ["Read", "Grep", "Glob"]
permission_mode = "plan"
model = "haiku"

[targets.codex]
model = "gpt-5.4-mini"
sandbox_mode = "read-only"

[targets.copilot]
tools = ["search", "fetch"]
target = "vscode"
```

Target-specific prompt overrides are supported:

```toml
[targets.claude]
prompt_append_file = "prompts/repo-explorer.claude.md"
```

## Skill Examples

This repository does not vendor real workflow skills from any private or
project-specific skill set. Skill examples are intentionally limited to tiny
fixtures such as `examples/skills/hello/SKILL.md`, so the public package stays
focused on definition translation rather than distributing an opinionated skill
library.

## CLI

Validate definitions:

```bash
uv run agent-def-translator validate --definitions-dir examples/agents
```

Validate only one platform projection:

```bash
uv run agent-def-translator validate --definitions-dir examples/agents --target codex
```

Generate all supported targets:

```bash
uv run agent-def-translator translate \
  --definitions-dir examples/agents \
  --output-dir generated
```

Check generated files without updating them:

```bash
uv run agent-def-translator diff \
  --definitions-dir examples/agents \
  --output-dir generated
```

Optional E2E smoke is available, but it is not part of the default check/test
workflow:

```bash
uv run poe e2e
```

To also inspect installed external CLI help surfaces when available:

```bash
uv run poe e2e-live
```

## Python API

```python
from pathlib import Path

from agent_def_translator import Target, generate

generated = generate(
    definitions_dir=Path("examples/agents"),
    output_dir=Path("generated"),
    targets=(Target.CLAUDE, Target.CODEX, Target.COPILOT),
)
```

## Design

- `name`, `description`, and `instructions` are canonical.
- Platform differences stay in `[targets.<target>]`.
- Generated files are disposable and should not become the source of truth.
- Output is deterministic so drift can be detected in CI.
- Validation renders each selected target, so missing prompt append files and
  unsupported target-specific metadata types fail before generation.
- Concrete workflow skills are out of scope; examples use only minimal
  demonstration skills.

## License

MIT License. See `LICENSE`.
