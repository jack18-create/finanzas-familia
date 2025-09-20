from db import list_budgets, sum_contribs, sum_contribs_by_user, add_contribution
import json, math

def fmt_clp(n: int) -> str:
    n = int(n)
    s = f"{n:,}".replace(",", ".")
    return f"${s}"

def _remaining_for_user_row(row, user):
    budget_id, template_key, name, ctype, owner, limit_total, shares_json = row
    if ctype == "shared":
        shares = json.loads(shares_json or "{}")
        share = float(shares.get(user, 0.0))
        target_user = int(round(limit_total * share))
        done_by_user = sum_contribs_by_user(budget_id, user)
        remaining = max(0, target_user - done_by_user)
    else:
        if owner != user:
            return 0
        total_done = sum_contribs_by_user(budget_id, user)
        remaining = max(0, int(limit_total) - int(total_done))
    return remaining

def proportional_allocate(user: str, amount: int, month: str):
    rows = list_budgets(month)
    candidates = []
    for r in rows:
        rem = _remaining_for_user_row(r, user)
        if rem > 0:
            candidates.append((r, rem))
    total_need = sum(rem for _, rem in candidates)
    allocs = []
    if total_need == 0 or amount <= 0:
        return allocs, int(amount)

    provisional = []
    for r, rem in candidates:
        weight = rem / total_need
        provisional_amt = int(math.floor(amount * weight))
        provisional.append((r, min(provisional_amt, rem)))

    assigned = sum(a for _, a in provisional)
    leftover = amount - assigned

    i = 0
    while leftover > 0 and i < len(provisional):
        r, already = provisional[i]
        _, rem2 = next(item for item in candidates if item[0] == r)
        if already < rem2:
            provisional[i] = (r, already + 1)
            leftover -= 1
        i = (i + 1) % len(provisional)

    for r, amt in provisional:
        if amt <= 0:
            continue
        add_contribution(r[0], user, int(amt))
        allocs.append({
            "budget_id": r[0],
            "name": r[2],
            "type": r[3],
            "owner": r[4],
            "limit_total": r[5],
            "allocated": int(amt)
        })

    return allocs, int(leftover)

def progress_of_row(row):
    budget_id, template_key, name, ctype, owner, limit_total, shares_json = row
    total = sum_contribs(budget_id)
    pct = min(1.0, (total / limit_total) if limit_total else 0.0)
    return total, pct, (total >= limit_total)