"""Tier-2F: Fundamental analysis signal generator.

10-step pipeline per filing. First module to make real Haiku + DeepSeek
API calls in production with Tier-2F-specific prompts. Manual entrypoint:
  python -m agents.tier2_fundamental --filing-id <N> [--dry-run]

Production trigger comes from Tier-0F poller (Phase 5 Batch B).
"""

import os
import json
import argparse
from pathlib import Path

from dotenv import load_dotenv

from utils.fno_ban_list import is_in_ban
from utils.neon_fundamentals import get_fundamentals
from utils.yfinance_chart import get_chart_snapshot
from utils.filing_memory_brief import get_filing_memory_brief
from utils.pattern_insights_retriever import get_relevant_patterns
from utils.ai_consensus import run_analyst, run_verifier, determine_consensus
from utils.position_sizer import calculate_position_size
from utils.capital_ledger import get_current_portfolio, deploy_capital
from utils.tiered_target_generator import generate_targets
from utils.telegram_client import send_message
from utils.supabase_client import get_client

load_dotenv()

REQUIRED_ENVS = [
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "NEON_CONNECTION_STRING",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_TIER3_CHANNEL",
]
missing = [k for k in REQUIRED_ENVS if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing required env vars: {missing}")

sb = get_client()

# Tier-2F prompt templates loaded at module level -- passed as prompt_template= to
# run_analyst() / run_verifier() (overrides Phase 3 defaults from ai_consensus.py).
_TIER2F_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
TIER2F_ANALYST_PROMPT = (_TIER2F_PROMPTS_DIR / "tier2f_analyst_v1.txt").read_text(encoding="utf-8")
TIER2F_VERIFIER_PROMPT = (_TIER2F_PROMPTS_DIR / "tier2f_verifier_v1.txt").read_text(encoding="utf-8")

# Module constants
HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEEPSEEK_MODEL = "deepseek-v4-flash"
CONFIDENCE_FLOOR = 50
CONFIDENCE_CEILING = 85
SOLO_MODE_HAIRCUT = 10
AGREEMENT_THRESHOLD = 70
AVG_CONFIDENCE_FLOOR = 65
HORIZON_TO_DAYS = {"SHORT": 3, "MEDIUM": 10, "LONG": 30}

# Test-mode bypass for stage 4 (NIFTY mood) -- production must NEVER set this.
TIER2F_TEST_MODE = os.getenv("TIER2F_TEST_MODE", "false").lower() == "true"


def process_filing(filing_id: int, dry_run: bool = False) -> dict:
    """10-step pipeline: context gathering -> AI consensus -> sizing -> trade insert.

    Args:
        filing_id: filings_log.id row to process.
        dry_run: if True, runs full pipeline but exits before DB insert (step 9 return).

    Returns:
        dict with keys: trade_id / skip + diagnostic fields.
    """
    # --- Load filing ---
    filing_rows = sb.table("filings_log").select("*").eq("id", filing_id).execute().data
    if not filing_rows:
        return {"skip": "filing_not_found", "filing_id": filing_id}
    filing = filing_rows[0]
    symbol = filing["symbol"]

    # --- Step 1: F&O ban check ---
    banned = is_in_ban(symbol)
    print(f"[STAGE 1: fno_ban_check] symbol={symbol}, banned={banned}")
    if banned:
        return {"skip": "fno_ban", "symbol": symbol}

    # --- Step 2: Neon company_profiles lookup ---
    fundamentals = get_fundamentals(symbol)
    print(f"[STAGE 2: fundamentals] symbol={symbol}, found={fundamentals is not None}")
    if fundamentals is None:
        return {"skip": "not_nifty500", "symbol": symbol}

    # --- Step 3: Chart snapshot ---
    try:
        chart = get_chart_snapshot(symbol + ".NS")
    except Exception as e:
        return {"skip": "chart_unavailable", "symbol": symbol, "error": str(e)}
    if not chart or not chart.get("last_close"):
        return {"skip": "chart_unavailable", "symbol": symbol, "error": "empty or missing last_close"}
    print(f"[STAGE 3: chart] symbol={symbol}, last_close={chart.get('last_close')}, trend={chart.get('trend')}")

    # --- Step 4: NIFTY mood ---
    try:
        nifty_chart = get_chart_snapshot("^NSEI")
        nifty_close = nifty_chart["last_close"]
        nifty_sma50 = nifty_chart["sma_50"]
        nifty_trend = nifty_chart["trend"]
        if nifty_close < nifty_sma50 and nifty_trend == "DOWNTREND":
            nifty_mood = "BEARISH"
        elif nifty_close > nifty_sma50 and nifty_trend == "UPTREND":
            nifty_mood = "BULLISH"
        else:
            nifty_mood = "NEUTRAL"
    except Exception as e:
        print(f"[STAGE 4: nifty_mood] ^NSEI chart failed: {e} -- defaulting to NEUTRAL")
        nifty_mood = "NEUTRAL"
    print(f"[STAGE 4: nifty_mood] mood={nifty_mood}")
    if nifty_mood == "BEARISH":
        if not TIER2F_TEST_MODE:
            return {"skip": "nifty_bearish", "nifty_mood": nifty_mood}
        print(f"[STAGE 4: nifty_mood] mood=BEARISH but TIER2F_TEST_MODE=true -- BYPASSING skip for testing")

    # --- Step 5a: Relevant patterns from pattern_insights ---
    patterns = get_relevant_patterns(filing["event_type"], fundamentals["sector"], limit=3)
    print(f"[STAGE 5a: patterns] event_type={filing['event_type']}, sector={fundamentals['sector']}, found={len(patterns)}")

    # --- Step 5b: Filing memory brief ---
    memory = get_filing_memory_brief(symbol_base=symbol, current_event_type=filing["event_type"])
    print(f"[STAGE 5b: memory_brief] symbol={symbol}, len={len(memory)} chars")

    # --- Build context dict ---
    context = {
        "symbol": symbol,
        "sector": fundamentals["sector"],
        "market_cap_cr": fundamentals.get("market_cap_cr"),
        "business_summary": fundamentals.get("business_summary"),
        "chart_snapshot": {
            "last_close": chart["last_close"],
            "rsi_14": chart["rsi_14"],
            "macd": chart["macd"],
            "macd_signal": chart["macd_signal"],
            "macd_hist": chart["macd_hist"],
            "trend": chart["trend"],
            "support": chart["support"],
            "resistance": chart["resistance"],
        },
        "nifty_mood": nifty_mood,
        "relevant_patterns": patterns,
        "filing_memory_brief": memory,
        "filing": filing,
    }

    # ==================================================================
    # Steps 6-8: AI consensus (Haiku analyst + DeepSeek verifier)
    # ==================================================================

    fallback_mode = None
    haiku_output = None
    flash_output = None

    # --- Step 6: Haiku analyst with Tier-2F prompt ---
    try:
        haiku_output = run_analyst(context, prompt_template=TIER2F_ANALYST_PROMPT)
    except Exception as e:
        print(f"[STAGE 6: haiku] failed: {e} -- entering SOLO_DEEPSEEK fallback")
        fallback_mode = "SOLO_DEEPSEEK"

    if haiku_output:
        print(f"[STAGE 6: haiku] tradeable={haiku_output.get('tradeable')}, bias={haiku_output.get('directional_bias')}, conf={haiku_output.get('confidence')}")

    # Early-skip on Haiku tradeable=False
    if haiku_output and not haiku_output.get("tradeable"):
        return {"skip": "haiku_not_tradeable", "haiku": haiku_output, "fallback_mode": None}

    # --- Step 7: DeepSeek verifier with Tier-2F prompt ---
    try:
        flash_output = run_verifier(context, haiku_output, prompt_template=TIER2F_VERIFIER_PROMPT)
    except Exception as e:
        print(f"[STAGE 7: flash] failed: {e} -- entering {'SOLO_HAIKU' if haiku_output else 'BOTH_DOWN'} fallback")
        fallback_mode = "SOLO_HAIKU" if haiku_output else "BOTH_DOWN"

    if flash_output:
        print(f"[STAGE 7: flash] verdict={flash_output.get('verdict')}, agreement={flash_output.get('agreement_score')}, bias={flash_output.get('my_directional_bias')}, conf={flash_output.get('my_confidence')}")

    if fallback_mode == "BOTH_DOWN":
        return {"skip": "both_apis_down"}

    # --- Step 8: Consensus or solo decision ---
    if fallback_mode is None:
        action, reason = determine_consensus(haiku_output, flash_output)
    elif fallback_mode == "SOLO_DEEPSEEK":
        haircut_conf = flash_output["my_confidence"] - SOLO_MODE_HAIRCUT
        action = "PROCEED" if haircut_conf >= AVG_CONFIDENCE_FLOOR else "SKIP"
        reason = f"Solo DeepSeek (haircut applied), conf={haircut_conf}"
    elif fallback_mode == "SOLO_HAIKU":
        haircut_conf = haiku_output["confidence"] - SOLO_MODE_HAIRCUT
        action = "PROCEED" if haircut_conf >= AVG_CONFIDENCE_FLOOR else "SKIP"
        reason = f"Solo Haiku (haircut applied), conf={haircut_conf}"

    print(f"[STAGE 8: consensus] action={action}, reason={reason}, fallback_mode={fallback_mode}")

    if action == "SKIP":
        if fallback_mode is None and flash_output.get("verdict") == "CHALLENGE":
            _insert_disagreement(filing, haiku_output, flash_output, reason)
        return {
            "skip": reason,
            "haiku": haiku_output,
            "flash": flash_output,
            "fallback_mode": fallback_mode,
        }

    # ==================================================================
    # Steps 9-10: Sizing + paper_trades insert
    # ==================================================================

    # --- Determine direction + advisory stop-loss ---
    if fallback_mode == "SOLO_DEEPSEEK":
        direction_bias = flash_output["my_directional_bias"]
        analyst_sl_pct = 5.0
    else:
        direction_bias = haiku_output["directional_bias"]
        analyst_sl_pct = haiku_output.get("stop_loss_pct", 5.0)

    if direction_bias == "NEUTRAL":
        return {"skip": "neutral_bias_no_trade"}
    direction = "BUY" if direction_bias == "BULLISH" else "SELL"

    # --- Compute average confidence + conviction ---
    if fallback_mode is None:
        avg_conf = (haiku_output["confidence"] + flash_output["my_confidence"]) / 2
    elif fallback_mode == "SOLO_DEEPSEEK":
        avg_conf = flash_output["my_confidence"] - SOLO_MODE_HAIRCUT
    else:   # SOLO_HAIKU
        avg_conf = haiku_output["confidence"] - SOLO_MODE_HAIRCUT

    conviction = _confidence_to_conviction(avg_conf)

    # --- Entry from chart ---
    entry = context["chart_snapshot"]["last_close"]

    # --- Generate canonical targets + stop_loss ---
    targets = generate_targets(entry_price=entry, direction=direction, conviction=conviction)
    t1, t2, t3 = targets["t1"], targets["t2"], targets["t3"]
    t4 = targets.get("t4")       # only present when conviction="HIGH"; goes into raw_signal JSONB
    sl = targets["stop_loss"]

    print(f"[STAGE 9: sizing] entry={entry:.2f}, sl={sl:.2f}, t1={t1:.2f}, t2={t2:.2f}, t3={t3:.2f}, conviction={conviction}, avg_conf={avg_conf:.0f}")

    # --- Position sizing ---
    portfolio = get_current_portfolio()
    qty, size_rs = calculate_position_size(
        total_equity=portfolio["total_equity"],
        cash_available=portfolio["cash_available"],
        entry_price=entry,
        stop_loss_price=sl,
    )
    if qty <= 0:
        return {"skip": "insufficient_cash_or_risk_too_wide", "portfolio": portfolio}

    print(f"[STAGE 9: sizing] qty={qty}, size_rs={size_rs}, cash_avail={portfolio['cash_available']}")

    # --- DRY-RUN exit point ---
    if dry_run:
        return {
            "dry_run": True,
            "would_trade": {
                "symbol": symbol,
                "direction": direction,
                "entry": round(entry, 2),
                "sl": round(sl, 2),
                "t1": round(t1, 2),
                "t2": round(t2, 2),
                "t3": round(t3, 2),
                "t4": round(t4, 2) if t4 else None,
                "qty": qty,
                "size_rs": size_rs,
                "conviction": conviction,
                "avg_conf": avg_conf,
                "fallback_mode": fallback_mode,
                "analyst_sl_pct_advisory": analyst_sl_pct,
                "haiku": haiku_output,
                "flash": flash_output,
            },
        }

    # --- Step 10: paper_trades insert ---
    horizon = haiku_output.get("horizon", "MEDIUM") if haiku_output else "MEDIUM"
    trade_payload = {
        "ticker": symbol + ".NS",
        "source": "TIER2F",
        "filing_id": filing_id,
        "direction": direction,
        "entry_price": round(entry, 2),
        "stop_loss": round(sl, 2),
        "target_price": round(t1, 2),
        "t2_price": round(t2, 2),
        "t3_price": round(t3, 2),
        "quantity": qty,
        "position_size_rs": size_rs,
        "horizon": horizon,
        "max_holding_days": HORIZON_TO_DAYS.get(horizon, 10),
        "status": "OPEN",
        "raw_signal": json.dumps({
            "haiku": haiku_output,
            "flash": flash_output,
            "fallback_mode": fallback_mode,
            "conviction": conviction,
            "avg_conf": avg_conf,
            "analyst_sl_pct_advisory": analyst_sl_pct,
            "t4_price": round(t4, 2) if t4 else None,
            "context_summary": {
                "sector": context["sector"],
                "nifty_mood": context["nifty_mood"],
            },
        }),
    }

    try:
        inserted = sb.table("paper_trades").insert(trade_payload).execute().data[0]
        trade_id = inserted["id"]
    except Exception as e:
        if "uniq_paper_trades_ticker_date_source" in str(e):
            return {"skip": "duplicate_ticker_today_for_source"}
        raise

    # --- Deploy capital ---
    deploy_capital(trade_id, size_rs)
    print(f"[STAGE 10: insert] trade_id={trade_id}, size_rs={size_rs}, deployed")

    # --- Compose Telegram message text (actual send in checkpoint 5) ---
    mode_tag = {
        None: "[TIER2F]",
        "SOLO_DEEPSEEK": "[TIER2F:SOLO_DSK]",
        "SOLO_HAIKU": "[TIER2F:SOLO_HKU]",
    }[fallback_mode]

    message_text = (
        f"{mode_tag} {symbol} {direction} @ {round(entry, 2)} "
        f"| SL {round(sl, 2)} | T1/T2/T3 {round(t1, 2)}/{round(t2, 2)}/{round(t3, 2)} "
        f"| Qty {qty} | Size Rs.{size_rs:,.0f} | Conf {avg_conf:.0f} ({conviction})"
    )
    _tg_send(message_text)
    print(f"[STAGE 10: telegram] sent")

    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "t1": round(t1, 2),
        "t2": round(t2, 2),
        "t3": round(t3, 2),
        "t4": round(t4, 2) if t4 else None,
        "qty": qty,
        "size_rs": size_rs,
        "conviction": conviction,
        "avg_conf": avg_conf,
        "fallback_mode": fallback_mode,
        "telegram_sent": True,
    }


