# Platform References

`agent-def-translator` exists to translate one canonical coding-agent
definition into target-native files. The target formats should be grounded in
the public documentation for each platform, not in private examples or local
repository conventions.

Use this page when changing a target renderer, adding a target-specific field,
or deciding whether a concept belongs in this package.

## In Scope Today

These references describe the agent definition surfaces that this package
currently renders.

### Claude Code Agents

- [Create custom subagents](https://code.claude.com/docs/en/subagents)

Use this as the primary source for Claude Code agent files. It documents the
Markdown file shape, YAML front matter fields, prompt body, tool restrictions,
model selection, permission modes, project/user/plugin scopes, hooks, skills,
and subagent lifecycle behavior.

### OpenAI Codex Agents

- [Codex subagents](https://developers.openai.com/codex/subagents)

Use this as the primary source for Codex agent definitions and Codex-specific
agent configuration. Keep Codex fields separate from Claude and Copilot fields
in `[targets.codex]`.

### GitHub Copilot Custom Agents

- [Creating custom agents for Copilot cloud agent](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/create-custom-agents)
- [Custom agents configuration](https://docs.github.com/en/copilot/reference/custom-agents-configuration)
- [VS Code custom agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents)
- [VS Code subagents](https://code.visualstudio.com/docs/copilot/agents/subagents)

Use GitHub Docs as the primary source for GitHub Copilot custom agent files.
Use VS Code Docs when checking IDE-specific custom agent behavior and VS Code's
subagent orchestration surface. The GitHub custom agents configuration
reference should be treated as the stricter source when deciding which front
matter keys can be emitted.

## Design Principles

These rules summarize the stable parts of the comparison work that led to this
package.

### Canonical Definition, Target Projection

The platforms share a broad concept: define a specialized agent role, then let a
parent agent delegate work to it. The target file formats and execution models
do not line up cleanly:

- Claude Code uses Markdown plus YAML front matter.
- Codex uses TOML.
- GitHub Copilot uses custom agent Markdown files and platform-specific
  configuration surfaces.

The practical model is therefore one canonical role definition plus deterministic
target projections. Avoid designing a canonical file that tries to be valid
native input for every target at once.

### Separate Capability Layers

Keep these concepts separate in the canonical model:

- Skill: how work is performed.
- Agent: who performs the work.
- MCP: what external tools or data sources can be reached.
- Plugin: how capabilities are packaged or distributed.

Some target platforms bundle these concepts together for installation, but a
translator should not collapse them into one table. This keeps agent rendering
small and lets skill, plugin, and MCP translation evolve without breaking the
agent definition contract.

## Adjacent Concepts

These references are useful context, but they do not define the canonical agent
definition format by themselves.

### Skills

- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [GitHub Copilot agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)
- [VS Code agent skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills)
- [Skills in ChatGPT](https://help.openai.com/en/articles/20001066-skills-in-chatgpt)
- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [Agent Skills](https://agentskills.io/home)
- [Agent Skills specification](https://agentskills.io/specification)

Skills describe reusable task instructions and bundled context. They are related
to agents because an agent may load, invoke, or be distributed with skills.
`agent-def-translator` translates skill definitions into target-specific
`SKILL.md` directories and Codex `agents/openai.yaml` metadata when needed.
Bundled skill resources are broader than only `scripts/`, `references/`, and
`assets/`: the Agent Skills specification permits additional files and
directories, and vendor docs mention examples such as templates, top-level
reference files, and helper scripts. Treat these as opaque resource files that
are copied with the generated skill directory; the generated `SKILL.md` should
reference them with relative paths so each target agent loads them on demand.

Treat vendor documentation as the source for target behavior. Treat the Agent
Skills site and specification as ecosystem context for common skill concepts,
not as a source for target-specific rendered output.

Keep skill rendering separate from plugin packaging. Skill translation owns
`SKILL.md` and resource files; plugin translation owns distribution manifests
and bundle layout.

### Plugins

- [Claude Code plugins](https://code.claude.com/docs/en/plugins)
- [Claude Code plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Codex plugins](https://developers.openai.com/codex/plugins)
- [Codex build plugins](https://developers.openai.com/codex/plugins/build)
- [GitHub Copilot CLI plugins](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-cli-plugins)
- [GitHub Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)

Plugins are distribution containers for capabilities such as agents, skills, and
commands. `agent-def-translator plugin translate` models this as a
packaging/linking step: generated subagents, skills, and MCP config fragments are
copied or merged into target-specific plugin directories, and platform manifests
are generated from one canonical plugin definition.

Claude Code and Codex expose plugins as explicit distribution units. GitHub
Copilot has CLI plugin concepts, but its coding-agent customization surfaces are
still better modeled here as custom agents plus skills plus MCP configuration.
For that reason the Copilot plugin output is a bundle directory with a manifest
and copied generated artifacts rather than an attempt to invent a new Copilot
agent runtime.

## MCP Configs

`agent-def-translator` translates MCP config definitions into target-specific
config fragments. It does not implement MCP servers, start MCP servers, or own
user authentication.

Keep MCP references here because target agent definitions often mention tools,
and MCP config translation is intentionally adjacent to agent definition
translation.

- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Codex MCP](https://developers.openai.com/codex/mcp)
- [OpenAI Docs MCP](https://platform.openai.com/docs/docs-mcp)
- [OpenAI Connectors and MCP servers](https://platform.openai.com/docs/guides/tools-connectors-mcp)
- [GitHub Copilot: Extend cloud agent with MCP](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/extend-cloud-agent-with-mcp)
- [GitHub Copilot: MCP concept](https://docs.github.com/en/copilot/concepts/context/mcp)

MCP config definitions use a separate canonical model from agent roles. For
example, agent definitions may reference logical tools or capability names,
while MCP config definitions own server URLs, transport details, authentication
environment variable names, allowed tools, and target-specific wiring.

Do not treat MCP as another agent target. MCP is a tool and data-source
connection layer that an agent may use.

## Selection Rules

- Prefer official vendor documentation over blog posts, examples, or local
  generated files.
- Keep references grouped by concept: agent definitions, skills, plugins, and
  MCP should not be mixed into one target table.
- Prefer canonical shared intent plus target-specific projection over a lowest
  common denominator native file.
- Treat redirects as unstable. Store the final canonical URL when practical.
- Re-check these links before adding new rendered fields, because platform
  configuration surfaces change frequently.
- Avoid encoding one platform's lifecycle concepts into the canonical model
  unless another target can either represent them or safely ignore them.
