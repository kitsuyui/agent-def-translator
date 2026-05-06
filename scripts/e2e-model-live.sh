#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK_ROOT="${E2E_MODEL_LIVE_WORK_ROOT:-${SOURCE_ROOT}/.tmp/e2e-model-live}"

CLAUDE_MODEL="${ADT_E2E_CLAUDE_MODEL:-haiku}"
CODEX_MODEL="${ADT_E2E_CODEX_MODEL:-gpt-5.4-mini}"
COPILOT_MODEL="${ADT_E2E_COPILOT_MODEL:-gpt-5.4-mini}"

SUBAGENT_MARKER="ADT_SUBAGENT_LIVE_OK"
SKILL_MARKER="ADT_SKILL_LIVE_OK"
MCP_MARKER="openaiDeveloperDocs"

usage() {
  cat <<'USAGE'
Usage: scripts/e2e-model-live.sh

Runs optional live end-to-end checks that call installed agent CLIs with short
model prompts. This is intentionally outside the default pytest suite.

Environment:
  ADT_E2E_CLAUDE_MODEL    Claude model alias/name to use (default: haiku)
  ADT_E2E_CODEX_MODEL     Codex model name to use (default: gpt-5.4-mini)
  ADT_E2E_COPILOT_MODEL   Copilot model name to use (default: gpt-5.4-mini)
  E2E_MODEL_LIVE_WORK_ROOT  Override the disposable work directory
USAGE
}

require_marker() {
  marker="$1"
  path="$2"
  if ! grep -Fq -- "$marker" "$path"; then
    echo "expected marker not found: $marker in $path" >&2
    echo "--- ${path} ---" >&2
    sed -n '1,160p' "$path" >&2 || true
    exit 1
  fi
}

copy_dir() {
  source="$1"
  destination="$2"
  rm -rf "$destination"
  mkdir -p "$(dirname "$destination")"
  cp -R "$source" "$destination"
}

