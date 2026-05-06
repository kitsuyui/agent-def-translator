# MCP Config Format

MCP config definitions are TOML files. Each file describes one MCP server
connection in a target-neutral shape, plus optional target-specific metadata.

`agent-def-translator` does not implement MCP servers and does not manage
authentication. It translates connection definitions into config fragments that
Claude Code, Codex, and GitHub Copilot can consume or merge into their own MCP
configuration files.

## File Naming

The file stem must match the canonical `name`.

```text
mcp/openai-docs.toml
```

```toml
name = "openai-docs"
```

Names must match:

```text
^[A-Za-z0-9._-]+$
```

## Required Fields

```toml
name = "openai-docs"
description = "OpenAI developer documentation MCP server."
transport = "http"
url = "https://developers.openai.com/mcp"
```

- `name`: stable identifier and output filename stem.
- `description`: short human-readable connection description.
- `transport`: `stdio`, `http`, or `sse`.

HTTP and SSE servers require `url`. Stdio servers require `command`.

## Stdio Servers

```toml
name = "local-docs"
description = "Local documentation server."
transport = "stdio"
command = "node"
args = ["server.js", "--stdio"]

[env]
DOCS_ROOT = "./docs"
```

## Target Tables

Target-specific fields live under `[targets.<target>]`.

```toml
[targets.codex]
server_name = "openaiDeveloperDocs"

[targets.claude]
server_name = "openaiDeveloperDocs"

[targets.copilot]
server_name = "openaiDeveloperDocs"
tools = ["*"]
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

## Generated Paths

For a definition named `openai-docs` and `--output-dir generated`, the default
paths are:

```text
generated/claude/mcp/openai-docs.json
generated/codex/mcp/openai-docs.toml
generated/copilot/mcp/openai-docs.json
```

These are target-native config fragments, not full user config ownership. The
caller can merge them into project or user configuration according to the target
tool's install workflow.

## Supported Metadata Types

The portable fields are:

- `url`: string, for `http` and `sse`
- `command`: string, for `stdio`
- `args`: list of strings
- `env`: table of string values
- `headers`: table of string values
- `tools`: list of strings
- `bearer_token_env_var`: string, currently emitted for Codex HTTP servers

Target-specific tables may override these fields. They may also set:

- `enabled`: boolean
- `server_name`: string

Keep authentication material out of definitions. Prefer environment variable
names such as `bearer_token_env_var` or `env` keys whose values are resolved by
the target runtime.
