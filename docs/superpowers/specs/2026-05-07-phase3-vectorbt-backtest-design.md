# Phase 3 — SMA 50/200 Vectorbt Backtest

**Date:** 2026-05-07  
**Status:** Approved  
**Scope:** Standalone backtest script — no CI, no agent, manually run

---

## Goal

Validate whether a pure SMA 50/200 crossover strategy generates positive risk-adjusted returns on our 10-stock NSE watchlist over a 3-year period (2022–2025). Output: interactive HTML report + terminal summary.

---

## Architecture

**New file:** `scripts/backtest_sma.py`  
**New folder:** `reports/` (gitignored)  
**Dependency added:** `vectorbt>=0.26.2` in `requirements.txt`

No changes to agents, utils, or CI workflows.

### Script Flow

```
1. Fetch 3Y daily OHLCV for all 10 tickers via yfinance (2022-01-01 to today)
2. Compute SMA-50 and SMA-200 per ticker (pandas rolling mean on Close)
3. Generate entry/exit boolean arrays from crossover conditions
4. Run vbt.Portfolio.from_signals() with equal-weight Rs 25k per ticker
5. Print per-ticker + portfolio summary table to terminal
6. Save interactive HTML report to reports/backtest_sma_YYYYMMDD.html
```

---

## Tickers

Same 10 as Tier-2 watchlist:

```python
TICKERS = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "SBIN.NS", "BAJFINANCE.NS", "WIPRO.NS", "ADANIENT.NS", "HCLTECH.NS"
]
```

---

## Signal Logic

| Condition | Rule |
|-----------|------|
| Entry (BUY) | SMA-50 crosses above SMA-200 (golden cross): `sma50 > sma200` AND previous bar `sma50 <= sma200` |
| Exit (SELL) | SMA-50 crosses below SMA-200 (death cross): `sma50 < sma200` AND previous bar `sma50 >= sma200` |

- No stop-loss, no partial exits — pure crossover
- SMA-200 requires 200-day warmup; data fetched from 2022-01-01 so first valid signal available mid-2022

---

## Portfolio Config

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `init_cash` | Rs 2,50,000 | Total ST capital |
| `size` | Rs 25,000 per ticker | Equal weight across 10 stocks |
| `size_type` | `"value"` | Rupee amount, not shares |
| `fees` | 0.1% per trade | Brokerage + STT estimate |
| `freq` | `"D"` | Daily bars |
| Data source | yfinance | 3Y daily OHLCV |

---

## Output

### Terminal Summary

```
Backtest: SMA 50/200 | 2022-01-01 to 2025-05-07 | 10 tickers

Ticker        Total Return    CAGR    Sharpe    Max DD    # Trades
-----------  -------------  ------  --------  --------  --------
RELIANCE.NS        +18.4%    5.8%      0.42    -12.3%         4
TCS.NS             +31.2%    9.4%      0.71     -8.1%         3
...
PORTFOLIO          +22.7%    7.1%      0.58    -10.2%        32

Report saved: reports/backtest_sma_20250507.html
```

### HTML Report (vectorbt built-in)

- Cumulative returns chart (portfolio vs buy-and-hold benchmark)
- Drawdown chart
- Trade list table
- Stats: Total Return, CAGR, Sharpe Ratio, Max Drawdown, Win Rate, Avg Trade Duration

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| yfinance fetch fails for a ticker | Print warning, skip ticker, continue |
| Ticker has < 200 days of data | Print warning, skip ticker |
| `reports/` folder missing | `os.makedirs` auto-create |

No exceptions propagate — script always completes for remaining tickers.

---

## Testing

No automated tests. This is an exploratory analysis script, not a CI agent. Correctness verified by running the script and inspecting terminal output + HTML report manually.

---

## Out of Scope

- Comparing AI signals (Tier-2) vs SMA baseline — deferred to Phase 3.1
- Parameter tuning (different SMA windows) — deferred
- QuestDB integration — not needed; yfinance is the sole data source
- Live trading or paper trade logging — read-only backtest only
