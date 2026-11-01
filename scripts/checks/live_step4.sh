#!/usr/bin/env bash
# Live Step 4 checks against real Bedrock: Pidgin scenarios P1-P5 and no-guessing scenarios N1-N3.
# Usage: bash scripts/checks/live_step4.sh      (a few minutes; keep the Mac awake, e.g. caffeinate -i bash ...)
# Run it twice after any prompt change. It never edits prompts.
set -u
cd "$(dirname "$0")/../.."

PORT="${BANK_API_PORT:-8001}"
BASE="http://127.0.0.1:${PORT}"
STARTED=0
API_PID=""
LIVECFG=$(mktemp -d)
TOOLLOG="$LIVECFG/tool_calls.jsonl"
MANIFEST_TMP="$LIVECFG/seed_manifest.md"

cleanup() {
  cp "$TOOLLOG" /tmp/live_step4_tool_calls.jsonl 2>/dev/null || true
  if [ "$STARTED" = "1" ] && [ -n "$API_PID" ]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  rm -rf "$LIVECFG"
}
trap cleanup EXIT

# temp config copy with a fresh tool log and the real Bedrock provider (config/settings.yaml is never edited)
cp config/settings.yaml "$LIVECFG/settings.yaml"
cp config/tools.yaml "$LIVECFG/tools.yaml"
python3 - "$LIVECFG/settings.yaml" "$TOOLLOG" <<'PY'
import sys
import yaml

path, log_path = sys.argv[1], sys.argv[2]
with open(path) as handle:
    data = yaml.safe_load(handle)
data["logging"]["tool_log_path"] = log_path
data["llm"]["provider"] = "bedrock"
with open(path, "w") as handle:
    yaml.safe_dump(data, handle, sort_keys=False)
PY
echo "INFO: temp config at $LIVECFG, tool log at $TOOLLOG"

# fresh seed, written to a temp manifest (the tracked manifest is not touched)
if ! python3 -c "import sys; from bank_api.seed import main; main(manifest_path=sys.argv[1])" "$MANIFEST_TMP" >/tmp/live_step4_seed.log 2>&1; then
  echo "FAIL: seed fresh data (see /tmp/live_step4_seed.log)"
  echo "RESULT: 0 passed, 1 failed, 0 errors"
  exit 1
fi
echo "INFO: seeded fresh data"

# make sure the real bank API is running
http_code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null || true)
if [ "$http_code" = "200" ]; then
  echo "INFO: using running bank API on $BASE"
else
  python3 -m uvicorn bank_api.main:create_app --factory --host 127.0.0.1 --port "$PORT" \
    >/tmp/live_step4_bank_api.log 2>&1 &
  API_PID=$!
  STARTED=1
  code=""
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null || true)
    if [ "$code" = "200" ]; then break; fi
    sleep 0.5
  done
  if [ "$code" != "200" ]; then
    echo "FAIL: bank API did not start on $BASE (see /tmp/live_step4_bank_api.log)"
    echo "RESULT: 0 passed, 1 failed, 0 errors"
    exit 1
  fi
  echo "INFO: started bank API on $BASE"
fi

RUBIES_LIVE_CONFIG_DIR="$LIVECFG" BANK_API_URL="$BASE" TOOLLOG="$TOOLLOG" MANIFEST_TMP="$MANIFEST_TMP" \
  python3 scripts/checks/live_step4.py
rc=$?
exit $rc
