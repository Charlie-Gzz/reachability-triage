#!/usr/bin/env bash
# Run the whole frozen eval without supervision, then rebuild results, assets and site.
#
#   1. Claude stages (`rt showcase --skip-local`). When a stage stops on the subscription's usage limit
#      (exit 75), wait and retry; every finding is cached, so each retry continues where the last one stopped.
#   2. Local model (LM Studio): load Qwen2.5 Coder 14B, run `rt showcase` (Claude stages are all cached
#      by then, so only the local stage runs), unload.
#   3. `rt refresh` (eval + assets + site).
#
# Usage:  bash scripts/eval_unattended.sh            (log: .work/eval_unattended.log)
# Env:    RETRY_MINUTES (default 30), MAX_RETRIES (default 40), LOCAL_MODEL, LOCAL_PORT (default 1235)
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p .work
LOG=.work/eval_unattended.log
RETRY_MINUTES=${RETRY_MINUTES:-30}
MAX_RETRIES=${MAX_RETRIES:-40}
LOCAL_MODEL=${LOCAL_MODEL:-qwen2.5-coder-14b-instruct}
LOCAL_PORT=${LOCAL_PORT:-1235}

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

say "=== stage 1: Claude configs (full, ablations, remediation) ==="
tries=0
while :; do
  uv run rt showcase --skip-local 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  case $rc in
    0) say "Claude stages complete"; break ;;
    75)
      tries=$((tries + 1))
      if (( tries > MAX_RETRIES )); then say "still limited after $MAX_RETRIES retries; giving up"; exit 75; fi
      say "usage limit; retry $tries/$MAX_RETRIES in ${RETRY_MINUTES} min"
      sleep $((RETRY_MINUTES * 60)) ;;
    3) say "project cap of Claude calls reached; stopping"; exit 3 ;;
    *) say "showcase failed with exit $rc; stopping"; exit "$rc" ;;
  esac
done

say "=== stage 2: local model ($LOCAL_MODEL on :$LOCAL_PORT) ==="
if command -v lms >/dev/null 2>&1; then
  lms server status 2>&1 | grep -q "running" || lms server start --port "$LOCAL_PORT" 2>&1 | tee -a "$LOG"
  lms load "$LOCAL_MODEL" -y -c 16384 2>&1 | tee -a "$LOG"
  uv run rt showcase 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  lms unload --all 2>&1 | tee -a "$LOG"
  [[ $rc -eq 0 ]] || say "local stage exited $rc (continuing to refresh)"
else
  say "lms not found; skipping the local model"
fi

say "=== stage 3: rt refresh ==="
uv run rt refresh 2>&1 | tee -a "$LOG"
say "done (exit ${PIPESTATUS[0]})"
