#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK_ROOT="${E2E_WORK_ROOT:-${SOURCE_ROOT}/.tmp/e2e-smoke}"
LIVE=0

usage() {
  cat <<'USAGE'
Usage: scripts/e2e-smoke.sh [--live]

Runs a disposable end-to-end smoke test under .tmp/e2e-smoke.

Default mode:
  - creates a small subagent definition project
  - validates definitions through the installed CLI entry point
  - generates Claude, Codex, and Copilot artifacts
  - checks deterministic drift detection
  - builds the Python package

--live mode additionally checks external CLI help surfaces when the
corresponding commands are installed. It does not call model APIs.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --live)
      LIVE=1
      shift
      ;;
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

require_marker() {
  marker="$1"
  path="$2"
  if ! grep -Fq -- "$marker" "$path"; then
    echo "expected marker not found: $marker in $path" >&2
    exit 1
  fi
}

cd "${SOURCE_ROOT}"
rm -rf "${WORK_ROOT}"
mkdir -p "${WORK_ROOT}/definitions/agents" "${WORK_ROOT}/definitions/prompts"
mkdir -p "${WORK_ROOT}/definitions/mcp"

cat > "${WORK_ROOT}/definitions/agents/hello.toml" <<'EOF'
name = "hello"
description = "Reply with a short greeting."
instructions = """
Reply with exactly one short greeting.
"""

[targets.claude]
tools = []
prompt_append_file = "../prompts/hello.claude.md"

[targets.codex]
sandbox_mode = "read-only"

[targets.copilot]
tools = []
target = "vscode"
EOF

cat > "${WORK_ROOT}/definitions/prompts/hello.claude.md" <<'EOF'
Do not use tools.
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

uv run agent-def-translator subagent validate \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  > "${WORK_ROOT}/validate.txt"
require_marker "hello.toml" "${WORK_ROOT}/validate.txt"

uv run agent-def-translator agent validate \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  2> "${WORK_ROOT}/agent-validate.stderr" \
  > "${WORK_ROOT}/agent-validate.txt"
require_marker "hello.toml" "${WORK_ROOT}/agent-validate.txt"
require_marker "deprecated" "${WORK_ROOT}/agent-validate.stderr"

uv run agent-def-translator translate \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  --output-dir "${WORK_ROOT}/generated" \
  2> "${WORK_ROOT}/translate.stderr" \
  > "${WORK_ROOT}/translate.txt"
require_marker "deprecated" "${WORK_ROOT}/translate.stderr"

uv run agent-def-translator subagent translate \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  --output-dir "${WORK_ROOT}/generated-subagent-resource" \
  > "${WORK_ROOT}/subagent-translate.txt"

uv run agent-def-translator subagent diff \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/diff.txt"

uv run agent-def-translator mcp validate \
  --definitions-dir "${WORK_ROOT}/definitions/mcp" \
  > "${WORK_ROOT}/mcp-validate.txt"
require_marker "openai-docs.toml" "${WORK_ROOT}/mcp-validate.txt"

uv run agent-def-translator mcp translate \
  --definitions-dir "${WORK_ROOT}/definitions/mcp" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/mcp-translate.txt"

uv run agent-def-translator mcp diff \
  --definitions-dir "${WORK_ROOT}/definitions/mcp" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/mcp-diff.txt"

require_marker "Do not use tools." \
  "${WORK_ROOT}/generated/claude/agents/hello.md"
require_marker 'sandbox_mode = "read-only"' \
  "${WORK_ROOT}/generated/codex/agents/hello.toml"
require_marker 'target: "vscode"' \
  "${WORK_ROOT}/generated/copilot/agents/hello.agent.md"
require_marker '[mcp_servers.openaiDeveloperDocs]' \
  "${WORK_ROOT}/generated/codex/mcp/openai-docs.toml"
require_marker '"openaiDeveloperDocs"' \
  "${WORK_ROOT}/generated/claude/mcp/openai-docs.json"
require_marker '"tools"' \
  "${WORK_ROOT}/generated/copilot/mcp/openai-docs.json"

uv build --out-dir "${WORK_ROOT}/dist" > "${WORK_ROOT}/build.log"
ls "${WORK_ROOT}/dist"/*.whl > "${WORK_ROOT}/wheel.txt"
ls "${WORK_ROOT}/dist"/*.tar.gz > "${WORK_ROOT}/sdist.txt"

if [ "${LIVE}" -eq 1 ]; then
  if command -v claude >/dev/null 2>&1; then
    claude --help > "${WORK_ROOT}/claude-help.txt"
    require_marker "--print" "${WORK_ROOT}/claude-help.txt"
    mkdir -p "${WORK_ROOT}/live/claude-project" "${WORK_ROOT}/live/claude-home"
    cp "${WORK_ROOT}/generated/claude/mcp/openai-docs.json" \
      "${WORK_ROOT}/live/claude-project/.mcp.json"
    (
      cd "${WORK_ROOT}/live/claude-project"
      HOME="${WORK_ROOT}/live/claude-home" claude mcp list \
        > "${WORK_ROOT}/claude-mcp-list.txt"
    )
    require_marker "openaiDeveloperDocs" \
      "${WORK_ROOT}/claude-mcp-list.txt"
  else
    echo "SKIP claude: command not found"
  fi

  if command -v codex >/dev/null 2>&1; then
    codex exec --help > "${WORK_ROOT}/codex-exec-help.txt"
    require_marker "--sandbox" "${WORK_ROOT}/codex-exec-help.txt"
    mkdir -p "${WORK_ROOT}/live/codex-home/.codex"
    cp "${WORK_ROOT}/generated/codex/mcp/openai-docs.toml" \
      "${WORK_ROOT}/live/codex-home/.codex/config.toml"
    HOME="${WORK_ROOT}/live/codex-home" codex mcp list --json \
      > "${WORK_ROOT}/codex-mcp-list.json"
    require_marker "openaiDeveloperDocs" \
      "${WORK_ROOT}/codex-mcp-list.json"
  else
    echo "SKIP codex: command not found"
  fi

  if command -v copilot >/dev/null 2>&1; then
    copilot --help > "${WORK_ROOT}/copilot-help.txt"
    require_marker "--agent" "${WORK_ROOT}/copilot-help.txt"
    mkdir -p "${WORK_ROOT}/live/copilot-config"
    cp "${WORK_ROOT}/generated/copilot/mcp/openai-docs.json" \
      "${WORK_ROOT}/live/copilot-config/mcp-config.json"
    copilot mcp list --config-dir "${WORK_ROOT}/live/copilot-config" --json \
      > "${WORK_ROOT}/copilot-mcp-list.json"
    require_marker "openaiDeveloperDocs" \
      "${WORK_ROOT}/copilot-mcp-list.json"
  else
    echo "SKIP copilot: command not found"
  fi
fi

echo "e2e smoke passed: ${WORK_ROOT}"
