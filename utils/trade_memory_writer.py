"""Phase 7 capture-half: write LIVE_TRADE rows to SUPABASE trade_memory_v2.

Two halves of the capture path (master plan §9.1 + §9.2):
  - build_live_trade_memory_row(...) : PURE row builder (no I/O, unit-tested).
  - insert_live_trade_memory(...)    : signal-time insert (§9.1), NON-FATAL.
  - update_trade_memory_outcome(...) : close-time outcome backfill (§9.2), NON-FATAL.

Both DB functions mirror tier2_fundamental._insert_disagreement's fail-open
contract: a trade_memory_v2 write failure logs and continues, NEVER raises, so
it can never block live signal generation, the paper_trades insert, capital
deploy, or a trade close. trade_memory_v2 lives in SUPABASE.

Match key: paper_trades.id (int) <-> trade_memory_v2.paper_trade_id.
pattern_tags is a Postgres text[] (pass a Python list); full_context is jsonb
(pass a dict) -- both consistent with agents/memory_seed.py's seed rows.
"""


def _tag_key(value) -> str:
    """Seed-mirroring tag slug: 'Consumer Defensive' -> 'consumer_defensive'.

    None/empty -> 'unknown' (pure; never raises). Matches agents/memory_seed.py
    sector_key = (sector or "unknown").replace(" ", "_").lower().
    """
    return (value or "unknown").replace(" ", "_").lower()


def _reasoning(output) -> str | None:
    """Extract .reasoning from a Haiku/DeepSeek output dict; None-safe.

    output may be None (SOLO fallback mode) or lack the key -> None.
    """
    if not isinstance(output, dict):
        return None
    return output.get("reasoning")


def build_live_trade_memory_row(trade_id, haiku_output, flash_output, sector,
                                market_cap_cr, nifty_mood, symbol_base, event_type) -> dict:
    """Build the trade_memory_v2 insert dict for a freshly-opened LIVE trade (§9.1).

    PURE: no I/O. outcome='OPEN' with NULL pnl_pct/holding_days at signal time;
    the close-time backfill (§9.2) fills those later, matched on paper_trade_id.
    pattern_tags mirrors the seed format but tags the live source. full_context
    carries both agents' full outputs (None-safe for SOLO fallback modes).
    """
    return {
        "source_type": "LIVE_TRADE",
        "symbol_base": symbol_base,
        "event_type": event_type,
        "sector": sector,
        "market_cap_cr": market_cap_cr,
        "nifty_mood": nifty_mood,
        "outcome": "OPEN",
        "pnl_pct": None,
        "holding_days": None,
        "paper_trade_id": trade_id,
        "haiku_reasoning": _reasoning(haiku_output),
        "deepseek_reasoning": _reasoning(flash_output),
        "pattern_tags": [
            f"event_{_tag_key(event_type)}",
            f"sector_{_tag_key(sector)}",
            "source_live_trade",
        ],
        "full_context": {
            "haiku": haiku_output,
            "flash": flash_output,
        },
    }


def insert_live_trade_memory(sb, row, dry_run: bool = False) -> int | None:
    """Insert a LIVE_TRADE row into SUPABASE trade_memory_v2 (§9.1). NON-FATAL.

    Returns the new row id on success, None on dry-run or any failure. A failure
    here must NEVER propagate -- the paper_trade and capital deploy are already
    committed by the caller, and signal generation must not be blocked.
    """
    if dry_run:
        print(f"  [DRY-RUN] would insert trade_memory_v2 LIVE_TRADE row "
              f"for paper_trade_id={row.get('paper_trade_id')}")
        return None
    try:
        inserted = sb.table("trade_memory_v2").insert(row).execute().data[0]
        print(f"[trade_memory] LIVE_TRADE row id={inserted['id']} "
              f"paper_trade_id={row.get('paper_trade_id')} captured")
        return inserted["id"]
    except Exception as e:
        print(f"[trade_memory] insert failed: {e} -- continuing "
              f"(capture non-critical; trade already recorded)")
        return None


def update_trade_memory_outcome(sb, paper_trade_id, outcome, pnl_pct,
                                holding_days, dry_run: bool = False) -> int:
    """Backfill outcome onto the matching LIVE_TRADE row at close (§9.2). NON-FATAL.

    Matches on paper_trade_id. Returns the number of rows updated (0 if none /
    dry-run / failure). A failure here must NEVER propagate -- the trade close,
    pnl persistence, and capital release are already done by the caller.
    """
    if dry_run:
        print(f"  [DRY-RUN] would update trade_memory_v2 outcome for "
              f"paper_trade_id={paper_trade_id} -> {outcome} pnl_pct={pnl_pct} "
              f"holding_days={holding_days}")
        return 0
    try:
        updated = sb.table("trade_memory_v2").update({
            "outcome": outcome,
            "pnl_pct": pnl_pct,
            "holding_days": holding_days,
        }).eq("paper_trade_id", paper_trade_id).execute().data
        n = len(updated)
        if n == 0:
            print(f"[trade_memory] no LIVE_TRADE row for paper_trade_id="
                  f"{paper_trade_id} (pre-capture trade?) -- nothing to backfill")
        else:
            print(f"[trade_memory] backfilled {n} row(s) for paper_trade_id="
                  f"{paper_trade_id} -> {outcome} pnl_pct={pnl_pct} holding_days={holding_days}")
        return n
    except Exception as e:
        print(f"[trade_memory] outcome update failed: {e} -- continuing "
              f"(backfill non-critical; trade already closed)")
        return 0
