# Phase 5 Batch A — Tier-2F Fundamental Signal Generator + First Live AI Consensus Test

**Repo:** `goelvipulvg-max/stockmarket-brain`
**Branch:** `main` (direct commits — no feature branch)
**Reference:** `docs/stockmarket-brain-v3.1-master-plan.md` §7 (Phase 5)
**Predecessor:** Phase 4 Batch B (commits `f2f98e9` + `a21787b`)
**Successor (Batch B):** Tier-0F poller + Tier-3 duplicate-rule fix + integration (V5.1, V5.7, V5.8)
**Brief version:** v4 (FINAL — v3 + B1-B4 schema recon corrections)

---

## §0 Goal + Scope + Definition of Done

### Goal

Build `agents/tier2_fundamental.py` — the intelligent signal generator that turns a single material `filings_log` row into a sized paper trade via 2-AI consensus (Haiku 4.5 analyst + DeepSeek V4 Flash verifier). This is also the **first live API test of `determine_consensus()`** with Tier-2F's filing-analysis output shape (Phase 3 Batch B `2b17ad7` tested it with mock dicts only).

### Scope (IN)

- **Pre-build (§B0):** Modify `utils/ai_consensus.py` to accept `prompt_path` param (backward-compatible). Build `utils/pattern_insights_retriever.py`.
- **Build (§B1-B3):** `agents/tier2_fundamental.py`, `prompts/tier2f_analyst_v1.txt`, `prompts/tier2f_verifier_v1.txt`, `tests/test_phase5_batchA.py`
- **Verify (§V):** 5 gates (V5.2-V5.6) + Tier-1F regression check (no break from ai_consensus.py modification)
- **Telegram alerts** to existing "StockMarket-Brain Trades" channel (env var `TELEGRAM_TIER3_CHANNEL`) with `[TIER2F]` prefix — no new channel

### Scope (OUT — deferred to Batch B)

- `agents/tier0f_poller.py` — event-driven Supabase poller (cron `*/5 3-9 * * 1-5`)
- `agents/tier3_position_manager.py` modification — Gap 5 fix (one OPEN per `(ticker, source)`)
- V5.1 (Tier-0F dry run), V5.7 (Tier-3 duplicate rule), V5.8 (full live pipeline within 10 min)
- Production cron deployment (Tier-2F is manually invokable in Batch A; gets its automation in Batch B)
- Dedicated `TELEGRAM_TIER2F_CHANNEL` — defer to Phase 8 monitoring split

### Scope (OUT — schema tech debt for future)

- `paper_trades` has only `t1_hit` + `t2_hit` booleans. T3/T4 hit tracking columns missing. Tier-3 position manager handles hit tracking — not Tier-2F's concern. Future Phase 1 follow-up.
- `paper_trades` has no `t4_price`, no `full_reasoning` JSONB. Tier-2F stores T4 + full Haiku/Flash bundle inside `raw_signal` JSONB instead.

### Definition of Done (Batch A)

1. **Tier-1F regression check passes** — after ai_consensus.py modification, Tier-1F still produces a valid signal end-to-end with no code change at its callsites
2. All 5 gates (V5.2-V5.6) pass with REAL evidence — JSON output captured, DB row inspected, ledger reconciled
3. `python -m agents.tier2_fundamental --filing-id <N> --dry-run` returns a complete trade plan without errors on a known-good material filing
4. `python -m agents.tier2_fundamental --filing-id <N>` (live, no `--dry-run`) creates exactly one `paper_trades` row with `source='TIER2F'`, decrements `portfolio.cash_available` by exactly `position_size_rs`, and sends one Telegram alert
5. Three commits pushed to `main`: pre-build commit (ai_consensus + retriever utility), code commit (Tier-2F + prompts + tests), brief commit
6. No machine-local files committed; no throwaway recon/debug scripts committed

---

## §0.1 Document map (read in this order)

```
§0    Goal + Scope + DoD
§0.1  This map
§0.2  Read-before-starting          ← open deps, cron strategy, tomorrow morning checks
§0.3  Fallback mode reference        ← 4 execution paths
§0.4  Gate Reference Card            ← V5.2-V5.6 + Tier-1F regression
§0.5  v3 → v4 changes summary       ← what B1-B4 recon revised

§R    Recon (DONE 2026-05-20)        ← all 18 items + B1-B4 schema findings resolved

§B0   Pre-build modifications
§B0.0   Mini-recon (module globals + determine_consensus internals)
§B0.1   Modify utils/ai_consensus.py (prompt_path param, backward-compat)
§B0.2   Build utils/pattern_insights_retriever.py
§B0.3   Tier-1F regression check
§B0.4   Commit pre-build

§B1   Build — Prompts                ← analyst + verifier .txt files
§B2   Build — Pipeline (6 approval checkpoints)
§B3   Build — Tests

§V    Verify — Run gates + Tier-1F regression
§S    Ship — 3 commits (pre-build, code, brief)
§A    Working agreements
```

**Total expected build time:** 6-8 hours (§B0 ~1.5h, §B1 ~45min, §B2 ~3h, §B3 ~1h, §V ~30min, §S ~15min).

---

## §0.2 Read before starting

These are open items that **affect execution but are not blockers**. Re-read this every time you sit down to resume.

1. **V0.8 status — `filings_log.published_at` populated?** Column EXISTS in schema (B3 confirmed). Question is whether it's actually populated for new filings. **No Phase 5 Batch A impact** (Tier-2F reads `classified_at`, not `published_at`). Phase 6 after-hours engine will need this resolved. Track separately.

2. **cron strategy for Phase 5+ new crons (DECISION LOCKED):**
   - **Primary:** cron-job.org (trigger via GitHub `workflow_dispatch` API with PAT token)
   - **Fallback:** GitHub Actions internal cron at lower cadence (e.g. every 30 min)
   - **Reason:** GitHub Actions scheduled automation has shown unreliability — up to 15-min delays. For Tier-0F poller (`*/5` cadence), this is a dealbreaker.
   - **Applies to:** Tier-0F poller (Batch B), after-hours engine (Phase 6), Tier-4F nightly (Phase 7), health monitor (Phase 8). Batch A has no cron (manual entrypoint only).

3. **Existing 2 cron jobs (filing-memory-sync, filing-memory-backfill) — verify-first policy:**
   - Leave on GitHub Actions for now
   - Tomorrow morning (May 21) verification:
     - `SELECT count(*) FILTER (WHERE base_price IS NOT NULL) FROM filing_memory;` → expect ~144 (92 + 52 - 2 delisted)
     - GitHub Actions tab → "Filing Memory Backfill" first scheduled run (cron `0 19 * * 1-5` UTC = 00:30 IST May 21) — exit code 0
     - GitHub Actions tab → "Filing Memory Sync" all May 20 market-hour runs (~37 expected) — exit code 0 each
   - **Migration trigger:** any cron skipped or > 30 min late → migrate to cron-job.org PRIMARY.

4. **Tier-1F news-driven trade engine** (separate locked concept) — placement in v3.1 sequence still undecided. NOT part of Phase 5 Batch A or B.

