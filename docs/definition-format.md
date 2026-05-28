# Definition Format

Definitions are TOML files. Each file describes one subagent role in a
platform-neutral shape, plus optional target-specific metadata.

## File Naming

The file stem must match the canonical `name`.

```text
agents/repo-explorer.toml
```

```toml
name = "repo-explorer"
```

Names must match:

```text
^[A-Za-z0-9._-]+$
```

Duplicate names in one `--definitions-dir` are rejected.

## Required Fields

```toml
name = "repo-explorer"
description = "Read repository context and summarize relevant files."
instructions = """
Inspect repository rules, locate the relevant files, and report concise findings
with file paths. Do not edit files.
"""
```

- `name`: stable identifier and output filename stem.
- `description`: short human-readable role description.
- `instructions`: canonical prompt body used when a target does not override it.

## Target Tables

Target-specific fields live under `[targets.<target>]`.
See [Platform references](references.md) for the official documentation used to
ground target-specific output formats.

```toml
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

Supported target names are:

- `claude`
- `codex`
- `copilot`

The loader also accepts legacy top-level tables such as `[claude]`, `[codex]`,
`[copilot]`, and `[vscode]`. New definitions should use `[targets.<target>]`.

Legacy top-level target tables are deprecated. When the loader sees one, it
emits a `DeprecationWarning` so callers can detect remaining call sites and
migrate them. They are scheduled for removal no earlier than
`agent-def-translator` 1.0.0. The two syntaxes cannot be mixed for the same
target: if a definition configures `claude` through both `[targets.claude]`
and `[claude]` (or any other equivalent pair), `load_definition` raises
`DefinitionError` instead of silently picking a winner. Only subagent
definitions accept the legacy syntax; skill, MCP config, and plugin
definitions accept only `[targets.<target>]`.

## Prompt Composition

By default, a target uses the canonical `instructions` field.

Use `prompt_override` when a target needs a completely different prompt:

```toml
[targets.codex]
prompt_override = "Use this Codex-specific prompt instead."
```

Use `prompt_append` for small inline additions:

```toml
[targets.codex]
prompt_append = "Return a concise final report."
```

Use `prompt_append_file` for larger target-specific additions:

```toml
[targets.claude]
prompt_append_file = "../prompts/repo-explorer.claude.md"
```

`prompt_append_file` is resolved relative to `--definitions-dir`, not relative
to the current shell directory. This makes CLI calls stable from CI and wrapper
scripts.

`prompt_append` and `prompt_append_file` are mutually exclusive.

## Generated Paths

For a definition named `repo-explorer` and `--output-dir generated`, the default
paths are:

```text
generated/claude/agents/repo-explorer.md
generated/codex/agents/repo-explorer.toml
generated/copilot/agents/repo-explorer.agent.md
```

Generated files include a source comment such as:

```text
Generated from repo-explorer.toml by agent-def-translator.
```

The source path is shown relative to `--definitions-dir` when possible.

## Supported Metadata Types

Target-specific metadata is copied into generated front matter or TOML output
after prompt fields are removed.

Supported scalar values are:

- strings
- booleans
- integers

Lists and nested tables are supported for YAML/TOML output where the target
format can represent them. Nested lists are rejected.

### Target-specific field shapes

Some fields are normalized differently per target:

- **`tools`, `disallowedTools`, `allowedTools`**: Supply a list in the definition.
  For Claude output the list is joined into a comma-separated string (e.g.,
  `"Read, Grep, Glob"`), because that is the shape Claude frontmatter expects.
  For Codex and Copilot the list is preserved as-is.
