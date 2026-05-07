import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv(override=True)
from utils.supabase_client import get_client

IST = ZoneInfo("Asia/Kolkata")
MIN_SAMPLES = 3


def compute_stats(trades: list) -> dict:
    by_confidence = defaultdict(lambda: {"wins": 0, "total": 0})
    by_ticker_all = defaultdict(lambda: {"wins": 0, "total": 0})
    by_direction = defaultdict(lambda: {"wins": 0, "total": 0})

    for t in trades:
        is_win = t["status"] == "TARGET_HIT"
        conf = t["confidence_tier2"]
        by_confidence[conf]["total"] += 1
        if is_win:
            by_confidence[conf]["wins"] += 1

        ticker = t["ticker"]
        by_ticker_all[ticker]["total"] += 1
        if is_win:
            by_ticker_all[ticker]["wins"] += 1

        direction = t["direction"]
        by_direction[direction]["total"] += 1
        if is_win:
            by_direction[direction]["wins"] += 1

    by_ticker = {k: v for k, v in by_ticker_all.items() if v["total"] >= 2}

    return {
        "by_confidence": dict(by_confidence),
        "by_ticker": by_ticker,
        "by_direction": dict(by_direction),
        "total_resolved": len(trades),
    }


def format_memory_text(stats: dict, date_str: str) -> str:
    if stats["total_resolved"] == 0:
        return "No resolved trades yet."

    lines = [f"=== Historical Performance (as of {date_str}) ===", ""]

    lines.append("By confidence:")
    for conf in sorted(stats["by_confidence"]):
        s = stats["by_confidence"][conf]
        if s["total"] >= MIN_SAMPLES:
            pct = round(s["wins"] / s["total"] * 100)
            lines.append(f"  Conf {conf}: {s['wins']}W/{s['total']}T = {pct}%")
        else:
            lines.append(f"  Conf {conf}: {s['total']}T — insufficient data")

    if stats["by_ticker"]:
        lines.append("")
        lines.append("By ticker (min 2 trades):")
        for ticker in sorted(stats["by_ticker"]):
            s = stats["by_ticker"][ticker]
            pct = round(s["wins"] / s["total"] * 100)
            lines.append(f"  {ticker}: {s['wins']}W/{s['total']}T = {pct}%")

    if stats["by_direction"]:
        lines.append("")
        lines.append("By direction:")
        for direction in sorted(stats["by_direction"]):
            s = stats["by_direction"][direction]
            if s["total"] >= MIN_SAMPLES:
                pct = round(s["wins"] / s["total"] * 100)
                lines.append(f"  {direction}: {s['wins']}W/{s['total']}T = {pct}%")
            else:
                lines.append(f"  {direction}: {s['total']}T — insufficient data")

    return "\n".join(lines)


def main():
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    print(f"Running Tier-4 Memory Manager — {today_str}")

    supabase = get_client()

    rows = (
        supabase.table("tier3_decisions")
        .select("confidence_tier2,ticker,direction,paper_trades(status)")
        .eq("approved", True)
        .in_("paper_trades.status", ["TARGET_HIT", "SL_HIT"])
        .execute()
        .data
    )

    trades = [
        {
            "confidence_tier2": r["confidence_tier2"],
            "ticker": r["ticker"],
            "direction": r["direction"],
            "status": r["paper_trades"]["status"],
        }
        for r in rows
        if r.get("paper_trades") and r["paper_trades"].get("status") in ("TARGET_HIT", "SL_HIT")
    ]

    print(f"Resolved approved trades found: {len(trades)}")

    stats = compute_stats(trades)
    memory_text = format_memory_text(stats, today_str)

    supabase.table("trade_memory").upsert(
        {
            "computed_date": today_str,
            "total_resolved": stats["total_resolved"],
            "memory_text": memory_text,
        },
        on_conflict="computed_date",
    ).execute()

    print(f"trade_memory upserted for {today_str} ({stats['total_resolved']} resolved trades)")
    print(memory_text)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: Tier-4 Memory Manager crashed — {type(e).__name__}: {e}")
        sys.exit(1)