5. **paper_trades hit-tracking gap** — only `t1_hit` + `t2_hit` exist. T3/T4 hit columns missing. Tracked as tech debt; resolves in a future Phase 1 follow-up. Tier-2F not affected.

---

## §0.3 Fallback mode reference

Four execution paths. Logged in `paper_trades.raw_signal.fallback_mode`. Critical to understand BEFORE reading §B2.3.

| Mode | Trigger | Behavior | Confidence used |
|------|---------|----------|-----------------|
| `None` (full consensus) | Both APIs succeed, no exception | Run `determine_consensus(haiku, flash)` from `utils/ai_consensus.py` | Avg of `haiku["confidence"]` + `flash["my_confidence"]` |
| `SOLO_DEEPSEEK` | Haiku throws `AnthropicError` | DeepSeek runs alone | `flash["my_confidence"] - 10` (haircut) |
| `SOLO_HAIKU` | DeepSeek throws `DeepSeekError`, Haiku succeeded | Haiku runs alone | `haiku["confidence"] - 10` (haircut) |
| `BOTH_DOWN` | Both APIs throw | Skip, no trade, log only | N/A |

**Decision threshold for SOLO modes:** `haircut_conf >= AVG_CONFIDENCE_FLOOR (65)` → PROCEED, else SKIP.

**Telegram alert mode tags:** `[TIER2F]` for full, `[TIER2F:SOLO_DSK]` and `[TIER2F:SOLO_HKU]` for solo modes.

---

## §0.4 Gate Reference Card

| Gate | What it proves | Real API? | DB write? | Built in | Tested in | Cleanup |
|------|----------------|-----------|-----------|----------|-----------|---------|
| **R1F** *(prerequisite)* | Tier-1F still works after ai_consensus.py modification | YES (1 run) | Whatever Tier-1F normally does | §B0.1 | §B0.3 | Tier-1F's own cleanup |
| **V5.2** | Haiku + Flash both return valid JSON matching expected schemas | YES (both) | No (dry-run) | §B2.3 | §B3.2 | N/A |
| **V5.3** | `paper_trades` insert with `source='TIER2F'`, all Phase 1 columns populated | YES | YES | §B2.4 | §B3.3 | DELETE trade + ledger entries + restore portfolio |
| **V5.4** | `portfolio.cash_available` decreased by exactly `position_size_rs`; ledger entry written | YES | YES | §B2.4 | §B3.3 | Same as V5.3 (combined test) |
| **V5.5** | SOLO_DEEPSEEK and SOLO_HAIKU fallbacks work when one API client is broken | Partial | No (dry-run) | §B2.3 | §B3.4 | N/A |
| **V5.6** | Disagreement → row in `agent_disagreements`, NO trade in `paper_trades` | YES (forced) | YES (disagreement only) | §B2.3 | §B3.5 | DELETE disagreement row |

**Out of scope (Batch B):** V5.1 (Tier-0F dry-run), V5.7 (Tier-3 duplicate rule), V5.8 (full live pipeline within 10 min).

---

## §0.5 v3 → v4 changes summary

§R B1-B4 SQL output (Supabase Dashboard, 2026-05-20) caught 3 schema mismatches. **If you read v3 already, this table is your diff.**

| Area | v3 assumption | B1-B4 reality | v4 resolution |
|------|---------------|---------------|---------------|
| **paper_trades target columns** | `target_1`, `target_2`, `target_3`, `target_4` | Schema has `target_price` (T1, Tier-2 legacy), `t2_price`, `t3_price`. NO `target_1`, NO `t4_price`, NO `t1_price`. | §B2.4 insert payload uses `target_price`/`t2_price`/`t3_price`. T4 (HIGH conviction only) stored in `raw_signal` JSONB. |
| **paper_trades reasoning JSONB** | New `full_reasoning` JSONB column | Schema has only `raw_signal` JSONB (Tier-2 legacy). NO `full_reasoning`. | §B2.4 uses `raw_signal` for Tier-2F's full bundle (haiku, flash, fallback_mode, conviction, avg_conf, t4_price, context_summary). Discrimination by `source='TIER2F'`. |
| **filings_log symbol field** | `filing["symbol_base"]` | Schema column is `symbol` (NOT `symbol_base`). `symbol_base` exists only in filing_memory (Phase 4 Batch B). | All filings_log reads use `filing["symbol"]`. When passing to `get_filing_memory_brief(symbol_base=...)`, pass the `symbol` value — Phase 4 Batch B's param name is unchanged. |
| **paper_trades hit tracking** | Assumed t1/2/3/4_hit booleans | Only `t1_hit` + `t2_hit` exist. T3/T4 hit tracking missing. | Out of scope for Batch A (Tier-3 handles hits). Tech debt noted in §0.2 #5. |
| **paper_trades composite UNIQUE** | Assumed `uniq_paper_trades_ticker_date_source` exists | ✅ Confirmed present (B1b) | No change |
| **portfolio initialized** | Assumed needs init | ✅ Row exists: cash=₹10L, deployed=0, open_positions=0 | No init needed |

---
## §0.6 Execution adjustments (post §B0.0 mini-recon)

§B0.0 mini-recon revealed 4 execution-level tweaks. Brief structure unchanged.

- §B0.1 param renamed: `prompt_path` → `prompt_template` (accepts text string, not file path)
- §B0.1 mechanism: keep module-level constants UNCHANGED, functions take optional text override
- §B0.3 Tier-1F regression: N/A — zero external callers of run_analyst/run_verifier found
- §B2.1/§B2.3: Tier-2F loads its prompts at module import; passes text via `prompt_template=`
- §B3.4 V5.5: monkeypatch attr names confirmed as `haiku_client` and `deepseek_client`
- §B2.4 trade_payload: `signal_date` removed during §B3 testing — it's a generated column in Supabase (caught via test V5.6 live insert error). `created_at` auto-populates instead.

## §R — Recon (DONE 2026-05-20)

Original recon brief in v2 (§R.1-§R.5) executed by Antigravity + Supabase Dashboard SQL Editor. All 18 items resolved.

### Recon resolutions (collapsed inline from v3 §0.5 + v4 §0.5)

