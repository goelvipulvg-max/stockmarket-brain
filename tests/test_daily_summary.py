"""DB-free unit tests for agents/daily_summary.py pure helpers (Phase 8 §10.3).

Run: .venv\\Scripts\\python.exe tests\\test_daily_summary.py

Tests only the no-I/O helpers: last_market_day, fmt_rs, format_winrate_line,
format_summary. No DB calls. Dummy Supabase env set so import needs no creds.
"""
import os
import sys
import pathlib
from datetime import date

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agents.daily_summary import (
    last_market_day, fmt_rs, format_winrate_line, format_summary,
)


def check(desc, got, want):
    assert got == want, f"FAIL: {desc} -> got {got!r}, want {want!r}"
    print(f"  ok: {desc}")


def check_in(desc, hay, needle):
    assert needle in hay, f"FAIL: {desc} -> {needle!r} not in:\n{hay}"
    print(f"  ok: {desc}")


# --- last_market_day: Mon reports Fri (skips weekend); Tue reports Mon ---
# 2026-06-01 is a Monday -> previous trading day Fri 2026-05-29.
check("Mon 2026-06-01 -> Fri 2026-05-29", last_market_day(date(2026, 6, 1)), date(2026, 5, 29))
# 2026-06-02 is a Tuesday -> previous trading day Mon 2026-06-01.
check("Tue 2026-06-02 -> Mon 2026-06-01", last_market_day(date(2026, 6, 2)), date(2026, 6, 1))

# --- fmt_rs: Indian grouping + sign + None ---
check("10,00,000", fmt_rs(1000000), "Rs.10,00,000")
check("8,32,504 (rounds .24 down)", fmt_rs(832504.24), "Rs.8,32,504")
check("1,67,496 (rounds .76 up)", fmt_rs(167495.76), "Rs.1,67,496")
check("negative rounds to -10", fmt_rs(-9.72), "-Rs.10")
check("zero", fmt_rs(0.0), "Rs.0")
check("small 500", fmt_rs(500), "Rs.500")
check("None -> N/A", fmt_rs(None), "N/A")
check("garbage -> N/A", fmt_rs("abc"), "N/A")

# --- format_winrate_line: n=0 graceful, populated, preliminary flag ---
check("n=0 graceful", format_winrate_line({"n": 0}),
      "Win rate: n/a (no resolved TIER2F trades yet)")
populated = format_winrate_line({
    "n": 5, "n_win": 3, "n_loss": 2, "win_rate": 0.6,
    "expectancy_pct": 1.25, "preliminary": True,
})
check_in("populated win%", populated, "Win rate: 60% (3W/2L of 5)")
check_in("populated expectancy", populated, "Expectancy: +1.25%/trade")
check_in("preliminary flag", populated, "(!) preliminary")
# win_rate None (e.g. all break-even) -> N/A, no crash
check_in("win_rate None -> N/A", format_winrate_line({"n": 2, "win_rate": None, "expectancy_pct": None}),
         "Win rate: N/A")

# --- format_summary: assembles all lines, n=0-today shape ---
text = format_summary({
    "report_date": date(2026, 5, 29),
    "filings": 12, "signals": 4, "trades": 0, "queue": 0,
    "cash": 832504.24, "deployed": 167495.76, "equity": 1000000.0,
    "realized": 0.0, "open_positions": 3,
    "winrate_line": "Win rate: n/a (no resolved TIER2F trades yet)",
})
check_in("title date", text, "Daily Summary — 29-May-2026")
check_in("session day label", text, "Last session (Fri 29-May):")
check_in("filings line", text, "Filings classified: 12")
check_in("signals line", text, "Tradeable signals (mat. &amp; conf≥60): 4")
check_in("trades line", text, "New TIER2F trades: 0")
check_in("queue line", text, "Queue: 0")
check_in("equity line", text, "Equity: Rs.10,00,000")
check_in("cash+deployed", text, "cash Rs.8,32,504 + deployed Rs.1,67,496")
check_in("open positions", text, "Open positions: 3")
check_in("realized (HTML-escaped P&L)", text, "Realized P&amp;L: Rs.0")
check_in("winrate passthrough", text, "no resolved TIER2F trades yet")

print("ALL TESTS PASSED")
