import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv(override=True)
from utils.supabase_client import get_client
from utils.telegram_client import send_message as tg_send

IST = ZoneInfo("Asia/Kolkata")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_TIER3_CHANNEL = os.getenv("TELEGRAM_TIER3_CHANNEL", "").strip()

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)


def apply_rules(signal: dict, open_trades: list) -> tuple:
    for trade in open_trades:
        if trade["ticker"] == signal["ticker"] and trade["id"] != signal["id"]:
            return False, "duplicate_open_position"
    if signal["confidence"] < 8:
        return False, "confidence_below_threshold"
    rsi = signal.get("rsi") or 50.0
    if signal["direction"] == "BUY" and rsi > 80:
        return False, "extreme_rsi"
    if signal["direction"] == "SELL" and rsi < 20:
        return False, "extreme_rsi"
    return True, None


def evaluate_with_claude(signal: dict, filings: list, news: list, client) -> dict:
    ticker_base = signal["ticker"].replace(".NS", "")

    filings_text = "\n".join(
        f"- [{f['event_type']}] {f['summary']} (score: {f['material_score']})"
        for f in filings
    ) if filings else "None"

    news_text = "\n".join(
        f"- {n['title']}: {n['summary']} (score: {n['score']})"
        for n in news
    ) if news else "None"

    prompt = f"""You are a position manager for an NSE swing trading system.

Signal from Tier-2:
- Ticker: {signal['ticker']}
- Direction: {signal['direction']}
- Entry: ₹{signal['entry_price']} | Target: ₹{signal['target_price']} | SL: ₹{signal['stop_loss']}
- Tier-2 Confidence: {signal['confidence']}/10
- Reason: {signal['reason']}
- RSI: {signal['rsi']} | MACD: {signal['macd']}

Recent filings for {ticker_base} (last 3):
{filings_text}

Recent market news (general, last 5):
{news_text}

Respond ONLY in this JSON format:
{{"verdict": "APPROVE" or "REJECT", "confidence": <int 1-10>, "reason": "<one line>"}}

APPROVE if the signal is supported or not contradicted by filings/news.
REJECT only if there is a specific negative catalyst (bad earnings, regulatory action, major negative news)."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {"verdict": "REJECT", "confidence": 0, "reason": "parse_error", "_parse_error": True}


def format_pick_message(signal: dict, tier3_confidence: int, tier3_reason: str) -> str:
    direction = signal["direction"]
    arrow = "\U0001f4c8" if direction == "BUY" else "\U0001f4c9"
    return (
        f'✅ <b>TIER-3 APPROVED</b> — <b>{signal["ticker"]}</b>\n\n'
        f'{arrow} Direction: {direction}\n'
        f'\U0001f4b0 Entry: ₹{signal["entry_price"]:.2f} | Target: ₹{signal["target_price"]:.2f} | SL: ₹{signal["stop_loss"]:.2f}\n'
        f'\U0001f3af Tier-2 Confidence: {signal["confidence"]}/10 | Tier-3 Confidence: {tier3_confidence}/10\n'
        f'\U0001f4b5 Position Size: ₹25,000\n\n'
        f'\U0001f4dd Tier-2: {signal["reason"]}\n'
        f'\U0001f50d Tier-3: {tier3_reason}'
    )


def format_summary_message(approved: list, rejected_reasons: list, date_str: str) -> str:
    total_capital = len(approved) * 25000
    reason_counts = Counter(rejected_reasons)
    breakdown = "\n".join(
        f"• {count} × {reason}" for reason, count in reason_counts.items()
    )
    msg = (
        f'\U0001f4cb <b>Tier-3 Daily Summary — {date_str}</b>\n\n'
        f'✅ Approved: {len(approved)}  |  ❌ Rejected: {len(rejected_reasons)}\n'
        f'\U0001f4b0 Total capital to deploy today: ₹{total_capital:,}'
    )
    if breakdown:
        msg += f'\n\nRejected breakdown:\n{breakdown}'
    return msg


def log_decision(supabase, decision: dict) -> None:
    raise NotImplementedError


def main():
    raise NotImplementedError


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: Tier-3 Position Manager crashed — {type(e).__name__}: {e}")
        sys.exit(1)
