# CLI Usage

`agent-def-translator` is designed to be used from the command line. Downstream
projects can call the CLI from their own build scripts, CI workflows, or
generation commands without depending on internal Python implementation details.

## Install-Free Execution

After the package is published to PyPI, use `uvx` to run it in an isolated
environment:

```bash
uvx agent-def-translator --help
```

For local development inside this repository, use:

```bash
uv run agent-def-translator --help
```

## Commands

Commands are also available in resource-oriented form:

```bash
uvx agent-def-translator subagent validate --definitions-dir agents
uvx agent-def-translator subagent translate --definitions-dir agents --output-dir generated
uvx agent-def-translator skill translate --definitions-dir skills --output-dir generated
uvx agent-def-translator mcp validate --definitions-dir mcp
uvx agent-def-translator mcp translate --definitions-dir mcp --output-dir generated
```

Subagent and MCP config translation are implemented today. The `skill`
namespace is reserved for future skill definition translation and currently
returns an explicit "not implemented yet" error.

The legacy top-level `validate`, `translate`, and `diff` commands, plus
`validate-agents`, `translate-agents`, `diff-agents`, and the `agent` resource,
remain deprecated aliases for the corresponding `subagent` commands. They still
run, but print a warning to stderr.

### validate

Validate definition files and render the selected target projections in memory.
This catches TOML shape errors, unknown fields, missing prompt append files, and
unsupported target-specific metadata types before writing generated files.

```bash
uvx agent-def-translator subagent validate --definitions-dir agents
```

Validate only one target:

```bash
uvx agent-def-translator subagent validate --definitions-dir agents --target codex
```

Repeat `--target` to validate multiple targets:

```bash
uvx agent-def-translator subagent validate \
  --definitions-dir agents \
  --target claude \
  --target copilot
```

On success, the command prints each validated definition path and exits with
`0`. On definition errors, it prints `error: ...` to stderr and exits with `2`.

### translate

Generate platform-native subagent files.

```bash
uvx agent-def-translator subagent translate \
  --definitions-dir agents \
  --output-dir generated
```

Generate only one target:

```bash
uvx agent-def-translator subagent translate \
  --definitions-dir agents \
  --output-dir generated \
  --target codex
```

On success, the command prints each written artifact path and exits with `0`.

### diff

Check whether generated files are current without rewriting them.

```bash
uvx agent-def-translator subagent diff \
  --definitions-dir agents \
  --output-dir generated
```

`diff` exits with:

- `0`: every selected generated file matches the current definitions.
- `1`: at least one selected generated file is missing or stale.
- `2`: a definition error prevented rendering.

When drift exists, the command prints the stale or missing output paths. This is
the preferred CI check after generated files have been committed.

## Typical Repository Workflow

1. Edit `agents/*.toml` and any referenced prompt files.
2. Run `subagent validate`.
3. Run `subagent translate`.
4. Review and commit both the canonical definition changes and generated files.
5. Run `subagent diff` in CI to keep generated files synchronized.

Example:

```bash
uvx agent-def-translator subagent validate --definitions-dir agents
uvx agent-def-translator subagent translate --definitions-dir agents --output-dir generated
uvx agent-def-translator subagent diff --definitions-dir agents --output-dir generated
```

## MCP Config Workflow

MCP config definitions are separate from subagent role definitions. They describe
connection configuration for MCP servers, then render target-native config
fragments.

Validate MCP config definitions:

```bash
uvx agent-def-translator mcp validate --definitions-dir mcp
```

Generate MCP config fragments:

```bash
uvx agent-def-translator mcp translate \
  --definitions-dir mcp \
  --output-dir generated
```

Check generated MCP config fragments in CI:

```bash
uvx agent-def-translator mcp diff \
  --definitions-dir mcp \
  --output-dir generated
```

For a definition named `openai-docs`, this writes:

```text
generated/
  claude/mcp/openai-docs.json
  codex/mcp/openai-docs.toml
  copilot/mcp/openai-docs.json
```

## Target Names

Supported targets are:

- `claude`
- `codex`
- `copilot`

`vscode` is accepted as an alias for `copilot` in definition files for
compatibility, but new CLI usage should prefer `copilot`.
