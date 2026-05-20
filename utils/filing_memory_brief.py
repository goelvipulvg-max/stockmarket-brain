import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv(override=True)
from utils.supabase_client import get_client


def get_filing_memory_brief(symbol_base: str, current_event_type: str) -> str:
    """Return a compact filing-memory brief for symbol_base, grouped by event_type.

    Queries only matured (outcome_10d_status='FILLED') material filings.
    Returns a fixed no-history string when no matured filings exist.
    """
    sb = get_client()

    resp = (
        sb.table("filing_memory")
        .select("event_type,filing_date,alpha_10d")
        .eq("symbol_base", symbol_base)
        .gte("material_score", 6)
        .eq("outcome_10d_status", "FILLED")
        .order("filing_date", desc=True)
        .limit(30)
        .execute()
    )
    rows = resp.data or []

    if not rows:
        return "No matured material filing history for this company."

    n = len(rows)

    # Group by event_type
    by_event = defaultdict(list)
    for row in rows:
        ev = row.get("event_type", "UNKNOWN")
        a = row.get("alpha_10d")
        if a is not None:
            by_event[ev].append(float(a))

    lines = [f"{symbol_base} -- Filing Memory ({n} material filings, last 30):"]

    for ev in sorted(by_event.keys()):
        alphas = by_event[ev]
        count = len(alphas)
        avg = round(sum(alphas) / count, 1)
        wins = sum(1 for a in alphas if a > 3)
        lines.append(f"  {ev}: {count} events, avg {avg:+.1f}% alpha(10d), {wins}/{count} positive")

    # Most recent matching row for current_event_type
    for row in rows:
        if row.get("event_type") == current_event_type:
            a = row.get("alpha_10d")
            if a is not None:
                fd = row.get("filing_date", "?")
                lines.append(f"  Most recent {current_event_type}: {fd} -> {float(a):+.1f}% alpha in 10d")
            break

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python utils/filing_memory_brief.py <symbol_base> <event_type>")
        print("Example: python utils/filing_memory_brief.py RELIANCE dividend")
        sys.exit(1)

    symbol = sys.argv[1]
    event = sys.argv[2]
    print(get_filing_memory_brief(symbol, event))
