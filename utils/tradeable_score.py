"""Loop 5 — Tradeable Score Gate: filters filings by event_type materiality."""

TRADEABLE_SCORES = {
    "EARNINGS_RESULT":     9,
    "DIVIDEND":            8,
    "BULK_DEAL":           8,
    "INSIDER_TRADING":     7,
    "MERGER_ACQUISITION":  7,
    "BUYBACK":             7,
    "BOARD_MEETING":       5,
    "AGM":                 3,
    "INVESTOR_PRES":       2,
    "NEWSPAPER_PUB":       1,
    "GENERAL_UPDATE":      1,
}

MINIMUM_TRADEABLE_SCORE = 6


def get_tradeable_score(event_type: str) -> int:
    return TRADEABLE_SCORES.get(event_type.upper(), 3)


def is_tradeable(event_type: str) -> bool:
    score = get_tradeable_score(event_type)
    return score >= MINIMUM_TRADEABLE_SCORE
