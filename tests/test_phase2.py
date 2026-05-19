"""
Phase 2 Verification Tests — V2.1 through V2.5.
Touches ONLY portfolio + capital_ledger tables.
NEVER touches paper_trades, filings_log, or any other live table.

Run: .venv/Scripts/python.exe tests/test_phase2.py
"""
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(override=True)
from utils.supabase_client import get_client
from utils.capital_ledger import get_current_portfolio, deploy_capital, release_capital
from utils.position_sizer import calculate_position_size

sb = get_client()

PASS = 0
FAIL = 0
test_ledger_ids = []  # track ledger rows we create, for surgical cleanup


def check(label, condition):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {label}")
        PASS += 1
    else:
        print(f"  FAIL  {label}")
        FAIL += 1


# -- Capture original portfolio state --
original = get_current_portfolio()
print(f"Original portfolio: id={original['id']} "
      f"cash=Rs.{float(original['cash_available']):,.2f} "
      f"deployed=Rs.{float(original['capital_deployed']):,.2f} "
      f"realized_pnl=Rs.{float(original.get('realized_pnl_rs') or 0):,.2f} "
      f"open={original['open_positions']}")


# ===========================================
# V2.1 — Portfolio initialized correctly
# ===========================================
print("\n-- V2.1: Portfolio initialized --")
check("row exists", original is not None)
check("id = 1", original["id"] == 1)
check("starting_capital = Rs.10,00,000", float(original["starting_capital"]) == 1_000_000)
check("cash_available = Rs.10,00,000", float(original["cash_available"]) == 1_000_000)
check("capital_deployed = 0", float(original["capital_deployed"]) == 0)
check("total_equity = Rs.10,00,000", float(original["total_equity"]) == 1_000_000)
check("open_positions = 0", original["open_positions"] == 0)


# ===========================================
# V2.2 — deploy_capital: cash decreases, ledger row created
# ===========================================
print("\n-- V2.2: deploy_capital --")
TEST_AMOUNT = 15_000  # small deploy, well within limits

try:
    deploy_capital(None, TEST_AMOUNT)  # paper_trade_id=NULL = test marker
    pf = get_current_portfolio()

    check(f"cash decreased by Rs.{TEST_AMOUNT:,}",
          abs(float(pf["cash_available"]) - (1_000_000 - TEST_AMOUNT)) < 1)
    check(f"capital_deployed = Rs.{TEST_AMOUNT:,}",
          abs(float(pf["capital_deployed"]) - TEST_AMOUNT) < 1)
    check("open_positions = 1", pf["open_positions"] == 1)
    check("total_equity = cash + deployed (D4: at cost, no MTM)",
          abs(float(pf["total_equity"]) - (float(pf["cash_available"]) + float(pf["capital_deployed"]))) < 1)

    # Verify the ledger row
    ledger = sb.table("capital_ledger").select("*") \
        .is_("paper_trade_id", "null") \
        .eq("txn_type", "DEPLOY") \
        .order("id", desc=True).limit(1).execute().data
    check("capital_ledger DEPLOY row created", len(ledger) == 1)
    if ledger:
        test_ledger_ids.append(ledger[0]["id"])
        check("  txn_type = DEPLOY", ledger[0]["txn_type"] == "DEPLOY")
        check(f"  amount_rs = -{TEST_AMOUNT}", float(ledger[0]["amount_rs"]) == -TEST_AMOUNT)
        check(f"  cash_after = {1_000_000 - TEST_AMOUNT}",
              abs(float(ledger[0]["cash_after"]) - (1_000_000 - TEST_AMOUNT)) < 1)
        print(f"  Ledger: id={ledger[0]['id']} txn={ledger[0]['txn_type']} "
              f"amount={ledger[0]['amount_rs']} cash_after={ledger[0]['cash_after']}")

except Exception as e:
    check(f"deploy_capital raised no exception: {type(e).__name__}: {e}", False)


# ===========================================
# V2.3 — release_capital: cash returns + P&L applied
# ===========================================
print("\n-- V2.3: release_capital --")
PNL_PROFIT = 850  # simulate a profitable trade

try:
    release_capital(None, TEST_AMOUNT, PNL_PROFIT)
    pf = get_current_portfolio()

    expected_cash = 1_000_000 + PNL_PROFIT  # original cash + profit
    check(f"cash returned + profit (Rs.{float(pf['cash_available']):,.2f})",
          abs(float(pf["cash_available"]) - expected_cash) < 1)
    check("capital_deployed = 0", abs(float(pf["capital_deployed"])) < 1)
    check("open_positions = 0", pf["open_positions"] == 0)
    check(f"realized_pnl = Rs.{PNL_PROFIT}",
          abs(float(pf["realized_pnl_rs"]) - PNL_PROFIT) < 1)
    check("total_equity reflects profit",
          abs(float(pf["total_equity"]) - expected_cash) < 1)

    # Verify the ledger row
    ledger = sb.table("capital_ledger").select("*") \
        .is_("paper_trade_id", "null") \
        .eq("txn_type", "PNL_REALIZED") \
        .order("id", desc=True).limit(1).execute().data
    check("capital_ledger PNL_REALIZED row created", len(ledger) == 1)
    if ledger:
        test_ledger_ids.append(ledger[0]["id"])
        check("  txn_type = PNL_REALIZED", ledger[0]["txn_type"] == "PNL_REALIZED")
        expected_return = TEST_AMOUNT + PNL_PROFIT
        check(f"  amount_rs = {expected_return}",
              abs(float(ledger[0]["amount_rs"]) - expected_return) < 1)
        print(f"  Ledger: id={ledger[0]['id']} txn={ledger[0]['txn_type']} "
              f"amount={ledger[0]['amount_rs']} cash_after={ledger[0]['cash_after']}")

