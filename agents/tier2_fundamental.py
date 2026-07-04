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
from utils.liquidity_check import check_liquidity
from utils.neon_fundamentals import get_fundamentals
from utils.yfinance_chart import get_chart_snapshot
from utils.price_structure import compute_price_structure, validate_price_structure
from utils.volume_structure import compute_volume_structure, validate_volume_structure
from utils.reward_risk import RR_FLOOR
from utils.filing_memory_brief import get_filing_memory_brief
from utils.pattern_insights_retriever import get_relevant_patterns
from utils.ai_consensus import run_analyst, run_verifier, determine_consensus, _run_deepseek_as_analyst, _safe_conf
from utils.position_sizer import calculate_position_size
from utils.capital_ledger import get_current_portfolio, deploy_capital
from utils.tiered_target_generator import generate_targets
from utils.telegram_client import send_message
from utils.supabase_client import get_client
from utils.trade_memory_writer import build_live_trade_memory_row, insert_live_trade_memory

load_dotenv(override=True)

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
AGREEMENT_THRESHOLD = 70
AVG_CONFIDENCE_FLOOR = 65
HORIZON_TO_DAYS = {"SHORT": 3, "MEDIUM": 10, "LONG": 30}

# Test-mode bypass for stage 4 (NIFTY mood) -- production must NEVER set this.
TIER2F_TEST_MODE = os.getenv("TIER2F_TEST_MODE", "false").lower() == "true"

# Dormant stock-level price-structure gate (reliability-gap #1). While false,
# structure is computed + shadow-logged + fed to the LLM, but NEVER skips a
# filing. Flip true (tier2f.yml) only after the B2 backtest validates the rule.
USE_PRICE_STRUCTURE_GATE = os.getenv("USE_PRICE_STRUCTURE_GATE", "false").strip().lower() == "true"

# Dormant volume-confirmation gate (reliability-gap #3). While false, volume is
# computed + shadow-logged + fed to the LLM, but NEVER skips a filing. Flip true
# (tier2f.yml) only after the B2 backtest validates the rule.
USE_VOLUME_GATE = os.getenv("USE_VOLUME_GATE", "false").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Stage 2: AI-Driven SL (Path C Hybrid) - DORMANT in Commit 1
# SL is validated/clamped from AI consensus and used live; Target is
# shadow-logged only (fixed T1/T2/T3 ladder still drives exits).
# Activated by setting USE_AI_SL=true in tier2f.yml (Commit 2c).
# While USE_AI_SL is false, production behaviour is unchanged.
# ---------------------------------------------------------------------------
USE_AI_SL = os.getenv("USE_AI_SL", "false").strip().lower() == "true"

# Safety guardrails (percentages; long-only assumption for now)
SL_FLOOR_PCT = 2.0                # tightest allowed SL distance
SL_CAP_PCT = 10.0                 # widest allowed SL distance
TARGET_FLOOR_PCT = 2.0            # smallest worthwhile target distance
TARGET_HALLUCINATION_PCT = 50.0   # target beyond this is treated as garbage
# RR_FLOOR imported from utils.reward_risk -- single source of truth (gap #5)


