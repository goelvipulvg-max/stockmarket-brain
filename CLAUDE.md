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

## Context Navigation (3 layers — cheapest first, STOP when you have enough)
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
2. **Vault** — for design intent, strategy and "why", read the Obsidian vault at
   `C:\Users\goelv\StockMarket-Brain-v2-Hybrid-CLEAN\StockMarket-Brain` (start at
   `00-Start-Here\VAULT-INDEX.md`). Vault docs describe the original design and may lag the code —
   **treat the code as the source of truth.**
3. **Raw code** — open only the specific files the graph/vault pointed you to. Avoid blind full-repo reads.

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
