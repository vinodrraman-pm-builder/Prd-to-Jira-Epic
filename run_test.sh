#!/usr/bin/env bash
# run_test.sh — Run the PRD-to-Jira agent against the local dummy Jira server.
#
# Usage:
#   1.  Start the mock server in one terminal:
#         python mock_jira_server.py
#
#   2.  In a second terminal, set your Anthropic key and run this script:
#         ANTHROPIC_API_KEY=sk-ant-... bash run_test.sh
#
#   Optionally pass a different PRD file as the first argument:
#         ANTHROPIC_API_KEY=sk-ant-... bash run_test.sh my_other_prd.md

set -euo pipefail

# ── Dummy Jira credentials (match the mock server) ────────────────────────────
export JIRA_URL="http://localhost:8080"
export JIRA_EMAIL="test@example.com"
export JIRA_API_TOKEN="dummy-token-for-local-testing"
export JIRA_PROJECT_KEY="DEMO"

# ── Anthropic key — must be provided by the caller ────────────────────────────
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "❌  ANTHROPIC_API_KEY is not set."
  echo "    Export it before running:"
  echo "      export ANTHROPIC_API_KEY=sk-ant-..."
  exit 1
fi

# ── PRD file (default: sample_prd.md) ────────────────────────────────────────
PRD_FILE="${1:-sample_prd.md}"

if [ ! -f "$PRD_FILE" ]; then
  echo "❌  PRD file not found: $PRD_FILE"
  exit 1
fi

# ── Check that the mock server is up ─────────────────────────────────────────
if ! curl -sf "http://localhost:8080/" -o /dev/null 2>/dev/null; then
  echo "❌  Mock Jira server is not running on http://localhost:8080"
  echo "    Start it first in another terminal:"
  echo "      python mock_jira_server.py"
  exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  PRD file : $PRD_FILE"
echo "  Jira     : $JIRA_URL  (project: $JIRA_PROJECT_KEY)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 prd_to_jira_agent.py "$PRD_FILE"

echo ""
echo "✅  Done. View your epic at: http://localhost:8080/"