**A1 — `utils/ai_consensus.py`:**
- `run_analyst(context) -> dict`, `run_verifier(context, analyst_output) -> dict`, `determine_consensus(haiku, flash) -> (str, str)`, `get_consensus(context) -> dict` (bundled wrapper — Tier-2F WON'T use this).
- Phase 3 prompts use horizon `INTRADAY/SWING/POSITIONAL` + confidence 1-100, no `stop_loss_pct`. Tier-2F needs OWN prompts → **§B0.1 adds `prompt_path` param.**
- SDK clients module-global at lines 22-23 → **§B0.0 confirms exact attr names for §B3.4 V5.5 monkeypatch.**

**A2 — `utils/yfinance_chart.py`:**
- `get_chart_snapshot(ticker) -> dict {ticker, last_close, rsi_14, macd, macd_signal, macd_hist, sma_50, sma_200, trend, support, resistance, close_series}`.
- `trend` values: `UPTREND/DOWNTREND/SIDEWAYS/INSUFFICIENT_DATA`.

**A3 — `utils/neon_fundamentals.py`:**
- `get_fundamentals(symbol) -> dict | None {sector, market_cap_cr, business_summary}`. Appends `.NS` internally. Returns None if not in NIFTY500 (implicit NIFTY500 check).

**A4 — `utils/fno_ban_list.py`:**
- `is_in_ban(symbol) -> bool` (NOT `is_banned`). 2-hour cache. Fail-open: exceptions → returns False.

**A5 — `utils/filing_memory_brief.py`:**
- `get_filing_memory_brief(symbol_base, current_event_type) -> str`. Param name is `symbol_base` (Phase 4 Batch B locked).

**A6 — `utils/position_sizer.py`** (NOT capital_ledger.py):
- `calculate_position_size(total_equity, cash_available, entry_price, stop_loss_price) -> Tuple[int, float]`.
- `utils/capital_ledger.py` has `get_current_portfolio()`, `deploy_capital(paper_trade_id, amount_rs)`, `release_capital()`.

**A7 — `utils/tiered_target_generator.py`:**
- `generate_targets(entry_price, direction, conviction) -> dict {t1, t2, t3, t4, stop_loss}`. `conviction` is string `"HIGH"/"MEDIUM"/"LOW"`. T4 only present when conviction="HIGH".
- Confidence → conviction map: ≥80=HIGH, ≥65=MEDIUM, <65=LOW.

**A8 — `get_relevant_patterns()`:**
- Function MISSING. `pattern_insights` table populated but no retrieval utility. **§B0.2 builds `utils/pattern_insights_retriever.py`.**

**B1 paper_trades schema (34 columns):**
- ✅ Phase 1 capital columns present: `source`, `quantity`, `position_size_rs`, `pnl_rs`, `horizon`, `max_holding_days`
- Target columns: `target_price` (T1), `t2_price`, `t3_price`. NO t4_price.
- Reasoning JSONB: `raw_signal` (Tier-2 legacy, Tier-2F reuses)
- Hit tracking: `t1_hit`, `t2_hit` only

**B1b paper_trades indexes:**
- ✅ Composite UNIQUE `uniq_paper_trades_ticker_date_source` present
- Plus pkey + 3 btree indexes (status, confidence, signal_date)

**B2 agent_disagreements (15 columns):**
- All master plan §4.4 columns present: id, created_at, filing_id, ticker, event_type, haiku_decision, haiku_confidence, haiku_reasoning, deepseek_decision, deepseek_confidence, deepseek_reasoning, final_action, backtest_outcome, actual_price_move_pct, full_context

**B3 filings_log (20 columns):**
- Identity/content: id, symbol (NOT symbol_base), company_name, exchange, event_type, summary, material_score, raw_title, source_url, published_at, classified_at
- Phase 0.2 additions: is_material, directional_bias, reasoning, picked_by_tier0f, picked_at, trade_confidence
- Plus: telegram_sent, url_hash, fo_checked
- Note: `published_at` column EXISTS (V0.8 question is about whether populated, not whether column exists)

**B4 portfolio:**
- ✅ Row 1 exists: starting=1000000, cash_available=1000000, deployed=0, total_equity=1000000, open_positions=0, updated_at=2026-05-19. V5.3/V5.4 can run cleanly.

**C1-C5 env vars:** All SET — ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, NEON_CONNECTION_STRING, TELEGRAM_BOT_TOKEN, TELEGRAM_TIER3_CHANNEL.

**D1 Tier-2 reference:** `agents/tier2_signals.py` `log_paper_trade()` at line 126 inserts 13 fields including `raw_signal` JSONB. NO `source` field in current Tier-2 inserts (relies on `source` column DEFAULT 'TIER2'). Tier-2F adds explicit `source='TIER2F'`. DO NOT modify Tier-2 file.

---

## §B0 — Pre-build modifications

Before touching `agents/tier2_fundamental.py`, three shared-infrastructure pieces must be in place.

### §B0.0 ✋ Mini-recon (5 minutes, read-only)

Antigravity reads `utils/ai_consensus.py` and reports:

1. **Module global client names at lines 22-23** — likely `_anthropic_client` / `_deepseek_client` or similar. Exact names needed for §B3.4 V5.5 monkeypatch.

2. **`determine_consensus(haiku, flash)` implementation** — view the function body, confirm which keys it reads from `haiku` and `flash` dicts. Expected per master plan §7.3:
   - From haiku: `tradeable`, `directional_bias`, `confidence`
   - From flash: `verdict`, `agreement_score`, `my_directional_bias`, `my_confidence`
   - Mismatches → §B1 prompts revise

3. **Callers of `run_analyst()` and `run_verifier()`:**
   ```powershell
   Select-String -Path "agents\*.py","scripts\*.py" -Pattern "run_analyst|run_verifier" -CaseSensitive
   ```
   List every callsite for §B0.3 regression check.

4. **Phase 3 prompt paths used by current `run_analyst()`/`run_verifier()`** — view imports + constants at top of `ai_consensus.py`. Note current hardcoded path.

Report all 4 items in chat. claude.ai will review before §B0.1.

### §B0.1 ✋ Modify utils/ai_consensus.py (backward-compatible)

**Goal:** Add `prompt_path: str | None = None` param to `run_analyst()` and `run_verifier()`. Default behavior unchanged.

**Pattern:**

```python
# Before (current):
def run_analyst(context: dict) -> dict:
    with open("prompts/tier1f_analyst_v1.txt") as f:   # or whatever the current path is
        prompt_template = f.read()
    # ... rest unchanged

# After (v4):
DEFAULT_ANALYST_PROMPT = "prompts/tier1f_analyst_v1.txt"   # match §B0.0 finding

def run_analyst(context: dict, prompt_path: str | None = None) -> dict:
    path = prompt_path or DEFAULT_ANALYST_PROMPT
    with open(path) as f:
        prompt_template = f.read()
    # ... rest unchanged
```

Same pattern for `run_verifier(context, analyst_output, prompt_path: str | None = None)`.

**No changes** to `determine_consensus()` or `get_consensus()`. Tier-2F won't use `get_consensus()` — needs fine-grained fallback control.

**Verify §B0.1:** `python -c "from utils.ai_consensus import run_analyst, run_verifier; print('OK')"` → no error.

### §B0.2 ✋ Build utils/pattern_insights_retriever.py

**File:** `utils/pattern_insights_retriever.py`

```python
"""Pattern insights retrieval — for injection into Tier-2F + Phase 6 + Phase 7 prompts.

Reads aggregated patterns from Supabase pattern_insights table (populated by
agents/memory_seed.py extract_initial_patterns()). Returns top N active patterns
matching event_type OR sector, ordered by confidence (HIGH > MEDIUM > LOW) then
sample_size desc.
"""
from typing import List, Dict
from utils.supabase_client import sb   # confirm exact path during §B0.0 (may be different module)


def get_relevant_patterns(event_type: str, sector: str, limit: int = 3) -> List[Dict]:
    """Return top `limit` active pattern_insights rows matching event_type OR sector.

    Args:
        event_type: e.g. "RESULTS", "M_AND_A", "DIVIDEND"
        sector: e.g. "Industrials", "Financial Services"
        limit: max rows to return (default 3)

    Returns:
        List of dicts with pattern_insights columns (pattern_key, sector, event_type,
        sample_size, win_rate, avg_outcome_score, confidence, insight_text).
        Empty list if no patterns match or query fails.
    """
    try:
        rows = sb.table("pattern_insights").select("*") \
            .eq("active", True) \
            .or_(f"event_type.eq.{event_type},sector.eq.{sector}") \
            .order("confidence", desc=True) \
            .order("sample_size", desc=True) \
            .limit(limit) \
            .execute().data
        return rows or []
    except Exception as e:
        print(f"[pattern_insights_retriever] Query failed: {e} -- returning empty list")
        return []   # fail-open: missing patterns don't block trade
```

**Verify §B0.2:**
```powershell
$env:PYTHONPATH="C:/dev/stockmarket-brain"; .venv\Scripts\python.exe -c "from utils.pattern_insights_retriever import get_relevant_patterns; print(get_relevant_patterns('RESULTS', 'Industrials', 3))"
```
→ returns list (possibly empty). NO exception.

### §B0.3 ✋ Tier-1F regression check

After §B0.1 modification, Tier-1F must still work end-to-end. Two paths:

**Path 1 — Static (5 min):** From §B0.0 callsite list, confirm none break (no callers passed `prompt_path` before; default-None means existing calls unchanged).

**Path 2 — Dynamic (15-30 min, if Tier-1F has a test/dry-run script):** Run Tier-1F end-to-end against a known good fixture. Output should match last known good.

If no Tier-1F test script → Path 1 is sufficient. Document limitation in §V capture.

**Pass:** No callsites broken (Path 1) AND, if available, dynamic run produces same output (Path 2).

### §B0.4 Commit pre-build changes

After §B0.1 + §B0.2 pass + §B0.3 regression clears:

1. `git status` — verify clean except for the two new/modified files
2. `git add utils/ai_consensus.py utils/pattern_insights_retriever.py`
3. Write to `.commit_msg.tmp`:
   ```
   refactor(phase-5): pre-build for Batch A

   - utils/ai_consensus.py: add prompt_path param to run_analyst() and run_verifier() (backward-compat, default None preserves Tier-1F behavior)
   - utils/pattern_insights_retriever.py: new -- get_relevant_patterns(event_type, sector, limit=3) for Tier-2F + Phase 6 + Phase 7 reuse

   Prerequisite for Phase 5 Batch A Tier-2F build.
   ```
4. `git commit -F .commit_msg.tmp`
5. `Remove-Item .commit_msg.tmp`
6. `git push origin main`
7. `git log --oneline -3`

This is **Commit 1 of 3** for Batch A.

---

## §B1 — Build: Prompts

Both prompts use Python's `.format()` placeholders. **Critical rule:** `{{ }}` double braces ONLY in `.txt` files (escaping for `.format()`), NEVER in Python source.

### §B1.1 prompts/tier2f_analyst_v1.txt (Haiku 4.5)

**Persona:** Sober Indian equity analyst, 5-10 yr experience. NOT a hype bot.

**Input placeholders:** `{filing_title}`, `{filing_summary}`, `{event_type}`, `{material_score}`, `{trade_confidence}`, `{directional_bias_tier0}`, `{symbol}`, `{sector}`, `{market_cap_cr}`, `{business_summary}`, `{chart_snapshot}` (compact text including `last_close`, `rsi_14`, `macd`, `macd_signal`, `macd_hist`, `trend`, `support`, `resistance`), `{nifty_mood}`, `{relevant_patterns}` (top 3 from `pattern_insights_retriever`), `{filing_memory_brief}` (~50 words from Phase 4 Batch B).

**Required JSON output schema** (keys are contract with `determine_consensus()`):
```
{{
  "tradeable": true | false,
  "directional_bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "expected_move_pct": 1.0-15.0,
  "horizon": "SHORT" | "MEDIUM" | "LONG",
  "stop_loss_pct": 2.0-8.0,
  "confidence": 50-85,
  "reasoning": "<=80 words"
}}
```

Horizon mapping:
- SHORT = 1-3 trading days
- MEDIUM = 5-10 trading days
- LONG = 10-30 trading days

**Hard rules in prompt:**
- Confidence MUST be 50-85. Anything outside = invalid. No false promises.
- `tradeable=false` if `material_score < 6` OR sector mismatch OR `event_type='OTHER'`.
- Reasoning MUST reference at least one piece of context (patterns OR memory brief OR chart).
- Output ONLY the JSON. No preamble. No markdown fences.

### §B1.2 prompts/tier2f_verifier_v1.txt (DeepSeek V4 Flash)

**Persona:** Independent skeptic. Job is to CHALLENGE Haiku's call.

**Input placeholders:** Same context as analyst PLUS Haiku's `reasoning` + `directional_bias` + `horizon` (but **NOT Haiku's `confidence` number** — anchoring bias prevention).

