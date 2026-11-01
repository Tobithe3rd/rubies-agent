#!/usr/bin/env bash
# Shared manifest-drift check.
#   manifest_classify <base_file> <current_file>
#       prints optional INFO lines, then exactly one of: PASS | NOCHANGE | FAIL: <base line>  ->  <current line>
#   manifest_check "<label>" <base-tag>
#       compares the manifest committed at <base-tag> with the current manifest.
# Tolerated drift (the seed is generated relative to the run day):
#   dates, KYC tiers, monthly inflow amounts, sequential reference numbers (RUB-NN-NNNNNN), the Transactions count.
# Everything else (names, phones, scenario amounts, last4, fixed refs such as RUB-DB-001, other counts) must match.
# Needs check(label, 1|0, [detail]) and skip(label) from the caller; falls back to plain versions.

declare -F check >/dev/null || check() { if [ "$2" = 1 ]; then echo "PASS: $1"; else echo "FAIL: $1${3:+ ($3)}"; fi; }
declare -F skip  >/dev/null || skip()  { echo "SKIP: $1"; }

MANIFEST_PATH="data/generated/seed_manifest.md"
MANIFEST_OLD_PATH="data/seed_manifest.md"   # location before the layout refactor (for example at chat3-done)

manifest_classify() {
  local base="$1" cur="$2"
  if [ ! -f "$base" ] || [ ! -f "$cur" ]; then
    echo "FAIL: manifest file missing  ->  $cur"
    return 0
  fi
  { diff -U0 "$base" "$cur" 2>/dev/null || true; } | python3 -c '
import sys, re
from collections import defaultdict
raw = [l for l in sys.stdin.read().splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
removed = [l[1:] for l in raw if l.startswith("-")]
added = [l[1:] for l in raw if l.startswith("+")]
if not removed and not added:
    print("NOCHANGE")
    sys.exit(0)
dr = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
tr = re.compile(r"\btier[0-9]\b")
inf = re.compile(r"₦[0-9,]+/mo")
rf = re.compile(r"\bRUB-([0-9]{2})-[0-9]{6}\b")
tx = re.compile(r"^Transactions: [0-9]+$")
nd = lambda s: dr.sub("DATE", s)
nt = lambda s: tr.sub("TIER", s)
ndt = lambda s: nd(nt(s))
nv = lambda s: tx.sub("Transactions: N", rf.sub(r"RUB-\1-SEQ", inf.sub("₦INFLOW/mo", s)))
nb = lambda s: nv(ndt(s))
rn = sorted(map(nb, removed))
an = sorted(map(nb, added))
if rn == an:
    gr, ga = defaultdict(list), defaultdict(list)
    for l in removed: gr[nb(l)].append(l)
    for l in added: ga[nb(l)].append(l)
    tier = date = runday = False
    for k in set(gr) | set(ga):
        for r, a in zip(gr[k], ga[k]):
            if r != a:
                if nt(r) == nt(a): tier = True
                elif nd(r) == nd(a): date = True
                elif ndt(r) == ndt(a): tier = date = True
                else: runday = True
    if tier: print("INFO: manifest tier drift (KYC tier follows run-day balances)")
    if date: print("INFO: manifest has date-only drift")
    if runday: print("INFO: manifest run-day-derived drift (inflow amounts, reference sequence numbers, transaction count)")
    print("PASS")
    sys.exit(0)
for i in range(max(len(rn), len(an))):
    r = rn[i] if i < len(rn) else "<none>"
    a = an[i] if i < len(an) else "<none>"
    if r != a:
        print("FAIL: " + r + "  ->  " + a)
        sys.exit(0)
print("FAIL: unclassified difference  ->  ")
' || true
  return 0
}

manifest_check() {
  local label="$1" base="$2" bpath tmp out first
  if ! git rev-parse -q --verify "$base" >/dev/null 2>&1; then
    skip "$label (tag $base not found)"
    return 0
  fi
  if git cat-file -e "$base:$MANIFEST_PATH" 2>/dev/null; then
    bpath="$MANIFEST_PATH"
  elif git cat-file -e "$base:$MANIFEST_OLD_PATH" 2>/dev/null; then
    bpath="$MANIFEST_OLD_PATH"
  else
    skip "$label (no manifest committed at $base)"
    return 0
  fi
  if [ ! -f "$MANIFEST_PATH" ]; then
    check "$label" 0 "current manifest missing: $MANIFEST_PATH"
    return 0
  fi
  tmp=$(mktemp)
  git show "$base:$bpath" > "$tmp"
  out=$(manifest_classify "$tmp" "$MANIFEST_PATH")
  rm -f "$tmp"
  printf '%s\n' "$out" | grep '^INFO:' || true
  if printf '%s\n' "$out" | grep -qE '^(PASS|NOCHANGE)$'; then
    check "$label" 1
  else
    first=$(printf '%s\n' "$out" | grep '^FAIL:' | head -1)
    check "$label" 0 "${first#FAIL: }"
  fi
}
