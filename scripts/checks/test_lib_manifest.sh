#!/usr/bin/env bash
# Self-test for lib_manifest.sh. Temp files only: no servers, no AWS.
LIB="$(cd "$(dirname "$0")" && pwd)/lib_manifest.sh"
RES=""; DETAIL=""
check() { if [ "$2" = 1 ]; then RES=PASS; else RES=FAIL; fi; DETAIL="${3:-}"; }
skip()  { RES=SKIP; DETAIL="$1"; }
source "$LIB"

D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
fails=0; total=0

base_manifest() { cat <<'EOM'
# Seed manifest

| Name | Phone | Scenario | Reference / last4 | KYC tier |
|---|---|---|---|---|
| Adebayo Ogunleye | +2348031234567 | Lost card demo | 0001 | tier3 |
| Ngozi Okonkwo | +2348052345678 | Low inflow | ₦12,752/mo, 549d | tier1 |
| Fatima Ibrahim | +2348093456789 | Failed transfer (ref RUB-03-000037) | RUB-03-000037, ₦50,000, 2026-10-29 | tier3 |
| Bola Adeyemi | +2348115678901 | Double debit | RUB-DB-001 / RUB-DB-002, ₦25,000, 2026-10-30 | tier1 |

Customers: 20
Transactions: 525
Cards: 3
Loans: 1
EOM
}

mk()   { base_manifest > "$D/base.md"; base_manifest > "$D/cur.md"; }
swap() {
  python3 - "$D/cur.md" "$1" "$2" <<'PY'
import sys
p, a, b = sys.argv[1:4]
s = open(p, encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(s.replace(a, b))
PY
}
t() {  # name, expected regex
  total=$((total+1))
  local out; out=$(manifest_classify "$D/base.md" "$D/cur.md")
  if printf '%s\n' "$out" | grep -qE "$2"; then echo "PASS: $1"
  else echo "FAIL: $1 (expected $2, got: $(printf '%s' "$out" | tr '\n' '|'))"; fails=$((fails+1)); fi
}

mk;                                                    t "identical manifest"                    '^NOCHANGE$'
mk; swap "2026-10-29" "2026-11-02";                    t "date-only change"                      '^PASS$'
mk; swap "| tier1 |" "| tier2 |";                      t "tier-only change"                      '^PASS$'
mk; swap "2026-10-29" "2026-11-02"; swap "| tier1 |" "| tier2 |"; t "date and tier change"       '^PASS$'
mk; swap "₦12,752/mo" "₦11,885/mo";                    t "inflow amount changed"                 '^PASS$'
mk; swap "RUB-03-000037" "RUB-03-000014";              t "reference sequence number changed"     '^PASS$'
mk; swap "Transactions: 525" "Transactions: 487";      t "transaction count changed"             '^PASS$'
mk; swap "₦12,752/mo" "₦11,885/mo"; swap "RUB-03-000037" "RUB-03-000014"; swap "Transactions: 525" "Transactions: 487"; swap "2026-10-29" "2026-10-30"; swap "| tier1 |" "| tier2 |"; t "all run-day fields together" '^PASS$'
mk; swap "RUB-03-000037" "RUB-07-000037";              t "reference group changed"               '^FAIL:'
mk; swap "RUB-DB-001" "RUB-DB-009";                    t "fixed reference changed"               '^FAIL:'
mk; swap "+2348115678901" "+2348115670000";            t "phone changed"                         '^FAIL:'
mk; swap "₦50,000" "₦60,000";                          t "failed-transfer amount changed"        '^FAIL:'
mk; swap "₦25,000" "₦26,000";                          t "double-debit amount changed"           '^FAIL:'
mk; swap "| 0001 |" "| 0002 |";                        t "card last4 changed"                    '^FAIL:'
mk; swap "Fatima Ibrahim" "Fatima Ibrahim Jr";         t "name changed"                          '^FAIL:'
mk; swap "Low inflow" "High inflow";                   t "scenario text changed"                 '^FAIL:'
mk; swap "Customers: 20" "Customers: 21";              t "customer count changed"                '^FAIL:'
mk; swap "Cards: 3" "Cards: 4";                        t "card count changed"                    '^FAIL:'
mk; swap "Loans: 1" "Loans: 2";                        t "loan count changed"                    '^FAIL:'
mk; swap "| tier1 |" "| tier2 |"; swap "Bola Adeyemi" "Bola Adeyemi Jr"; t "tier change plus name change" '^FAIL:'
mk; grep -v "Bola Adeyemi" "$D/cur.md" > "$D/cur2.md"; mv "$D/cur2.md" "$D/cur.md"; t "deleted customer row" '^FAIL:'
mk; echo "| New Person | +2348000000000 | - |  | tier1 |" >> "$D/cur.md"; t "added customer row"  '^FAIL:'
mk; rm -f "$D/base.md";                                t "missing base file"                     '^FAIL:'

total=$((total+1)); RES=""
manifest_check "x" no-such-tag-xyz >/dev/null
if [ "$RES" = "SKIP" ]; then echo "PASS: missing tag prints SKIP, not PASS"; else echo "FAIL: missing tag gave '$RES'"; fails=$((fails+1)); fi

echo "RESULT: $((total-fails)) passed, $fails failed"
[ "$fails" = 0 ]
