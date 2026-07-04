"""Backfill nse500_membership: point-in-time NIFTY500 join dates for fix (a) survivorship.

Sets member_since per current member: floor 2024-01-01 by default (incl. the Mar-2024
residual, which is drop-identical to floor), overridden by the dated joiner cohorts.
Default DRY-RUN; pass --apply to write. Idempotent via ON CONFLICT(symbol) DO UPDATE.

Cohort provenance:
  SEP24 - official niftyindices press release ind_prs23082024.pdf  (eff 2024-09-30)
  MAR25 - official niftyindices press release ind_prs21022025.pdf  (eff 2025-03-28)
  SEP25 - Wayback CSV diff 2025-08-15 -> 2026-01-07               (eff 2025-09-30)
  MAR26 - Wayback CSV diff 2026-01-07 -> 2026-05-02               (eff 2026-03-28)
NSE DUMMY demerger placeholders (DUMMYHDLVR, DUMMYVEDL1-4) were removed from the raw
Wayback diffs; they are not real members and are absent from watchlist/event_outcomes.
"""
import os
import sys
import argparse
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.neon_client import get_neon_connection

FLOOR = date(2024, 1, 1)

SEP24 = [  # eff 2024-09-30, source 'circular'  (27 official inclusions)
    "AADHARHFC", "ABSLAMC", "ANANTRAJ", "BASF", "BHARTIHEXA", "GRINFRA", "GET&D",
    "GODIGIT", "GODREJAGRO", "IFCI", "INDGN", "IREDA", "INOXINDIA", "JPPOWER",
    "JKTYRE", "JYOTICNC", "KIRLOSBROS", "KIRLOSENG", "NETWEB", "NEWGEN", "PFIZER",
    "PTCIL", "SCI", "TBOTEK", "TECHNOE", "DBREALTY", "VINATIORGA",
]
MAR25 = [  # eff 2025-03-28, source 'circular'  (30 official inclusions)
    "ACMESOLAR", "AFCONS", "ALIVUS", "AIIL", "BAJAJHFL", "FIRSTCRY", "DCMSHRIRAM",
    "GRAVITA", "HYUNDAI", "IGIL", "IKS", "JSWHL", "LTFOODS", "NAVA", "NEULANDLAB",
    "NIVABUPA", "NTPCGREEN", "OLAELEC", "PGEL", "PREMIERENE", "RPOWER", "SAGILITY",
    "SAILIFE", "SARDAEN", "SWIGGY", "TARIL", "VMM", "WAAREEENER", "WOCKPHARMA", "ZENTEC",
]
SEP25 = [  # eff 2025-09-30, source 'wayback'  (22 real; DUMMYHDLVR removed)
    "ABLBL", "AEGISVOPAK", "AGARWALEYE", "AKZOINDIA", "ATHERENERG", "BLUEJET",
    "CHOICEIN", "ENRIN", "FORCEMOT", "HEXT", "ITCHOTELS", "JSWCEMENT", "KSB",
    "MAHSCOOTER", "NUVOCO", "ONESOURCE", "PGHH", "RELINFRA", "SWANCORP", "THELEELA",
    "TMPV", "VENTIVE",
]
MAR26 = [  # eff 2026-03-28, source 'wayback'  (33 real; DUMMYVEDL1-4 removed)
    "ABDL", "ACUTAAS", "ANTHEM", "ANURAS", "BELRISE", "CANHLIFE", "CARTRADE",
    "CEMPRO", "CPPLUS", "EMMVEE", "GABRIEL", "GALLANTT", "GROWW", "HDBFS", "ICICIAMC",
    "JAINREC", "JSWDULUX", "LENSKART", "LGEINDIA", "LTM", "MEESHO", "PARADEEP",
    "PINELABS", "PIRAMALFIN", "PWL", "SPLPETRO", "TATACAP", "TEGA", "TENNIND",
    "TMCV", "TRAVELFOOD", "URBANCO", "ZYDUSWELL",
]

# Oldest first so the most recent join wins on any overlap (leave-rejoin, e.g. DCMSHRIRAM)
COHORTS = [
    ("circular", date(2024, 9, 30), SEP24),
    ("circular", date(2025, 3, 28), MAR25),
    ("wayback",  date(2025, 9, 30), SEP25),
    ("wayback",  date(2026, 3, 28), MAR26),
]


def _bare(sym):
    return (sym or "").strip().upper().replace(".NS", "").replace(".ns", "")


def build_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM nse500_watchlist")
        members = sorted({_bare(r[0]) for r in cur.fetchall()})
    mapping = {m: (FLOOR, "floor") for m in members}   # Mar-2024 residual collapses into floor
    unknown = []
    for source, msd, names in COHORTS:
        for raw in names:
            s = _bare(raw)
            if s in mapping:
                mapping[s] = (msd, source)
            else:
                unknown.append((s, source, str(msd)))
    rows = [(s, msd, src) for s, (msd, src) in mapping.items()]
    return rows, unknown


def summarize(rows):
    by_src = Counter(src for _, _, src in rows)
    by_date = Counter(str(msd) for _, msd, _ in rows)
    print("Per-source:      ", dict(by_src))
    print("Per-member_since:", dict(sorted(by_date.items())))
    print("Total rows:      ", len(rows))


def main(apply_changes):
    conn = get_neon_connection()
    try:
        rows, unknown = build_rows(conn)
        print("=" * 60)
        print("nse500_membership backfill -", "APPLY" if apply_changes else "DRY-RUN")
        print("=" * 60)
        summarize(rows)
        if unknown:
            print(f"\nNOTE: {len(unknown)} cohort symbols not in current watchlist "
                  f"(rename/churn; skipped):")
            for s, src, msd in unknown:
                print(f"   {s} ({src} {msd})")
        if not apply_changes:
            print("\nDRY-RUN: no DB writes. Pass --apply to write.")
            return
        with conn.cursor() as cur:
            for s, msd, src in rows:
                cur.execute(
                    "INSERT INTO nse500_membership (symbol, member_since, source) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (symbol) DO UPDATE "
                    "SET member_since = EXCLUDED.member_since, source = EXCLUDED.source",
                    (s, msd, src),
                )
        conn.commit()
        print(f"\nAPPLY: upserted {len(rows)} rows.")
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to DB (default: dry-run)")
    main(ap.parse_args().apply)
