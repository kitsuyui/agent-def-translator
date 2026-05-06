# Skill Format

Skill definitions are TOML files. Each file describes one portable skill and
renders target-native `SKILL.md` files for Claude Code, Codex, and GitHub
Copilot.

`agent-def-translator` translates skill definitions only. It does not package
plugins, install skills, manage marketplaces, provision MCP servers, or execute
the generated skills.

## File Naming

The file stem must match the canonical `name`.

```text
skills/hello.toml
```

```toml
name = "hello"
```

Skill names must use lowercase letters, numbers, and single hyphens. They must
be 1-64 characters long and match the filename stem.

## Required Fields

```toml
name = "hello"
description = "Say hello when the user asks for a greeting."
instructions = "Reply with one short greeting."
source_dir = "hello"
```

- `name`: portable skill identifier.
- `description`: short trigger-facing description.
- `instructions`: Markdown body written into generated `SKILL.md` files.
- `source_dir`: optional portable skill resource directory, relative to
  `--definitions-dir`. All files in this directory are copied into each
  generated target skill directory, except `SKILL.md` and
  `agents/openai.yaml`, which are generated from the canonical definition.

## Portable Frontmatter

These optional fields are rendered into `SKILL.md` frontmatter when supported by
the target:

- `license`
- `compatibility`
- `metadata`
- `allowed_tools`
- `argument_hint`
- `user_invocable`
- `disable_model_invocation`
- `context`

The TOML definition uses snake_case names. Generated `SKILL.md` frontmatter uses
platform-facing hyphenated names such as `allowed-tools`,
`user-invocable`, and `disable-model-invocation`.

## Target Tables

Target-specific fields live under `[targets.<target>]`.

```toml
[targets.claude]
context = "fork"
agent = "general-purpose"

[targets.codex]
display_name = "Hello"
short_description = "Say hello."
allow_implicit_invocation = true

[targets.copilot]
user_invocable = false
```

Supported target names are:

- `claude`
- `codex`
- `copilot`

`vscode` is accepted as an alias for `copilot` in target tables.

Use `enabled = false` to skip a target:

```toml
[targets.copilot]
enabled = false
```

## Codex Metadata

Codex skill UI and invocation policy metadata is rendered to
`agents/openai.yaml` beside the generated `SKILL.md` when needed.

```toml
[targets.codex]
display_name = "Hello"
short_description = "Say hello."
allow_implicit_invocation = true

[targets.codex.dependencies]
tools = ["shell"]
```

This writes:

```text
generated/codex/skills/hello/SKILL.md
generated/codex/skills/hello/agents/openai.yaml
```

## Generated Paths

For a definition named `hello` and `--output-dir generated`, the default paths
are:

```text
generated/claude/skills/hello/SKILL.md
generated/codex/skills/hello/SKILL.md
generated/copilot/skills/hello/SKILL.md
```

If Codex metadata is present, `agents/openai.yaml` is generated under the Codex
skill directory.

If `source_dir = "hello"` is present, bundled resources are copied recursively.
Common skill resource paths include:

```text
skills/hello/scripts/
skills/hello/references/
skills/hello/assets/
skills/hello/templates/
skills/hello/runbook.md
```

For example, `skills/hello/scripts/run.sh` is copied to
`generated/claude/skills/hello/scripts/run.sh`,
`generated/codex/skills/hello/scripts/run.sh`, and
`generated/copilot/skills/hello/scripts/run.sh`.

This follows the Agent Skills model: `SKILL.md` is the required entrypoint,
while additional files such as scripts, references, templates, examples,
runbooks, and assets are loaded by target agents only when the generated
`SKILL.md` references them.

## Scope

The generated skill directories are disposable target projections. Keep reusable
intent in the TOML definition, and keep platform-specific behavior in
`[targets.<target>]` tables.

Plugin packaging is intentionally separate. A future `plugin` resource should
own plugin manifests, bundling, and distribution concerns.
