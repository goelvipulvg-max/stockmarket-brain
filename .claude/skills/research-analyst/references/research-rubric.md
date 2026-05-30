# Research Rubric — stockmarket-brain external-evidence scout

This is the lens the `research-analyst` skill reads in Phase 2. Where `gap-rubric.md` judges *our own engine's* fidelity, this rubric judges **external claims** — a paper, a strategy, a blog's backtest — before we trust one enough to surface. The question every finding must answer: *is this real, and would it actually help this system?*

Never surface a finding without (a) an evidence grade and (b) a real, whitelisted source.

---

## 1. Evidence grade (always state one)

Grade how much the claim has actually been demonstrated — not how exciting it sounds:

- **Proven** — replicated, out-of-sample, real-money track record, or peer-reviewed with a robust method.
- **Promising** — a single credible study or strong backtest, but with caveats (one market, one period, author-run).
- **Theory-only** — logically argued or mechanistically plausible, but not empirically validated.
- **Unverified** — a claim with no traceable evidence. **Usually don't surface**; if you do, label it loudly and say why it's still worth a mention.

The grade sets the recommendation's tone: Proven → a confident "worth doing"; Promising → "worth a small test"; Theory-only → "worth thinking about."

## 2. Skeptic lenses (reuse gap-rubric's four — applied OUTWARD)

`gap-rubric.md` already defines these for our engine. **Don't re-derive them — point to them** (gap-rubric Dimensions 1–3 and 7) and apply each to the *external* claim:

- **Survivorship** — did it only count winners (surviving funds, still-listed stocks, the one backtest that worked)?
- **Overfit / p-hacking** — tuned on the same data it's judged on? Many params + one window = likely luck. (with enough trials, random no-edge strategies routinely produce an impressive "best" Sharpe purely by chance — the core of backtest overfitting; cf. López de Prado's Deflated Sharpe Ratio.)
- **Cost-blind** — does the edge survive real frictions (brokerage, STT, GST, slippage)? Most published edges are gross; ours must be net.
- **Point-in-time / look-ahead** — does it use info unavailable at decision time (restated fundamentals, adjusted prices feeding entries, future-dated data)?

Plus one that matters for any claim:
- **Sample & regime span** — enough events across more than one market regime, or one calm stretch?

A finding that fails a lens isn't auto-dropped — but the failure must be named in the report's "catch / risk" line.

## 3. Fit-to-stack (feasibility — the filter gap-rubric doesn't have)

A true, proven edge we can't implement here isn't worth surfacing as actionable. Ask:

- Does it work within **NSE filings + paper-engine** reality (event-driven, filing fundamentals, yfinance charts)?
- Is the **data reachable** — via what `smb_audit_ro` can read, the existing feeds, or a clearly-named new source?
- Does it respect the **no-live-execution** constraint (paper trades only, no broker order routing)?

If it doesn't fit, reframe it into something that does, or say plainly "not implementable here, noted for awareness."

## 4. Novelty (new-to-us)

Before surfacing, confirm it isn't already known or settled:

- Cross-check `research-history.md` (SURFACED / DISMISSED / EXPLORING / ADOPTED) — never re-surface a DISMISSED idea without new evidence.
- Cross-check `audit-history.md` (SHIPPED / PARKED / AVOID / PENDING) — if the engine already shipped or knowingly parked it, it's not novel.

## 5. The worth-it score → which ledger tier

> **Worth-it = Relevance × Evidence × Feasibility × Novelty**

If any factor is near-zero, the finding doesn't surface — a proven-but-irrelevant paper, a relevant-but-unverified claim, or a great-but-already-shipped idea all fail the gate.

Make the gate concrete: grade **Relevance / Feasibility / Novelty** as **H / M / L** and **Evidence** on the §1 scale, then sort each candidate into the tier it will occupy in `research-history.md` (so scoring and memory share one vocabulary):

- **SURFACED** — Evidence ∈ {Proven, Promising} AND Relevance, Feasibility, Novelty all ≥ M. Ranked by **leverage = impact × tractability** in the report.
- **EXPLORING** — relevant + novel, but Evidence is mixed / Promising-with-caveats OR Feasibility is uncertain. Note it; don't act.
- **DISMISSED** — Unverified, off-whitelist, already SHIPPED / PARKED / AVOID, or doesn't-fit-stack. Log the reason so it never re-surfaces.

## 6. Source whitelist (strict — cite-or-drop)

**Allowed (credible only):**
- **Academic:** SSRN, arXiv (q-fin), NBER, Google Scholar, and other **peer-reviewed journals / repositories** (e.g. EconStor, BMC, ScienceDirect, JSTOR).
- **Regulatory / exchange:** SEBI (sebi.gov.in), NSE (nseindia.com), RBI, official exchange data.
- **Reputed practitioner / quant:** established quant research (e.g. Alpha Architect, QuantPedia), CFA Institute, recognised desks.

**Skip (never as primary evidence):** retail forums (Reddit / ValuePickr threads), YouTube gurus, Telegram tip channels, SEO-spam, unsourced blogs.

A surfaced claim with no traceable whitelisted source is a **bug**, not a finding.

**Enforce it structurally (not just as a wish):**
- Every surfaced finding's source line **must** carry **domain + publication date** — e.g. `arxiv.org · 2026-03`, `sebi.gov.in · 2024-11`. No domain or no date → treat the claim as **Unverified**.
- **Auto-reject** off-whitelist domains and **stale** sources (a "new" claim resting on old work) — unless the staleness or the source is explicitly justified in that finding's **catch / risk** line.

## 7. Plain-Hinglish "Matlab:" library (research edition)

Every surfaced finding carries a **"Matlab:"** line in simple Hinglish (Roman script) with a real-world Indian analogy — beginner-friendly, no jargon. Adapt the wording to the evidence; keep the analogy:

- **Proven, fits us** — Matlab: Yeh doosri jagah baar-baar chal chuki hai aur apne setup mein laga sakte hain — aजमाya hua nuskha, bas apne kitchen mein try karna hai.
- **Promising but unproven** — Matlab: Ek baar accha chala matlab pakka nahi — ek baar ki barish se kuआं nahi bharta. Chhote test se shuru karo.
- **Theory-only** — Matlab: Kaagaz pe sahi lagta hai par kisi ne asli paise se kar ke nahi dikhaya — abhi sirf sोचne layak, lagane layak nahi.
- **Cost-blind external backtest** — Matlab: Unka hisaab bhi brokerage/tax/slippage bhool gaya — wahi galti bahar bhi profit ko bada dikhati hai.
- **Survivorship in a study** — Matlab: Study ne sirf chalne wale dekhe, band ho gaye chhod diye — number asli se phula hua.
- **Overfit strategy** — Matlab: Purane data pe itna fit kar diya ki sirf usi pe achhi lagti hai, naye market mein fail — ek hi question-paper ratt ke exam dene jaisa.
- **Doesn't fit our stack** — Matlab: Cheez sahi hai par apne setup (NSE filings, paper engine) mein lag hi nahi sakti — achhi recipe par hamare kitchen mein woh oven hi nahi.

For any novel finding type, write a fresh Matlab line in the same style.
