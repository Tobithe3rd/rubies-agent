from __future__ import annotations

import math
import random
import datetime
from typing import Optional

from core.config import load_config
from providers.datastore.sqlite import SQLiteDataStore


# --- unit helpers ---

def naira_to_kobo(n) -> int:
    """Convert a naira amount to kobo."""
    return int(n * 100)


def _ceil_to_1000_naira(kobo: int) -> int:
    """Round a kobo amount up to the nearest 1,000 naira."""
    unit = naira_to_kobo(1000)
    return int(math.ceil(kobo / unit) * unit)


CREDIT_NARRATIONS = ["Transfer in", "POS refund", "Cash deposit"]
DEBIT_NARRATIONS = [
    "Airtime purchase",
    "ATM withdrawal",
    "Utility bill payment",
    "POS purchase",
    "Transfer out",
]

SALARY_AMOUNTS_NAIRA = [150000, 250000, 300000, 350000, 400000, 450000,
                        500000, 600000, 700000, 800000, 900000]


def _split(total: int, min_each: int, max_each: int) -> list[int]:
    """Split a kobo total into random parts each within [min_each, max_each]."""
    amounts: list[int] = []
    remaining = total
    while remaining > 0:
        amt = min(max_each, remaining)
        if amt > min_each:
            amt = random.randint(max(min_each, amt // 2), amt)
        if 0 < remaining - amt < min_each:
            amt = remaining - min_each
        if amt <= 0:
            amt = remaining
        amounts.append(amt)
        remaining -= amt
    return amounts


def eligibility_info(dataset: dict, cid: int, today_dt: datetime.datetime) -> str:
    """Average monthly inflow in naira and account age in days, for the manifest."""
    credits_kobo = sum(
        t.get("amount_kobo", 0)
        for t in dataset.get("transactions", [])
        if t.get("account_id") == cid
        and t.get("status") == "success"
        and t.get("direction") == "credit"
    )
    avg_monthly_naira = credits_kobo / 3 / 100
    acct = next((a for a in dataset.get("accounts", []) if a.get("id") == cid), None)
    age_days = (
        (today_dt - datetime.datetime.strptime(acct["opened_at"], "%Y-%m-%d")).days
        if acct else 0
    )
    return f"₦{avg_monthly_naira:,.0f}/mo, {age_days}d"


def build_dataset(cfg, today: Optional[str] = None) -> dict:
    if today is None:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_dt = datetime.datetime.strptime(today, "%Y-%m-%d")

    random.seed(cfg.settings.seed.random_seed)

    names = [
        ("Adebayo Ogunleye", "+2348031234567"),
        ("Ngozi Okonkwo", "+2348052345678"),
        ("Fatima Ibrahim", "+2348093456789"),
        ("Chidi Nwankwo", "+2348074567890"),
        ("Bola Adeyemi", "+2348115678901"),
        ("Olumide Adeyemi", "+2348136789012"),
        ("Aisha Bello", "+2348157890123"),
        ("Emeka Obi", "+2348178901234"),
        ("Funmi Okoro", "+2348199012345"),
        ("Tunde Afolabi", "+2348210123456"),
        ("Zainab Suleiman", "+2348231234567"),
        ("Ibrahim Musa", "+2348252345678"),
        ("Chinwe Okonkwo", "+2348273456789"),
        ("Adebisi Adeyemi", "+2348294567890"),
        ("Ngozi Afolabi", "+2348315678901"),
        ("Fatima Okoro", "+2348336789012"),
        ("Emeka Bello", "+2348357890123"),
        ("Chidi Adeyemi", "+2348378901234"),
        ("Bola Suleiman", "+2348399012345"),
        ("Olumide Okonkwo", "+2348410123456"),
    ]

    dataset = {
        "customers": [],
        "accounts": [],
        "transactions": [],
        "cards": [],
        "loans": [],
        "disputes": [],
        "otps": [],
        "sessions": [],
    }

    for i, (name, phone) in enumerate(names):
        dataset["customers"].append({
            "id": i + 1,
            "full_name": name,
            "phone": phone,
            "created_at": (today_dt - datetime.timedelta(days=random.randint(30, 730))).strftime("%Y-%m-%d"),
        })

    # Accounts: customer 15 is the new account; everyone else opened at least 90 days ago.
    for i, name in enumerate(names, start=1):
        account_type = random.choice(["savings", "current"])
        kyc_tier = random.choice(["tier1", "tier2", "tier3"])
        opened_days_ago = 15 if i == 15 else random.randint(90, 730)
        dataset["accounts"].append({
            "id": i,
            "customer_id": i,
            "account_number": f"10{i:08d}",
            "account_type": account_type,
            "kyc_tier": kyc_tier,
            "balance_kobo": 0,
            "opening_balance_kobo": 0,
            "status": "active",
            "opened_at": (today_dt - datetime.timedelta(days=opened_days_ago)).strftime("%Y-%m-%d"),
        })

    accounts_by_id = {a["id"]: a for a in dataset["accounts"]}
    name_by_id = {c["id"]: c["full_name"] for c in dataset["customers"]}

    def other_counterparty(self_id: int) -> str:
        options = [n for cid, n in name_by_id.items() if cid != self_id]
        return random.choice(options)

    def make_time(day: datetime.datetime) -> str:
        return day.strftime("%Y-%m-%d") + f" {random.randint(0, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"

    seq = {i: 0 for i in range(1, 21)}

    def next_ref(cid: int) -> str:
        seq[cid] += 1
        return f"RUB-{cid:02d}-{seq[cid]:06d}"

    txns: list[dict] = []

    def add_txn(cid, direction, amount_kobo, narration, status="success",
                created_at=None, counterparty_name=None, counterparty_bank="GTBank",
                reference=None, failure_reason=None, channel=None):
        txns.append({
            "id": 0,
            "account_id": cid,
            "reference": reference or next_ref(cid),
            "direction": direction,
            "amount_kobo": amount_kobo,
            "status": status,
            "channel": channel or random.choice(["transfer", "pos", "atm", "ussd", "mobile"]),
            "narration": narration,
            "counterparty_name": counterparty_name or other_counterparty(cid),
            "counterparty_bank": counterparty_bank,
            "failure_reason": failure_reason,
            "created_at": created_at,
        })

    for cid in range(1, 21):
        acct = accounts_by_id[cid]
        opened_dt = datetime.datetime.strptime(acct["opened_at"], "%Y-%m-%d")
        age_days = (today_dt - opened_dt).days
        max_days_back = min(89, age_days)

        has_salary = cid not in (2, 15)  # only Ngozi Okonkwo and Ngozi Afolabi have no salary
        credits_total_kobo = 0

        # --- salary credits: 5th of each of the last 3 months, on/before today and on/after opened_at
        if has_salary:
            salary_kobo = naira_to_kobo(450000) if cid == 18 else naira_to_kobo(random.choice(SALARY_AMOUNTS_NAIRA))
            y, m = today_dt.year, today_dt.month
            salary_dates = []
            for _ in range(3):
                d = datetime.datetime(y, m, 5)
                if d <= today_dt and d >= opened_dt:
                    salary_dates.append(d)
                m -= 1
                if m == 0:
                    m = 12
                    y -= 1
            for d in salary_dates:
                add_txn(cid, "credit", salary_kobo, "SALARY",
                        created_at=d.strftime("%Y-%m-%d 09:00:00"),
                        counterparty_name="Federal Ministry of Finance")
                credits_total_kobo += salary_kobo

        # --- random credits
        if cid == 2:
            # low inflow: 2,000-12,000 naira each, total 10,000-25,000 naira per month
            target = random.randint(naira_to_kobo(30000), naira_to_kobo(75000))
            credit_amounts = _split(target, naira_to_kobo(2000), naira_to_kobo(12000))
        elif cid == 15:
            credit_amounts = [random.randint(naira_to_kobo(1000), naira_to_kobo(10000))
                              for _ in range(random.randint(4, 8))]
        elif cid == 18:
            credit_amounts = [random.randint(naira_to_kobo(5000), naira_to_kobo(40000))
                              for _ in range(random.randint(3, 5))]
        else:
            credit_amounts = [random.randint(naira_to_kobo(500), naira_to_kobo(50000))
                              for _ in range(random.randint(3, 6))]

        for amt in credit_amounts:
            day = today_dt - datetime.timedelta(days=random.randint(0, max_days_back))
            add_txn(cid, "credit", amt, random.choice(CREDIT_NARRATIONS), created_at=make_time(day))
            credits_total_kobo += amt

        # --- random debits: 50-85% of total credits for salaried customers
        if cid == 2:
            debit_target = int(credits_total_kobo * random.uniform(0.3, 0.6))
            debit_amounts = _split(debit_target, naira_to_kobo(500), naira_to_kobo(5000)) if debit_target > 0 else []
        elif cid == 15:
            debit_target = int(credits_total_kobo * random.uniform(0.3, 0.7))
            debit_amounts = _split(debit_target, naira_to_kobo(500), naira_to_kobo(5000)) if debit_target > 0 else []
        else:
            debit_target = int(credits_total_kobo * random.uniform(0.5, 0.85))
            debit_amounts = _split(debit_target, naira_to_kobo(500), naira_to_kobo(80000)) if debit_target > 0 else []

        for amt in debit_amounts:
            day = today_dt - datetime.timedelta(days=random.randint(0, max_days_back))
            add_txn(cid, "debit", amt, random.choice(DEBIT_NARRATIONS), created_at=make_time(day))

    # --- scenario a) FAILED TRANSFER (customer 3, Fatima Ibrahim): 50,000 naira, 2 days ago
    failed_day = today_dt - datetime.timedelta(days=2)
    add_txn(3, "debit", naira_to_kobo(50000), "Transfer out", status="failed",
            created_at=failed_day.strftime("%Y-%m-%d 14:30:00"),
            counterparty_name="Chidi Nwankwo", failure_reason="Beneficiary bank timeout")

    # --- scenario b) DOUBLE DEBIT (customer 5, Bola Adeyemi): 2 x 25,000 naira, yesterday
    yesterday = today_dt - datetime.timedelta(days=1)
    add_txn(5, "debit", naira_to_kobo(25000), "POS purchase", created_at=yesterday.strftime("%Y-%m-%d 14:02:00"),
            counterparty_name="Adebayo Ogunleye", reference="RUB-DB-001")
    add_txn(5, "debit", naira_to_kobo(25000), "POS purchase", created_at=yesterday.strftime("%Y-%m-%d 14:05:00"),
            counterparty_name="Adebayo Ogunleye", reference="RUB-DB-002")

    # --- scenario f) PENDING TRANSFER (customer 7, Aisha Bello): 15,000 naira, 1 day ago
    add_txn(7, "debit", naira_to_kobo(15000), "Transfer out", status="pending",
            created_at=yesterday.strftime("%Y-%m-%d 09:45:00"),
            counterparty_name="Ngozi Okonkwo")

    # --- safety: no transaction may predate its account's opened_at
    for t in txns:
        acct = accounts_by_id[t["account_id"]]
        opened_dt = datetime.datetime.strptime(acct["opened_at"], "%Y-%m-%d")
        created_dt = datetime.datetime.strptime(t["created_at"], "%Y-%m-%d %H:%M:%S")
        if created_dt < opened_dt:
            time_part = t["created_at"].split(" ")[1]
            t["created_at"] = opened_dt.strftime("%Y-%m-%d") + " " + time_part

    # --- assign ids
    for idx, t in enumerate(txns, start=1):
        t["id"] = idx

    # --- balances: derived from a running balance over successful rows only
    floor_kobo = naira_to_kobo(5000)
    for cid in range(1, 21):
        acct = accounts_by_id[cid]
        successful = sorted(
            [t for t in txns if t["account_id"] == cid and t["status"] == "success"],
            key=lambda t: t["created_at"],
        )
        cumulative = 0
        min_cumulative = 0
        credits_kobo = 0
        debits_kobo = 0
        for t in successful:
            if t["direction"] == "credit":
                cumulative += t["amount_kobo"]
                credits_kobo += t["amount_kobo"]
            else:
                cumulative -= t["amount_kobo"]
                debits_kobo += t["amount_kobo"]
            min_cumulative = min(min_cumulative, cumulative)
        needed = floor_kobo - min_cumulative
        if needed < floor_kobo:
            needed = floor_kobo
        opening = _ceil_to_1000_naira(needed)
        acct["opening_balance_kobo"] = opening
        acct["balance_kobo"] = opening + credits_kobo - debits_kobo

    dataset["transactions"] = txns

    # --- cards: 3 active (1, 4, 8) + 1 already-blocked on customer 4
    dataset["cards"].append({
        "id": 1, "customer_id": 1, "last4": "0001", "card_type": "debit",
        "status": "active", "created_at": today, "blocked_at": None,
    })
    dataset["cards"].append({
        "id": 4, "customer_id": 4, "last4": "0004", "card_type": "debit",
        "status": "active", "created_at": today, "blocked_at": None,
    })
    dataset["cards"].append({
        "id": 8, "customer_id": 8, "last4": "0008", "card_type": "debit",
        "status": "active", "created_at": today, "blocked_at": None,
    })
    dataset["cards"].append({
        "id": 999, "customer_id": 4, "last4": "9999", "card_type": "debit",
        "status": "blocked",
        "created_at": (today_dt - datetime.timedelta(days=30)).strftime("%Y-%m-%d"),
        "blocked_at": today,
    })

    # --- active loan (customer 10, Tunde Afolabi)
    dataset["loans"].append({
        "id": 1,
        "customer_id": 10,
        "principal_kobo": naira_to_kobo(200000),
        "outstanding_kobo": naira_to_kobo(150000),
        "next_repayment_date": (today_dt + datetime.timedelta(days=30)).strftime("%Y-%m-%d"),
        "next_repayment_kobo": naira_to_kobo(25000),
        "status": "active",
    })

    return dataset


def main():
    cfg = load_config()
    store = SQLiteDataStore(cfg.settings.bank_api, cfg.env)
    store.init_schema()
    store.reset_data()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    dataset = build_dataset(cfg, today=today_str)
    store.insert_seed_data(dataset)

    today_dt = datetime.datetime.strptime(today_str, "%Y-%m-%d")
    customers = dataset.get("customers", [])
    transactions = dataset.get("transactions", [])
    cards = dataset.get("cards", [])
    loans = dataset.get("loans", [])

    def find_txn(account_id, status=None, reference=None):
        for t in transactions:
            if t["account_id"] != account_id:
                continue
            if status is not None and t["status"] != status:
                continue
            if reference is not None and t["reference"] != reference:
                continue
            return t
        return None

    failed_txn = find_txn(3, status="failed")
    pending_txn = find_txn(7, status="pending")
    db1 = find_txn(5, reference="RUB-DB-001")
    db2 = find_txn(5, reference="RUB-DB-002")
    loan = loans[0] if loans else None

    lines = ["# Seed manifest", ""]
    lines.append("| Name | Phone | Scenario | Reference / last4 |")
    lines.append("|---|---|---|---|")
    for c in customers:
        cid = c["id"]
        notes = []
        if cid == 3 and failed_txn:
            notes.append(f"Failed transfer (ref {failed_txn['reference']})")
        if cid == 5:
            notes.append("Double debit (RUB-DB-001/002, yesterday)")
        if cid == 1:
            notes.append("Lost card demo")
        if cid == 4:
            notes.append("Already-blocked card")
        if cid in (1, 4, 8):
            notes.append("Card holder (active card)")
        if cid == 18:
            notes.append("High steady inflow, no loan")
        if cid == 2:
            notes.append("Low inflow")
        if cid == 10:
            notes.append("Active loan")
        if cid == 15:
            notes.append("Very new account (15 days)")
        if cid == 7 and pending_txn:
            notes.append(f"Pending transfer (ref {pending_txn['reference']})")

        card_refs = [card["last4"] for card in cards if card["customer_id"] == cid]

        if cid == 3 and failed_txn:
            last_col = (f"{failed_txn['reference']}, "
                        f"₦{failed_txn['amount_kobo'] / 100:,.0f}, "
                        f"{failed_txn['created_at'].split(' ')[0]}")
        elif cid == 7 and pending_txn:
            last_col = (f"{pending_txn['reference']}, "
                        f"₦{pending_txn['amount_kobo'] / 100:,.0f}, "
                        f"{pending_txn['created_at'].split(' ')[0]}")
        elif cid == 5 and db1 and db2:
            last_col = (f"{db1['reference']} / {db2['reference']}, "
                        f"₦{db1['amount_kobo'] / 100:,.0f}, "
                        f"{db1['created_at'].split(' ')[0]}")
        elif cid == 10 and loan:
            last_col = (f"₦{loan['outstanding_kobo'] / 100:,.0f} outstanding, "
                        f"next {loan['next_repayment_date']}")
        elif cid in (18, 2, 15):
            last_col = eligibility_info(dataset, cid, today_dt)
        elif card_refs:
            last_col = card_refs[-1]
        else:
            last_col = ""

        scenario_text = "; ".join(notes) if notes else "-"
        lines.append(f"| {c['full_name']} | {c['phone']} | {scenario_text} | {last_col} |")

    lines.append("")
    lines.append(f"Customers: {len(customers)}")
    lines.append(f"Transactions: {len(transactions)}")
    lines.append(f"Cards: {len(cards)}")
    lines.append(f"Loans: {len(loans)}")
    with open("data/seed_manifest.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("Seed complete. Manifest written to data/seed_manifest.md")


if __name__ == "__main__":
    main()
