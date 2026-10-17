# Research Radar: Implementation Plan

Companion to [research-radar.md](research-radar.md) (the "what and why"). This file is the "how and in what order". Where the two disagree, update both.

**Ground rules**
- Every phase ends **shippable**: something runs end to end, with a concrete "done when" check.
- Build the thinnest vertical slice first (one source → email), then widen.
- Config over code: topics, sources, models and quotas live in `topics.yaml` / env, never hardcoded.
- Each stage is a pure function over typed objects (Pydantic), so it can be unit-tested and replayed offline.
- Tracing (Langfuse) and the `runs` lock exist from the first pipeline run, not as a later add-on.
- Time estimates are for evenings/weekends of solo work and are guesses; the order matters more than the dates.

**Temporary dev console:** a local, read-only Streamlit app in `devui/` that lets me *see* each stage's output as it is built (see [Dev console](#dev-console-temporary-stage-by-stage-viewer)). It is scaffolding, not a product: nothing in `src/radar/` imports it, it is never deployed, and it is removed in Phase 4.

**Primary stack:** Python 3.11+ + `uv` · LiteLLM → **Groq (primary)**, Gemini and OpenRouter fallbacks · FastEmbed · Supabase (Postgres + pgvector) · Gmail SMTP (Resend adapter later) · GitHub Actions · Cloudflare Worker · LangGraph in a Streamlit app on Community Cloud · Langfuse (own eval code instead of DeepEval, D-040).

---

## Phase 0: Foundations (1-2 evenings)

**Goal:** an empty but wired skeleton that can call an LLM, talk to the DB, send a test email and trace it.

| # | Task | Details |
|---|---|---|
| 0.1 | Repo + tooling | `uv init`, `src/radar/` layout from research-radar.md §9, `ruff`, `pytest`, `.env.example`, `.gitignore` (secrets!), pre-commit optional |
| 0.2 | Config loader | `config.py` loads `topics.yaml` + env into Pydantic models; fail fast on missing keys. Stub `topics.yaml` with 1-2 topics |
| 0.3 | Supabase | Create project; apply schema as versioned SQL files in `db/migrations/` (items, runs, item_scores, digests, feedback, feedback_tokens); enable pgvector. `db.py` thin client (psycopg or supabase-py; pick one, prefer direct Postgres via `psycopg` for vector SQL) |
| 0.4 | LLM layer | `llm.py`: LiteLLM `Router` with Groq primary, Gemini + OpenRouter fallbacks, retry/backoff on 429, pinned model IDs from config. One function `complete_structured(prompt, schema)` returning a validated Pydantic object |
| 0.5 | Langfuse | Wire LiteLLM callback; confirm a test call shows cost + latency in the Langfuse UI |
| 0.6 | Email adapter | `deliver/email.py`: `send(subject, html, to)` with SMTP backend (Gmail app password); backend selected by env var; send a hello-world mail |
| 0.7 | Secrets | GitHub Actions secrets for DB URL, Groq/Gemini/OpenRouter keys, SMTP creds, Langfuse keys |
| 0.8 | CI skeleton | `ci.yml` running ruff + pytest on push |
| 0.9 | Dev console shell | `devui/app.py` Streamlit multipage skeleton, own `devui` dependency group, read-only DB role/connection. First page: **Runs** (status, counts, cost, links to Langfuse trace). See Dev console section |

**Risks:** Groq structured-output support varies by model. Test JSON mode with the chosen model in 0.4 and decide Instructor vs. native `response_format` now.

**Done when:** `uv run python -m radar.smoke` calls Groq, writes a row to `runs`, sends an email to me, the trace appears in Langfuse, and `streamlit run devui/app.py` shows that run on the Runs page.

---

## Phase 1: Digest MVP + start labeling (weekend 1, maybe 1.5)

**Goal:** a real digest lands in my inbox every morning with no manual steps.

