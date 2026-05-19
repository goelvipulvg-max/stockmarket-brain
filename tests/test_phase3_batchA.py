"""
Phase 3 — Batch A Verification Gates (V3.1, V3.3, V3.4 + neon_fundamentals smoke).
Tests yfinance_chart, fno_ban_list, trading_calendar, neon_fundamentals.
"""
import sys
sys.path.insert(0, "C:/dev/stockmarket-brain")
from datetime import date
from dotenv import load_dotenv
load_dotenv(override=True)

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {label}")
        PASS += 1
    else:
        print(f"  FAIL  {label}")
        FAIL += 1


# ============================================================
# V3.1 — yfinance_chart: RELIANCE.NS -> RSI/MACD/support/2-year
# ============================================================
print("-- V3.1: yfinance_chart.get_chart_snapshot('RELIANCE.NS') --")
from utils.yfinance_chart import get_chart_snapshot

try:
    snap = get_chart_snapshot("RELIANCE.NS")
except Exception as e:
    snap = None
    check(f"fetch succeeded (not raised {type(e).__name__})", False)

if snap:
    check("ticker = RELIANCE.NS", snap["ticker"] == "RELIANCE.NS")
    check("last_close > 0", snap["last_close"] > 0)
    check("rsi_14 in 0-100", snap["rsi_14"] is not None and 0 < snap["rsi_14"] < 100)
    check("macd populated", snap["macd"] is not None)
    check("macd_signal populated", snap["macd_signal"] is not None)
    check("macd_hist populated", snap["macd_hist"] is not None)
    check("macd_hist = macd - signal",
          abs(snap["macd_hist"] - (snap["macd"] - snap["macd_signal"])) < 0.01)
    check("sma_50 populated", snap["sma_50"] is not None and snap["sma_50"] > 0)
    check("sma_200 populated", snap["sma_200"] is not None and snap["sma_200"] > 0)
    check("support > 0", snap["support"] > 0)
    check("resistance > 0", snap["resistance"] > 0)
    check("resistance >= support", snap["resistance"] >= snap["support"])
    valid_trends = {"UPTREND", "DOWNTREND", "SIDEWAYS", "INSUFFICIENT_DATA"}
    check(f"trend in {valid_trends}", snap["trend"] in valid_trends)
    check("trend != INSUFFICIENT_DATA (RELIANCE has 2yr data)",
          snap["trend"] != "INSUFFICIENT_DATA")
    check("close_series has 200+ points", len(snap["close_series"]) >= 200)
    print(f"  last_close={snap['last_close']} rsi={snap['rsi_14']} trend={snap['trend']}")
    print(f"  macd={snap['macd']:.4f} signal={snap['macd_signal']:.4f} hist={snap['macd_hist']:.4f}")
    print(f"  sma_50={snap['sma_50']:.2f} sma_200={snap['sma_200']:.2f}")
    print(f"  support={snap['support']:.2f} resistance={snap['resistance']:.2f}")


# ============================================================
# V3.4 — trading_calendar: weekends + NSE holidays skip
# ============================================================
print("\n-- V3.4: trading_calendar --")
from utils.trading_calendar import is_trading_day, next_trading_day, add_trading_days

# Weekends
sat = date(2026, 1, 24)
sun = date(2026, 1, 25)
check(f"Saturday {sat} not trading", not is_trading_day(sat))
check(f"Sunday {sun} not trading", not is_trading_day(sun))

# Republic Day
hol = date(2026, 1, 26)
check(f"Republic Day {hol} not trading", not is_trading_day(hol))
check(f"  next trading day after {hol} = {next_trading_day(hol)}",
      next_trading_day(hol) == date(2026, 1, 27))

# Critical: strictly-forward add_trading_days
friday = date(2026, 1, 9)
check(f"Friday {friday} is trading", is_trading_day(friday))
add5 = add_trading_days(friday, 5)
check(f"add_trading_days({friday}, 5) == 2026-01-16  (got {add5})",
      add5 == date(2026, 1, 16))
