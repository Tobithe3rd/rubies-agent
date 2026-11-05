#!/usr/bin/env bash
# Shared protected-path check. Usage: protected_check <label-prefix> <base-tag>
#   e.g. protected_check o chat3-done   -> emits "o1. protected paths untouched since chat3-done"
# Needs check(label, 1|0, [detail]) and skip(label) from the caller; falls back to plain versions.

declare -F check >/dev/null || check() { if [ "$2" = 1 ]; then echo "PASS: $1"; else echo "FAIL: $1${3:+ ($3)}"; fi; }
declare -F skip  >/dev/null || skip()  { echo "SKIP: $1"; }

# Strict: any modification or deletion fails, except reviewed files matching their tag.
PROT_STRICT=(agent/session.py agent/bank_client.py agent/errors.py agent/tool_runtime.py)
# Parallel arrays: each reviewed tag exempts the space-separated file list at the same index.
PROT_REVIEWED_TAGS=(attachment-confirm-guard-reviewed phone-validation-reviewed)
PROT_REVIEWED_FILES=(
  "agent/session.py agent/tool_runtime.py"
  "bank_api/auth.py bank_api/main.py"
)
# Protected trees, minus planned exemptions (files with their own line-level rules are excluded here).
PROT_TREES=(bank_api providers rag)
SEED_REVIEWED_TAG="seed-fix-reviewed"   # reviewed seed fix; seed.py must match this tag exactly
PROT_EXEMPT=(':(exclude)providers/llm' ':(exclude)rag/query_rewrite.py' ':(exclude)rag/threshold_report.py' ':(exclude)rag/README.md' ':(exclude)bank_api/seed.py' ':(exclude)rag/calibrate.py' ':(exclude)rag/analyze_dev_set.py')

# True when <file> is byte-identical to the reviewed tag that lists it.
_reviewed_exempt() {
  local f="$1" i tag files
  for i in "${!PROT_REVIEWED_TAGS[@]}"; do
    tag="${PROT_REVIEWED_TAGS[$i]}"
    for files in ${PROT_REVIEWED_FILES[$i]}; do
      if [ "$files" = "$f" ]; then
        git rev-parse -q --verify "$tag" >/dev/null 2>&1 \
          && git diff --quiet "$tag" -- "$f"
        return
      fi
    done
  done
  return 1
}

# Changed lines of <file> since <base> that do NOT match the allowed regex.
_bad_lines() {
  git diff -U0 "$1" -- "$2" 2>/dev/null \
    | grep -E '^[+-]' \
    | grep -vE '^(\+\+\+|---) (a/|b/|/dev/null)' \
    | grep -vE "$3"
}

protected_check() {
  local pfx="$1" base="$2" problems="" out f
  if ! git rev-parse -q --verify "$base" >/dev/null 2>&1; then
    skip "${pfx}1. protected paths (tag ${base} not found)"
    return 0
  fi

  out=""
  for f in "${PROT_STRICT[@]}"; do
    if [ -z "$(git diff --name-only --diff-filter=MD "$base" -- "$f")" ]; then continue; fi
    if _reviewed_exempt "$f"; then continue; fi
    out="$out$f "
  done
  if [ -n "$out" ]; then problems="$problems [strict] $out"; fi

  out=""
  for f in $(git diff --name-only "$base" -- "${PROT_TREES[@]}" "${PROT_EXEMPT[@]}"); do
    if _reviewed_exempt "$f"; then continue; fi
    out="$out$f "
  done
  if [ -n "$out" ]; then problems="$problems [protected tree] $out"; fi

  # seed.py: manifest-path-only changes since $base, OR byte-identical to the reviewed seed fix.
  out=$(_bad_lines "$base" bank_api/seed.py 'seed_manifest' | head -3 | tr '\n' ' ')
  if [ -n "$out" ]; then
    if git rev-parse -q --verify "$SEED_REVIEWED_TAG" >/dev/null 2>&1 && git diff --quiet "$SEED_REVIEWED_TAG" -- bank_api/seed.py; then
      :
    else
      problems="$problems [seed.py differs from $base and from $SEED_REVIEWED_TAG] $out"
    fi
  fi

  # calibrate.py / analyze_dev_set.py: every changed line must be a data/ or eval/ path string.
  for f in rag/calibrate.py rag/analyze_dev_set.py; do
    out=$(_bad_lines "$base" "$f" '(eval/|data/)' | head -3 | tr '\n' ' ')
    if [ -n "$out" ]; then problems="$problems [$f non-path lines] $out"; fi
  done

  if [ -z "$problems" ]; then
    check "${pfx}1. protected paths untouched since ${base} (path-only refactor and planned files exempt)" 1
  else
    check "${pfx}1. protected paths untouched since ${base}" 0 "$problems"
  fi
}
