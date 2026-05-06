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

### validate

Validate definition files and render the selected target projections in memory.
This catches TOML shape errors, unknown fields, missing prompt append files, and
unsupported target-specific metadata types before writing generated files.

```bash
uvx agent-def-translator validate --definitions-dir agents
```

Validate only one target:

```bash
uvx agent-def-translator validate --definitions-dir agents --target codex
```

Repeat `--target` to validate multiple targets:

```bash
uvx agent-def-translator validate \
  --definitions-dir agents \
  --target claude \
  --target copilot
```

On success, the command prints each validated definition path and exits with
`0`. On definition errors, it prints `error: ...` to stderr and exits with `2`.

### translate

Generate platform-native agent files.

```bash
uvx agent-def-translator translate \
  --definitions-dir agents \
  --output-dir generated
```

Generate only one target:

```bash
uvx agent-def-translator translate \
  --definitions-dir agents \
  --output-dir generated \
  --target codex
```

On success, the command prints each written artifact path and exits with `0`.

### diff

Check whether generated files are current without rewriting them.

```bash
uvx agent-def-translator diff \
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
2. Run `validate`.
3. Run `translate`.
4. Review and commit both the canonical definition changes and generated files.
5. Run `diff` in CI to keep generated files synchronized.

Example:

```bash
uvx agent-def-translator validate --definitions-dir agents
uvx agent-def-translator translate --definitions-dir agents --output-dir generated
uvx agent-def-translator diff --definitions-dir agents --output-dir generated
```

## Target Names

Supported targets are:

- `claude`
- `codex`
- `copilot`

`vscode` is accepted as an alias for `copilot` in definition files for
compatibility, but new CLI usage should prefer `copilot`.
