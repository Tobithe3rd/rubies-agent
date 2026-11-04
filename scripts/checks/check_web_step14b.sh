#!/usr/bin/env bash
# Web refactor guard (step 14b): unit tests, web file size and OpenAPI drift.
set -u
cd "$(dirname "$0")/../.."

BEFORE="${OPENAPI_BEFORE:-/tmp/openapi-before.json}"
AFTER="${OPENAPI_AFTER:-/tmp/openapi-after.json}"
passes=0
fails=0

check() {
  local name="$1" ok="$2" detail="${3:-}"
  if [ "$ok" = "1" ]; then
    echo "PASS: $name"
    passes=$((passes + 1))
  else
    echo "FAIL: $name ($detail)"
    fails=$((fails + 1))
  fi
}

# ---------------------------------------------------------------- pytest
python3 -m pytest -q >/tmp/check_web_step14b_pytest.log 2>&1
pytest_rc=$?
check "pytest -q" "$([ "$pytest_rc" -eq 0 ] && echo 1 || echo 0)" \
  "rc=${pytest_rc}; see /tmp/check_web_step14b_pytest.log"

# ---------------------------------------------------------------- file size
python3 scripts/checks/check_web_file_size.py --scope python \
  >/tmp/check_web_step14b_size.log 2>&1
size_rc=$?
check "web file size (--scope python)" "$([ "$size_rc" -eq 0 ] && echo 1 || echo 0)" \
  "rc=${size_rc}; see /tmp/check_web_step14b_size.log"

# ---------------------------------------------------------------- openapi
if [ ! -f "$BEFORE" ]; then
  python3 - "$BEFORE" <<'PY'
import json, sys
from adapters.web_chat import create_app
from core.config import load_config
app = create_app(load_config(config_dir="config"))
open(sys.argv[1], "w").write(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
PY
  echo "NOTE: $BEFORE was missing; generated it from the current app"
fi

python3 - "$AFTER" <<'PY'
import json, sys
from adapters.web_chat import create_app
from core.config import load_config
app = create_app(load_config(config_dir="config"))
open(sys.argv[1], "w").write(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
PY
openapi_rc=$?

if [ "$openapi_rc" -ne 0 ]; then
  check "openapi generated" 0 "rc=${openapi_rc}"
else
  diff -u "$BEFORE" "$AFTER" >/tmp/check_web_step14b_openapi.diff 2>&1
  diff_rc=$?
  check "openapi unchanged" "$([ "$diff_rc" -eq 0 ] && echo 1 || echo 0)" \
    "see /tmp/check_web_step14b_openapi.diff"
fi

echo "RESULT: ${passes} passed, ${fails} failed"
[ "$fails" -eq 0 ]
