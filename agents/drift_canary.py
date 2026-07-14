"""Verifier Drift Canary (O-6) -- weekly offline probe of the DeepSeek verifier.

Why: the serving stack behind the `deepseek-v4-flash` alias changed materially
between 2026-05-29 and 2026-07-07 with zero commits on our side (O-3 A/B,
reports/2026-07-14-thinking-ab.md) -- it caused the N-1 starvation AND shifted
the verifier's effective temperament. It took ~6 weeks to notice. This canary
re-runs 5 FROZEN verifier prompts (data/drift_canary/cases/) against the
production call config and compares the verdict/agreement/confidence/bias
fingerprint plus token telemetry against a stored baseline
(data/drift_canary/baseline.json).

Design contract (approved 2026-07-14):
- Inputs are frozen verbatim prompt strings -- NO re-rendering, no chart/DB
  reads at run time. A prompt-template change (e.g. O-2) requires a manual,
  approved re-baseline with a new baseline_version. Never automatic.
- 3 repeats per case at temperature 0.3; comparisons on the MEDIAN (majority
  for categorical fields).
- States: GREEN (exit 0) / RED drift (exit 1) / CANARY FAILED (exit 2).
  GREEN is sent ONLY when all 5 cases produced >=2/3 valid parsed responses
  AND the comparator ran. The canary's own death is a distinct loud alert,
  never silence, never a false GREEN.
- Telegram -> TELEGRAM_TIER3_CHANNEL (ops channel, health_monitor precedent).
  DRIFT_CANARY_DRY_RUN=true prints instead of sending.
- Run history -> Supabase drift_canary_runs (dedicated table; fail-open:
  an insert failure never blocks the alert path).

This module deliberately does NOT import call config from utils/ai_consensus.py
(live trading path stays untouched); the constants below MIRROR the production
verifier config at utils/ai_consensus.py:18-29 and must be kept in sync if N-1
ever changes.

Usage:
  python -m agents.drift_canary                     # weekly check vs baseline
  python -m agents.drift_canary --capture-baseline  # one-time baseline (manual)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

from openai import OpenAI

from utils.ai_consensus import determine_consensus
from utils.json_extract import extract_json
from utils.telegram_client import send_message

# --- Config mirror of the production verifier call (ai_consensus.py:18-29) ---
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.3
MAX_TOKENS = 2500
EXTRA_BODY = {"thinking": {"type": "disabled"}}
CONFIG_LABEL = "prod_nothink_2500"

REPEATS = 3
# Alert thresholds (median vs baseline) -- design doc 2026-07-14 (d).
AGR_RED = 15        # |median agreement - baseline| >= 15 -> case RED
CONF_RED = 10       # |median confidence - baseline| >= 10 -> case RED
AGR_YELLOW = 10     # 10..14 -> case YELLOW
TOKENS_RED_MULT = 2.0   # median completion tokens >= 2x baseline -> case RED
# Pole cases: a median verdict flip on either one alone makes the canary RED.
POLE_CASES = {"gillette_may27", "synth_maxbull"}

_BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "drift_canary"
CASES_DIR = _BASE_DIR / "cases"
BASELINE_PATH = _BASE_DIR / "baseline.json"

DRY_RUN = os.getenv("DRIFT_CANARY_DRY_RUN", "false").strip().lower() == "true"

deepseek = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
                  base_url="https://api.deepseek.com")


# ---------------------------------------------------------------------------
# Probe calls
# ---------------------------------------------------------------------------

def call_once(prompt: str) -> dict:
    """One verifier call. Never raises -- errors come back inside the dict."""
    out = {"verdict": None, "agreement_score": None, "my_confidence": None,
           "my_directional_bias": None, "finish_reason": None,
           "prompt_tokens": None, "completion_tokens": None, "reasoning_tokens": None,
           "latency_ms": None, "empty_content": True, "parse_ok": False, "error": None}
    try:
        t0 = time.perf_counter()
        resp = deepseek.chat.completions.create(
            model=MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
            extra_body=EXTRA_BODY,
            messages=[{"role": "user", "content": prompt}],
        )
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        choice = resp.choices[0]
        out["finish_reason"] = choice.finish_reason
        usage = resp.usage
        out["prompt_tokens"] = usage.prompt_tokens
        out["completion_tokens"] = usage.completion_tokens
        details = getattr(usage, "completion_tokens_details", None)
        out["reasoning_tokens"] = getattr(details, "reasoning_tokens", None) if details else None
        content = choice.message.content or ""
        out["empty_content"] = not content.strip()
        if not out["empty_content"]:
            parsed = extract_json(content)
            out["parse_ok"] = True
            for k in ("verdict", "agreement_score", "my_confidence", "my_directional_bias"):
                out[k] = parsed.get(k)
    except Exception as e:  # transport, auth, JSON -- all land here
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def run_case(case: dict) -> dict:
    """REPEATS calls for one frozen case. Adds gate decision per valid repeat."""
    repeats = []
    for i in range(REPEATS):
        r = call_once(case["prompt"])
        r["repeat_idx"] = i
        if r["parse_ok"]:
            fp = {k: r[k] for k in ("verdict", "agreement_score",
                                    "my_confidence", "my_directional_bias")}
            r["decision"], r["decision_reason"] = determine_consensus(
                case["analyst_output"], fp)
        else:
            r["decision"], r["decision_reason"] = None, r["error"] or "empty/unparseable"
        repeats.append(r)
        print(f"  [{case['case_name']}] repeat {i}: "
              f"{r['verdict']}/{r['agreement_score']}/{r['my_directional_bias']}/{r['my_confidence']} "
              f"decision={r['decision']} fin={r['finish_reason']} "
              f"ctok={r['completion_tokens']} rtok={r['reasoning_tokens']} "
              f"{r['latency_ms']}ms" + (f" ERROR={r['error']}" if r["error"] else ""))
    return {"case_name": case["case_name"], "repeats": repeats}


# ---------------------------------------------------------------------------
# Median fingerprint + comparison
# ---------------------------------------------------------------------------

def _median(nums):
    nums = sorted(n for n in nums if n is not None)
    return nums[len(nums) // 2] if nums else None


def _majority(vals):
    vals = [v for v in vals if v is not None]
    for v in set(vals):
        if vals.count(v) >= 2:
            return v
    return None  # no 2/3 majority -> instability


def summarize_case(case_run: dict):
    """Median fingerprint across valid repeats; None if the case is INVALID (<2 valid)."""
    valid = [r for r in case_run["repeats"] if r["parse_ok"]]
    if len(valid) < 2:
        return None
    return {
        "verdict": _majority([r["verdict"] for r in valid]),
        "agreement_score": _median([r["agreement_score"] for r in valid]),
        "my_confidence": _median([r["my_confidence"] for r in valid]),
        "my_directional_bias": _majority([r["my_directional_bias"] for r in valid]),
        "decision": _majority([r["decision"] for r in valid]),
        "median_completion_tokens": _median([r["completion_tokens"] for r in valid]),
        "n_valid": len(valid),
        "n_reasoning": sum(1 for r in valid if (r["reasoning_tokens"] or 0) > 0),
    }


def compare_case(name: str, cur: dict | None, base: dict):
    """Returns (status, reasons). status in GREEN/YELLOW/RED/INVALID."""
    if cur is None:
        return "INVALID", ["<2/3 valid responses (transport or parse failure)"]
    reasons = []
    if cur["verdict"] != base["verdict"] or cur["verdict"] is None:
        reasons.append(f"verdict {base['verdict']} -> {cur['verdict']}")
    if cur["my_directional_bias"] != base["my_directional_bias"] or cur["my_directional_bias"] is None:
        reasons.append(f"bias {base['my_directional_bias']} -> {cur['my_directional_bias']}")
    if cur["decision"] != base["decision"]:
        reasons.append(f"gate decision {base['decision']} -> {cur['decision']}")
    d_agr = abs((cur["agreement_score"] or 0) - (base["agreement_score"] or 0))
    if d_agr >= AGR_RED:
        reasons.append(f"agreement {base['agreement_score']} -> {cur['agreement_score']} (|d|={d_agr})")
    d_conf = abs((cur["my_confidence"] or 0) - (base["my_confidence"] or 0))
    if d_conf >= CONF_RED:
        reasons.append(f"confidence {base['my_confidence']} -> {cur['my_confidence']} (|d|={d_conf})")
    if cur["n_reasoning"] >= 2:
        reasons.append(f"reasoning tokens present in {cur['n_reasoning']}/3 repeats (thinking-disable ignored?)")
    base_tok = base.get("median_completion_tokens") or 0
    if base_tok and (cur["median_completion_tokens"] or 0) >= TOKENS_RED_MULT * base_tok:
        reasons.append(f"completion tokens {base_tok} -> {cur['median_completion_tokens']} (>= {TOKENS_RED_MULT}x)")
    if reasons:
        return "RED", reasons
    if AGR_YELLOW <= d_agr < AGR_RED:
        return "YELLOW", [f"agreement moved {d_agr} (noise band)"]
    return "GREEN", []


# ---------------------------------------------------------------------------
# Persistence (fail-open) + alerting
# ---------------------------------------------------------------------------

def insert_history(case_run: dict, drift_status: str, baseline_version: str) -> None:
    """Append raw repeats to Supabase drift_canary_runs. Fail-open by contract."""
    try:
        from utils.supabase_client import get_client
        sb = get_client()
        rows = []
        for r in case_run["repeats"]:
            rows.append({
                "case_name": case_run["case_name"], "repeat_idx": r["repeat_idx"],
                "model": MODEL, "config_label": CONFIG_LABEL,
                "verdict": r["verdict"], "agreement_score": r["agreement_score"],
                "my_confidence": r["my_confidence"],
                "my_directional_bias": r["my_directional_bias"],
                "decision": r["decision"], "finish_reason": r["finish_reason"],
                "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
                "reasoning_tokens": r["reasoning_tokens"], "latency_ms": r["latency_ms"],
                "empty_content": r["empty_content"], "parse_ok": r["parse_ok"],
                "drift_status": drift_status, "baseline_version": baseline_version,
            })
        sb.table("drift_canary_runs").insert(rows).execute()
        print(f"  [history] {len(rows)} rows inserted for {case_run['case_name']}")
    except Exception as e:
        print(f"  [history] insert failed: {e} -- continuing (history is non-critical)")


def notify(text: str) -> bool:
    """Telegram to the ops channel; DRY_RUN prints instead. Returns delivery bool."""
    if DRY_RUN:
        print("\n[DRY_RUN] would send Telegram:\n" + text)
        return True
    return send_message(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_TIER3_CHANNEL", ""),
        text=text,
        parse_mode="",
    )


def fmt_case_line(name, base, cur, status, reasons):
    b = f"{base['verdict']}/{base['agreement_score']}/{base['my_directional_bias']}/{base['my_confidence']}"
    c = ("INVALID" if cur is None else
         f"{cur['verdict']}/{cur['agreement_score']}/{cur['my_directional_bias']}/{cur['my_confidence']}")
    line = f"{name}: {b} -> {c} [{status}]"
    if reasons:
        line += " | " + "; ".join(reasons)
    return line


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_cases():
    cases = []
    for p in sorted(CASES_DIR.glob("*.json")):
        cases.append(json.loads(p.read_text(encoding="utf-8")))
    if not cases:
        raise RuntimeError(f"no frozen cases found in {CASES_DIR}")
    return cases


def capture_baseline(case_runs):
    """Write baseline.json from this run's medians. Refuses on any INVALID case."""
    baseline = {"baseline_version": datetime.now(timezone.utc).date().isoformat(),
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "model": MODEL, "config_label": CONFIG_LABEL, "cases": {}}
    for cr in case_runs:
        s = summarize_case(cr)
        if s is None or s["verdict"] is None or s["my_directional_bias"] is None:
            raise RuntimeError(f"cannot baseline {cr['case_name']}: unstable/invalid repeats")
        s["repeats_raw"] = [{k: r[k] for k in ("verdict", "agreement_score", "my_confidence",
                                               "my_directional_bias", "decision",
                                               "completion_tokens", "reasoning_tokens",
                                               "latency_ms", "finish_reason")}
                            for r in cr["repeats"]]
        baseline["cases"][cr["case_name"]] = s
    BASELINE_PATH.write_text(json.dumps(baseline, indent=1, ensure_ascii=False),
                             encoding="utf-8")
    print(f"\n[baseline] written -> {BASELINE_PATH} (version {baseline['baseline_version']})")


