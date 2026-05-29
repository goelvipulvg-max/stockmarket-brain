"""Volume confirmation metrics (pure computation, no I/O).

Derives volume signals from the chart snapshot produced by
utils.yfinance_chart.get_chart_snapshot (which now also returns `volume` and
`volume_series`):
  - avg_volume_20d  (mean of the last VOL_LOOKBACK sessions, NaN-scrubbed)
  - vol_vs_avg_ratio (latest volume / avg)
  - volume_spike    (ratio >= VOL_SPIKE_RATIO -- context-only flag, NOT gated)

compute_volume_structure() never raises and never hits the network -- any
missing / None / 0 / NaN / too-short input yields a None metric.
validate_volume_structure() turns the metrics into a deterministic skip verdict
for the (currently DORMANT) USE_VOLUME_GATE in tier2_fundamental. Reliability-gap #3.

Caveat: the "latest" bar is the last COMPLETED session, which for a filing may
predate the post-filing reaction -- so this is best read as an
active-trading / liquidity-heat proxy, not literal post-event reaction volume.

Insufficient-data policy: a None metric => the gate check is "no-opinion = pass".
The gate NEVER skips on missing data.
"""
from typing import Optional

# --- validate_volume_structure threshold (DORMANT; tune after the B2 backtest) ---
MIN_VOL_VS_AVG = 1.0      # latest volume must be >= 20d average (lenient: veto only dead names)

# --- compute_volume_structure params ---
VOL_LOOKBACK = 20         # trading days for the rolling average (matches SR window)
VOL_SPIKE_RATIO = 1.5     # context-only "spike" flag threshold (NOT gated)


def _safe_float(v) -> Optional[float]:
    """Coerce to float; reject None / non-numeric / NaN."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def compute_volume_structure(chart, vol_lookback=VOL_LOOKBACK) -> dict:
    """Derive volume metrics from a chart snapshot dict.

    `chart` needs `volume` (latest bar) and `volume_series` (raw list). Returns
    a dict with volume, avg_volume_20d, vol_vs_avg_ratio, volume_spike,
    vol_lookback. Never raises; missing/short/NaN inputs yield None metrics.
    """
    result = {
        "volume": None,
        "avg_volume_20d": None,
        "vol_vs_avg_ratio": None,
        "volume_spike": None,
        "vol_lookback": vol_lookback,
    }
    if not isinstance(chart, dict):
        return result

    result["volume"] = _safe_float(chart.get("volume"))

    series = chart.get("volume_series")
    if series:
        clean = [v for v in (_safe_float(x) for x in series) if v is not None]
        if len(clean) >= vol_lookback:
            window = clean[-vol_lookback:]
            avg = sum(window) / len(window)
            result["avg_volume_20d"] = avg
            if avg != 0 and result["volume"] is not None:
                ratio = result["volume"] / avg
                result["vol_vs_avg_ratio"] = ratio
                result["volume_spike"] = ratio >= VOL_SPIKE_RATIO

    return result


def validate_volume_structure(structure) -> dict:
    """Deterministic gate verdict from compute_volume_structure() output.

    DORMANT: only consulted when USE_VOLUME_GATE=true in tier2_fundamental.
    A None ratio => the check passes (no-opinion). `passes` is True iff the
    volume check passes.

    Returns {passes, checks: {volume_ok}, reasons}.
    """
    checks = {"volume_ok": True}
    reasons = []

    ratio = structure.get("vol_vs_avg_ratio")
    if ratio is not None and ratio < MIN_VOL_VS_AVG:
        checks["volume_ok"] = False
        reasons.append("low_volume")

    return {"passes": all(checks.values()), "checks": checks, "reasons": reasons}
