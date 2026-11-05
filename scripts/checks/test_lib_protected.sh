#!/usr/bin/env bash
# Self-test for lib_protected.sh using throwaway git repos.
LIB="$(cd "$(dirname "$0")" && pwd)/lib_protected.sh"
RES=""; DETAIL=""
check() { if [ "$2" = 1 ]; then RES=PASS; else RES=FAIL; fi; DETAIL="${3:-}"; }
skip()  { RES=SKIP; DETAIL="$1"; }
source "$LIB"

fails=0; total=0
mk_repo() {
  T=$(mktemp -d); cd "$T" || exit 1
  git init -q
  mkdir -p agent bank_api rag providers/llm
  for f in session bank_client errors tool_runtime runner affirmation; do echo "$f v1" > "agent/$f.py"; done
  for f in auth main service; do echo "$f v1" > "bank_api/$f.py"; done
  printf 'with open("data/seed_manifest.md", "w") as f:\n    pass\nPHONE = "+2348031234567"\n' > bank_api/seed.py
  printf 'OUTPUT_PATH = "data/rag_calibration.json"\nx = 1\n' > rag/calibrate.py
  printf 'DEFAULT_REPORT = "data/rag_threshold_report.json"\ny = 1\n' > rag/analyze_dev_set.py
  echo "search v1" > rag/search.py
  git add -A
  git -c user.name=t -c user.email=t@t commit -q -m base
  git tag base
  git tag affirmation-guard-reviewed
}
run_case() {  # name expected setup_fn
  total=$((total+1)); mk_repo; "$3"; protected_check t base
  if [ "$RES" = "$2" ]; then echo "PASS: $1 -> $RES"; else echo "FAIL: $1 expected $2, got $RES ($DETAIL)"; fails=$((fails+1)); fi
  cd /; rm -rf "$T"
}

c_none()       { :; }
c_seed_ok()    { printf 'with open("data/generated/seed_manifest.md", "w") as f:\n    pass\nPHONE = "+2348031234567"\n' > bank_api/seed.py; }
c_seed_bad()   { printf 'with open("data/seed_manifest.md", "w") as f:\n    pass\nPHONE = "+2348039999999"\n' > bank_api/seed.py; }
c_cal_ok()     { printf 'OUTPUT_PATH = "eval/reports/rag_calibration.json"\nx = 1\n' > rag/calibrate.py; }
c_cal_bad()    { printf 'OUTPUT_PATH = "data/rag_calibration.json"\nx = 2\n' > rag/calibrate.py; }
c_ana_ok()     { printf 'DEFAULT_REPORT = "eval/reports/rag_threshold_report.json"\ny = 1\n' > rag/analyze_dev_set.py; }
c_ana_bad()    { printf 'DEFAULT_REPORT = "data/rag_threshold_report.json"\ny = 2\n' > rag/analyze_dev_set.py; }
c_session()    { echo "session v2" > agent/session.py; }
c_runtime()    { echo "tool_runtime v2" > agent/tool_runtime.py; }
c_reviewed_session() { echo "session v2" > agent/session.py; commit_affirmation_reviewed; }
c_reviewed_runtime() { echo "tool_runtime v2" > agent/tool_runtime.py; commit_affirmation_reviewed; }
c_reviewed_session_changed_after_tag() {
  echo "session v2" > agent/session.py; commit_affirmation_reviewed
  echo "session v3" > agent/session.py
}
c_reviewed_runtime_changed_after_tag() {
  echo "tool_runtime v2" > agent/tool_runtime.py; commit_affirmation_reviewed
  echo "tool_runtime v3" > agent/tool_runtime.py
}
c_reviewed_session_without_tag() {
  git tag -d affirmation-guard-reviewed >/dev/null
  echo "session v2" > agent/session.py
}
c_reviewed_session_but_unrelated_strict_changed() {
  echo "session v2" > agent/session.py; commit_affirmation_reviewed
  echo "bank_client v2" > agent/bank_client.py
}
commit_affirmation_reviewed() {
  git add -A
  git -c user.name=t -c user.email=t@t commit -q -m affirmation-review
  git tag -f affirmation-guard-reviewed >/dev/null
}
c_old_tag_only() {
  git tag -d affirmation-guard-reviewed >/dev/null
  echo "session v2" > agent/session.py
  git add -A
  git -c user.name=t -c user.email=t@t commit -q -m old-review
  git tag attachment-confirm-guard-reviewed
}
c_reviewed_runner() { echo "runner v2" > agent/runner.py; commit_affirmation_reviewed; }
c_reviewed_runner_changed_after_tag() {
  echo "runner v2" > agent/runner.py; commit_affirmation_reviewed
  echo "runner v3" > agent/runner.py
}
c_reviewed_affirmation_changed_after_tag() {
  echo "affirmation v2" > agent/affirmation.py; commit_affirmation_reviewed
  echo "affirmation v3" > agent/affirmation.py
}
c_pinned_without_tag() { git tag -d affirmation-guard-reviewed >/dev/null; }
c_reviewed_auth() { echo "auth v2" > bank_api/auth.py; commit_phone_reviewed; }
c_reviewed_main() { echo "main v2" > bank_api/main.py; commit_phone_reviewed; }
c_reviewed_auth_changed_after_tag() {
  echo "auth v2" > bank_api/auth.py; commit_phone_reviewed
  echo "auth v3" > bank_api/auth.py
}
c_reviewed_auth_without_tag() { echo "auth v2" > bank_api/auth.py; }
c_non_reviewed_bank_file() { echo "service v2" > bank_api/service.py; }
commit_phone_reviewed() {
  git add -A
  git -c user.name=t -c user.email=t@t commit -q -m phone-review
  git tag phone-validation-reviewed
}
c_search()     { echo "search v2" > rag/search.py; }
c_exempt_new() { echo new > rag/query_rewrite.py; echo m > providers/llm/bedrock.py; git add -A; }
c_new_tree()   { echo x > rag/other.py; git add -A; }
c_seed_reviewed() { printf 'with open("data/seed_manifest.md", "w") as f:\n    pass\nPHONE = "+2348031234567"\nSALARY = 3\n' > bank_api/seed.py; git add -A; git -c user.name=t -c user.email=t@t commit -q -m seedfix; git tag seed-fix-reviewed; }
c_seed_after_review() { printf 'with open("data/seed_manifest.md", "w") as f:\n    pass\nPHONE = "+2348031234567"\nSALARY = 3\n' > bank_api/seed.py; git add -A; git -c user.name=t -c user.email=t@t commit -q -m seedfix; git tag seed-fix-reviewed; printf 'with open("data/seed_manifest.md", "w") as f:\n    pass\nPHONE = "+2348039999999"\nSALARY = 3\n' > bank_api/seed.py; }