def validate_ai_signal(entry_price, ai_sl_price, ai_target_price):
    """Validate a single (already-blended) AI SL/Target suggestion for a LONG position.

    Path C Hybrid: SL is clamped into [SL_FLOOR_PCT, SL_CAP_PCT] and used live;
    Target is validated only to gate the signal and is shadow-logged, never used
    to override the fixed T1/T2/T3 ladder.

    Rejection (caller should fall back to fixed SL) happens when:
      - target distance is hallucinated (> TARGET_HALLUCINATION_PCT), or
      - target distance is below TARGET_FLOOR_PCT, or
      - reward:risk on the clamped SL is below RR_FLOOR.

    Assumes a LONG position: ai_sl_price < entry_price < ai_target_price.
    Consensus blending of Haiku + DeepSeek happens upstream (Commit 2).

    Returns dict: accepted, validated_sl_price, validated_target_price,
    sl_pct, target_pct, rr, clamp_applied, rejection_reason.
    """
    result = {
        "accepted": False,
        "validated_sl_price": None,
        "validated_target_price": None,
        "sl_pct": None,
        "target_pct": None,
        "rr": None,
        "clamp_applied": False,
        "rejection_reason": None,
    }

    if not entry_price or entry_price <= 0:
        result["rejection_reason"] = "invalid_entry_price"
        return result
    if not ai_sl_price or ai_sl_price <= 0:
        result["rejection_reason"] = "invalid_sl_price"
        return result
    if not ai_target_price or ai_target_price <= 0:
        result["rejection_reason"] = "invalid_target_price"
        return result
    if ai_sl_price >= entry_price:
        result["rejection_reason"] = "sl_not_below_entry"
        return result
    if ai_target_price <= entry_price:
        result["rejection_reason"] = "target_not_above_entry"
        return result

    sl_pct = (entry_price - ai_sl_price) / entry_price * 100.0
    target_pct = (ai_target_price - entry_price) / entry_price * 100.0
    result["target_pct"] = round(target_pct, 4)

    if target_pct > TARGET_HALLUCINATION_PCT:
        result["rejection_reason"] = "target_hallucination"
        return result
    if target_pct < TARGET_FLOOR_PCT:
        result["rejection_reason"] = "target_below_floor"
        return result

    clamped_sl_pct = min(max(sl_pct, SL_FLOOR_PCT), SL_CAP_PCT)
    result["clamp_applied"] = abs(clamped_sl_pct - sl_pct) > 1e-9
    result["sl_pct"] = round(clamped_sl_pct, 4)

    rr = target_pct / clamped_sl_pct
    result["rr"] = round(rr, 4)
    if rr < RR_FLOOR:
        result["rejection_reason"] = "rr_below_floor"
        return result

    result["validated_sl_price"] = round(entry_price * (1 - clamped_sl_pct / 100.0), 2)
    result["validated_target_price"] = round(ai_target_price, 2)
    result["accepted"] = True
    return result


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

    # --- Step 1.5: Liquidity gate (₹5 Cr average daily traded value) ---
    is_liquid, liquidity_value = check_liquidity(symbol)
    print(f"[STAGE 1.5: liquidity] symbol={symbol}, is_liquid={is_liquid}, avg_daily_value_inr={liquidity_value:,.0f}")
    if not is_liquid:
        return {"skip": "illiquid", "symbol": symbol, "avg_daily_value_inr": round(liquidity_value, 2)}

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
    nifty_chart = None
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

    # --- Step 4b: Stock-level price structure (active context; DORMANT gate) ---
    structure = compute_price_structure(chart, nifty_chart)
    gate = validate_price_structure(structure)
    print(
        f"[STAGE 4b: price_structure] above_sma50={structure['above_sma50']}, "
        f"pct_from_52wk_high={structure['pct_from_52wk_high']}, "
        f"rs_vs_nifty_63d={structure['rs_vs_nifty_63d']}, "
        f"gate_passes={gate['passes']}, reasons={gate['reasons']}"
    )
    if USE_PRICE_STRUCTURE_GATE and not gate["passes"]:
        if not TIER2F_TEST_MODE:
            return {"skip": "price_structure", "structure": structure, "gate": gate}
        print("[STAGE 4b: price_structure] gate FAILED but TIER2F_TEST_MODE=true -- BYPASSING skip for testing")

    # --- Step 4c: Volume confirmation (active context; DORMANT gate) ---
    vol_structure = compute_volume_structure(chart)
    vol_gate = validate_volume_structure(vol_structure)
    print(
        f"[STAGE 4c: volume] vol_vs_avg_ratio={vol_structure['vol_vs_avg_ratio']}, "
        f"avg_volume_20d={vol_structure['avg_volume_20d']}, "
        f"volume_spike={vol_structure['volume_spike']}, "
        f"gate_passes={vol_gate['passes']}, reasons={vol_gate['reasons']}"
    )
    if USE_VOLUME_GATE and not vol_gate["passes"]:
        if not TIER2F_TEST_MODE:
            return {"skip": "volume_confirmation", "volume_structure": vol_structure, "gate": vol_gate}
        print("[STAGE 4c: volume] gate FAILED but TIER2F_TEST_MODE=true -- BYPASSING skip for testing")

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
            "sma_50": chart["sma_50"],
            "sma_200": chart["sma_200"],
            "support": chart["support"],
            "resistance": chart["resistance"],
        },
        "price_structure": structure,
        "volume_structure": vol_structure,
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

    # --- Step 6: Haiku analyst (or DeepSeek-as-analyst fallback) with Tier-2F prompt ---
    try:
        haiku_output = run_analyst(context, prompt_template=TIER2F_ANALYST_PROMPT)
    except Exception as e:
        print(f"[STAGE 6: haiku] failed: {e} -- attempting DeepSeek as analyst fallback")
        try:
            haiku_output = _run_deepseek_as_analyst(context, prompt_template=TIER2F_ANALYST_PROMPT)
            fallback_mode = "SOLO_DEEPSEEK"
            print(f"[STAGE 6: deepseek-analyst] fallback succeeded")
        except Exception as e2:
            print(f"[STAGE 6: deepseek-analyst] also failed: {e2} -- BOTH_DOWN")
            return {"skip": "both_apis_down"}

    if haiku_output:
        print(f"[STAGE 6: {'haiku' if fallback_mode is None else 'deepseek-analyst'}] tradeable={haiku_output.get('tradeable')}, bias={haiku_output.get('directional_bias')}, conf={haiku_output.get('confidence')}")

    # Early-skip on analyst tradeable=False
    if haiku_output and not haiku_output.get("tradeable"):
        return {"skip": "haiku_not_tradeable", "haiku": haiku_output, "fallback_mode": None}

    # --- Step 7: DeepSeek verifier — only for consensus path (Haiku succeeded) ---
    if fallback_mode is None:
        try:
            flash_output = run_verifier(context, haiku_output, prompt_template=TIER2F_VERIFIER_PROMPT)
        except Exception as e:
            print(f"[STAGE 7: flash] failed: {e} -- entering SOLO_HAIKU fallback")
            fallback_mode = "SOLO_HAIKU"

    if flash_output:
        print(f"[STAGE 7: flash] verdict={flash_output.get('verdict')}, agreement={flash_output.get('agreement_score')}, bias={flash_output.get('my_directional_bias')}, conf={flash_output.get('my_confidence')}")

    # --- Step 8: Consensus or solo decision ---
    if fallback_mode is None:
        action, reason = determine_consensus(haiku_output, flash_output)
    else:
        # Solo path: haiku_output is always analyst-format (Haiku or DeepSeek-as-analyst).
        # flash_output is never used here — the solo model already rendered its verdict.
        conf = _safe_conf(haiku_output, "confidence")
        if conf is None:
            action, reason = "SKIP", "Solo — missing or invalid confidence field"
        else:
            haircut_conf = int(conf * 0.9)
            tradeable = haiku_output.get("tradeable", False)
            if tradeable and haircut_conf >= AVG_CONFIDENCE_FLOOR:
                action = "PROCEED"
                reason = f"Solo {fallback_mode} (0.9x haircut), conf={haircut_conf}"
            else:
                action = "SKIP"
                reason = (
                    f"Solo {fallback_mode} — confidence {haircut_conf} < {AVG_CONFIDENCE_FLOOR}"
                    if tradeable else "Analyst says not tradeable"
                )

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
    # All paths: haiku_output is always analyst-format at this point.
    direction_bias = haiku_output.get("directional_bias", "NEUTRAL")
    analyst_sl_pct = haiku_output.get("stop_loss_pct", 4.0)

    if direction_bias == "NEUTRAL":
        return {"skip": "neutral_bias_no_trade"}
    direction = "BUY" if direction_bias == "BULLISH" else "SELL"

    # --- Compute average confidence + conviction ---
    if fallback_mode is None:
        # Consensus path: both models succeeded; determine_consensus already
        # validated the confidence fields — safe to use bracket access.
        avg_conf = (haiku_output["confidence"] + flash_output["my_confidence"]) / 2
    else:
        # Solo path: confidence from the solo analyst model with 0.9x haircut.
        conf = _safe_conf(haiku_output, "confidence")
        avg_conf = int(conf * 0.9) if conf else 0

    # HOTFIX-5: clamp confidence to [50, 85] before conviction mapping.
    avg_conf = max(CONFIDENCE_FLOOR, min(CONFIDENCE_CEILING, avg_conf))

    conviction = _confidence_to_conviction(avg_conf)

    # --- Entry from chart ---
    entry = context["chart_snapshot"]["last_close"]

    # --- Stage 2: AI-Driven SL eligibility + blend (Path C Hybrid, dormant until USE_AI_SL=true) ---
    # LONG-only; requires both models (no SOLO blend). SL = max-of-SLs (conservative);
    # target = confidence-weighted average (shadow-logged only, never overrides the ladder).
    ai_sl_eligible = bool(
        USE_AI_SL
        and fallback_mode is None
        and direction == "BUY"
        and haiku_output.get("stop_loss_pct") and haiku_output.get("target_pct")
        and flash_output.get("my_stop_loss_pct") and flash_output.get("my_target_pct")
    )
    ai_sl_validation = None
    ai_sl_used = False
    blend_method = None
    blended_inputs = None
    if ai_sl_eligible:
        h_sl = float(haiku_output["stop_loss_pct"])
        f_sl = float(flash_output["my_stop_loss_pct"])
        h_tgt = float(haiku_output["target_pct"])
        f_tgt = float(flash_output["my_target_pct"])
        h_conf = float(haiku_output["confidence"])
        f_conf = float(flash_output["my_confidence"])
        blended_sl_pct = max(h_sl, f_sl)
        conf_sum = h_conf + f_conf
        blended_target_pct = (h_tgt * h_conf + f_tgt * f_conf) / conf_sum if conf_sum else (h_tgt + f_tgt) / 2
        blend_method = "sl_max_target_confwavg_v1"
        blended_inputs = {
            "h_sl": h_sl, "f_sl": f_sl,
            "h_target": h_tgt, "f_target": f_tgt,
            "h_conf": h_conf, "f_conf": f_conf,
            "blended_sl_pct": round(blended_sl_pct, 4),
            "blended_target_pct": round(blended_target_pct, 4),
        }
        ai_sl_price = round(entry * (1 - blended_sl_pct / 100.0), 2)
        ai_target_price = round(entry * (1 + blended_target_pct / 100.0), 2)
        ai_sl_validation = validate_ai_signal(entry, ai_sl_price, ai_target_price)
        print(f"[STAGE 9: ai_sl] eligible, blended_sl_pct={blended_sl_pct:.2f}, blended_target_pct={blended_target_pct:.2f}, accepted={ai_sl_validation['accepted']}, reason={ai_sl_validation['rejection_reason']}")

    # --- Generate canonical targets + stop_loss ---
    targets = generate_targets(entry_price=entry, direction=direction, conviction=conviction)
    t1, t2, t3 = targets["t1"], targets["t2"], targets["t3"]
    t4 = targets.get("t4")       # only present when conviction="HIGH"; goes into raw_signal JSONB
    sl = targets["stop_loss"]

    # --- Stage 2: apply AI-validated SL if accepted (Path C: SL live, target shadow-only) ---
    ladder_sl_price = sl
    if ai_sl_eligible and ai_sl_validation and ai_sl_validation["accepted"]:
        sl = ai_sl_validation["validated_sl_price"]
        ai_sl_used = True
        print(f"[STAGE 9: ai_sl] OVERRIDE applied -> sl={sl:.2f} (ladder was {ladder_sl_price:.2f})")

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
        "confidence": round(avg_conf),
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
        "raw_signal": {
            "haiku": haiku_output,
            "flash": flash_output,
            "fallback_mode": fallback_mode,
            "conviction": conviction,
            "avg_conf": avg_conf,
            "analyst_sl_pct_advisory": analyst_sl_pct,
            "ladder_sl_price": round(ladder_sl_price, 2),
            "ai_sl_validation": ai_sl_validation,
            "ai_sl_used": ai_sl_used,
            "blend_method": blend_method,
            "blended_inputs": blended_inputs,
            "t4_price": round(t4, 2) if t4 else None,
            "context_summary": {
                "sector": context["sector"],
                "nifty_mood": context["nifty_mood"],
            },
        },
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

    # --- Phase 7 §9.1: capture LIVE_TRADE row to trade_memory_v2 (SUPABASE) ---
    # NON-FATAL: paper_trade + capital are already committed above; a capture
    # failure must never block signal generation. Wrapped here AND inside the
    # writer (mirrors _insert_disagreement's fail-open contract).
    try:
        mem_row = build_live_trade_memory_row(
            trade_id=trade_id,
            haiku_output=haiku_output,
            flash_output=flash_output,
            sector=context["sector"],
            market_cap_cr=context["market_cap_cr"],
            nifty_mood=context["nifty_mood"],
            symbol_base=symbol,
            event_type=filing["event_type"],
        )
        insert_live_trade_memory(sb, mem_row)
    except Exception as e:
        print(f"[trade_memory] capture skipped: {e} -- continuing (non-critical)")

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
            "full_context": {
                "haiku": haiku,
                "flash": flash,
                "reason": reason,
                "filing_summary": filing.get("summary"),
            },
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
