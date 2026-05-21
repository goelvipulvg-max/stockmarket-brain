"""Pattern insights retrieval -- for injection into Tier-2F + Phase 6 + Phase 7 prompts.

Reads aggregated patterns from Supabase pattern_insights table (populated by
agents/memory_seed.py extract_initial_patterns()). Returns top N active patterns
matching event_type OR sector, ordered by confidence (HIGH > MEDIUM > LOW) then
sample_size desc.
"""
from typing import List, Dict
from utils.supabase_client import get_client

sb = get_client()


def get_relevant_patterns(event_type: str, sector: str, limit: int = 3) -> List[Dict]:
    """Return top `limit` active pattern_insights rows matching event_type OR sector.

    Args:
        event_type: e.g. "RESULTS", "M_AND_A", "DIVIDEND"
        sector: e.g. "Industrials", "Financial Services"
        limit: max rows to return (default 3)

    Returns:
        List of dicts with pattern_insights columns (pattern_key, sector, event_type,
        sample_size, win_rate, avg_outcome_score, confidence, insight_text).
        Empty list if no patterns match or query fails.
    """
    try:
        # Normalize to lowercase -- pattern_insights stores lowercase event_type and sector
        # (seeded from event_outcomes via memory_seed.py extract_initial_patterns).
        # Tier-2F production passes uppercase event_type ("DIVIDEND") and TitleCase sector ("Industrials").
        ev = event_type.lower() if event_type else ""
        sec = sector.lower() if sector else ""
        rows = sb.table("pattern_insights").select("*") \
            .eq("active", True) \
            .or_(f"event_type.eq.{ev},sector.eq.{sec}") \
            .order("confidence", desc=True) \
            .order("sample_size", desc=True) \
            .limit(limit) \
            .execute().data
        return rows or []
    except Exception as e:
        print(f"[pattern_insights_retriever] Query failed: {e} -- returning empty list")
        return []   # fail-open: missing patterns don't block trade