run_or_skip() {
  command_name="$1"
  shift
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "SKIP ${command_name}: command not found"
    return 0
  fi
  "$@"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "${SOURCE_ROOT}"
rm -rf "${WORK_ROOT}"
mkdir -p "${WORK_ROOT}/definitions/agents"
mkdir -p "${WORK_ROOT}/definitions/skills/adt-live-skill/references"
mkdir -p "${WORK_ROOT}/definitions/mcp"
mkdir -p "${WORK_ROOT}/live/project"
git init -q "${WORK_ROOT}/live/project"

cat > "${WORK_ROOT}/definitions/agents/adt-live-agent.toml" <<EOF
name = "adt-live-agent"
description = "Return the live subagent test payload."
instructions = """
When asked for the live subagent payload, reply exactly:
${SUBAGENT_MARKER}
Do not add any other words.
"""

[targets.claude]
tools = []

[targets.codex]
sandbox_mode = "read-only"

[targets.copilot]
tools = []
target = "vscode"
EOF

cat > "${WORK_ROOT}/definitions/skills/adt-live-skill.toml" <<EOF
name = "adt-live-skill"
description = "Return the live skill test payload."
instructions = """
When this skill is invoked, reply exactly:
${SKILL_MARKER}
Do not add any other words.
"""
source_dir = "adt-live-skill"
user_invocable = true
disable_model_invocation = false
allowed_tools = []

[targets.codex]
display_name = "ADT Live Skill"
short_description = "Return the live skill test payload."
allow_implicit_invocation = true
EOF

cat > "${WORK_ROOT}/definitions/skills/adt-live-skill/references/payload.md" <<EOF
# Payload

${SKILL_MARKER}
EOF

cat > "${WORK_ROOT}/definitions/mcp/openai-docs.toml" <<'EOF'
name = "openai-docs"
description = "OpenAI developer documentation MCP server."
transport = "http"
url = "https://developers.openai.com/mcp"

[targets.codex]
server_name = "openaiDeveloperDocs"

[targets.claude]
server_name = "openaiDeveloperDocs"

[targets.copilot]
server_name = "openaiDeveloperDocs"
tools = ["*"]
EOF

uv run agent-def-translator subagent translate \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/subagent-translate.txt"
uv run agent-def-translator skill translate \
  --definitions-dir "${WORK_ROOT}/definitions/skills" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/skill-translate.txt"
uv run agent-def-translator mcp translate \
  --definitions-dir "${WORK_ROOT}/definitions/mcp" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/mcp-translate.txt"

copy_dir \
  "${WORK_ROOT}/generated/claude/agents" \
  "${WORK_ROOT}/live/project/.claude/agents"
copy_dir \
  "${WORK_ROOT}/generated/claude/skills" \
  "${WORK_ROOT}/live/project/.claude/skills"
mkdir -p "${WORK_ROOT}/live/project/.codex" "${WORK_ROOT}/live/project/.agents"
copy_dir \
  "${WORK_ROOT}/generated/codex/agents" \
  "${WORK_ROOT}/live/project/.codex/agents"
copy_dir \
  "${WORK_ROOT}/generated/codex/skills" \
  "${WORK_ROOT}/live/project/.agents/skills"
mkdir -p "${WORK_ROOT}/live/project/.github"
copy_dir \
  "${WORK_ROOT}/generated/copilot/agents" \
  "${WORK_ROOT}/live/project/.github/agents"
copy_dir \
  "${WORK_ROOT}/generated/copilot/skills" \
  "${WORK_ROOT}/live/project/.github/skills"

run_claude_live() {
  cp "${WORK_ROOT}/generated/claude/mcp/openai-docs.json" \
    "${WORK_ROOT}/live/project/.mcp.json"

  (
    cd "${WORK_ROOT}/live/project"
    claude \
      --print \
      --no-session-persistence \
      --model "${CLAUDE_MODEL}" \
      --agent adt-live-agent \
      "Return only the live subagent payload from your agent instructions." \
      > "${WORK_ROOT}/claude-subagent.txt"
  )
  require_marker "${SUBAGENT_MARKER}" "${WORK_ROOT}/claude-subagent.txt"

  (
    cd "${WORK_ROOT}/live/project"
    claude \
      --print \
      --no-session-persistence \
      --model "${CLAUDE_MODEL}" \
      "/adt-live-skill Return only the payload from this skill." \
      > "${WORK_ROOT}/claude-skill.txt"
  )
  require_marker "${SKILL_MARKER}" "${WORK_ROOT}/claude-skill.txt"

  (
    cd "${WORK_ROOT}/live/project"
    claude mcp list \
      > "${WORK_ROOT}/claude-mcp-list.txt"
  )
  require_marker "${MCP_MARKER}" "${WORK_ROOT}/claude-mcp-list.txt"
}

run_codex_live() {
  require_marker \
    "${SUBAGENT_MARKER}" \
    "${WORK_ROOT}/generated/codex/agents/adt-live-agent.toml"

  (
    cd "${WORK_ROOT}/live/project"
    codex debug prompt-input "Use \$adt-live-skill." \
      > "${WORK_ROOT}/codex-prompt-input.json"
  )
  require_marker "adt-live-skill" "${WORK_ROOT}/codex-prompt-input.json"

  codex exec \
    --cd "${WORK_ROOT}/live/project" \
    --skip-git-repo-check \
    --ephemeral \
    --ignore-rules \
    --config 'mcp_servers.openaiDeveloperDocs.url="https://developers.openai.com/mcp"' \
    --model "${CODEX_MODEL}" \
    --sandbox read-only \
    "Use \$adt-live-skill. Return only the payload from that skill." \
    > "${WORK_ROOT}/codex-skill.txt"
  require_marker "${SKILL_MARKER}" "${WORK_ROOT}/codex-skill.txt"

  codex \
    --config 'mcp_servers.openaiDeveloperDocs.url="https://developers.openai.com/mcp"' \
    mcp list --json \
    > "${WORK_ROOT}/codex-mcp-list.json"
  require_marker "${MCP_MARKER}" "${WORK_ROOT}/codex-mcp-list.json"
}

run_copilot_live() {
  mkdir -p "${WORK_ROOT}/live/copilot-config"
  cp "${WORK_ROOT}/generated/copilot/mcp/openai-docs.json" \
    "${WORK_ROOT}/live/copilot-config/mcp-config.json"

  (
    cd "${WORK_ROOT}/live/project"
    copilot \
      --additional-mcp-config "@${WORK_ROOT}/generated/copilot/mcp/openai-docs.json" \
      --model "${COPILOT_MODEL}" \
      --agent adt-live-agent \
      --silent \
      --allow-all \
      --prompt "Return only the live subagent payload from your agent instructions." \
      > "${WORK_ROOT}/copilot-subagent.txt"
  )
  require_marker "${SUBAGENT_MARKER}" "${WORK_ROOT}/copilot-subagent.txt"

  (
    cd "${WORK_ROOT}/live/project"
    copilot \
      --additional-mcp-config "@${WORK_ROOT}/generated/copilot/mcp/openai-docs.json" \
      --model "${COPILOT_MODEL}" \
      --silent \
      --allow-all \
      --prompt "/adt-live-skill Return only the payload from this skill." \
      > "${WORK_ROOT}/copilot-skill.txt"
  )
  require_marker "${SKILL_MARKER}" "${WORK_ROOT}/copilot-skill.txt"

  copilot mcp list \
    --config-dir "${WORK_ROOT}/live/copilot-config" \
    --json \
    > "${WORK_ROOT}/copilot-mcp-list.json"
  require_marker "${MCP_MARKER}" "${WORK_ROOT}/copilot-mcp-list.json"
}

run_or_skip claude run_claude_live
run_or_skip codex run_codex_live
run_or_skip copilot run_copilot_live

echo "e2e model live passed: ${WORK_ROOT}"