**Required JSON output schema:**
```
{{
  "verdict": "CONFIRM" | "CHALLENGE",
  "agreement_score": 0-100,
  "my_directional_bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "my_confidence": 50-85,
  "reasoning": "<=80 words"
}}
```

**Hard rules in prompt:**
- If `my_directional_bias` != Haiku's `directional_bias` → `verdict=CHALLENGE`, `agreement_score < 50`.
- If `verdict=CHALLENGE`, reasoning MUST cite specific weakness in Haiku's reasoning.
- `my_confidence` is DeepSeek's INDEPENDENT confidence.
- Output ONLY the JSON. No preamble.

---

## §B2 — Build: Pipeline (`agents/tier2_fundamental.py`)

**~500-700 lines expected.** Build incrementally — 6 sequential approval checkpoints below. Press `1` per individual edit. NEVER "allow all".

### §B2.0 Build roadmap — 6 approval checkpoints

```
✋ APPROVAL POINT 1 of 6 — Skeleton (§B2.1)
✋ APPROVAL POINT 2 of 6 — Context gathering (§B2.2)
✋ APPROVAL POINT 3 of 6 — AI consensus (§B2.3) -- FIRST LIVE API TEST
✋ APPROVAL POINT 4 of 6 — Sizing + paper_trades insert (§B2.4)
✋ APPROVAL POINT 5 of 6 — Telegram alert + __main__ (§B2.5)
✋ APPROVAL POINT 6 of 6 — Final review pass (§B2.6)
```

**IMPORTANT — code blocks below are STRUCTURE + INTENT, not literal copy-paste.** Antigravity should:
1. Adapt to actual recon findings (A1-A8 signatures, B1 column names) — exact names may differ.
2. Match `ai_consensus.py` interface as confirmed by §B0.0 mini-recon.
3. Mirror existing `agents/tier2_signals.py` style for consistency (per D1 recon).
4. NEVER use em-dashes (`—`) in `print()` statements — Windows cp1252 crash. ALWAYS use `--`.

### §B2.1 ✋ Checkpoint 1 — Skeleton

Module docstring:
```python
"""Tier-2F: Fundamental analysis signal generator.

10-step pipeline per filing. First module to make real Haiku + DeepSeek
API calls in production with Tier-2F-specific prompts. Manual entrypoint:
  python -m agents.tier2_fundamental --filing-id <N> [--dry-run]

Production trigger comes from Tier-0F poller (Phase 5 Batch B).
"""
```

