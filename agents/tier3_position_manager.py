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


def evaluate_with_claude(signal: dict, filings: list, news: list, client, memory_text: str = "No resolved trades yet.") -> dict:
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

Historical trading performance:
{memory_text}

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
    try:
        supabase.table("tier3_decisions").insert(decision).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "23505" in str(e):
            print(f"  -> Already decided for {decision['ticker']} today, skipping")
        else:
            print(f"  -> tier3_decisions log failed: {type(e).__name__}: {e}")


def main():
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    date_display = now_ist.strftime("%d %b %Y")
    print(f"Running Tier-3 Position Manager — {today_str}")

    supabase = get_client()

    signals = (
        supabase.table("paper_trades")
        .select("*")
        .eq("signal_date", today_str)
        .eq("status", "OPEN")
        .execute()
        .data
    )
    signals = [s for s in signals if s["direction"] in ("BUY", "SELL")]
    print(f"Signals from Tier-2 today: {len(signals)}")

    if not signals:
        summary = format_summary_message([], [], date_display)
        tg_send(TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL, summary)
        print("No signals today. Summary posted.")
        return

    open_trades = (
        supabase.table("paper_trades")
        .select("id,ticker,status")
        .eq("status", "OPEN")
        .execute()
        .data
    )

    news = (
        supabase.table("news_log")
        .select("title,summary,score")
        .order("fetched_at", desc=True)
        .limit(5)
        .execute()
        .data
    )

    memory_row = (
        supabase.table("trade_memory")
        .select("memory_text")
        .order("computed_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    memory_text = memory_row[0]["memory_text"] if memory_row else "No resolved trades yet."
    print(f"Trade memory loaded: {len(memory_text)} chars")

    approved = []
    rejected_reasons = []

    for signal in signals:
        ticker = signal["ticker"]
        print(f"\n{ticker}:")

        rule_pass, reject_reason = apply_rules(signal, open_trades)
        if not rule_pass:
            print(f"  REJECTED by rules: {reject_reason}")
            log_decision(supabase, {
                "signal_date": today_str,
                "ticker": ticker,
                "paper_trade_id": signal["id"],
                "direction": signal["direction"],
                "confidence_tier2": signal["confidence"],
                "rule_pass": False,
                "approved": False,
                "reject_reason": reject_reason,
                "position_size": 0,
            })
            rejected_reasons.append(reject_reason)
            continue

        ticker_base = ticker.replace(".NS", "")
        filings = (
            supabase.table("filings_log")
            .select("event_type,summary,material_score")
            .eq("symbol", ticker_base)
            .order("published_at", desc=True)
            .limit(3)
            .execute()
            .data
        )

        result = evaluate_with_claude(signal, filings, news, anthropic_client, memory_text=memory_text)
        verdict = result["verdict"]
        tier3_confidence = result["confidence"]
        tier3_reason = result["reason"]
        is_parse_error = result.get("_parse_error", False)

        is_approved = verdict == "APPROVE"
        final_reject_reason = None if is_approved else (
            "claude_parse_error" if is_parse_error else "claude_reject"
        )

        log_decision(supabase, {
            "signal_date": today_str,
            "ticker": ticker,
            "paper_trade_id": signal["id"],
            "direction": signal["direction"],
            "confidence_tier2": signal["confidence"],
            "rule_pass": True,
            "confidence_tier3": None if is_parse_error else tier3_confidence,
            "approved": is_approved,
            "reject_reason": final_reject_reason,
            "position_size": 25000 if is_approved else 0,
        })

        if is_approved:
            print(f"  APPROVED — Tier-3 confidence: {tier3_confidence}/10")
            approved.append(signal)
            msg = format_pick_message(signal, tier3_confidence, tier3_reason)
            tg_send(TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL, msg)
        else:
            print(f"  REJECTED by Claude: {final_reject_reason}")
            rejected_reasons.append(final_reject_reason)

    summary = format_summary_message(approved, rejected_reasons, date_display)
    tg_send(TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL, summary)
    print(f"\nDone. Approved: {len(approved)} | Rejected: {len(rejected_reasons)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: Tier-3 Position Manager crashed — {type(e).__name__}: {e}")
        sys.exit(1)
