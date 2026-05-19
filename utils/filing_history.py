"""Filing history aggregator — reads research_cache for a symbol's past filings."""

import json
from dotenv import load_dotenv
load_dotenv(override=True)

from utils.neon_client import get_neon_connection


def get_filing_history(symbol, limit=30):
    """Return up to `limit` filing summaries, newest-first by filing_date.

    Each dict: {symbol, filing_date, event_desc, summary, created_at}
    """
    conn = get_neon_connection()
    skipped = 0
    results = []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT query_text, response_text, created_at
                   FROM research_cache
                   WHERE symbol = %s
                     AND response_text IS NOT NULL
                     AND response_text != ''
                   ORDER BY (query_text::jsonb ->> 'source_date') DESC NULLS LAST
                   LIMIT %s""",
                (f"{symbol}.NS", limit)
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    for query_text, response_text, created_at in rows:
        try:
            qj = json.loads(query_text)
        except (json.JSONDecodeError, TypeError):
            skipped += 1
            continue

        filing_date = qj.get("source_date")
        if not filing_date:
            skipped += 1
            continue

        raw = qj.get("raw", {})
        event_desc = raw.get("desc") if isinstance(raw, dict) else None

        results.append({
            "symbol": symbol,
            "filing_date": filing_date,
            "event_desc": event_desc,
            "summary": response_text,
            "created_at": created_at.isoformat(),
        })

    if skipped > 0:
        print(f"  [WARN] filing_history skipped {skipped} row(s) for {symbol}"
              " due to malformed query_text")

    return results


def to_brief(history):
    """Compact AI-prompt-ready string from get_filing_history() output."""
    if not history:
        return "No filing history available for this company."

    lines = [f"{history[0]['symbol']} — {len(history)} filings:"]
    for h in history:
        words = (h["summary"] or "").split()
        preview = " ".join(words[:20])
        desc = h["event_desc"] or "(no description)"
        lines.append(f"  {h['filing_date']} — {desc}: {preview}")
    return "\n".join(lines)


if __name__ == "__main__":
    history = get_filing_history("RELIANCE", limit=5)
    print(f"Rows returned: {len(history)}")
    if history:
        for h in history:
            print(f"  {h['filing_date']} | {h['event_desc'][:60] if h['event_desc'] else '(none)'}")
    print()
    print(to_brief(history))
