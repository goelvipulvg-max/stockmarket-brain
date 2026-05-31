"""DB-free unit tests for utils/trade_memory_writer.py pure builder (Phase 7 §9.1).

Run: .venv\\Scripts\\python.exe tests\\test_trade_memory_writer.py

Tests ONLY the no-I/O pure builder build_live_trade_memory_row. The two DB
functions (insert_live_trade_memory / update_trade_memory_outcome) do real
Supabase I/O and are verified live, not here. No DB, no creds needed.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from utils.trade_memory_writer import build_live_trade_memory_row


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


def check_true(desc, cond):
    assert cond, f"FAIL: {desc}"
    print(f"  ok: {desc}")


# Realistic signal outputs (shape mirrors raw_signal probe: GILLETTE id 161).
HAIKU = {
    "tradeable": True,
    "directional_bias": "BULLISH",
    "confidence": 72,
    "reasoning": "Interim dividend signals strong cash position; uptrend intact.",
    "stop_loss_pct": 4.0,
    "horizon": "SHORT",
}
FLASH = {
    "verdict": "AGREE",
    "my_directional_bias": "BULLISH",
    "my_confidence": 68,
    "reasoning": "Concur — defensive name, low downside on a dividend event.",
    "agreement_score": 85,
}

row = build_live_trade_memory_row(
    trade_id=161,
    haiku_output=HAIKU,
    flash_output=FLASH,
    sector="Consumer Defensive",
    market_cap_cr=35000.0,
    nifty_mood="NEUTRAL",
    symbol_base="GILLETTE",
    event_type="DIVIDEND",
)

# --- shape: exactly the trade_memory_v2 capture-half columns (no id/created_at) ---
EXPECTED_KEYS = {
    "source_type", "symbol_base", "event_type", "sector", "market_cap_cr",
    "nifty_mood", "outcome", "pnl_pct", "holding_days", "paper_trade_id",
    "haiku_reasoning", "deepseek_reasoning", "pattern_tags", "full_context",
}
check("row has exactly the capture-half keys", set(row.keys()), EXPECTED_KEYS)

# --- signal-time invariants ---
check("source_type is LIVE_TRADE", row["source_type"], "LIVE_TRADE")
check("outcome is OPEN at signal time", row["outcome"], "OPEN")
check("pnl_pct is None at signal time", row["pnl_pct"], None)
check("holding_days is None at signal time", row["holding_days"], None)
check("paper_trade_id set to trade_id", row["paper_trade_id"], 161)

# --- passthrough scalars ---
check("symbol_base passthrough", row["symbol_base"], "GILLETTE")
check("event_type passthrough", row["event_type"], "DIVIDEND")
check("sector passthrough", row["sector"], "Consumer Defensive")
check("market_cap_cr passthrough", row["market_cap_cr"], 35000.0)
check("nifty_mood passthrough", row["nifty_mood"], "NEUTRAL")

# --- reasoning extraction ---
check("haiku_reasoning extracted", row["haiku_reasoning"], HAIKU["reasoning"])
check("deepseek_reasoning extracted", row["deepseek_reasoning"], FLASH["reasoning"])

# --- pattern_tags: list[str], seed-mirroring shape with source_live_trade ---
check("pattern_tags is a list", isinstance(row["pattern_tags"], list), True)
check("pattern_tags exact",
      row["pattern_tags"],
      ["event_dividend", "sector_consumer_defensive", "source_live_trade"])

# --- full_context carries both agents' full outputs (jsonb dict) ---
check("full_context is a dict", isinstance(row["full_context"], dict), True)
check("full_context.haiku == haiku_output", row["full_context"]["haiku"], HAIKU)
check("full_context.flash == flash_output", row["full_context"]["flash"], FLASH)

# --- SOLO_DEEPSEEK: haiku_output is None -> no crash, haiku_reasoning None ---
solo_dsk = build_live_trade_memory_row(
    trade_id=999, haiku_output=None, flash_output=FLASH,
    sector="Healthcare", market_cap_cr=None, nifty_mood="BULLISH",
    symbol_base="LUPIN", event_type="RESULTS",
)
check("SOLO_DEEPSEEK: haiku_reasoning None", solo_dsk["haiku_reasoning"], None)
check("SOLO_DEEPSEEK: deepseek_reasoning present", solo_dsk["deepseek_reasoning"], FLASH["reasoning"])
check("SOLO_DEEPSEEK: full_context.haiku is None", solo_dsk["full_context"]["haiku"], None)
check("SOLO_DEEPSEEK: market_cap_cr None passthrough", solo_dsk["market_cap_cr"], None)
check("SOLO_DEEPSEEK: pattern_tags", solo_dsk["pattern_tags"],
      ["event_results", "sector_healthcare", "source_live_trade"])

# --- SOLO_HAIKU: flash_output is None -> no crash, deepseek_reasoning None ---
solo_hku = build_live_trade_memory_row(
    trade_id=998, haiku_output=HAIKU, flash_output=None,
    sector="Industrials", market_cap_cr=12000.0, nifty_mood="NEUTRAL",
    symbol_base="ASHOKLEY", event_type="CONTRACT_WIN",
)
check("SOLO_HAIKU: deepseek_reasoning None", solo_hku["deepseek_reasoning"], None)
check("SOLO_HAIKU: haiku_reasoning present", solo_hku["haiku_reasoning"], HAIKU["reasoning"])
check("SOLO_HAIKU: full_context.flash is None", solo_hku["full_context"]["flash"], None)
check("SOLO_HAIKU: pattern_tags lowercases CONTRACT_WIN",
      solo_hku["pattern_tags"][0], "event_contract_win")

# --- defensive: None sector / None event_type -> 'unknown', no crash ---
defensive = build_live_trade_memory_row(
    trade_id=1, haiku_output=HAIKU, flash_output=FLASH,
    sector=None, market_cap_cr=None, nifty_mood=None,
    symbol_base="FOO", event_type=None,
)
check("None event_type -> event_unknown", defensive["pattern_tags"][0], "event_unknown")
check("None sector -> sector_unknown", defensive["pattern_tags"][1], "sector_unknown")
check("None sector passthrough stays None", defensive["sector"], None)

# --- reasoning missing key (dict without 'reasoning') -> None, no crash ---
no_reason = build_live_trade_memory_row(
    trade_id=2, haiku_output={"confidence": 70}, flash_output={"my_confidence": 65},
    sector="Energy", market_cap_cr=500.0, nifty_mood="NEUTRAL",
    symbol_base="BAR", event_type="ORDER",
)
check("missing haiku reasoning key -> None", no_reason["haiku_reasoning"], None)
check("missing flash reasoning key -> None", no_reason["deepseek_reasoning"], None)

print("ALL TESTS PASSED")