def _tg_send(message: str) -> None:
    """Telegram alert to 'StockMarket-Brain Trades' channel (env: TELEGRAM_TIER3_CHANNEL).

    Matches Tier-3 calling pattern. Uses HTML parse_mode. Fail-open: never blocks trade.
    """
    try:
        send_message(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_TIER3_CHANNEL"),
            text=message,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[_tg_send] Telegram send failed: {e} -- continuing (trade already recorded)")


def _insert_disagreement(filing, haiku, flash, reason) -> int:
    """Log a disagreement to agent_disagreements table. Returns inserted row id."""
    try:
        row = {
            "filing_id": filing["id"],
            "ticker": filing["symbol"],
            "event_type": filing["event_type"],
            "haiku_decision": haiku.get("directional_bias"),
            "haiku_confidence": haiku.get("confidence"),
            "haiku_reasoning": haiku.get("reasoning"),
            "deepseek_decision": flash.get("my_directional_bias"),
            "deepseek_confidence": flash.get("my_confidence"),
            "deepseek_reasoning": flash.get("reasoning"),
            "final_action": None,
            "backtest_outcome": None,
            "actual_price_move_pct": None,
            "full_context": json.dumps({
                "haiku": haiku,
                "flash": flash,
                "reason": reason,
                "filing_summary": filing.get("summary"),
            }),
        }
        inserted = sb.table("agent_disagreements").insert(row).execute().data[0]
        print(f"[disagreement] logged id={inserted['id']} ticker={filing['symbol']} reason={reason}")
        return inserted["id"]
    except Exception as e:
        print(f"[disagreement] insert failed: {e} -- continuing (disagreement tracking non-critical)")
        return -1


def _confidence_to_conviction(conf: float) -> str:
    """Map average confidence to conviction label.

    >= 80 -> HIGH, >= 65 -> MEDIUM, < 65 -> LOW
    """
    if conf >= 80:
        return "HIGH"
    if conf >= 65:
        return "MEDIUM"
    return "LOW"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tier-2F fundamental signal generator")
    parser.add_argument("--filing-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = process_filing(args.filing_id, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
