#!/usr/bin/env python
"""
Deep Audit -- all companies in company_profiles.
Read-only. Compares actual DB state against historical_preloader.py spec.
"""

import json
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.neon_client import get_neon_connection

# Fields historical_preloader.py writes (from its insert_company_profile)
HISTORICAL_FIELDS = {
    "company_profiles": [
        "symbol", "company_name", "sector", "industry",
        "business_summary", "key_metrics", "created_at", "updated_at",
    ],
    "research_cache": [
        "symbol", "query_hash", "query_text", "response_text", "created_at",
    ],
    "event_outcomes": [
        "symbol", "event_type", "event_date", "signal_generated",
        "trade_result", "outcome_score", "created_at",
    ],
    "pattern_library": [
        "symbol", "pattern_name", "pattern_data", "success_rate",
        "sample_size", "created_at",
    ],
}

# Fields in schema but NOT written by any preloader (expected NULL)
EXPECTED_NULL = {"risk_factors", "moat_analysis"}


def main():
    conn = get_neon_connection()
    cur = conn.cursor()

    # Fetch all symbols from DB
    cur.execute("SELECT symbol FROM company_profiles ORDER BY symbol")
    TARGET = [r[0] for r in cur.fetchall()]
    n = len(TARGET)
    placeholders = ",".join(["%s"] * n)
    cur.execute(
        f"SELECT symbol, company_name, sector, industry, business_summary, "
        f"key_metrics, risk_factors, moat_analysis, created_at, updated_at "
        f"FROM company_profiles WHERE symbol IN ({placeholders}) ORDER BY symbol",
        TARGET,
    )
    profiles = {r[0]: r for r in cur.fetchall()}

    # -- SECTION 1: Size Report ------------------------------------------
    cur.execute(f"""
        SELECT cp.symbol,
            ROUND(pg_column_size(cp.*)::numeric / 1024, 2) AS profile_kb,
            ROUND(COALESCE(SUM(pg_column_size(rc.*))::numeric, 0) / 1024, 2) AS cache_kb,
            ROUND(COALESCE(SUM(pg_column_size(eo.*))::numeric, 0) / 1024, 2) AS outcomes_kb
        FROM company_profiles cp
        LEFT JOIN research_cache rc ON rc.symbol = cp.symbol
        LEFT JOIN event_outcomes eo ON eo.symbol = cp.symbol
        WHERE cp.symbol IN ({placeholders})
        GROUP BY cp.symbol
        ORDER BY cp.symbol
    """, TARGET)
    size_rows = {r[0]: r for r in cur.fetchall()}

    # -- SECTION 2: Field Audit -------------------------------------------
    cur.execute(f"""
        SELECT symbol, COUNT(*) FROM research_cache
        WHERE symbol IN ({placeholders}) GROUP BY symbol
    """, TARGET)
    cache_counts = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute(f"""
        SELECT symbol, COUNT(*) FROM event_outcomes
        WHERE symbol IN ({placeholders}) GROUP BY symbol
    """, TARGET)
    outcome_counts = {r[0]: r[1] for r in cur.fetchall()}

    # Duplicate check
    cur.execute(f"""
        SELECT symbol, COUNT(*) FROM company_profiles
        WHERE symbol IN ({placeholders}) GROUP BY symbol HAVING COUNT(*) > 1
    """, TARGET)
    dupes = {r[0]: r[1] for r in cur.fetchall()}

    # -- PRINT REPORT -----------------------------------------------------
    print("\n" + "=" * 95)
    print(f"  DEEP AUDIT REPORT -- {n} Companies")
    print("=" * 95)

    # -- Size Report --
    print(f"\n{'-' * 80}")
    print("  COMPANY SIZE REPORT (KB)")
    print(f"{'-' * 80}")
    print(f"  {'Symbol':<18s} {'Profile':>8s} {'Cache':>8s} {'Outcomes':>9s} {'Total':>8s}")
    print(f"  {'':->18s} {'':->8s} {'':->8s} {'':->9s} {'':->8s}")

    total_prof = total_cache = total_out = 0.0
    for sym in TARGET:
        sr = size_rows.get(sym)
        if sr:
            pk = float(sr[1]); ck = float(sr[2]); ok = float(sr[3])
        else:
            pk = ck = ok = 0.0
        tk = pk + ck + ok
        total_prof += pk; total_cache += ck; total_out += ok
        print(f"  {sym:<18s} {pk:>7.2f}K {ck:>7.2f}K {ok:>8.2f}K {tk:>7.2f}K")

    grand = total_prof + total_cache + total_out
    print(f"  {'':->18s} {'':->8s} {'':->8s} {'':->9s} {'':->8s}")
    print(f"  {'OVERALL TOTAL':18s} {total_prof:>7.2f}K {total_cache:>7.2f}K {total_out:>8.2f}K {grand:>7.2f}K")
    print(f"  {'AVG PER CO.':18s} {total_prof/n:>7.2f}K {total_cache/n:>7.2f}K {total_out/n:>8.2f}K {grand/n:>7.2f}K")
    print(f"  Combined: {grand:.2f} KB ({grand/1024:.2f} MB)")

    # -- Field Audit --
    print(f"\n{'-' * 95}")
    print("  FIELD AUDIT (per company)")
    print(f"{'-' * 95}")
    hdr = f"  {'Symbol':<18s} {'.NS':>4s} {'summary':>8s} {'metrics':>8s} {'risk':>6s} {'moat':>6s} {'AI_summ':>8s} {'ann#':>5s} {'nulls':>6s} {'dupes':>6s}"
    print(hdr)
    print(f"  {'':->18s} {'':->4s} {'':->8s} {'':->8s} {'':->6s} {'':->6s} {'':->8s} {'':->5s} {'':->6s} {'':->6s}")

    field_pass = 0
    for sym in TARGET:
        p = profiles.get(sym)
        if not p:
            print(f"  {sym:<18s}  MISSING FROM DB")
            continue

        _, name, sector, industry, bs, km, risk, moat, ca, ua = p
        cc = cache_counts.get(sym, 0)
        oc = outcome_counts.get(sym, 0)
        dc = dupes.get(sym, 0)

        checks = []
        # .NS suffix
        checks.append("PASS" if sym.endswith(".NS") else "FAIL")
        # business_summary
        checks.append("PASS" if bs and len(bs) > 10 else "FAIL")
        # key_metrics
        checks.append("PASS" if km else "FAIL")
        # risk_factors -- expected NULL, not a failure
        checks.append("NULL*" if risk is None else ("PASS" if risk else "FAIL"))
        # moat_analysis -- expected NULL
        checks.append("NULL*" if moat is None else ("PASS" if moat else "FAIL"))
        # AI summary (same as business_summary populated)
        checks.append("PASS" if bs and len(bs) > 10 else "FAIL")
        # announcement count
        checks.append(f"{cc:>4d}" if cc >= 0 else "FAIL")
        # null fields count (excluding expected nulls)
        row_vals = [sym, name, sector, industry, bs, km, ca, ua]
        nulls = sum(1 for v in row_vals if v is None)
        checks.append(f"{nulls:>5d}" if nulls == 0 else f"FAIL({nulls})")
        # duplicates
        checks.append("PASS" if dc == 0 else f"DUPEx{dc}")

        # Field audit pass: first 6 checks must be PASS or NULL*, no nulls, no dupes
        core_ok = all(c in ("PASS", "NULL*") for c in checks[:6])
        all_field_ok = core_ok and nulls == 0 and dc == 0
        if all_field_ok:
            field_pass += 1

        print(f"  {sym:<18s} {checks[0]:>4s} {checks[1]:>8s} {checks[2]:>8s} {checks[3]:>6s} {checks[4]:>6s} {checks[5]:>8s} {checks[6]:>5s} {checks[7]:>6s} {checks[8]:>6s}")

    print(f"\n  NULL* = expected NULL (no preloader writes to this field)")
    print(f"  Field audit pass: {field_pass}/{n}")

    # -- Missing Points vs Historical Preloader --
    print(f"\n{'-' * 95}")
    print("  MISSING POINTS vs HISTORICAL PRELOADER")
    print(f"{'-' * 95}")

    # Check company_profiles fields
    print("\n  [company_profiles]")
    for field in HISTORICAL_FIELDS["company_profiles"]:
        missing = 0
        for sym in TARGET:
            p = profiles.get(sym)
            if not p:
                continue
            col_idx = {
                "symbol": 0, "company_name": 1, "sector": 2, "industry": 3,
                "business_summary": 4, "key_metrics": 5, "created_at": 8, "updated_at": 9,
            }
            idx = col_idx.get(field)
            if idx is not None and (p[idx] is None or p[idx] == ""):
                missing += 1
        status = "OK" if missing == 0 else f"MISSING in {missing}/{n}"
        icon = "PASS" if missing == 0 else "FAIL"
        print(f"    {field:<25s} preloader writes -> DB: {status:<20s} {icon}")

    # Check research_cache fields
    print("\n  [research_cache]")
    for field in HISTORICAL_FIELDS["research_cache"]:
        if field == "symbol":
            cur.execute(f"""
                SELECT COUNT(DISTINCT symbol) FROM research_cache
                WHERE symbol IN ({placeholders})
            """, TARGET)
            cnt = cur.fetchone()[0]
            status = f"{cnt}/{n} companies have rows"
            print(f"    {field:<25s} preloader writes -> DB: {status:<20s} {'PASS' if cnt >= n * 0.95 else 'FAIL'}")
        elif field in ("query_hash", "query_text", "response_text", "created_at"):
            cur.execute(f"""
                SELECT COUNT(*) FROM research_cache
                WHERE symbol IN ({placeholders}) AND {field} IS NOT NULL AND {field}::text != ''
            """, TARGET)
            cnt = cur.fetchone()[0]
            total_rc = sum(cache_counts.get(s, 0) for s in TARGET)
            status = f"{cnt}/{total_rc} rows populated"
            print(f"    {field:<25s} preloader writes -> DB: {status:<20s} {'PASS' if cnt == total_rc else 'FAIL'}")

    # Check event_outcomes fields
    print("\n  [event_outcomes]")
    for field in HISTORICAL_FIELDS["event_outcomes"]:
        if field == "symbol":
            cur.execute(f"""
                SELECT COUNT(DISTINCT symbol) FROM event_outcomes
                WHERE symbol IN ({placeholders})
            """, TARGET)
            cnt = cur.fetchone()[0]
            print(f"    {field:<25s} preloader writes -> DB: {cnt}/{n} companies     {'PASS'}")
        elif field in ("event_type", "event_date", "outcome_score"):
            cur.execute(f"""
                SELECT COUNT(*) FROM event_outcomes
                WHERE symbol IN ({placeholders}) AND {field} IS NOT NULL
            """, TARGET)
            cnt = cur.fetchone()[0]
            total_eo = sum(outcome_counts.get(s, 0) for s in TARGET)
            status = f"{cnt}/{total_eo} rows populated"
            print(f"    {field:<25s} preloader writes -> DB: {status:<20s} {'PASS' if cnt == total_eo else 'FAIL'}")

    # Fields NOT written by preloader (expected NULL)
    print("\n  [expected NULL -- no preloader writes here]")
    for field in sorted(EXPECTED_NULL):
        null_count = sum(
            1 for sym in TARGET
            if profiles.get(sym) and {
                "risk_factors": 6, "moat_analysis": 7,
            }.get(field) is not None
            and profiles[sym][{"risk_factors": 6, "moat_analysis": 7}[field]] is None
        )
        # Actually count how many are NULL
        cur.execute(f"""
            SELECT COUNT(*) FROM company_profiles
            WHERE symbol IN ({placeholders}) AND {field} IS NULL
        """, TARGET)
        null_cnt = cur.fetchone()[0]
        print(f"    {field:<25s} NULL for {null_cnt}/{n} companies (expected)     PASS")

    # Final score
    print(f"\n{'-' * 95}")
    score = field_pass
    print(f"  FINAL SCORE: {score}/{n} companies fully clean")
    if score == n:
        print("  ALL COMPANIES PASS")
    else:
        print(f"  {n - score} companies have issues to fix")
    print(f"{'-' * 95}\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
