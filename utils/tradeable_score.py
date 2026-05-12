"""Loop 5 — Tradeable Score Gate: filters filings by event_type materiality."""

TRADEABLE_SCORES = {
    # ─── Earnings & Results ───
    "EARNINGS_RESULT":     9,
    "RESULTS":             9,   # alias used by DeepSeek classifier

    # ─── Corporate Actions ───
    "DIVIDEND":            8,
    "BONUS":               7,
    "SPLIT":               6,
    "BUYBACK":             7,

    # ─── Strategic Events ───
    "MERGER_ACQUISITION":  7,
    "FUND_RAISE":          6,
    "CONTRACT_WIN":        7,

    # ─── Governance & Risk ───
    "INSIDER_TRADING":     7,
    "BULK_DEAL":           8,
    "MANAGEMENT_CHANGE":   6,
    "LEGAL":               6,   # legal action often = exit signal

    # ─── Routine / Low Impact ───
    "BOARD_MEETING":       5,
    "AGM":                 3,
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
