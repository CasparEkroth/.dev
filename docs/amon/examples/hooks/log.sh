#!/usr/bin/env bash
# Example amon hook: append lifecycle info to ./agent.log (under CWD).
# Wire from agent JSON:
#   "hooks": { "start": "~/.amon/hooks/log.sh", ... }

set -euo pipefail

LOG_FILE="${CWD:-.}/agent.log"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

{
  echo "========== hook log =========="
  echo "timestamp       : $TIMESTAMP"
  echo "SESSION_ID      : ${SESSION_ID:-}"
  echo "HOOK_EVENT_NAME : ${HOOK_EVENT_NAME:-}"
  echo "CWD             : ${CWD:-}"
  echo "PROMPT          : ${PROMPT:-}"
  echo "RESPONSE        : ${RESPONSE:-}"
  echo "TOOL_NAME       : ${TOOL_NAME:-}"
  echo "TOOL_INPUT      : ${TOOL_INPUT:-}"
  echo "TOOL_OUTPUT     : ${TOOL_OUTPUT:-}"
  echo "================================"
  echo
} >> "$LOG_FILE"