**Required imports (corrected per §R):**
```python
import os, json, argparse
from datetime import date
from dotenv import load_dotenv

from utils.fno_ban_list import is_in_ban                    # A4: NOT is_banned
from utils.neon_fundamentals import get_fundamentals        # A3
from utils.yfinance_chart import get_chart_snapshot         # A2
from utils.filing_memory_brief import get_filing_memory_brief
from utils.pattern_insights_retriever import get_relevant_patterns   # NEW in §B0.2
from utils.ai_consensus import run_analyst, run_verifier, determine_consensus
from utils.position_sizer import calculate_position_size    # A6: in position_sizer.py
from utils.capital_ledger import get_current_portfolio, deploy_capital
from utils.tiered_target_generator import generate_targets  # A7: exists
from utils.telegram_client import send_message              # C5: confirm exact import in §B0.0
from utils.supabase_client import sb                        # confirm path during §B0.0
```

**Module-level setup:**
```python
load_dotenv()   # ONCE at module load (NO env-strip loop)

REQUIRED_ENVS = [
    "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
    "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
    "NEON_CONNECTION_STRING",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_TIER3_CHANNEL",
]
missing = [k for k in REQUIRED_ENVS if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing required env vars: {missing}")

# Module constants
HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEEPSEEK_MODEL = "deepseek-v4-flash"
ANALYST_PROMPT_PATH = "prompts/tier2f_analyst_v1.txt"
VERIFIER_PROMPT_PATH = "prompts/tier2f_verifier_v1.txt"
CONFIDENCE_FLOOR = 50
CONFIDENCE_CEILING = 85
SOLO_MODE_HAIRCUT = 10
AGREEMENT_THRESHOLD = 70   # used by determine_consensus internally
AVG_CONFIDENCE_FLOOR = 65   # used by determine_consensus internally; SOLO modes use directly
HORIZON_TO_DAYS = {"SHORT": 3, "MEDIUM": 10, "LONG": 30}
```

Function stubs:
- `process_filing(filing_id: int, dry_run: bool = False) -> dict`
- `_tg_send(message: str) -> None` — Telegram wrapper using Tier-3 pattern
- `_insert_disagreement(filing, haiku, flash, reason) -> int`
- `_confidence_to_conviction(conf: float) -> str` — A7 helper: ≥80=HIGH, ≥65=MEDIUM, <65=LOW
- `if __name__ == "__main__":` with argparse

**Verify checkpoint 1:** `python -c "from agents import tier2_fundamental"` → no ImportError.

### §B2.2 ✋ Checkpoint 2 — Context gathering (pipeline steps 1-5)

Each step prints `[STAGE N: name] <outcome>`.