def main():
    ap = argparse.ArgumentParser(description="Tier-2F verifier drift canary (O-6)")
    ap.add_argument("--capture-baseline", action="store_true",
                    help="capture a new baseline instead of comparing (manual, approved runs only)")
    args = ap.parse_args()

    try:
        cases = load_cases()
        print(f"[canary] {len(cases)} frozen cases, config={CONFIG_LABEL}, "
              f"repeats={REPEATS}, mode={'BASELINE-CAPTURE' if args.capture_baseline else 'compare'}")

        case_runs = [run_case(c) for c in cases]

        if args.capture_baseline:
            capture_baseline(case_runs)
            for cr in case_runs:
                insert_history(cr, "BASELINE", datetime.now(timezone.utc).date().isoformat())
            return 0

        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        statuses, lines = {}, []
        for cr in case_runs:
            name = cr["case_name"]
            base = baseline["cases"].get(name)
            if base is None:
                statuses[name] = ("INVALID", ["case missing from baseline -- re-baseline needed"])
                lines.append(f"{name}: NOT IN BASELINE {baseline['baseline_version']}")
                continue
            cur = summarize_case(cr)
            status, reasons = compare_case(name, cur, base)
            statuses[name] = (status, reasons)
            lines.append(fmt_case_line(name, base, cur, status, reasons))

        n_invalid = sum(1 for s, _ in statuses.values() if s == "INVALID")
        n_red = sum(1 for s, _ in statuses.values() if s == "RED")
        pole_flip = any(
            s == "RED" and any(r.startswith("verdict") for r in reasons)
            for name, (s, reasons) in statuses.items() if name in POLE_CASES
        )

        if n_invalid >= 2:
            overall = "FAILED"       # transport-level death, not drift
        elif pole_flip or n_red >= 2:
            overall = "RED"
        elif n_red == 1 or any(s in ("YELLOW", "INVALID") for s, _ in statuses.values()):
            overall = "GREEN_WITH_WARNINGS"
        else:
            overall = "GREEN"

        for cr in case_runs:
            insert_history(cr, statuses[cr["case_name"]][0], baseline["baseline_version"])

        body = "\n".join(lines)
        print(f"\n[canary] overall={overall}\n{body}")

        if overall == "FAILED":
            sent = notify("CANARY FAILED -- verifier drift canary could not get valid "
                          f"responses ({n_invalid}/{len(cases)} cases invalid). DeepSeek API/key "
                          f"problem likely. NOT a drift verdict.\n{body}")
            return 2 if sent else 2
        if overall == "RED":
            sent = notify("DRIFT ALERT (RED) -- DeepSeek verifier fingerprint moved vs "
                          f"baseline {baseline['baseline_version']}.\n{body}\n"
                          "Action: do not trust consensus verdicts blindly; re-run the O-3-style "
                          "A/B (reports/2026-07-14-thinking-ab.md) and consider re-baselining.")
            return 1 if sent else 1
        warn = "" if overall == "GREEN" else " (with warnings -- see run log)"
        sent = notify(f"Drift canary GREEN{warn} -- {len(cases) - n_invalid}/{len(cases)} cases "
                      f"match baseline {baseline['baseline_version']}; tokens nominal.")
        if not sent:
            print("[canary] GREEN ping failed to deliver -- exiting non-zero for GH visibility")
            return 1
        return 0

    except Exception as e:
        # The canary's own death must be loud: distinct alert, non-zero exit, never GREEN.
        msg = f"CANARY FAILED -- unhandled error: {type(e).__name__}: {e}"
        print(f"[canary] {msg}")
        try:
            notify(msg)
        except Exception as e2:
            print(f"[canary] alert also failed: {e2}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