except Exception as e:
    check(f"release_capital raised no exception: {type(e).__name__}: {e}", False)


# ===========================================
# V2.4 — Position sizing: 12% cap + 20% buffer (math only, no DB)
# ===========================================
print("\n-- V2.4: Position sizing --")

# Standard case: Rs.10L equity, full cash, entry=2500, SL=2375 (5% SL)
qty, pos = calculate_position_size(1_000_000, 1_000_000, 2500, 2375)
check("qty > 0", qty > 0)
check("12% cap: pos <= Rs.1,20,000", pos <= 120_000 + 1)  # float tolerance
print(f"  Standard (entry=2500 SL=2375): qty={qty} pos=Rs.{pos:,.2f}")

# Wide SL: entry=5000, SL=4000 (20% risk — risk-based qty should be tiny,
# but 12% cap is the binding constraint)
qty, pos = calculate_position_size(1_000_000, 1_000_000, 5000, 4000)
check("wide SL: 12% cap still respected", pos <= 120_000 + 1)
check("wide SL: qty > 0", qty > 0)
print(f"  Wide SL (entry=5000 SL=4000): qty={qty} pos=Rs.{pos:,.2f}")

# Tight cash: only Rs.2L available out of Rs.10L equity
# deployable = 200000 - (1000000 * 0.20) = 0 → actually 0 deployable
# So this should return (0, 0)
qty, pos = calculate_position_size(1_000_000, 200_000, 2500, 2375)
check("tight cash (Rs.2L): buffer blocks — returns (0,0)",
      qty == 0 and pos == 0)
print(f"  Tight cash (cash=Rs.2L): qty={qty} pos=Rs.{pos:,.2f}")

# Entry = SL: zero risk per share
qty, pos = calculate_position_size(1_000_000, 1_000_000, 2500, 2500)
check("entry = SL: returns (0, 0)", qty == 0 and pos == 0)

# Very small equity -- 12% cap of Rs.5K = Rs.600, can't buy even 1 share @ Rs.1,000
qty, pos = calculate_position_size(5_000, 5_000, 1000, 950)
check("tiny equity: 12% cap < 1 share, returns (0, 0)", qty == 0 and pos == 0)
print(f"  Tiny equity (Rs.5K): qty={qty} pos=Rs.{pos:,.2f}")


# ===========================================
# V2.5 — Insufficient cash: raises ValueError, no crash
# ===========================================
print("\n-- V2.5: Insufficient cash --")
try:
    deploy_capital(None, 50_00_000)  # Rs.50L — well beyond available
    check("ValueError raised for insufficient cash", False)
except ValueError as e:
    check("ValueError raised (correct)", True)
    print(f"  Correctly raised: {e}")
except Exception as e:
    check(f"expected ValueError, got {type(e).__name__}: {e}", False)


# ===========================================
# Cleanup — restore original portfolio + remove test ledger rows
# ===========================================
print("\n-- Cleanup --")

# Reset portfolio to original state
sb.table("portfolio").update({
    "cash_available": original["cash_available"],
    "capital_deployed": original["capital_deployed"],
    "total_equity": original["total_equity"],
    "realized_pnl_rs": original.get("realized_pnl_rs", 0),
    "open_positions": original["open_positions"],
    "updated_at": datetime.now().isoformat(),
}).eq("id", original["id"]).execute()

# Delete only the ledger rows WE created (surgical — not all NULL rows)
if test_ledger_ids:
    for lid in test_ledger_ids:
        sb.table("capital_ledger").delete().eq("id", lid).execute()
    print(f"Deleted {len(test_ledger_ids)} test ledger rows (ids={test_ledger_ids})")
else:
    print("No test ledger rows to delete")

# Verify restored
pf = get_current_portfolio()
restored = (
    abs(float(pf["cash_available"]) - float(original["cash_available"])) < 1 and
    abs(float(pf["capital_deployed"]) - float(original["capital_deployed"])) < 1 and
    pf["open_positions"] == original["open_positions"]
)
check("portfolio restored to original state", restored)
print(f"  Final: cash=Rs.{float(pf['cash_available']):,.2f} "
      f"deployed=Rs.{float(pf['capital_deployed']):,.2f} "
      f"open={pf['open_positions']}")


# ===========================================
# Summary
# ===========================================
print(f"\n{'='*50}")
print(f"Phase 2 Verification: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
if FAIL == 0:
    print("ALL GATES PASS")
else:
    print(f"SOME GATES FAILED ({FAIL} failures)")
print(f"{'='*50}")
