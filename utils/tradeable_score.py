"""Loop 5 — Tradeable Score Gate: filters filings by event_type materiality."""

TRADEABLE_SCORES = {
    # ─── Earnings & Results ───
    "RESULTS":             9,

    # ─── Corporate Actions ───
    "DIVIDEND":            8,
    "BONUS":               7,
    "SPLIT":               6,
    "BUYBACK":             7,

    # ─── Strategic Events ───
    "MERGER_ACQUISITION":  7,
    "ACQUISITION":         5,
    "DIVESTMENT":          5,
    "FUND_RAISE":          6,
    "CONTRACT_WIN":        7,

    # ─── Governance & Risk ───
    "INSIDER_TRADING":     7,
    "BULK_DEAL":           8,
    "MANAGEMENT_CHANGE":   6,
    "LEGAL":               6,   # legal action often = exit signal
    "CREDIT_RATING":       5,
    "RATING_ACTION":       5,   # same event class as CREDIT_RATING — keep scores equal

    # ─── Routine / Low Impact ───
    "BOARD_MEETING":       5,
    "AGM":                 3,
    "AUDIT_REPORT":        3,
    "ALLOTMENT":           3,
    "ESOP":                3,
    "DISCLOSURE":          3,
    "POSTAL_BALLOT":       3,
    "ANNUAL_REPORT":       3,
    "VOTING_RESULTS":      3,
    "INVESTOR_PRES":       2,
    "NEWSPAPER_PUB":       1,
    "GENERAL_UPDATE":      1,
    "OTHER":               2,   # explicit default for unmatched
}

MINIMUM_TRADEABLE_SCORE = 6


def get_tradeable_score(event_type: str) -> int:
    return TRADEABLE_SCORES.get(event_type.upper(), 3)


def is_tradeable(event_type: str) -> bool:
    score = get_tradeable_score(event_type)
    return score >= MINIMUM_TRADEABLE_SCORE