run_case "no changes"                          PASS c_none
run_case "seed.py: manifest path only"         PASS c_seed_ok
run_case "seed.py: customer phone changed"     FAIL c_seed_bad
run_case "calibrate.py: eval/ path only"       PASS c_cal_ok
run_case "calibrate.py: code changed"          FAIL c_cal_bad
run_case "analyze_dev_set.py: eval/ path only" PASS c_ana_ok
run_case "analyze_dev_set.py: code changed"    FAIL c_ana_bad
run_case "agent/session.py modified"           FAIL c_session
run_case "agent/tool_runtime.py modified"      FAIL c_runtime
run_case "reviewed session.py matches the tag" PASS c_reviewed_session
run_case "reviewed tool_runtime.py matches the tag" PASS c_reviewed_runtime
run_case "reviewed session.py changed again after the tag" FAIL c_reviewed_session_changed_after_tag
run_case "reviewed tool_runtime.py changed again after the tag" FAIL c_reviewed_runtime_changed_after_tag
run_case "file matching only attachment-confirm-guard-reviewed fails" FAIL c_old_tag_only
run_case "reviewed session.py changed with the tag absent" FAIL c_reviewed_session_without_tag
run_case "reviewed session.py matches but unrelated strict file changed" FAIL c_reviewed_session_but_unrelated_strict_changed
run_case "pinned runner.py matches the tag" PASS c_reviewed_runner
run_case "pinned runner.py changed after the tag" FAIL c_reviewed_runner_changed_after_tag
run_case "pinned affirmation.py changed after the tag" FAIL c_reviewed_affirmation_changed_after_tag
run_case "pinned file with the tag missing" FAIL c_pinned_without_tag
run_case "reviewed bank_api/auth.py matches the tag" PASS c_reviewed_auth
run_case "reviewed bank_api/main.py matches the tag" PASS c_reviewed_main
run_case "reviewed bank_api file changed again after the tag" FAIL c_reviewed_auth_changed_after_tag
run_case "reviewed bank_api file changed with the tag absent" FAIL c_reviewed_auth_without_tag
run_case "non-reviewed protected bank_api file changed" FAIL c_non_reviewed_bank_file
run_case "rag/search.py modified"              FAIL c_search
run_case "new exempt files (query_rewrite, providers/llm)" PASS c_exempt_new
run_case "new non-exempt file in rag/"         FAIL c_new_tree
run_case "seed.py: reviewed fix matches the tag"        PASS c_seed_reviewed
run_case "seed.py: changed again after the review tag"  FAIL c_seed_after_review

total=$((total+1)); mk_repo; protected_check t no-such-tag
if [ "$RES" = "SKIP" ]; then echo "PASS: missing tag prints SKIP, not PASS"; else echo "FAIL: missing tag gave $RES"; fails=$((fails+1)); fi
cd /; rm -rf "$T"

echo "RESULT: $((total-fails)) passed, $fails failed"
[ "$fails" = 0 ]
