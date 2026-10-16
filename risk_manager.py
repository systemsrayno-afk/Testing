"""Position sizing helper. Educational only; validate instrument rules before trading."""


def position_size(account_size: float, risk_percent: float, entry: float, stop_loss: float, cash_limit: bool = True) -> dict:
    if account_size <= 0 or risk_percent < 0 or entry <= 0 or stop_loss <= 0:
        raise ValueError("Account, entry and stop must be positive; risk cannot be negative.")
    distance = abs(entry - stop_loss)
    if distance <= 0:
        raise ValueError("Entry and stop-loss must be different.")
    budget = account_size * risk_percent / 100
    by_risk = int(budget / distance)
    by_cash = int(account_size / entry) if cash_limit else by_risk
    qty = max(0, min(by_risk, by_cash))
    return {"risk_budget": round(budget, 2), "stop_distance": round(distance, 4), "quantity": qty,
            "planned_risk": round(qty * distance, 2), "cash_required": round(qty * entry, 2)}