check(f"add_trading_days({friday}, 1) == next_trading_day({friday})",
      add_trading_days(friday, 1) == next_trading_day(friday))
check(f"add_trading_days({friday}, 0) == {friday}  (trading day -> itself)",
      add_trading_days(friday, 0) == friday)

# Holiday clamp: n=0 -> next trading day
check(f"add_trading_days({hol}, 0) == next_trading_day({hol})",
      add_trading_days(hol, 0) == next_trading_day(hol))

# n >= 1 on holiday: strictly-after behaviour
add1_hol = add_trading_days(hol, 1)
nxt_hol = next_trading_day(hol)
check(f"add_trading_days({hol}, 1) == next_trading_day({hol})  [{add1_hol} == {nxt_hol}]",
      add1_hol == nxt_hol)

# Weekend: Saturday + 0 -> Monday
mon = date(2026, 1, 26)  # Note: Jan 26 is Republic Day (Mon), not a regular Mon
# Use a regular Sat where Mon is a trading day
sat2 = date(2026, 1, 10)
expected_mon = date(2026, 1, 12)
check(f"add_trading_days(Sat {sat2}, 0) -> Mon {expected_mon}  (got {add_trading_days(sat2, 0)})",
      add_trading_days(sat2, 0) == expected_mon)


# ============================================================
# V3.3 — fno_ban_list: fail-open + live fetch
# ============================================================
print("\n-- V3.3: fno_ban_list --")
from utils import fno_ban_list

# Clear any cached state
fno_ban_list._cache = None
fno_ban_list._cache_time = None

# Happy path: live fetch
ban_list = fno_ban_list.get_ban_list()
check("get_ban_list() returns list", isinstance(ban_list, list))
print(f"  Current bans ({len(ban_list)}): {ban_list if ban_list else '(none)'}")

check("is_in_ban('RELIANCE') -> bool, not banned",
      fno_ban_list.is_in_ban("RELIANCE") is False)

# Verify populated cache
check("cache is set after fetch", isinstance(fno_ban_list._cache, set))

# Fail-open: simulate fetch failure
old_url = fno_ban_list._BAN_LIST_URL
fno_ban_list._cache = None
fno_ban_list._cache_time = None
fno_ban_list._BAN_LIST_URL = "https://example.com/does-not-exist.csv"
try:
    result = fno_ban_list.get_ban_list()
    check("fail-open: get_ban_list() returns empty list (no exception)",
          isinstance(result, list) and len(result) == 0)
    result2 = fno_ban_list.is_in_ban("RELIANCE")
    check("fail-open: is_in_ban() returns False (no exception)",
          result2 is False)
except Exception as e:
    check(f"fail-open: no exception (got {type(e).__name__}: {e})", False)
finally:
    fno_ban_list._BAN_LIST_URL = old_url
    fno_ban_list._cache = None
    fno_ban_list._cache_time = None


# ============================================================
# A3 smoke — neon_fundamentals
# ============================================================
print("\n-- A3 smoke: neon_fundamentals --")
from utils.neon_fundamentals import get_fundamentals

f = get_fundamentals("RELIANCE")
check("RELIANCE returns dict (not None)", f is not None)
if f:
    check("sector non-empty", bool(f["sector"]))
    check("market_cap_cr > 0", f["market_cap_cr"] is not None and f["market_cap_cr"] > 0)
    check("business_summary non-empty", bool(f["business_summary"]))
    print(f"  sector={f['sector']}  mcap=Rs.{f['market_cap_cr']:,.2f} Cr")

f2 = get_fundamentals("RANDOM_NOT_IN_NIFTY500")
check("non-NIFTY500 symbol returns None", f2 is None)


# ============================================================
# Summary
# ============================================================
print(f"\n{'='*50}")
print(f"Phase 3 Batch A: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
if FAIL == 0:
    print("ALL GATES PASS — Batch A checkpoint clear")
else:
    print(f"SOME GATES FAILED ({FAIL} failures)")
print(f"{'='*50}")
