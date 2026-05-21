"""
Tier-0F Poller -- 2-min material filing dispatcher.

Reads filings_log for material rows (is_material=true, material_score>=6,
picked_by_tier0f=false), dispatches Tier-2F via GitHub Actions
workflow_dispatch API.

Triggered by cron-job.org every 2 minutes (PRIMARY) + GH internal cron
every 10 minutes (FALLBACK) per S2.0 architectural pattern.

Phase 5 Batch B deliverable D1.
"""

import os
import sys
import logging
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

from utils.supabase_client import get_client

load_dotenv(override=True)

# Module-level constants
GH_REPO = "goelvipulvg-max/stockmarket-brain"
TIER2F_WORKFLOW = "tier2f.yml"
LOOKBACK_MINUTES = 30
BATCH_LIMIT = 10
MIN_SCORE = 6

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s -- %(levelname)s -- %(message)s'
)
log = logging.getLogger("tier0f_poller")


def _query_pending_filings() -> list[dict]:
    """Returns list of {id, symbol, event_type, material_score, classified_at}
    for unprocessed material filings."""
    sb = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)).isoformat()

    r = sb.table('filings_log')\
        .select('id, symbol, event_type, material_score, classified_at')\
        .eq('is_material', True)\
        .gte('material_score', MIN_SCORE)\
        .eq('picked_by_tier0f', False)\
        .gte('classified_at', cutoff)\
        .order('classified_at', desc=False)\
        .limit(BATCH_LIMIT)\
        .execute()
    return r.data or []


def _dispatch_tier2f(filing_id: int) -> bool:
    """Calls GitHub Actions workflow_dispatch on tier2f.yml with filing_id input.
    Returns True if dispatch accepted (HTTP 204)."""
    pat = os.getenv("GITHUB_PAT")
    if not pat:
        log.error("GITHUB_PAT missing in environment")
        return False

    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{TIER2F_WORKFLOW}/dispatches"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": "main", "inputs": {"filing_id": str(filing_id)}}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code == 204:
            log.info(f"Dispatched Tier-2F for filing_id={filing_id}")
            return True
        log.error(f"Dispatch failed for filing_id={filing_id}: HTTP {r.status_code} -- {r.text[:200]}")
        return False
    except requests.RequestException as e:
        log.error(f"Dispatch exception for filing_id={filing_id}: {e}")
        return False


def _mark_picked(filing_id: int) -> bool:
    """Marks filing as picked_by_tier0f=true and picked_at=NOW().
    Returns True on success."""
    sb = get_client()
    try:
        sb.table('filings_log').update({
            'picked_by_tier0f': True,
            'picked_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', filing_id).execute()
        return True
    except Exception as e:
        log.error(f"Mark picked failed for filing_id={filing_id}: {e}")
        return False


def main(dry_run: bool = False) -> int:
    """Main poller entry point. Returns exit code (0 success, 1 partial failure)."""
    log.info(f"Tier-0F poller starting (dry_run={dry_run})")

    pending = _query_pending_filings()
    log.info(f"Found {len(pending)} pending filings")

    if not pending:
        return 0

    success_count = 0
    fail_count = 0

    for filing in pending:
        fid = filing['id']
        symbol = filing.get('symbol', 'UNKNOWN')
        log.info(f"Processing filing_id={fid} symbol={symbol}")

        if dry_run:
            log.info(f"[DRY RUN] Would dispatch Tier-2F for filing_id={fid}")
            success_count += 1
            continue

        if _dispatch_tier2f(fid) and _mark_picked(fid):
            success_count += 1
        else:
            fail_count += 1
            log.warning(f"Failed to dispatch+mark filing_id={fid}")

    log.info(f"Poller complete: {success_count} success, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    sys.exit(main(dry_run=dry))
