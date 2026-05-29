"""Upstox Company Fundamentals API — READ-ONLY spot-check.

Tests the Income Statement endpoint for a few NSE tickers to confirm, for Gap #2:
  (a) does the token work / does the API respond,
  (b) how many quarters of history come back (need >=5 for YoY, >=8 for backtest),
  (c) is the data clean (revenue / net profit / EPS / YoY-QoQ % look reasonable).

Pure GET — NO orders, NO writes, NO DB. Schema is inspected (not assumed), so the
raw structure is printed for manual verification rather than fabricated.

Usage: .venv/Scripts/python.exe scripts/upstox_fundamentals_spotcheck.py
"""
import os
import sys
import json
import requests
from dotenv import load_dotenv
load_dotenv(override=True)

UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()

# ISINs reused from agents/upstox_paper_trade.py:32-43 (NSE_EQ|ISIN -> bare ISIN)
TEST = {
    "RELIANCE": "INE002A01018",
    "TCS":      "INE467B01029",
    "INFY":     "INE009A01021",
}

BASE = "https://api.upstox.com/v2/fundamentals/{isin}/income-statement"
PARAMS = {"type": "consolidated", "time_period": "quarterly", "fs": "true"}


def _walk_lists(node, path="data"):
    """Yield (path, length, sample) for every list found in the structure."""
    if isinstance(node, list):
        sample = node[0] if node else None
        yield (path, len(node), sample)
        for i, item in enumerate(node[:1]):
            yield from _walk_lists(item, f"{path}[{i}]")
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_lists(v, f"{path}.{k}")


def _scan_metric(node, keyword, found):
    """Best-effort: collect dict nodes whose name/label/title contains `keyword`."""
    if isinstance(node, dict):
        label = str(node.get("name") or node.get("label") or node.get("title") or
                    node.get("category") or node.get("particular") or "")
        if keyword.lower() in label.lower():
            found.append(node)
        for v in node.values():
            _scan_metric(v, keyword, found)
    elif isinstance(node, list):
        for item in node:
            _scan_metric(item, keyword, found)


def check_ticker(name, isin):
    print("\n" + "=" * 64)
    print(f"{name}  (ISIN {isin})")
    print("=" * 64)
    url = BASE.format(isin=isin)
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}", "Accept": "application/json"},
            params=PARAMS,
            timeout=15,
        )
    except Exception as e:
        print(f"  [REQUEST FAILED] {type(e).__name__}: {e}")
        return

    print(f"  HTTP {r.status_code}  ({r.url})")

    if r.status_code == 401:
        print("  [TOKEN] 401 Unauthorized — UPSTOX_ACCESS_TOKEN expired/invalid.")
        print("          Fix: run scripts/generate_token.py to refresh the token, then re-run.")
        return
    if r.status_code != 200:
        body = r.text[:500]
        print(f"  [API ERROR] status={r.status_code}  body={body}")
        return

    try:
        body = r.json()
    except Exception as e:
        print(f"  [PARSE FAILED] not JSON: {e}; first 300 chars: {r.text[:300]}")
        return

    data = body.get("data", body)
    print(f"  top-level keys: {list(body.keys())}")
    if isinstance(data, dict):
        print(f"  data keys: {list(data.keys())}")

    # (b) period / quarter depth — heuristic: longest list in the structure
    lists = sorted(_walk_lists(data), key=lambda t: -t[1])
    if lists:
        print("  longest lists found (likely period series):")
        for p, n, _sample in lists[:5]:
            print(f"    len={n:<3}  at {p}")
        print(f"  => best-effort quarter depth: ~{lists[0][1]} periods")
    else:
        print("  no lists found in payload")

    # (c) metric spot-check — best-effort keyword scan
    for kw in ("Revenue", "Net Profit", "PAT", "EPS"):
        found = []
        _scan_metric(data, kw, found)
        if found:
            print(f"  [{kw}] matched {len(found)} node(s); first:")
            print("    " + json.dumps(found[0], default=str)[:400])
        else:
            print(f"  [{kw}] NOT FOUND by label heuristic (see raw dump below)")

    # raw structure for manual verification (trimmed)
    print("  --- raw data (trimmed to 3500 chars) ---")
    print("  " + json.dumps(data, indent=2, default=str)[:3500].replace("\n", "\n  "))


def main():
    print("Upstox Company Fundamentals — Income Statement spot-check (READ-ONLY GET)")
    if not UPSTOX_ACCESS_TOKEN:
        print("FATAL: UPSTOX_ACCESS_TOKEN not set in .env")
        print("  Fix: run scripts/generate_token.py to generate a token, then re-run.")
        sys.exit(1)
    print(f"Token present: {UPSTOX_ACCESS_TOKEN[:6]}...{UPSTOX_ACCESS_TOKEN[-4:]} (len {len(UPSTOX_ACCESS_TOKEN)})")
    for name, isin in TEST.items():
        check_ticker(name, isin)
    print("\nDone (read-only; no orders, no writes).")


if __name__ == "__main__":
    main()
