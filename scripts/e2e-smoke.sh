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
  - creates a small agent definition project
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

uv run agent-def-translator validate \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  > "${WORK_ROOT}/validate.txt"
require_marker "hello.toml" "${WORK_ROOT}/validate.txt"

uv run agent-def-translator translate \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/translate.txt"

uv run agent-def-translator diff \
  --definitions-dir "${WORK_ROOT}/definitions/agents" \
  --output-dir "${WORK_ROOT}/generated" \
  > "${WORK_ROOT}/diff.txt"

require_marker "Do not use tools." \
  "${WORK_ROOT}/generated/claude/agents/hello.md"
require_marker 'sandbox_mode = "read-only"' \
  "${WORK_ROOT}/generated/codex/agents/hello.toml"
require_marker 'target: "vscode"' \
  "${WORK_ROOT}/generated/copilot/agents/hello.agent.md"

uv build --out-dir "${WORK_ROOT}/dist" > "${WORK_ROOT}/build.log"
ls "${WORK_ROOT}/dist"/*.whl > "${WORK_ROOT}/wheel.txt"
ls "${WORK_ROOT}/dist"/*.tar.gz > "${WORK_ROOT}/sdist.txt"

if [ "${LIVE}" -eq 1 ]; then
  if command -v claude >/dev/null 2>&1; then
    claude --help > "${WORK_ROOT}/claude-help.txt"
    require_marker "--print" "${WORK_ROOT}/claude-help.txt"
  else
    echo "SKIP claude: command not found"
  fi

  if command -v codex >/dev/null 2>&1; then
    codex exec --help > "${WORK_ROOT}/codex-exec-help.txt"
    require_marker "--sandbox" "${WORK_ROOT}/codex-exec-help.txt"
  else
    echo "SKIP codex: command not found"
  fi

  if command -v copilot >/dev/null 2>&1; then
    copilot --help > "${WORK_ROOT}/copilot-help.txt"
    require_marker "--agent" "${WORK_ROOT}/copilot-help.txt"
  else
    echo "SKIP copilot: command not found"
  fi
fi

echo "e2e smoke passed: ${WORK_ROOT}"
