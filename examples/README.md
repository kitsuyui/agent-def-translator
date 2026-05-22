# examples/

This directory contains both definition sources (inputs to the CLI) and generated
outputs (produced by running the CLI), organized as follows:

## Definition directories (source — pass to `--definitions-dir`)

| Directory | Resource type | CLI subcommand |
| --- | --- | --- |
| `agents/` | Subagent definitions | `subagent translate` |
| `skill-definitions/` | Skill definitions | `skill translate` |
| `mcp/` | MCP config definitions | `mcp translate` |
| `plugin-definitions/` | Plugin bundle definitions | `plugin translate` |
| `prompts/` | Prompt-append files referenced by agent definitions | (input only, not passed to `--definitions-dir`) |

> **Note:** `agents/` and `mcp/` do not carry a `-definitions` suffix (unlike
> `skill-definitions/` and `plugin-definitions/`). This is a historical
> inconsistency; all four definition directories above are valid `--definitions-dir`
> inputs for their respective subcommands.

## Generated output directories (produced by the CLI — specified via `--output-dir`)

| Directory | Produced by |
| --- | --- |
| `skills/` | `skill translate --definitions-dir skill-definitions --output-dir skills` |

The generated directories are checked in as small reference artifacts so readers
can see what the CLI produces without running it locally.
