# Claude Context for stockmarket-brain repo

This repo contains all code for the StockMarket-Brain personal trading intelligence system.

## Architecture
- 5-tier AI agent hierarchy (Tier-0 to Tier-4)
- Hybrid strategy (LT 50% + ST 50%)
- Capital: Rs 10L total (Rs 5L LT + Rs 5L ST)

## Key folders
- agents/ - One Python file per tier
- prompts/ - System prompts as text files
- utils/ - Shared clients (Upstox, Telegram, Supabase, Pinecone)
- data/ - Reference data (trade history, ticker maps)
- scripts/ - Setup and test scripts

## Where things live (go straight here, skip the blind scan)
Verified 2026-06-01. Level-0 shortcut: if a target isn't listed, fall through to
Context Navigation below. Code is the source of truth; line refs are approximate.

DATA -- which DB owns what
- Trades/signals: Supabase `paper_trades` (col `source`: 'TIER2F' = fundamental path,
  'TIER2' = technical path).
  GOTCHA: TIER2F `raw_signal` is double-json-encoded (json.dumps at
  tier2_fundamental.py:486) -> stored as a JSONB string scalar; audit queries must
  CASE-decode (see memory tier2f_ai_sl_canary_2026_05_31).
- Capital: Supabase `portfolio` + `capital_ledger` -> utils/capital_ledger.py.
- Filing memory: Supabase `filing_memory` -> agents/filing_memory_sync.py.
- Fundamentals/sector: Neon (Postgres) `company_profiles` -> utils/neon_fundamentals.py
  (raw conn: utils/neon_client.py).

SIGNAL / RISK LOGIC
- Fundamental signal + AI-SL: agents/tier2_fundamental.py
  (USE_AI_SL flag :87, validate_ai_signal :97, AI-SL blend stage :379-486).
- Technical signal: agents/tier2_signals.py.
- Reward:risk floor: utils/reward_risk.py (RR_FLOOR=1.5, passes_rr_floor()).
- Position sizing: utils/position_sizer.py (RISK_PCT=0.00125, MAX_TRADE_PCT=0.025).
- Trade updates / SL-target hit / expiry: agents/update_paper_trades.py.

FLAGS -- defined in code, effective values in the workflow
- Defs: agents/tier2_fundamental.py (USE_AI_SL :87, USE_PRICE_STRUCTURE_GATE :72,
  USE_VOLUME_GATE :77).
- Effective: .github/workflows/tier2f.yml (USE_AI_SL="true" :36; both gates unset = DORMANT).
- Dormant gate logic: utils/price_structure.py (gap #1), utils/volume_structure.py (gap #3).

AGENTS / IO
- Two-AI consensus: utils/ai_consensus.py (Analyst=Claude Haiku 4.5, Verifier=DeepSeek V4 Flash).
- Telegram: utils/telegram_client.py (send_message; channel = per-caller bot_token+chat_id).
- Schedules: .github/workflows/*.yml (one per tier/agent).

## Context Navigation (4 layers — cheapest first, STOP when you have enough)
A cold full-read of this repo costs ~165K tokens. Navigate in order:
1. **Graph** — query the Graphify code graph instead of cold-reading (finds the relevant
   files/functions + how they connect). Graph lives at `graphify-out/graph.json`; a copy plus
   `GRAPH_REPORT.md` is mirrored into the vault at `<vault>\graphify\stockmarket-brain`.
   - **Windows: run queries through the repo-root wrapper `.\graphq.ps1`** — it sets `PYTHONUTF8=1` /
     `PYTHONIOENCODING=utf-8` for that process so Unicode output (`→`, `§`) doesn't crash the cp1252
     console. e.g. `.\graphq.ps1 query "how does X work"`, `.\graphq.ps1 path "A" "B"`,
     `.\graphq.ps1 explain "X"`.
   - The graph **auto-rebuilds AST-only (0 tokens)** on every commit via the installed post-commit hook;
     rebuild manually with `.\graphq.ps1 update .`. **NEVER run `graphify extract`** — it calls an LLM and
     spends tokens (the wrapper blocks it). AST-only, always.
2. **Symbols (Serena MCP)** — once the graph points you to a file/area, use Serena's semantic tools for
   exact symbol-level detail and complete reference lists BEFORE reading raw code: `find_symbol` (locate a
   definition), `find_referencing_symbols` (every call site), `get_symbols_overview` (a file's symbol map).
   LSP-based (Pyright) — no tokens, no API key. Fixes the AST graph's lexical-relevance gap (resolves e.g.
   "position sizing" to `utils/position_sizer.py`, not `docs/*.md`). Registered as a local `claude mcp`
   server; if its tools aren't visible, start a fresh session so the harness loads them.
3. **Vault** — for design intent, strategy and "why", read the Obsidian vault at
   `C:\Users\goelv\StockMarket-Brain-v2-Hybrid-CLEAN\StockMarket-Brain` (start at
   `00-Start-Here\VAULT-INDEX.md`). Vault docs describe the original design and may lag the code —
   **treat the code as the source of truth.**
4. **Raw code** — open only the specific files the graph/vault/symbols pointed you to. Avoid blind full-repo reads.

## Environment & Workflow Rules (non-negotiable)
- **Python**: always use `.venv\Scripts\python.exe`; never install project deps into global Python;
  code must use `load_dotenv(override=True)`.
- **Secrets**: never write secrets to global Windows env vars; never edit `.env` from the agent —
  if `.env` needs changes, STOP and ask the user to edit it in Notepad.
- **Git**: `git add <specific-file>` only — never `git add .`. One commit per task. Multi-line commit
  messages via `git commit -F .commit_msg.tmp`. Each phase ends with commit AND `git push origin main`
  (verify the push succeeded).
- **OS**: Windows + PowerShell — use Windows paths and Task Scheduler (not cron).
- **No behavioural change** to trading logic, gates, env flags or position sizing without explicit approval.