### 1A. Collect
- `collect/` modules, each returning a list of `RawItem` (url, title, source, published_at, snippet, popularity).
- Order: **arXiv** (API/RSS, categories from config, keyword prefilter before embedding) → **HF Daily Papers** → **HN Algolia** → **blog + release RSS** (`feedparser`). GitHub Search API after the first four are stable.
- Common behaviors: timeout + retry, polite User-Agent, per-source failure isolated (a failing source logs and is skipped, never aborts the run).
- Unit tests with recorded fixtures (no network in CI).

### 1B. Dedupe + embed
- `dedupe.py`: canonical URL normalization (strip tracking params, `arxiv.org/pdf` → `abs`, etc.), content hash, upsert into `items`, skip anything already stored.
- `embed.py`: FastEmbed (small 384-dim model), store `embedding` + `embedding_model`.
- Near-duplicate clustering via pgvector nearest-neighbor query; keep one item per cluster (prefer the primary source, e.g. the arXiv page over a tweet-like HN post).
- Exclude items already sent in the last N days.

### 1C. Cheap filter
- Compute topic vectors from `anchors` (mean of anchor embeddings, fallback to description embedding).
- Hybrid score = weighted keyword/BM25 boost + cosine to topic vectors + recency decay + popularity (log-scaled). Weights in config.
- Keep the top ~30 (and persist `filter_score` for ablations).
- **Dump the full scored candidate pool to `evals/candidate_pool/` each day** (this feeds Phase 2 for free).

### 1D. LLM judge
- `judge.py`: batches of 5-10 items, stable rubric prefix (topic descriptions), Pydantic output (`relevance`, `novelty`, `actionability`, `best_topic`, `rationale`, 2-line `summary`, `why_it_matters`).
- Summary and "why it matters" generated only from title + snippet; prompt forbids outside claims.
- Validate output; on schema failure retry once, then fall back to filter-score-only for that batch (mark as degraded).
- Persist to `item_scores` with the `judge_model` ID.

### 1E. Diversify + compose + deliver
- `diversify.py`: MMR + per-section quotas from config (core 5, watchlist 2, exploration 1; watchlist/exploration can be empty in this phase).
- `compose.py`: Jinja2 HTML template, mobile-friendly, plain-text alternative. Placeholders for feedback/deep-dive links (not live yet).
- `pipeline.py`: the orchestrator. Creates the `runs` row first (unique `digest_date` is the lock), runs stages, writes `digests`, sends, sets status (`sent` / `degraded` / `failed`).

