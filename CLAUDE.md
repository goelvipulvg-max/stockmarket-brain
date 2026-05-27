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