| Step | What | Skip condition |
|------|------|----------------|
| 1 | F&O ban check via `is_in_ban(filing["symbol"])` (A4) | Banned → `{'skip': 'fno_ban'}` |
| 2 | `fundamentals = get_fundamentals(filing["symbol"])` (A3) | Returns None → `{'skip': 'not_nifty500'}` |
| 3 | `chart = get_chart_snapshot(filing["symbol"] + '.NS')` (A2) | RuntimeError → `{'skip': 'chart_unavailable'}` |
| 4 | NIFTY mood: query `^NSEI` chart, check `close < sma_50 AND trend == DOWNTREND` (Antigravity picks logic based on `get_chart_snapshot` return shape) | BEARISH → `{'skip': 'nifty_bearish'}` |
| 5a | `patterns = get_relevant_patterns(filing["event_type"], fundamentals["sector"], limit=3)` | Empty OK |
| 5b | `memory = get_filing_memory_brief(symbol_base=filing["symbol"], current_event_type=filing["event_type"])` (A5; note: pass filings_log's `symbol` value to `symbol_base` param) | Empty OK |

Build context dict at end of stage 5:
```python
context = {
    "symbol": filing["symbol"],
    "sector": fundamentals["sector"],
    "market_cap_cr": fundamentals.get("market_cap_cr"),
    "business_summary": fundamentals.get("business_summary"),
    "chart_snapshot": {
        "last_close": chart["last_close"],
        "rsi_14": chart["rsi_14"],
        "macd": chart["macd"],
        "macd_signal": chart["macd_signal"],
        "macd_hist": chart["macd_hist"],
        "trend": chart["trend"],
        "support": chart["support"],
        "resistance": chart["resistance"],
    },
    "nifty_mood": nifty_mood,           # "BULLISH" / "BEARISH" / "NEUTRAL"
    "relevant_patterns": patterns,
    "filing_memory_brief": memory,
    "filing": filing,
}
```

**Verify checkpoint 2:** Invoke `process_filing(<good filing_id>, dry_run=True)` → reaches stage 5 with full context dict, no exceptions, no AI calls yet.

### §B2.3 ✋ Checkpoint 3 — AI consensus (pipeline steps 6-8) — FIRST LIVE API TEST

```python
fallback_mode = None
haiku_output = None
flash_output = None

# Step 6: Haiku analyst with Tier-2F prompt
try:
    haiku_output = run_analyst(context, prompt_path=ANALYST_PROMPT_PATH)
except Exception as e:
    print(f"[STAGE 6] Haiku failed: {e} -- entering SOLO_DEEPSEEK fallback")
    fallback_mode = "SOLO_DEEPSEEK"

# Early-skip on Haiku tradeable=False
if haiku_output and not haiku_output.get("tradeable"):
    return {"skip": "haiku_not_tradeable", "haiku": haiku_output}

# Step 7: DeepSeek verifier with Tier-2F prompt
try:
    flash_output = run_verifier(context, haiku_output, prompt_path=VERIFIER_PROMPT_PATH)
except Exception as e:
    print(f"[STAGE 7] DeepSeek failed: {e} -- entering SOLO_HAIKU fallback")
    fallback_mode = "SOLO_HAIKU" if haiku_output else "BOTH_DOWN"

if fallback_mode == "BOTH_DOWN":
    return {"skip": "both_apis_down"}

# Step 8: Consensus or solo decision
if fallback_mode is None:
    action, reason = determine_consensus(haiku_output, flash_output)
elif fallback_mode == "SOLO_DEEPSEEK":
    haircut_conf = flash_output["my_confidence"] - SOLO_MODE_HAIRCUT
    action = "PROCEED" if haircut_conf >= AVG_CONFIDENCE_FLOOR else "SKIP"
    reason = f"Solo DeepSeek (haircut applied), conf={haircut_conf}"
elif fallback_mode == "SOLO_HAIKU":
    haircut_conf = haiku_output["confidence"] - SOLO_MODE_HAIRCUT
    action = "PROCEED" if haircut_conf >= AVG_CONFIDENCE_FLOOR else "SKIP"
    reason = f"Solo Haiku (haircut applied), conf={haircut_conf}"

if action == "SKIP":
    if fallback_mode is None and flash_output.get("verdict") == "CHALLENGE":
        _insert_disagreement(filing, haiku_output, flash_output, reason)
    return {
        "skip": reason,
        "haiku": haiku_output,
        "flash": flash_output,
        "fallback_mode": fallback_mode,
    }
```

**Verify checkpoint 3:** Invoke `process_filing(<good filing_id>, dry_run=True)` → returns either `{"skip": ...}` with valid haiku/flash JSON OR proceeds. Inspect JSON — verify keys match §B1 schemas.

### §B2.4 ✋ Checkpoint 4 — Sizing + paper_trades insert (pipeline steps 9-10)

```python
# Determine direction + advisory SL
if fallback_mode == "SOLO_DEEPSEEK":
    direction_bias = flash_output["my_directional_bias"]
    analyst_sl_pct = 5.0   # SOLO DeepSeek doesn't return stop_loss_pct
elif fallback_mode == "SOLO_HAIKU" or fallback_mode is None:
    direction_bias = haiku_output["directional_bias"]
    analyst_sl_pct = haiku_output.get("stop_loss_pct", 5.0)

if direction_bias == "NEUTRAL":
    return {"skip": "neutral_bias_no_trade"}
direction = "BUY" if direction_bias == "BULLISH" else "SELL"

# Compute avg_conf for conviction mapping + Telegram
if fallback_mode is None:
    avg_conf = (haiku_output["confidence"] + flash_output["my_confidence"]) / 2
elif fallback_mode == "SOLO_DEEPSEEK":
    avg_conf = flash_output["my_confidence"] - SOLO_MODE_HAIRCUT
else:   # SOLO_HAIKU
    avg_conf = haiku_output["confidence"] - SOLO_MODE_HAIRCUT

conviction = _confidence_to_conviction(avg_conf)   # >=80=HIGH, >=65=MEDIUM, <65=LOW

# Entry from chart
entry = context["chart_snapshot"]["last_close"]

# Generate canonical targets + stop_loss (A7)
targets = generate_targets(entry_price=entry, direction=direction, conviction=conviction)
t1, t2, t3 = targets["t1"], targets["t2"], targets["t3"]
t4 = targets.get("t4")   # only present when conviction="HIGH"; goes into raw_signal JSONB
sl = targets["stop_loss"]

# Step 9: Sizing (A6: position_sizer.py, 4 params)
portfolio = get_current_portfolio()
qty, size_rs = calculate_position_size(
    total_equity=portfolio["total_equity"],
    cash_available=portfolio["cash_available"],
    entry_price=entry,
    stop_loss_price=sl,
)
if qty <= 0:
    return {"skip": "insufficient_cash_or_risk_too_wide", "portfolio": portfolio}

# DRY-RUN exit point
if dry_run:
    return {
        "dry_run": True,
        "would_trade": {
            "symbol": filing["symbol"], "direction": direction,
            "entry": round(entry, 2), "sl": round(sl, 2),
            "t1": round(t1, 2), "t2": round(t2, 2), "t3": round(t3, 2),
            "t4": round(t4, 2) if t4 else None,
            "qty": qty, "size_rs": size_rs,
            "conviction": conviction, "avg_conf": avg_conf,
            "fallback_mode": fallback_mode,
            "analyst_sl_pct_advisory": analyst_sl_pct,
            "haiku": haiku_output, "flash": flash_output,
        }
    }

# Step 10: paper_trades insert
# v4 NOTE: target columns are target_price (T1), t2_price, t3_price.
# T4 goes into raw_signal JSONB. No full_reasoning column -- use raw_signal.
horizon = (haiku_output["horizon"] if haiku_output else "MEDIUM")
trade_payload = {
    "ticker": filing["symbol"] + ".NS",
    "source": "TIER2F",
    "direction": direction,
    "entry_price": round(entry, 2),
    "stop_loss": round(sl, 2),
    "target_price": round(t1, 2),          # T1 -- Tier-2 legacy column name
    "t2_price": round(t2, 2),
    "t3_price": round(t3, 2),
    "quantity": qty,
    "position_size_rs": size_rs,
    "horizon": horizon,
    "max_holding_days": HORIZON_TO_DAYS.get(horizon, 10),
    "status": "OPEN",
    "raw_signal": json.dumps({              # v4: bundle goes here, NOT full_reasoning
        "haiku": haiku_output,
        "flash": flash_output,
        "fallback_mode": fallback_mode,
        "conviction": conviction,
        "avg_conf": avg_conf,
        "analyst_sl_pct_advisory": analyst_sl_pct,
        "t4_price": round(t4, 2) if t4 else None,
        "context_summary": {
            "sector": context["sector"],
            "nifty_mood": context["nifty_mood"],
        },
    }),
}

try:
    inserted = sb.table("paper_trades").insert(trade_payload).execute().data[0]
    trade_id = inserted["id"]
except Exception as e:
    if "uniq_paper_trades_ticker_date_source" in str(e):
        return {"skip": "duplicate_ticker_today_for_source"}
    raise

# Deploy capital + ledger entry
deploy_capital(trade_id, size_rs)

return {
    "trade_id": trade_id, "qty": qty, "size_rs": size_rs,
    "direction": direction, "entry": round(entry, 2),
    "conviction": conviction, "avg_conf": avg_conf,
    "fallback_mode": fallback_mode,
}
```

**Verify checkpoint 4:** Manually invoke `process_filing(<good filing_id>, dry_run=False)` ONCE → inspect `paper_trades` row → verify `portfolio.cash_available` decreased by `size_rs` → verify `capital_ledger` has DEPLOY entry. **THEN manually clean up** (DELETE trade + ledger + restore portfolio).

### §B2.5 ✋ Checkpoint 5 — Telegram alert + __main__

```python
mode_tag = {
    None: "[TIER2F]",
    "SOLO_DEEPSEEK": "[TIER2F:SOLO_DSK]",
    "SOLO_HAIKU": "[TIER2F:SOLO_HKU]",
}[fallback_mode]

message_text = (
    f"{mode_tag} {filing['symbol']} {direction} @ {round(entry, 2)} "
    f"| SL {round(sl, 2)} | T1/T2/T3 {round(t1, 2)}/{round(t2, 2)}/{round(t3, 2)} "
    f"| Qty {qty} | Size Rs.{size_rs:,.0f} | Conf {avg_conf:.0f} ({conviction})"
)
_tg_send(message_text)
```

`_tg_send()` helper using Tier-3 pattern (per D1 recon):
```python
def _tg_send(message: str) -> None:
    """Telegram alert to 'StockMarket-Brain Trades' channel (env: TELEGRAM_TIER3_CHANNEL).
    Matches Tier-3 calling pattern. Uses HTML parse_mode.
    """
    try:
        send_message(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_TIER3_CHANNEL"),
            text=message,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[_tg_send] Telegram send failed: {e} -- continuing (trade already recorded)")
```

Note: Use `Rs.` not `₹` — ASCII-safe.

`__main__`:
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tier-2F fundamental signal generator")
    parser.add_argument("--filing-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = process_filing(args.filing_id, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
```

**Verify checkpoint 5:** Live trigger → Telegram alert lands with correct mode tag. Clean up trade.

### §B2.6 ✋ Checkpoint 6 — Final review pass

Before §B3:

1. **Em-dash scan:** `Select-String -Path agents\tier2_fundamental.py -Pattern "—"` → ZERO matches.
2. **Env-leak scan:** `print(...os.getenv...)` or `print(...os.environ...)` → ZERO.
3. **Docstring completeness:** Every public function has docstring.
4. **Import cleanup:** No unused imports. `python -m pyflakes` if available.
5. **No throwaway files** left in `agents/`.
6. **Telegram only post-deploy:** `_tg_send()` AFTER dry-run exit.
7. **Prompt path constants used:** Grep `prompts/tier2f_` strings — appear at module top + §B2.3 only.

---

## §B3 — Build: Tests (`tests/test_phase5_batchA.py`)

5 gates, all Layer-1. **Cleanup is mandatory.**

### §B3.1 Test fixture

```python
import pytest, json
from datetime import date
from agents.tier2_fundamental import process_filing
from utils.capital_ledger import get_current_portfolio
from utils.supabase_client import sb

@pytest.fixture(scope="module")
def fixture_filing():
    rows = sb.table("filings_log").select("*") \
        .gte("material_score", 8) \
        .in_("event_type", ["RESULTS", "M_AND_A", "CONTRACT_WIN", "DIVIDEND", "ORDER_WIN"]) \
        .order("classified_at", desc=True).limit(1).execute().data
    if not rows:
        pytest.skip("No qualifying material filing in last 24h -- re-run tomorrow")
    return rows[0]
```

### §B3.2 T1 — V5.2: Haiku + Flash valid JSON

```python
def test_V5_2_valid_json(fixture_filing):
    result = process_filing(fixture_filing["id"], dry_run=True)
    assert ("haiku" in result) or (result.get("skip") in (
        "haiku_not_tradeable", "both_apis_down", "nifty_bearish",
        "fno_ban", "not_nifty500", "chart_unavailable"
    ))
    if result.get("haiku"):
        h = result["haiku"]
        assert set(h.keys()) >= {"tradeable", "directional_bias", "confidence", "reasoning"}
        assert h["directional_bias"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert 50 <= h["confidence"] <= 85
    if result.get("flash"):
        f = result["flash"]
        assert set(f.keys()) >= {"verdict", "agreement_score", "my_directional_bias", "my_confidence", "reasoning"}
        assert f["verdict"] in ("CONFIRM", "CHALLENGE")
        assert 50 <= f["my_confidence"] <= 85
```

### §B3.3 T2 — V5.3 & V5.4: paper_trades insert + capital deployed

```python
def test_V5_3_and_V5_4_live_insert(fixture_filing):
    pf_before = get_current_portfolio()
    result = process_filing(fixture_filing["id"], dry_run=False)

    if "trade_id" not in result:
        pytest.skip(f"Filing didn't produce a trade: {result.get('skip')}")

    trade_id = result["trade_id"]
    try:
        # V5.3
        row = sb.table("paper_trades").select("*").eq("id", trade_id).execute().data[0]
        assert row["source"] == "TIER2F"
        assert row["quantity"] > 0
        assert row["position_size_rs"] > 0
        assert row["status"] == "OPEN"
        # v4 correction: verify target column names
        assert row["target_price"] is not None    # T1
        assert row["t2_price"] is not None
        assert row["t3_price"] is not None
        # v4: raw_signal JSONB contains the bundle
        bundle = row["raw_signal"] if isinstance(row["raw_signal"], dict) else json.loads(row["raw_signal"])
        assert "haiku" in bundle or "fallback_mode" in bundle
        assert bundle.get("fallback_mode") in (None, "SOLO_DEEPSEEK", "SOLO_HAIKU")

        # V5.4
        pf_after = get_current_portfolio()
        assert abs(pf_after["cash_available"] - (pf_before["cash_available"] - row["position_size_rs"])) < 0.01
        ledger = sb.table("capital_ledger").select("*").eq("paper_trade_id", trade_id).execute().data
        assert len(ledger) == 1
        assert ledger[0]["txn_type"] == "DEPLOY"
    finally:
        # Always cleanup
        sb.table("paper_trades").delete().eq("id", trade_id).execute()
        sb.table("capital_ledger").delete().eq("paper_trade_id", trade_id).execute()
        sb.table("portfolio").update({
            "cash_available": pf_before["cash_available"],
            "capital_deployed": pf_before["capital_deployed"],
            "open_positions": pf_before["open_positions"],
        }).eq("id", pf_before["id"]).execute()
```

### §B3.4 T3 — V5.5: SOLO fallback via `monkeypatch.setattr` on module global

**Exact attribute names** confirmed in §B0.0 mini-recon. Below uses placeholder `<HAIKU_CLIENT_ATTR>` / `<DEEPSEEK_CLIENT_ATTR>` — Antigravity replaces with actual names.

```python
class _BrokenClient:
    """Raises on any attribute access -- simulates a broken SDK client."""
    def __getattr__(self, name):
        raise RuntimeError(f"Forced broken client (V5.5 test): .{name}")

def test_V5_5_solo_deepseek(monkeypatch, fixture_filing):
    from utils import ai_consensus
    monkeypatch.setattr(ai_consensus, "<HAIKU_CLIENT_ATTR>", _BrokenClient())   # placeholder
    result = process_filing(fixture_filing["id"], dry_run=True)
    expected = ("SOLO_DEEPSEEK", "both_apis_down", "haiku_not_tradeable")
    assert (result.get("fallback_mode") == "SOLO_DEEPSEEK") or (result.get("skip") in expected)

def test_V5_5_solo_haiku(monkeypatch, fixture_filing):
    from utils import ai_consensus
    monkeypatch.setattr(ai_consensus, "<DEEPSEEK_CLIENT_ATTR>", _BrokenClient())   # placeholder
    result = process_filing(fixture_filing["id"], dry_run=True)
    expected = ("SOLO_HAIKU", "both_apis_down", "haiku_not_tradeable")
    assert (result.get("fallback_mode") == "SOLO_HAIKU") or (result.get("skip") in expected)
```

### §B3.5 T4 — V5.6: Disagreement logged, no trade

```python
def test_V5_6_disagreement(monkeypatch, fixture_filing):
    from utils import ai_consensus
    monkeypatch.setattr(
        ai_consensus, "determine_consensus",
        lambda h, f: ("SKIP", "Direction mismatch (forced for V5.6 test)")
    )
    original_verifier = ai_consensus.run_verifier
    def fake_verifier(context, analyst_output, prompt_path=None):
        result = original_verifier(context, analyst_output, prompt_path=prompt_path)
        if isinstance(result, dict):
            result["verdict"] = "CHALLENGE"
            result["agreement_score"] = 30
        return result
    monkeypatch.setattr(ai_consensus, "run_verifier", fake_verifier)

    disagreements_before = sb.table("agent_disagreements").select("id", count="exact").execute().count
    result = process_filing(fixture_filing["id"], dry_run=False)
    disagreements_after = sb.table("agent_disagreements").select("id", count="exact").execute().count

    try:
        assert "trade_id" not in result
        assert disagreements_after == disagreements_before + 1
    finally:
        latest = sb.table("agent_disagreements").select("id").order("id", desc=True).limit(1).execute().data
        if latest:
            sb.table("agent_disagreements").delete().eq("id", latest[0]["id"]).execute()
```

### §B3.6 Test execution

```powershell
$env:PYTHONPATH="C:/dev/stockmarket-brain"; .venv\Scripts\python.exe -m pytest tests/test_phase5_batchA.py -v
```

**Expected:** all 5 tests PASS (or skips natural if fixture filing produces a skip — re-run next day).

---

## §V — Verify: Capture gate evidence

Paste back in claude.ai chat:

```
R1F PASS -- Tier-1F regression: <static-only OR static+dynamic>; callsites broken=0; dynamic run output identical (if Path 2 attempted)
V5.2 PASS -- haiku JSON: {<paste actual>}, flash JSON: {<paste actual>}
V5.3 PASS -- paper_trades row id=<N>: source='TIER2F', qty=<N>, size_rs=<N>, status='OPEN', target_price=<N>, t2_price=<N>, t3_price=<N>, raw_signal.fallback_mode=<N>
V5.4 PASS -- cash before=<N>, after=<N>, delta=<N> (matches size_rs); ledger row id=<N> txn_type='DEPLOY'
V5.5 PASS -- SOLO_DEEPSEEK: fallback_mode='SOLO_DEEPSEEK', conf=<N>; SOLO_HAIKU: fallback_mode='SOLO_HAIKU', conf=<N>
V5.6 PASS -- disagreement row id=<N>: haiku_decision='<>', deepseek_decision='<>', no paper_trades row created
```

**FAIL/BLOCKED/UNVERIFIED:** paste actual error verbatim. NEVER mark PASS without real evidence.

---

## §S — Ship: Three commits to main

### §S.1 Commit 1 (shipped per §B0.4) — Pre-build

Already covered above.

### §S.2 Commit 2 — Code

1. `git status`
2. `git add agents/tier2_fundamental.py`
3. `git add prompts/tier2f_analyst_v1.txt`
4. `git add prompts/tier2f_verifier_v1.txt`
5. `git add tests/test_phase5_batchA.py`
6. Write `.commit_msg.tmp` (see below)
7. `git commit -F .commit_msg.tmp`
8. `Remove-Item .commit_msg.tmp`
9. `git push origin main`
10. `git log --oneline -5`

**Commit 2 message (NO `Co-Authored-By`):**
```
feat(phase-5): Batch A -- Tier-2F fundamental signal generator + first live AI consensus test

- agents/tier2_fundamental.py: 10-step pipeline (is_in_ban, get_fundamentals, get_chart_snapshot, NIFTY mood, get_relevant_patterns + get_filing_memory_brief, Haiku 4.5 analyst via run_analyst(prompt_path=...), DeepSeek V4 Flash verifier via run_verifier(prompt_path=...), determine_consensus, calculate_position_size from position_sizer, generate_targets with conviction, paper_trades insert via target_price/t2_price/t3_price + raw_signal JSONB)
- prompts/tier2f_analyst_v1.txt: Haiku analyst with 50-85 confidence band, JSON schema matching determine_consensus contract
- prompts/tier2f_verifier_v1.txt: DeepSeek verifier with CONFIRM/CHALLENGE + agreement_score
- tests/test_phase5_batchA.py: V5.2-V5.6 gates with full cleanup; V5.5 uses monkeypatch.setattr on module globals

Gates PASS: R1F (Tier-1F regression), V5.2 (Haiku + Flash valid JSON, REAL API), V5.3 (paper_trades insert source='TIER2F', target_price/t2_price/t3_price columns populated, raw_signal JSONB has haiku/flash/fallback_mode bundle), V5.4 (capital deployed correctly), V5.5 (SOLO_DEEPSEEK + SOLO_HAIKU fallbacks), V5.6 (disagreement logged to agent_disagreements).

First live test of determine_consensus() with Tier-2F's filing-analysis output shape (Phase 3 Batch B 2b17ad7 was mock-tested only with Tier-1F news shape).

Tier-0F poller + Tier-3 mod + V5.1/V5.7/V5.8 deferred to Phase 5 Batch B.
```

### §S.3 Commit 3 — Brief

1. `git add docs/phase-5-batchA-execution-brief.md`
2. `.commit_msg.tmp` + commit + push (same pattern)
3. `git log --oneline -5`

**Commit 3 message:**
```
docs: Phase 5 Batch A execution brief v4

Self-contained execution plan for Tier-2F signal generator:
- v3 -> v4 changes: B1-B4 schema recon (target_price/t2_price/t3_price columns, raw_signal JSONB destination, filings_log uses 'symbol' field)
- §B0 pre-build modifications (ai_consensus.py prompt_path + pattern_insights_retriever.py)
- §B1 prompts matching determine_consensus() key contract
- §B2 6-checkpoint pipeline with all recon corrections applied (target naming, raw_signal storage, symbol field, position_sizer 4-param, generate_targets with conviction, tg_send pattern)
- §B3 tests with monkeypatch.setattr for V5.5

Companion to refactor(phase-5) pre-build + feat(phase-5) Batch A code commits.
```

---

## §A — Working agreements (carry forward from Phase 4 Batch B)

- Hinglish, aap/aapka register
- confirm-first on every non-trivial step before acting
- Antigravity workflow: **recon-first (read-only) → STOP & report → build/edit ONE file at a time → press `1` per edit (NEVER "allow all")**
- Pattern A (press `1` first, then next instruction) — NOT Pattern B (combined message that auto-accepts)
- Throwaway scripts (`scripts/recon_*`, `scripts/debug_*`, `scripts/smoke_*`) deleted after use, never committed
- Real tests (`tests/test_phase5_*`) ARE committed
- **Em-dashes (`—`) BANNED in Python `print()` statements** — Windows cp1252 crash. ALWAYS use `--`.
- Git on Windows: one command at a time, EXPLICIT `git add <file>` per file (NEVER `git add .`), multi-line commit via `-F .commit_msg.tmp` (NOT inline heredoc — PowerShell 965-byte limit), EXPLICIT `git push origin main`, verify with `git log --oneline -5` + `git status`
- Machine-local files (`.claude/settings.local.json`, `.claude/scheduled_tasks.lock`, `dumps/`) NEVER committed
- No gassing — every gate backed by real query output / real JSON dump; FAIL/BLOCKED/UNVERIFIED stated honestly
- NO `Co-Authored-By: Claude` in commits — keep history consistent with Phase 4 Batch A+B
- This chat (claude.ai) = planning + verification + review; execution happens in Antigravity. claude.ai cannot access `C:\dev\` files or run Supabase queries — paste outputs/screenshots back here.
- DDL (CREATE/ALTER TABLE/INDEX) via Supabase Dashboard SQL Editor ONLY — NOT supabase-py
- Trust no Antigravity self-summary on bugs — always read actual file content / actual query output.

---

*Brief v4 FINAL: 2026-05-20. All recon items resolved. Ready for Antigravity execution. Start with §B0.0 mini-recon → §B0.1 → §B0.2 → §B0.3 → §B0.4 (Commit 1) → §B1 → §B2 → §B3 → §V → §S.2 (Commit 2) → §S.3 (Commit 3).*