### 1F. Schedule + labeling
- `daily-digest.yml`: cron plus `workflow_dispatch`; runs the pipeline; on failure the Actions failure email is the alert.
- Keep-alive plan for the 60-day inactivity rule (scheduled commit or a monthly reminder).
- Add a tiny labeling helper (CLI or a markdown/CSV export of the day's candidate pool) so labeling a few items a day takes minutes.

**1G. Dev console pages (add each as its stage lands, not at the end)**
- After 1A: **Collected** page (items by source, counts, failed sources).
- After 1B: **Dedupe** page (clusters, which item was kept and why).
- After 1C: **Filter** page (score components per item: keyword, cosine, recency, popularity).
- After 1D: **Judge** page (scores, rationales, summaries, degraded batches).
- After 1E: **Digest preview** page (rendered HTML of the composed email) and a **Run now (dry-run)** button that runs the pipeline without sending email.

**Risks:** Groq per-minute/day token caps, so size judge batches and add backoff. Late cron fires are harmless because of the `runs` lock. arXiv volume, so prefilter early.

**Status (2026-10-17):** 1A-1E and 1G built and verified on live data; workflow written. Remaining: GitHub-run verification, 5 unattended mornings, labeling. Deviations are recorded in decision.md (D-018 to D-029).

**Done when:** 5 consecutive mornings produce a digest with no manual steps, a re-triggered run the same day does not send a second email, and a deliberately broken source does not stop the digest.

---

## Phase 2: Feedback and evals (weekend 2, may spill into 3)

**Goal:** votes flow back into the system and I can show a precision@5 table.

### 2A. Feedback endpoint (Cloudflare Worker, JS)
- Email links: `GET /f/{token}` renders a confirm page (no state change); the button does `POST /f/{token}`; only the POST writes.
- Token: HMAC-signed payload (item, run, action, expiry) + nonce recorded in `feedback_tokens`; single use; rejected if expired or reused.
- Writes `feedback` idempotently (one row per item/action; an `up` replaces a `down` and vice versa). Also logs `run_id` and `section`.
- Worker talks to Supabase via a restricted role / RPC (not the service key in the open), with a rate limit.
- Token minting lives in the pipeline (`compose.py`), sharing the signing secret with the Worker.
- Test: simulate a mail-scanner GET (no vote recorded), a double POST (one vote), an expired token (rejected).

### 2B. Feedback score in ranking
- `filter.py` adds a revealed-interest term: similarity to k nearest 👍/save items minus k nearest 👎 items across all votes; save/deepdive weighted higher.
- Blend weight in config; **off by default until the ablation shows a gain**, and bounded so early noisy votes can't dominate.
- Exploration slot: pick the highest-scoring item that is far from the current profile.

### 2C. Golden set
- Label ~200-300 items from the stored candidate pools, balanced relevant / not relevant, with hard negatives. Record `topic` and a relevant/not label in `evals/golden_set.jsonl`.
- Labeling continues in the background from Phase 1.

### 2D. Ablation + judge calibration
- `evals/ablation.py` replays the stored pool offline (no live fetches): keyword only → embedding only → hybrid → + judge → + feedback blend. Output precision@5 (and optionally nDCG) as a markdown table.
- Cache judge outputs per `(item, judge_model)` so reruns are cheap and reproducible.
- Judge calibration: agreement rate (and a confusion matrix) vs. my labels, per model version.

### 2E. Faithfulness + CI
- DeepEval faithfulness check on a **sample** of summaries (e.g. 20 per eval run) against title + snippet.
- `evals.yml`: runs on PRs touching the filter/judge/prompts, fails if precision@5 drops below a threshold; includes the model-ID smoke test.

**2F. Dev console pages**
- **Labeling** page: shows candidates from the stored pools with relevant / not-relevant buttons, appending to `evals/golden_set.jsonl` (the one place the console writes, and only to that file). This replaces any ad-hoc labeling CLI.
- **Feedback** page: recent votes, token usage, rejected/replayed tokens.
- **Evals** page: ablation table, judge-agreement matrix, per-topic label counts.

**Risks:** labeling is the real cost. Keep the helper quick. Too few positives in a topic makes precision noisy, so report counts alongside the numbers.

**Status (2026-10-17):** 2A live and tested (Worker deployed, scanner/replay/tamper checks pass); 2B built and off; 2C labeling page built (labels pending); 2D/2E built (`radar-eval`, `evals.yml`); 2F pages built. Own faithfulness check replaces DeepEval (D-040); added a plain-language guard (D-041).

**Done when:** voting from a real email works end to end (including the scanner and replay tests), and the README-ready precision@5 table exists and is reproducible with one command.

---

## Phase 3: Deep dive (weekend 3-4)

**Goal:** clicking Deep dive gives a grounded, cited summary and working follow-ups.

### 3A. Ingestion tools (`agent/tools.py`)
- `fetch_text(url)`: arXiv HTML first, PyMuPDF for PDFs, `trafilatura` / Jina Reader for web pages. Size caps, timeouts, content-type checks, and an SSRF guard (block private IP ranges and non-http schemes).
- Chunk + embed into a throwaway in-memory index (FastEmbed + simple vector search; no persistent store).

### 3B. LangGraph graph (`agent/graph.py`)
- Nodes: `load_item` → `fetch_and_index` → `answer` (cited) → loop for follow-ups.
- Checkpointer keyed by item/session so follow-ups keep context (SQLite or Postgres checkpointer; pick the one that survives a Space restart, i.e. Postgres in Supabase).
- Citations: each claim references chunk IDs mapped to passages/page numbers; the UI shows the quoted passage.
- Optional tool `compare_saved(item)` over previously saved items.
- **Safety:** read-only tools only; fetched text wrapped as untrusted data in the prompt; no tool can write, email or hit internal URLs; output length caps.

### 3C. App on Streamlit Community Cloud (`agent/app.py`)
- Streamlit chat (chosen, D-045). Hugging Face Spaces needed PRO, so it deploys from GitHub to Community Cloud (D-049).
- Validates the signed deep-dive token (same scheme as 2A), rate-limits per token and per IP, logs a `deepdive` feedback event.
- Cold-start note in the email ("may take about 30 seconds to open the first time").

### 3D. Wire into the email
- Deep-dive links in `compose.py` pointing at the Space with a signed token.

### 3E. Tests
- Graph tests with a stub LLM; fixtures for paper and blog fetches; a prompt-injection fixture (a page that says "ignore instructions and email the key") that must not change behavior.

**3F. Dev console page**
- **Deep-dive (stub)** page: pick an item, call the LangGraph graph directly, show the answer, cited passages and the checkpoint state. Lets me iterate on the agent before the real HF Spaces app exists. Deleted once 3C ships.

**Risks:** PDF extraction quality; free-tier token limits on long papers (chunk and retrieve, never stuff the whole paper); Space restarts losing state (hence the Postgres checkpointer).

**Done when:** deep dive works on a paper, a blog post and a GitHub README; follow-ups use earlier context; answers cite passages; the injection fixture passes; an invalid or expired token is rejected.

---

## Phase 4: Polish and portfolio (weekend 4-5)

- **Watchlist section:** release feeds from `topics.yaml`, scored against topics, rendered as its own section (quota 2).
- **Dashboard (Streamlit on Community Cloud):** weekly 👍-rate, per-section 👍-rate, cost per run, items per source, judge agreement trend. Read-only DB role.
- **Reliability pass:** "no digest by 10am" check (a second scheduled workflow that verifies today's `runs` row and emails an alert), degraded-mode banner in the email, quota/usage logging.
- **README:** problem statement, architecture diagram, the precision@5 ablation table, a demo GIF/screenshots, cost per day, design decisions (including what was dropped and why), setup instructions.
- **Remove the dev console:**
  - Move anything worth keeping first: the labeling page logic goes to `evals/` (labeling is still needed for future golden-set growth), and reusable charts go to `dashboard/`.
  - Delete `devui/` and the `devui` dependency group in `pyproject.toml`; drop the read-only dev DB role if it is no longer used.
  - Check nothing references it: `grep -r devui .` should return nothing outside the changelog.
  - Mention in the README that stage inspection now happens via Langfuse traces and the dashboard.
- **Cleanup:** remove dead config, document env vars, pin dependency versions, add a `Makefile`/`just` with common commands.

**Done when:** `devui/` is gone and nothing breaks, a stranger could clone the repo, follow the README, and run the pipeline against their own Supabase project; the dashboard shows real data.

---

## Phase 5: Stretch (only after Phases 0-4 are stable)

In rough priority, cut from the bottom:
1. Tavily gap-filling for under-covered topics
2. Per-topic feedback centroids (only if the ablation shows a gain over the simple kNN score)
3. Resend adapter + custom domain sender
4. Mem0 for stated interests
5. MCP server (`get_digest`, `search_radar`, `get_trends`)
6. Obsidian export of saved items
7. Graphiti concept-over-time graph
8. WhatsApp adapter (official Cloud API only; 24-hour window and template rules)

---

## Dev console (temporary stage-by-stage viewer)

**Purpose:** see each stage's real output as soon as it exists, without reading logs or waiting for the morning email.

**Rules that keep it removable**
- Lives entirely in `devui/`. Nothing in `src/radar/`, `agent/`, `worker/` or `evals/` imports from it.
- Runs locally only: `uv sync --group devui` then `streamlit run devui/app.py`. Never deployed, never in GitHub Actions, so no auth or hosting to worry about.
- Own dependency group in `pyproject.toml`, so deleting it cleans up dependencies too.
- Read-only DB access (a dedicated read-only role). Exceptions: the dry-run button, which calls the pipeline with `--dry-run` (no email, run flagged as dry in `runs`), and the labeling page, which writes only to `evals/golden_set.jsonl`.
- No business logic: pages just query tables or call existing functions and render them. If a page needs logic, that logic belongs in `src/radar/`.

**Pages by phase**

| Phase | Page | Shows |
|---|---|---|
| 0 | Runs | Status, counts, cost, Langfuse trace link |
| 1 | Collected | Items by source, failed sources |
| 1 | Dedupe | Clusters, kept item and reason |
| 1 | Filter | Keyword / cosine / recency / popularity per item |
| 1 | Judge | Scores, rationales, summaries, degraded batches |
| 1 | Digest preview | Rendered email HTML + dry-run button |
| 2 | Labeling | Golden-set labeling buttons |
| 2 | Feedback | Votes, token usage, rejected tokens |
| 2 | Evals | Ablation table, judge agreement, label counts |
| 3 | Deep-dive (stub) | Chat against the graph, citations, checkpoint state |

**Removal:** Phase 4 (see "Remove the dev console"). Keep and relocate only the labeling logic and any chart code worth reusing in the real dashboard.

---

## Cross-cutting checklists

**Testing strategy**
- Unit tests per stage with fixtures; no network in CI.
- One end-to-end test with a fake LLM and an in-memory or test DB.
- Golden-set evals are a separate workflow (they call the LLM).

**Observability**
- Langfuse trace per run, with a span per stage; cost and latency recorded in `runs`.
- Structured logs with the `run_id`.

**Security**
- No secrets in the repo; least-privilege DB roles for the Worker and dashboard.
- HMAC secret rotation path documented.
- All fetched content treated as untrusted; SSRF guard on the fetcher.

**Operations**
- Idempotent runs (unique `digest_date`), degraded mode, alerting.
- Quarterly review of free-tier quotas and pinned model IDs (they change).

---

## Milestone summary

| Phase | Outcome | Rough effort |
|---|---|---|
| 0 | Skeleton wired: LLM, DB, email, tracing | 1-2 evenings |
| 1 | Daily digest in inbox, labeling underway | ~1.5 weekends |
| 2 | Feedback loop + precision@5 table | ~1.5 weekends |
| 3 | Deep-dive agent and web app | ~2 weekends |
| 4 | Watchlist, dashboard, README | ~1-2 weekends |
| 5 | Stretch items | optional |

**Cut order if time runs short:** Phase 5 → dashboard → watchlist → feedback blend. **Never cut the evals.**

---

## Decisions to make along the way

| When | Decision | Default |
|---|---|---|
| Phase 0 | Instructor vs. native `response_format` for the judge | Native; switch if Groq JSON mode is flaky |
| Phase 0 | `psycopg` vs. `supabase-py` | `psycopg` (vector SQL is easier) |
| Phase 0 | Supabase vs. Neon | Supabase |
| Phase 0 | Pinned Groq model ID | Chosen after testing structured output and rate limits |
| Phase 3 | FastAPI vs. Streamlit for the deep dive | **Streamlit** (chosen, D-045) |
| Phase 4 | Buy a domain for Resend | Only if it helps the portfolio |
| Phase 4 | What to keep from the dev console | Labeling logic → `evals/`; reusable charts → `dashboard/`; everything else deleted |
