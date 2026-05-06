# Plugin Bundle Format

Plugin definitions describe how generated subagent, skill, and MCP config
artifacts are bundled into target-native plugin directories. They do not define
new agent behavior. Treat `plugin translate` as a packaging/linking step that
runs after `subagent translate`, `skill translate`, and `mcp translate`.

## Minimal Definition

```toml
name = "hello-bundle"
description = "Bundle generated hello components."
version = "0.1.0"
author = "Example Maintainer"

[components]
subagents = true
skills = true
mcp = true
```

Validate and generate bundles:

```bash
uvx agent-def-translator plugin validate --definitions-dir plugins
uvx agent-def-translator plugin translate \
  --definitions-dir plugins \
  --output-dir generated
```

`plugin translate` expects the selected component directories to already exist
under the same `--output-dir`:

```text
generated/
  claude/agents/
  claude/skills/
  claude/mcp/
  codex/agents/
  codex/skills/
  codex/mcp/
  copilot/agents/
  copilot/skills/
  copilot/mcp/
```

## Generated Layout

For a plugin named `hello-bundle`, the output is:

```text
generated/
  claude/plugins/hello-bundle/
    .claude-plugin/plugin.json
    .mcp.json
    agents/
    skills/
  codex/plugins/hello-bundle/
    .codex-plugin/plugin.json
    .mcp.json
    agents/
    skills/
  codex/marketplace.json
  copilot/plugins/hello-bundle/
    plugin.json
    .mcp.json
    agents/
    skills/
```

Codex also receives `marketplace.json` so local plugin installation workflows can
reference the generated plugin directory.

## Fields

Required fields:

- `name`: plugin name. The TOML filename stem must match this value.
- `description`: short human-readable description.
- `version`: plugin version string.

Optional metadata:

- `author`: rendered as an author object in plugin manifests.
- `repository`
- `homepage`
- `license`
- `keywords`: list of strings.

## Components

The `[components]` table controls which generated artifacts are bundled:

```toml
[components]
subagents = true
skills = true
mcp = true
resources_dir = "runtime"
require_subagents = true
require_skills = true
require_mcp = true
require_resources = true
```

- `subagents`: copies `generated/<target>/agents/` into the plugin bundle.
- `skills`: copies `generated/<target>/skills/` into the plugin bundle.
- `mcp`: merges generated MCP fragments into the plugin bundle's `.mcp.json`.
- `resources_dir`: optional directory relative to the plugin definition
  directory. Its files are copied into the plugin root for every selected target.
- `require_subagents`, `require_skills`, `require_mcp`, and
  `require_resources`: make the corresponding enabled component mandatory.
  They default to `true`. Set one to `false` when a component should be bundled
  only if its source directory exists.

If `[components]` is omitted, `subagents`, `skills`, and `mcp` default to `true`.

Copied files preserve their source permission bits, including executable bits.
`plugin diff` also reports drift when a generated copied file has the right
content but the wrong mode.

## Interface

The `[interface]` table provides display metadata. Codex plugin manifests use
this table directly, converting field names to the platform's camelCase shape:

```toml
[interface]
display_name = "Hello Bundle"
short_description = "Generated hello components."
long_description = "A tiny plugin bundle for examples."
developer_name = "Example Maintainer"
category = "Productivity"
capabilities = ["Read"]
website_url = "https://example.com/hello-bundle"
```

## Marketplace

The `[marketplace]` table controls the generated Codex marketplace file:

```toml
[marketplace]
name = "hello-local"
display_name = "Hello Local Plugins"
source_path = "./plugins/hello-bundle"
installation = "AVAILABLE"
authentication = "ON_INSTALL"
category = "Productivity"
```

## Target Overrides

Use `[targets.<target>]` to override metadata or disable a target:

```toml
[targets.copilot]
enabled = false

[targets.codex.interface]
display_name = "Hello Codex Bundle"
```

Supported targets are `claude`, `codex`, and `copilot`.

## Relationship to Other Resources

`subagent translate`, `skill translate`, and `mcp translate` compile canonical
definitions into target-native files. `plugin translate` then packages those
generated files into a distribution container. This keeps behavior translation
separate from plugin distribution concerns.
