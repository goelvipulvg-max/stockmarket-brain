"""Pre-Open Alert — sends top 5 gap-trade candidates from after_hours_queue to Telegram."""

import os
from datetime import date

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.telegram_client import send_message
from utils.neon_client import get_neon_connection, query

BOT = os.getenv("TELEGRAM_BOT_TOKEN")
TRADES_CHANNEL = os.getenv("TELEGRAM_TRADES_CHANNEL_ID")

EMOJI_MAP = {
    "RESULTS": "📊", "DIVIDEND": "💰", "MERGER_ACQUISITION": "🤝",
    "BONUS": "🎁", "SPLIT": "✂️", "BUYBACK": "🔄", "CONTRACT_WIN": "🏆",
    "INSIDER_TRADING": "🔍", "LEGAL": "⚖️", "FUND_RAISE": "💵",
    "MANAGEMENT_CHANGE": "👤", "BOARD_MEETING": "📋", "OTHER": "📌",
}

CONFIDENCE_MAP = {
    "HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴",
}


def fetch_pending():
    return query("""
        SELECT * FROM after_hours_queue
        WHERE status = 'PENDING'
        ORDER BY
            CASE confidence
                WHEN 'HIGH' THEN 3
                WHEN 'MEDIUM' THEN 2
                ELSE 1
            END DESC,
            tradeable_score DESC,
            ABS(expected_gap_pct) DESC
        LIMIT 5
    """)


def format_watchlist(items):
    today = date.today().strftime("%d-%b-%Y")
    lines = [f"⚡ <b>PRE-OPEN WATCHLIST — {today}</b>\n"]

    for idx, row in enumerate(items, 1):
        emoji = EMOJI_MAP.get(row["event_type"], "📌")
        conf_dot = CONFIDENCE_MAP.get(row["confidence"], "⚪")
        direction = "🟩" if (row["expected_gap_pct"] or 0) >= 0 else "🟥"
        action = row.get("recommended_action", "WATCH")

        lines.append(
            f"{idx}. {emoji} <b>{row['symbol']}</b> — {row['event_type']}\n"
            f"   {direction} Gap: {row['expected_gap_pct']}% | "
            f"{conf_dot} {row['confidence']} | "
            f"Score: {row['tradeable_score']}/10\n"
            f"   🎯 Entry: ₹{row['entry_price_low']}–₹{row['entry_price_high']} | "
            f"Target: ₹{row['target_price']} | "
            f"SL: ₹{row['stop_loss']}\n"
            f"   📋 {action}"
        )

    lines.append(f"\n🧠 StockMarket-Brain After Hours Pipeline")
    return "\n".join(lines)


def mark_alerted(items):
    conn = get_neon_connection()
    try:
        ids = [row["id"] for row in items]
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE after_hours_queue
                SET status = 'ALERTED', telegram_sent = TRUE
                WHERE id = ANY(%s)
            """, (ids,))
    finally:
        conn.close()


def main():
    print("\n" + "="*50)
    print("  Pre-Open Alert")
    print("="*50)

    items = fetch_pending()
    if not items:
        print("No pending after-hours items. Exiting.")
        return

    print(f"  Found {len(items)} pending item(s)")

    text = format_watchlist(items)
    print(text)

    send_message(BOT, TRADES_CHANNEL, text)
    print("  Sent to Telegram!")

    mark_alerted(items)
    print(f"  Marked {len(items)} as ALERTED")

    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
