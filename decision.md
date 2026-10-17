# Decision log

Every implementation decision: what the problem was, what we chose, why, and what we rejected. Newest entries go at the bottom of each phase. Add an entry whenever a choice is made, and mark old ones `Superseded by D-xxx` rather than deleting them.

**Status values:** Accepted · Superseded · Open (decided provisionally, revisit)

| ID | Phase | Decision | Status |
|---|---|---|---|
| D-001 | Design | Pipeline is deterministic code, not an agent | Accepted |
| D-002 | Design | Drop PydanticAI; judge = LiteLLM + Pydantic | Accepted |
| D-003 | Design | Keep LangGraph only for deep-dive | Accepted |
| D-004 | Design | Hybrid cheap filter with topic anchors | Accepted |
| D-005 | Design | Simple kNN feedback score before per-topic centroids | Accepted |
| D-006 | Design | Store snippets only, not full text | Accepted |
| D-007 | Design | Deep-dive on HF Spaces; Worker only for feedback | Accepted |
| D-008 | Design | Signed, single-use, POST-confirmed feedback links | Accepted |
| D-009 | 0 | Groq is the primary LLM | Accepted |
| D-010 | 0 | Gmail SMTP first, behind an adapter | Accepted |
| D-011 | 0 | Provider-agnostic structured output | Accepted |
| D-012 | 0 | Explicit Langfuse generations, not LiteLLM callback | Accepted |
| D-013 | 0 | Pin model IDs from live provider lists | Accepted (Gemini ID updated in D-037) |
| D-014 | 0 | Direct psycopg, SQL migrations, partial unique index lock | Accepted |
| D-015 | 0 | Python 3.11 and uv via pip | Accepted |
| D-016 | 0 | Temporary read-only dev console | Accepted |
| D-017 | 0 | Private repo; secrets via gh from .env | Accepted |
| D-018 | 1 | arXiv via the daily RSS feed, not the search API | Accepted |
| D-019 | 1 | Merge by canonical URL with source priority | Accepted |
| D-020 | 1 | Near-duplicate clustering in memory, not SQL | Accepted |
| D-021 | 1 | bge-small embeddings, stored once per item | Accepted |
| D-022 | 1 | Hybrid filter formula; topic vectors without anchors for now | Accepted |
| D-023 | 1 | Judge: small batches, strict prompt, graceful degradation | Accepted |
| D-024 | 1 | Watchlist = latest stable release per tool | Accepted |
| D-025 | 1 | Exploration slot = good item far from the usual profile | Accepted |
| D-026 | 1 | DB is the source of truth for scores and generated text | Accepted |
| D-027 | 1 | Dry-run semantics and run statuses | Accepted |
| D-028 | 1 | Scheduled workflow: 22:00 UTC (03:30 IST), serialized, cached model | Accepted (moved twice) |
| D-029 | 1 | Lint: ignore E501; dev console uses st.iframe | Accepted |
| D-030 | 1 | Digest written in plain language with a scenario example | Accepted |
| D-031 | 2 | Feedback: signed links to a Worker, writes via one locked-down database function | Accepted |
| D-032 | 2 | Golden labels live in a database table, labeled in the dev console | Accepted |
| D-033 | 2 | Anchors are real papers looked up on arXiv | Accepted |
| D-034 | 2 | Topic-balanced shortlist for the judge | Accepted |
| D-035 | 2 | Judge reliability: retry pass, pacing, hard timeouts | Accepted |
| D-036 | 2 | Text buttons instead of emoji for feedback | Accepted |
| D-037 | 2 | LLM chain fixes: Gemini 3.5 Flash-Lite, per-model timeouts, low reasoning effort | Accepted |
| D-038 | 2 | Vote-based ranking built, switched off until evals justify it | Accepted |
| D-039 | 2 | Evals are an offline replay of stored scores; LLM checks are opt-in | Accepted |
| D-040 | 2 | Own faithfulness check instead of DeepEval | Accepted |
| D-041 | 2 | Plain-language guard: shared glossary, checker, and rewrite pass | Superseded by D-043 |
| D-042 | 2 | Eval gate in CI with label-count and threshold rules | Accepted |
| D-043 | 2 | Entries must be specific AND plain: topic angles, explain-once vocabulary, editor pass, topic cap | Accepted |
| D-044 | 2 | Storage retention: slim after 30 days, delete after 180, keep what matters forever | Accepted |
| D-047 | 3 | One-click feedback: a browser click records at once; unverified clients still get the confirm page | Accepted |
| D-053 | 3 | Vote result page: a tick and one message, tries to close its own tab after 2.5 s | Accepted |
| D-052 | 3 | New GitHub repos with a README snippet, capped at 2 core picks, so repos join the papers | Accepted |
| D-051 | 3 | Deep-dive links last 7 days (vote links stay 30) | Accepted |
| D-050 | 3 | Email gets an Explain-in-depth button: stateless signed deepdive token to the Community Cloud app | Accepted |
| D-049 | 3 | Deep dive embeds in batches of 4 (2.4 GB -> 0.56 GB) and deploys to Streamlit Community Cloud | Accepted (pending deploy) |
| D-048 | 3 | Deep dive deploys as a Docker Space built by a script from this repo | Superseded by D-049 |
| D-045 | 3 | Deep dive UI is Streamlit (not FastAPI + htmx) | Accepted |
| D-046 | 3 | Deep dive agent: tool-less LangGraph, code-side retrieval, cited answers, SSRF-guarded fetch | Accepted (local, not deployed) |

---

## Design decisions (made during the plan review, before coding)

### D-001: Daily batch is a pipeline, not an agent
- **Problem:** The original brief mixed "agent" language into the daily flow.
- **Decision:** Collect → dedupe → filter → judge → diversify → compose is plain Python orchestrated by `pipeline.py`. Agents are used only where reasoning over open-ended input is needed (the deep-dive chat).
- **Why:** The steps are fixed and known. A deterministic pipeline is cheaper, testable stage by stage, reproducible for evals, and easier to trace and debug than an agent loop.
- **Rejected:** An orchestrating agent that chooses steps (more cost and variance, no benefit here).

### D-002: Drop PydanticAI; judge is LiteLLM + Pydantic
- **Problem:** The brief used PydanticAI as the "one new thing". The judge is a single batched structured-output call.
- **Decision:** Use LiteLLM for routing and a Pydantic schema for validation (see D-011). Instructor is the fallback if a provider's JSON mode proves unreliable.
- **Why:** PydanticAI adds a second abstraction on top of LiteLLM (model routing overlaps) for a job that needs no tools or agent loop. The project's real new learning is the eval + feedback-personalization loop.
- **Rejected:** PydanticAI (overkill here); Instructor as the default (extra dependency, still fine as a fallback).

### D-003: LangGraph stays, but only for the deep-dive
- **Problem:** Is a graph framework justified?
- **Decision:** Keep LangGraph for the deep-dive agent. The first answer is a linear RAG chain; the graph earns its place through checkpointed follow-up chat.
- **Why:** Per-item conversation state and follow-ups are the one place where stateful orchestration matters, and LangGraph is already familiar.
- **Rejected:** LangGraph for the daily batch (D-001); a hand-rolled chat loop (reinvents checkpointing).

### D-004: Hybrid cheap filter with topic anchors
- **Problem:** One embedded sentence per topic matches loosely and ranks generic "LLM" content too high.
- **Decision:** Filter score = keyword/BM25 boost + cosine to topic vectors built from 5-10 anchor items (description as fallback) + recency + popularity. arXiv is keyword-prefiltered before embedding.
- **Why:** Anchors define "what I actually want" far better than a description, keywords add precision, and anchors also seed the feedback model (cold start). Prefiltering keeps arXiv's volume affordable.
- **Rejected:** Embedding-only filtering (imprecise); LLM-scoring everything (too costly for free tiers).

### D-005: Simple kNN feedback score first
- **Problem:** Per-topic centroids of 👍/👎 would be noisy at roughly one vote a day.
- **Decision:** Score = similarity to the k nearest liked/saved items minus similarity to the k nearest disliked items, over all votes. Save and deep-dive count as stronger positives. Per-topic splitting only if the ablation shows a gain. The blend is off until the ablation justifies it.
- **Why:** Fewer parameters, works with little data, and the evals decide whether complexity is worth it.
- **Rejected:** Per-topic centroids from day one.

### D-006: Store snippets, not full text
- **Problem:** Supabase free tier caps the database at about 500MB.
- **Decision:** `items.snippet` holds title/abstract only. Full text is fetched at deep-dive time.
- **Why:** Keeps storage small, and also keeps us on the right side of source terms (summarize and link, don't copy).
- **Rejected:** Persisting raw article text.

### D-007: Deep-dive on Hugging Face Spaces; Worker for feedback only
- **Problem:** Where does the deep-dive page run?
- **Decision:** A Python app (FastAPI or Streamlit) on HF Spaces serves the deep-dive. The Cloudflare Worker (JS) handles only the feedback confirm page and POST.
- **Why:** The deep-dive needs Python libraries (PyMuPDF, trafilatura, FastEmbed) that Workers cannot run. The trade-off is a cold start of about 30 seconds after the Space sleeps; the email says so.
- **Rejected:** Deep-dive inside a Worker (no Python).

### D-008: Feedback links are signed, single-use and POST-confirmed (amended by D-047)
- **Problem:** Mail scanners pre-fetch links and would register phantom votes; links could be replayed or forged.
- **Decision:** A link opens a confirm page (GET changes nothing); only the button's POST records the vote. Tokens are HMAC-signed (item, run, action, expiry) with a stored nonce, single use, and votes are idempotent per item.
- **Why:** Defeats pre-fetching, replay and double counting.
- **Rejected:** Direct GET-to-vote links.

---

## Phase 0: Foundations

### D-009: Groq is the primary LLM
- **Problem:** Which provider leads the fallback chain?
- **Decision:** Groq first, Gemini and OpenRouter free models as fallbacks, via LiteLLM Router with 2 retries.
- **Why:** The user chose Groq. It is fast and has a free tier; fallbacks protect a daily run from a 429 or an outage.
- **Watch:** Groq's free tier is tight on tokens per minute and per day, so judge batches are 5-10 items with backoff.

### D-010: Gmail SMTP first, behind an adapter
- **Problem:** Which email provider?
- **Decision:** Gmail SMTP with an app password. `deliver/email.py` exposes `send(subject, html, to)`; the backend (smtp or resend) is picked by `EMAIL_BACKEND`.
- **Why:** Only one recipient and one email a day, no domain needed, 10 minutes of setup, and self-sent mail rarely hits spam. The adapter makes moving to Resend (when a domain exists) a config change.
- **Rejected:** Resend first (needs a verified domain to send to anyone but yourself); Brevo (no advantage here).
- **Note:** SMTP initially failed because the app password needed regenerating; fixed by the user.

### D-011: Provider-agnostic structured output
- **Problem:** Native `json_schema` support differs across Groq, Gemini and OpenRouter models.
- **Decision:** Ask for JSON mode, embed the JSON Schema in a system message, validate with Pydantic, and on failure re-ask once with the validation error (`radar.llm.complete_structured`).
- **Why:** Works identically across every provider in the fallback chain, so a fallback never changes behavior or breaks parsing.
- **Rejected:** Native `response_format=schema` (inconsistent); Instructor by default (see D-002).

### D-012: Explicit Langfuse generations, not the LiteLLM callback
- **Problem:** The first tracing attempt used LiteLLM's `langfuse_otel` callback.
- **Decision:** Wrap each LLM call in a Langfuse `generation` created with the Python SDK, recording model, role-labelled messages in and out, token usage, and reasoning (in metadata). The callback is not used.
- **Why:** Auditing the real trace showed the callback emitted a bare `SPAN` for Groq with no model, tokens, input or output, and its own environment label (`production`). The explicit generation nests correctly under the stage span and carries everything the Langfuse best-practices checklist asks for.
- **Rejected:** The callback (poor data for this provider); no tracing (observability is a project goal).
- **Open:** Cost shows empty because `openai/gpt-oss-120b` is not in Langfuse's pricing table; Groq is free tier so this is acceptable for now.
- **Also:** secrets are masked before export (`tracing.mask`), tracing is a no-op without keys, and `flush()` is called before exit.

### D-013: Pin model IDs from live provider lists
- **Problem:** All three IDs first written in `topics.yaml` returned "model not found".
- **Decision:** List each provider's models with the real keys and pin from that: `groq/openai/gpt-oss-120b`, `gemini/gemini-2.5-flash-lite`, `openrouter/nvidia/nemotron-3-super-120b-a12b:free`.
- **Why:** Free-tier catalogs change quickly; guessing IDs from memory fails. The plan also adds a CI model-ID smoke test.
- **Rejected:** "latest" aliases (silent behavior changes).

### D-014: Direct psycopg, SQL migrations, partial unique index as the run lock
- **Problem:** How to talk to Supabase, version the schema, and guarantee one digest per day?
- **Decision:** Plain `psycopg` against Postgres (pgvector SQL is easier than via supabase-py). Schema lives in `db/migrations/*.sql`, applied in order and tracked in `schema_migrations`. `runs` has a partial unique index on `digest_date` where `not is_dry_run`.
- **Why:** SQL migrations are transparent and portable (Neon would work too). The partial index makes duplicate real runs impossible at the database level while still allowing unlimited dry runs and smoke tests.
- **Rejected:** supabase-py (weaker for vector queries); a plain unique `digest_date` (would block dry runs); an ORM (unneeded weight).

### D-015: Python 3.11 and uv installed via pip
- **Problem:** The plan said Python 3.12, but the machine has 3.11, and `uv` was missing.
- **Decision:** `requires-python >=3.11`; installed uv with `pip install --user uv` and run it as `python -m uv`.
- **Why:** No feature needs 3.12, and avoiding a new interpreter download keeps setup simple. Installing uv through pip avoided changing PATH or running an unattended installer script.
- **Rejected:** Forcing 3.12 (extra download, no benefit).

### D-016: Temporary read-only dev console
- **Problem:** Hard to see what each stage produces without reading logs or waiting for the email.
- **Decision:** A local Streamlit app in `devui/` with its own dependency group, read-only DB access, no business logic, never deployed; removed in Phase 4 (labeling logic and reusable charts move first).
- **Why:** Fast feedback during build, and strict isolation (nothing in `src/` imports it) makes deletion a one-folder operation.
- **Rejected:** Reading raw SQL/logs only (slow); building the final dashboard early (premature).

### D-017: Private repo; secrets pushed with gh from .env
- **Problem:** Public or private repo, and how to put keys into GitHub Actions without exposing them?
- **Decision:** Private repo for now (public in Phase 4 after a secrets/history audit). The GitHub CLI was installed and logged in by the user; `gh secret set` reads values from the local `.env` and sends them via stdin, so nothing is printed or pasted. A secret scan runs on the staged diff before every commit.
- **Why:** The repo will hold personal labels and candidate data while rough; private still has ample free Actions minutes; the stdin approach keeps secrets out of chat and logs.
- **Incident:** The user had pasted real keys into `.env.example` (a committed template). They were moved to the git-ignored `.env` and the template restored to placeholders before any commit.
- **Rejected:** Public from day one; pasting secrets into the GitHub UI one by one (error-prone for the user).

---

## Phase 1: Digest MVP

### D-018: arXiv via the daily RSS feed, not the search API
- **Problem:** The first probe of `export.arxiv.org/api/query` returned HTTP 429.
- **Decision:** Read `rss.arxiv.org/atom/<cats>` (one request per run, "new" announcements only; replacements skipped), then keyword-prefilter before embedding.
- **Why:** The feed is built for daily consumption, needs one request, and does not rate-limit the way the search API does. The prefilter cut ~390 daily items to ~160.
- **Rejected:** Search API with sleeps and retries (fragile, slower).

### D-019: Merge by canonical URL with source priority
- **Problem:** The same paper arrives from arXiv, HF Daily Papers and HN under different URLs.
- **Decision:** `canonical_url` strips tracking params and collapses arXiv `pdf`/`html`/`export`/versioned links to `https://arxiv.org/abs/<id>`. HF Papers items are emitted with the arXiv URL. `merge_by_url` keeps the highest-priority source (arxiv > watchlist > hf_papers > rss > hn), the max popularity and the longest snippet.
- **Why:** One item per story, but the signals that matter (HF upvotes, HN points) are kept.

### D-020: Near-duplicate clustering in memory, not SQL
- **Problem:** The review said to do dedupe in SQL; the daily batch is only ~400 items.
- **Decision:** Exact dedupe and "already sent in the last N days" use SQL; near-duplicate clustering runs in memory with numpy (cosine >= 0.92, higher-priority and more popular items win). Dropped items get `cluster_id` pointing at the kept one.
- **Why:** A pairwise matrix over ~400 vectors is instant and far simpler to test than a lateral-join query. pgvector search will matter for the feedback score (Phase 2), where history is large.
- **Deviation from:** the design note "dedupe in SQL"; revisit if batches grow.

### D-021: bge-small embeddings, stored once per item
- **Decision:** FastEmbed `BAAI/bge-small-en-v1.5` (384-dim, CPU), pinned in `topics.yaml`. Only items without a stored embedding are embedded; the model name is stored per item. The first call downloads ~100MB, so CI caches `FASTEMBED_CACHE_PATH`.
- **Why:** Free, no API quota, good quality for its size, and matches `vector(384)`. Storing the model name makes a future model change detectable.

### D-022: Hybrid filter formula; topic vectors without anchors for now
- **Decision:** `score = 0.55*cosine + 0.20*keyword + 0.15*recency + 0.10*popularity (+ feedback, weight 0)`.
  - cosine is the best weighted match across topic vectors, rescaled from bge's typical 0.35-0.80 range to 0-1;
  - keywords: title hits count double, saturating at 4;
  - recency: half-life 3 days; items older than 14 days (7 for watchlist) are dropped;
  - popularity: log-scaled, capped at 200.
  Top 30 regular items plus up to 6 watchlist items go to the judge. Weights live in `topics.yaml`.
- **Why:** Transparent, tunable, and every component is stored so Phase 2 can ablate it.
- **Open:** No anchor items yet, so topic vectors come from the description plus keywords. Adding 5-10 anchors per topic is the next quality lever. (Anchors are plain text for now; URL anchors are not auto-fetched.)

### D-023: Judge: small batches, strict prompt, graceful degradation
- **Problem:** First judge outputs were inflated (many 8-9) and one 30-item call risks truncation and position bias.
- **Decision:** Batches of 6 with a stable system prompt (topic rubric). The prompt asks for strict scoring across the full range and bans invented facts in summaries. After the change, relevance spread over 4-8. Final rank = `0.6*relevance + 0.2*novelty + 0.2*actionability` (divided by 10) `+ 0.15*filter_score`. Items scoring below 4 relevance are ineligible. If a batch fails or an item is missing, that item falls back to its snippet text and filter-based rank and is flagged "unscored"; the digest is marked degraded.
- **Why:** A digest must still go out when the LLM chain is down (principle: degrade, don't die).
- **Watch:** Judge calibration against my own labels is a Phase 2 eval.

### D-024: Watchlist = latest stable release per tool
- **Problem:** The first run showed five Langfuse releases at once, and a `dev.3` pre-release.
- **Decision:** Only each tool's newest non-pre-release entry is collected (dev/rc/alpha/beta/nightly/preview skipped), and it must be within 7 days.
- **Why:** The section answers "what's new in the tools I track", not a changelog dump.

### D-025: Exploration slot = good item far from the usual profile
- **Decision:** Among judged, eligible, unpicked items, choose the one maximizing `0.5*rank + 0.5*(1 - cosine-to-nearest-topic)`.
- **Why:** Surfaces something relevant but outside the usual topics so the system can discover interests. Simple on purpose; revisit with feedback data.

### D-026: DB is the source of truth for scores and generated text
- **Problem:** Summaries and "why it matters" were not persisted, which blocks previews, replay and the deep-dive link.
- **Decision:** Migration `0002` adds `summary`, `why_it_matters` and `filter_parts` to `item_scores`. The local `evals/candidate_pool/*.jsonl` is a convenience dump of each run's pool, not the system of record (CI runs are ephemeral).
- **Why:** Everything needed to rebuild a digest or an ablation lives in Postgres.

### D-027: Dry-run semantics and run statuses
- **Decision:** `--dry-run` takes no lock and sends no email; `--dry-run --email` emails the result but still takes no lock. Dry-run rows have status `dry-run`; real runs end `sent` or `degraded`; exceptions end `failed`. "Already sent" exclusion counts only non-dry runs.
- **Why:** Safe iteration without burning the day's slot or re-sending, and a real scheduled run is never blocked by experiments.
- **Verified:** a second real run for the same date is refused by the partial unique index; dry runs are allowed.

### D-028: Scheduled workflow: 22:00 UTC (03:30 IST), serialized, cached model
- **Decision:** `daily-digest.yml` runs at 22:00 UTC = 03:30 IST (originally 01:30 UTC; moved to 03:30 UTC on 2026-10-17, then to 22:00 UTC the same day because GitHub started the 03:30 UTC run 4.5 h late and the email arrived at 13:31 IST), supports manual dispatch with a dry-run toggle, uses a `concurrency` group so two digests never run at once, and caches the FastEmbed model. `APP_ENV=production` and `APP_RELEASE=<sha>` tag the Langfuse traces.
- **Why:** Morning delivery in IST with a buffer for GitHub's scheduler delays (the free tier gives no start-time guarantee; an exact option is a Cloudflare Worker calling `workflow_dispatch`, planned for Phase 3). `digest_date` is the UTC date of the run, so one run per day still holds. Late or duplicate fires are harmless because of the run lock.

### D-029: Lint ignores E501; dev console uses st.iframe
- **Decision:** Ruff ignores E501 (long prompt and SQL strings; 100 columns stays advisory). The digest preview uses `st.iframe` (the old `components.html` is deprecated); the template autoescapes all item text, which is acceptable for a local-only tool.

### D-030: Digest written in plain language with a scenario example
- **Problem:** The first real digest was too technical to understand without asking another AI (jargon like "indirect prompt injection", "benchmark", "agentic", scores such as "rel 8 · new 7 · act 6").
- **Decision:** The target reader is a curious non-expert. The judge now writes four reader-facing fields per item: `headline` (plain-English rewrite of the title, max 14 words), `summary` (2 short sentences, only facts from the title/snippet), `example` (an "Imagine..." scenario in an everyday setting such as a bank, shop or help desk, explicitly an illustration) and `why_it_matters` (one plain sentence). The prompt carries a jargon-to-plain-words glossary, a banned-words list and one worked before/after example. The email shows a friendly source label ("Research paper", "New tool release") and topic label (`label` in `topics.yaml`), drops the numeric scores, and keeps the original title in small grey text. A one-line "how to read this" intro was added. Migration `0003` stores `headline` and `example`.
- **Why:** A digest that needs a second tool to decode defeats its purpose. A concrete scenario is the fastest way to make an abstract idea land, and showing the original title keeps the source traceable.
- **Guardrail:** Examples must start with "Imagine" and must not state results, numbers or abilities absent from the snippet, so the plain version stays honest.
- **Known limit:** Some terms still slip through ("reinforcement learning", "training-free", method names). Tightening is cheap via the glossary in `judge.py`. A later eval can score "understandable without help" with an LLM judge or by asking the reader.
- **Rejected:** Adding a separate glossary section to the email (more to read); keeping scores in the email (meaningless to a newcomer); two versions of each digest, simple and technical (double the tokens, split attention).

---

## Phase 2: Feedback and evals

### D-031: Feedback via signed links to a Worker, writing through one locked-down database function
- **Problem:** Email links must record 👍/👎/save without exposing the database, without mail scanners creating phantom votes, and without anyone forging or replaying votes.
- **Decision:**
  - The pipeline mints one token per item and action (`radar.feedback.mint`): base64url JSON `{nonce, item, run, action, expiry}` plus an HMAC-SHA256 signature, valid 30 days. The nonce is stored in `feedback_tokens`.
  - A Cloudflare Worker (`worker/src/index.js`) serves `/f/<token>`. A GET only shows a confirm page (it reads a headline through a database function and changes nothing), so scanners pre-fetching links do no harm. Only the button's POST records the vote.
  - The Worker verifies the signature and expiry, then calls the database function `record_feedback`, which re-checks the nonce (exists, unused, matches item/run/action, not expired), marks it used and upserts the vote. A second click returns "already recorded"; an up vote replaces a down vote and vice versa.
  - The Worker only holds the Supabase publishable key. Migration `0004` enables row-level security on every table, revokes all table access from the public roles, and grants them execute on exactly two functions (`feedback_token_info`, `record_feedback`). Checked live: direct table reads with the key return 401, and a bogus token returns "invalid".
  - A Python-minted token is verified by the Worker's JavaScript in a cross-language test.
- **Why:** Defence in depth: a leaked publishable key can do nothing but redeem a valid unused token, and the signing secret never leaves the pipeline and the Worker.
- **Rejected:** Direct GET-to-vote links (scanners), a service-role key in the Worker (too powerful), putting the vote logic in the Worker with raw SQL (no good way to connect).

### D-032: Golden labels live in a database table, labeled in the dev console
- **Problem:** The plan said `golden_set.jsonl`, but CI is ephemeral and labels should sit next to the data they refer to.
- **Decision:** Table `golden_labels(item_id, relevant, labeled_at)`. The dev console's Labeling page shows one item at a time (plain-language headline, summary, original title, link) with Relevant / Not relevant / Skip buttons, mixing items that made the digest with ones that did not (hard negatives). It is the only dev console page that writes, and only to that table.
- **Why:** Labels survive across machines, join directly with scores for the ablation, and the page is a single click per item.

### D-033: Anchors are real papers looked up on arXiv
- **Problem:** Topic definitions came from a one-sentence description plus keywords, and the user had no list of favourite papers.
- **Decision:** I picked 2-4 well-known papers per topic (ReAct, Self-RAG, MT-Bench, MemGPT, AgentDojo, ...), fetched their real titles and abstracts from the arXiv API (21 of 22 found), and stored them as plain text under `anchors` in `topics.yaml`, with the arXiv link in a comment. The topic vector is the mean of the description and its anchors.
- **Why:** Concrete examples define a topic better than a description, and starting from famous papers avoids asking the user for knowledge they don't have. They can edit or extend the list any time.
- **Open:** Anchors skew to classic work; the feedback score and labels will refine the real taste. `enterprise-genai` has only 2 anchors because it is poorly covered by arXiv.

### D-034: Topic-balanced shortlist for the judge
- **Problem:** After anchors were added, one topic (memory) took 9 of 17 shortlist slots, crowding out RAG.
- **Decision:** `select_top` guarantees each topic its best 2 items (if it has them), then fills by score with no topic above 30% of the slots (first tried 40%, which still let memory take 12 of 33), relaxing the cap only if slots would otherwise stay empty.
- **Why:** The digest should cover the user's whole set of topics, and the judge's effort should not be spent on one broad topic. Tested with a synthetic skewed pool.

### D-035: Judge reliability: retry pass, pacing, hard timeouts
- **Problem:** After the plain-language fields were added, 4-7 of ~17 items came back unscored (valid JSON, missing items), and one run hung for over 10 minutes.
- **Decision:** `judge_all` retries skipped or failed items in a second pass, waits 4 seconds between batches (free-tier tokens per minute), logs fallbacks and failures, and the router now has a 90-second hard timeout per attempt. Anything still unscored degrades to snippet text as before.
- **Why:** A daily job must finish and must score what it can; a hung provider must never stall the run.

### D-036: Text buttons instead of emoji for feedback
- **Problem:** 👍/👎/🔖 looked informal and unclear in the email.
- **Decision:** Each item ends with three pill-shaped text buttons: **More like this** (filled, primary), **Less like this** and **Save for later** (outlined). The Worker's confirm page uses the same wording ("Show you more items like this one?" → "Yes, more like this"), a clean "Research Radar" card, and a CSS tick or warning mark instead of emoji. A fourth button, **Explain in depth**, arrives with the Phase 3 deep-dive (the Worker already knows that action).
- **Why:** States the effect of the click rather than a vague like/dislike, looks professional in any mail client, and maps directly to the stored actions (`up`, `down`, `save`).

### D-037: LLM chain fixes: Gemini 3.5 Flash-Lite, per-model timeouts, low reasoning effort
- **Problem:** A run stalled for 5+ minutes. Diagnosis: Groq's free tier caps `gpt-oss-120b` at 200,000 tokens per day and a day of test runs used it up; the Gemini fallback `gemini-2.5-flash-lite` now returns 404 ("no longer available to new users"); so every batch fell through to the free OpenRouter model, which took ~5 minutes per call.
- **Decision:**
  - Gemini fallback pinned to `gemini-3.5-flash-lite` (the replacement Google's error names; verified, ~10-18 s per judge batch).
  - Timeouts (75 s) are set on each model deployment, not just the router, and retries drop to 1, so a rate-limited or slow provider is skipped quickly.
  - `reasoning_effort: low` for gpt-oss models: most of its output tokens were hidden reasoning, which scoring does not need. This roughly halves token use per run.
- **Why:** One daily run uses ~30-40k Groq tokens, well inside the limit, but development runs can exhaust it; the chain must then degrade to a fast fallback, not a slow one.
- **Watch:** Avoid many full runs on the same day while developing; use `--top-n 8` for iteration.

### D-038: Vote-based ranking built, switched off until evals justify it
- **Decision:** `radar.personalize` scores a candidate as (weighted mean similarity to its 5 nearest liked items) minus (the same for disliked items), scaled to -1..1. "Save for later" weighs 1.5, "More like this" 1.0, "Less like this" -1.0. Votes are ignored below 5. The score is stored in each item's filter breakdown and can enter ranking in two places: `filter.weights.feedback` (shortlist) and `personalize.final_blend` (final rank). Both are 0.
- **Why:** Follows D-005 (simple kNN before per-topic centroids). Turning it on is a config change once the ablation shows that a blend beats the current ranker on your labels.
- **Leakage guard:** the ablation scores each labeled item leave-one-out, so an item's own vote never counts towards its own score.

### D-039: Evals are an offline replay of stored scores; LLM checks are opt-in
- **Decision:** `radar-eval` joins `golden_labels` with the stored filter components and judge scores of each digest day (latest run per day) and recomputes every ranker with the current config weights: keywords only, embedding only, hybrid filter, hybrid + judge (current), and + votes at blends 0.1/0.2/0.3. It reports P@5 per day and pooled, P@10, average precision and ROC-AUC. The judge is calibrated by sweeping the relevance cut-off (precision, recall, F1, Cohen's kappa). Plain-language checks are deterministic. Only `--faithfulness N` calls an LLM. The report is written to `evals/reports/latest.md` and shown on the dev console's Evals page.
- **Why:** Free, fast, reproducible, and it answers "what would ranking have been with these weights?" without re-running the pipeline. Changing a weight in `topics.yaml` and re-running shows the effect immediately.
- **Caveat (in the report):** labels only exist for items that reached the judge, so rankers are compared within the shortlist, not over all ~400 collected items.
- **Deviation:** labels are 0/1 relevance (not graded), so nDCG was dropped in favour of average precision.

### D-040: Own faithfulness check instead of DeepEval
- **Problem:** The plan named DeepEval for summary faithfulness. It defaults to OpenAI, adds a large dependency, and its LLM calls would bypass our router, fallbacks and Langfuse tracing.
- **Decision:** A ~30-line equivalent in `radar.evals.quality`: the LLM lists every factual claim in the summary and marks each as supported by the source (title + abstract) or not; the score is the supported share. It runs through `llm.complete_structured`, so it uses the same fallback chain and appears in Langfuse under a `radar-eval` trace. The "Imagine..." example is excluded because it is an illustration by design.
- **Why:** Same method (claim extraction + verification), no new dependency, consistent tracing. First run: 5/5 summaries, 100% of claims supported.
- **Rejected:** DeepEval (dependency and provider coupling for one metric); RAGAS (RAG-specific, same issues).

### D-041: Plain-language guard: shared glossary, checker, and rewrite pass
- **Problem:** The first eval run showed 45% of recent digest items with unexplained jargon (38% in the latest run, written by the Gemini fallback, which follows the glossary less strictly).
- **Decision:** `radar.plain` holds the one glossary (jargon → plain wording) and one checker (`unexplained_jargon`: a term counts as explained when bracketed next to plain words). The judge prompt renders the glossary from it. After the digest items are chosen, any item still flagged gets one small LLM rewrite of its four reader fields. The rewrite is kept only if it reduces the flagged terms and keeps the format (example starts with "Imagine", headline length). Added "training-free", "reinforcement learning" and "framework" to the glossary.
- **Why:** Measuring and fixing with the same rule closes the loop: what the evals flag is exactly what the pipeline repairs. Rewriting only the ~8 chosen items costs one extra call per day.
- **Guard:** The rewrite prompt forbids changing facts; the faithfulness eval would catch drift.

### D-042: Eval gate in CI with label-count and threshold rules
- **Decision:** `evals.yml` runs weekly (with a 5-item faithfulness sample), on pull requests touching `src/radar/**` or `topics.yaml`, and on demand. `--gate` fails on: any pinned model ID missing at its provider, jargon rate above 35%, faithfulness below 85% (when checked), and precision@5 of the current ranker below 50%. The ranking check is skipped until 100 labels exist. Thresholds live in `topics.yaml` under `evals:`. The report is uploaded as a workflow artifact.
- **Why:** Turns silent regressions (a retired model, a prompt change that brings back jargon, a weight change that hurts ranking) into a red CI run, without blocking anything while labels are still being collected.

### D-043: Entries must be specific AND plain
- **Problem:** The user found that every entry "felt the same" even across topics. Measured on the last digests:
  - the written entries were *more* alike than the papers they describe (similarity 0.68 vs 0.67);
  - "AI assistants" appeared 26 times across 5 digests and "new method" 7 times;
  - about 3 headlines per digest started the same way ("A new ...");
  - examples reused the settings suggested in the prompt (customer support x4, travel x2, bank);
  - "why it matters" lines were stock phrases ("find and fix problems", "helps developers");
  - selection: 4 of 6 research picks were labelled "AI agents", and two picks were the same idea.
  Root causes: the glossary forced every term into the same generic phrase; the prompt listed example settings;
  "agents" absorbed any paper that mentioned agents; the core section had no topic limit.
- **First attempt (overcorrected):** specificity rules made entries distinct (0 shared headline openings, 5 different
  topics in the top 5) but technical: reading level jumped to grade 14.3 ("approximate nearest-neighbor indexes",
  "effect binding"). Earlier plain digests read at grade 8.7-10.3.
- **Decision:**
  - Each topic in `topics.yaml` gets an `angle` (what the reader cares about) and the agents topic a `scope_note`;
    the judge picks the most specific topic.
  - Writing rules hold two things at once: SPECIFIC about what was found (finding, situation, a concrete detail)
    and PLAIN about how it works (everyday descriptions). At most one technical term per entry, explained once in
    brackets; none in headlines or why-it-matters. A three-way calibration example (too generic / too technical /
    just right) is in the prompt. Examples come from the item's own domain; tool releases get no invented scenario.
  - Vocabulary moved from "replace every term" to "explain once, then use the precise term" (`plain.item_jargon`,
    which also accepts explanations a few words after the term).
  - An editor pass reads all chosen entries together and makes them plain and distinct. Per entry it is kept only
    if format holds, jargon does not increase and the reading grade does not rise (small slack when it removes
    jargon); overall only if entries do not become noticeably more alike.
  - Selection: at most 2 core picks per topic; MMR lambda 0.6; the exploration slot prefers a topic not yet shown.
  - Evals now measure variety (written vs source similarity, shared headline openings, phrases repeated across
    3+ entries) and reading level (Flesch-Kincaid grade, limit 11), with gate thresholds in `topics.yaml`.
- **Why:** "Feels the same" and "too technical" are both measurable; fixing one without measuring the other swung
  the output from one failure to the other.

### D-044: Storage retention
- **Problem:** ~200 new items a day at ~5 KB each is ~380 MB a year; the free Supabase tier is ~500 MB. Only ~6% of
  items ever reach a digest.
- **Decision:** `radar-maintain` runs after each daily digest (its own step, `continue-on-error`, so it can never
  block the email). Items that were in a real digest, got a vote, or have a golden label are kept forever. Others:
  slimmed after 30 days (abstract and embedding dropped, about 90% of the row; title and link kept so the item is
  still recognised; a re-collected item is re-embedded and its abstract restored), deleted after 180 days with their
  scores. Test runs older than 14 days lose their digests and the scores of unlabeled items; run rows still
  referenced by votes are kept. Feedback-link tokens go 7 days after expiry. A warning prints above 400 MB.
  `--preview` reports what would change inside a rolled-back transaction.
- **Verified:** sandbox run (backdated rows, rolled back): 100 deleted, 197 slimmed, 18 of 19 test runs removed and
  the 1 run referenced by votes kept; nothing changed afterwards.
- **Rejected:** a soft-delete "trash" flag on every table (more queries to filter it everywhere); keeping
  everything (fills the free tier in ~15 months).

### D-045: Deep dive UI is Streamlit
- **Problem:** the Phase 3 chat needs a UI. FastAPI + htmx starts faster and gives full control over auth and rate
  limits; Streamlit is much quicker to build and the user wanted to see how it is done.
- **Decision:** Streamlit (`agent/app.py`), chosen by the user. All logic stays in `src/radar/agent/`; the page only
  renders, so swapping to FastAPI later means rewriting one thin file.
- **Why:** build speed and the user's wish to learn it. Known costs: slower cold start on a sleeping Space, and no
  request layer, so the signed-token check, per-item question cap (20) and 3 s spacing are done inside the script
  with in-process counters (reset on restart; acceptable for a one-reader app). Per-IP limiting is not possible
  in Streamlit, so it is dropped from the plan; the signed token already limits who can open a chat.
- **Alternatives:** FastAPI + htmx (recommended, not chosen).

### D-046: Deep dive agent design
- **Decision:** `src/radar/agent/`. `tools.fetch_text` is the only network door: http(s) only, every resolved address
  must be public (`ip.is_global`, re-checked on every redirect hop), 8 MB and 20 s caps, content-type allow-list;
  arXiv tries HTML, then PDF, then the abstract page. PDFs keep page numbers (PyMuPDF, first 60 pages), web pages go
  through trafilatura. `index.py` splits text into ~900-char chunks and keeps an in-memory FastEmbed index per item.
  `graph.py` is a LangGraph `load_item -> fetch_and_index -> answer` graph with a `MemorySaver` checkpointer keyed by
  item id. The model has no tools: retrieval is done in code, the passages go into `<source n=..>` blocks (a closing
  tag inside a page is stripped), the system prompt says sources are untrusted data, and the answer is a validated
  `DeepAnswer` (text with [n] markers + cited numbers). Cited numbers the model was never given are dropped. Questions
  are capped at 500 characters, answers at 1800. If the page cannot be read, the digest summary is used and the reader
  sees a notice. Each turn is one Langfuse trace (`radar-deep-dive-turn`, session = item).
- **Why:** the strongest defence against prompt injection is that a hijacked model has nothing to call, so the worst
  case is a wrong paragraph. Plain-language wording rules from D-043 apply to answers.
- **Verified:** 22 offline tests (SSRF cases incl. redirect to a metadata address, oversize, PDF page numbers, injection
  fixture, history, citation filtering); a live run on a real arXiv item gave a cited three-part answer and a correct
  follow-up; the Streamlit page loads and handles a follow-up under `AppTest`.
- **Not done yet:** Postgres checkpointer (chat history is lost on restart; Streamlit session state keeps the
  visible chat), Hugging Face Space deployment, Deep dive links in the email (needs a `deepdive` token: same HMAC
  scheme as feedback, action `deepdive`, not single-use), GitHub README/blog-post fixture checks.

### D-047: One-click feedback (amends D-008 / D-031)
- **Problem:** The confirm page meant two clicks per vote. The reader wanted one click and a message for that action.
- **Decision:** In `worker/src/index.js`, a GET that carries `Sec-Fetch-Mode: navigate` (browsers send it on a real
  click; server-side mail scanners and link previewers do not) and no prefetch/prerender `Purpose` header records the
  vote at once and shows an action-specific message with the item headline ("Noted. You'll see more items like this.").
  Any other GET, and HEAD, still shows the old confirm page and writes nothing; its button POSTs as before. A used
  token now repeats the same message under "Already recorded". Tokens stay signed, single-use and expiring.
- **Why:** Keeps D-008's protection against phantom votes (unknown client = confirm page) while giving a real click the
  one-step flow. Worker tests: `node --test worker/test/handler.test.mjs` (7 cases, fake database).
- **Risk:** a scanner that spoofs browser navigation headers could consume a token. Judged unlikely for Gmail; the vote
  would simply read "Already recorded" and can be changed by the other button's link.
- **Deployed:** 2026-10-17, version f4f2454f.

### D-048: Deep dive deploys as a Docker Space assembled by `deploy/build_space.py` (SUPERSEDED by D-049)
- **Problem:** the Space creation form offered only Gradio and Static, and the Space is a separate git repo that must not
  carry secrets or dev-only files.
- **Decision:** create the Space as Gradio, then replace its README header with `sdk: docker`, `app_port: 8501`.
  `deploy/build_space.py` copies only `src/radar/`, `agent/app.py` and `topics.yaml` into a clone of the Space repo
  (`deploy/_space_build/`, git-ignored), pins dependencies from `uv.lock`, and writes the Dockerfile (non-root uid 1000, the
  embedding model baked into the image so a cold start does not download it). Secrets live only in the Space settings;
  `APP_ENV=production` disables the local `?item=` shortcut so only signed links open a chat. The Space is Public (no PRO),
  protected by the signed token, not by hiding the URL.
- **Verified:** the assembled folder runs on its own (app loads and answers an item). The Docker build itself has not run yet.

### D-049: Small embedding batches, and Streamlit Community Cloud as the host
- **Problem:** Hugging Face now requires PRO for Gradio and Docker Spaces on free CPU (HTTP 402 on create; the form forced
  ZeroGPU), so D-048 is impossible on the free tier. Free hosts have little memory (Render 512 MB, Community Cloud ~1 GB)
  and the app measured 2,405 MB after one deep dive.
- **Finding:** the memory was FastEmbed's default batch size of 256, not the model. Embedding the 132 chunks of a paper:
  batch 256 = 2,139 MB, 16 = 573 MB, 4 = 317 MB. The whole app with batch 4 measured 562 MB and gave the same answers.
- **Decision:** `embed_texts(batch_size=...)`; the deep-dive index uses 4. The pipeline keeps the default. Deploy to
  Streamlit Community Cloud from the GitHub repo (`agent/app.py`, secrets in its settings, `APP_ENV=production`).
  Render stays the fallback if Community Cloud will not take the private repo (it needs a keyword-search or leaner setup
  at 512 MB). The unused `deploy/` Hugging Face kit is to be removed once the deploy works.
- **Not verified:** whether free accounts may deploy a private repo (sources disagree); real memory on the host.

### D-050: Explain-in-depth button in the email
- **Decision:** each digest item gets a button linking to `DEEPDIVE_BASE_URL/?t=<token>` (`Env.deepdive_base_url`,
  default the Community Cloud app; set it empty to switch the links off). The token is `feedback.mint(..., "deepdive")`:
  signed with the same HMAC secret, 30-day expiry, but **stateless and reusable**, with no `feedback_tokens` row, so the
  reader can reopen a chat. Vote buttons are unchanged; links render independently (the deep dive works even if the vote
  Worker URL is unset). The email footer notes the first open can take about 30 seconds (the app wakes from sleep).
  The plain-text version carries the link too. No CI change: the URL is public and defaulted in code; the signing secret
  is already a GitHub secret.
- **Why:** reuses the existing signing scheme; a reusable token fits a multi-turn chat, and the app only reads data.
- **Verified:** 84 offline tests; a dry-run digest was emailed with the new buttons; a locally minted link opened the live
  app and answered follow-ups.
- **Open:** chat history is lost on an app restart (in-memory checkpointer); README and blog-post fixtures.

### D-051: Deep-dive links last 7 days
- **Decision:** `feedback.DEEPDIVE_TTL_DAYS = 7`; vote links keep 30 (`TTL_DAYS`) because labelling an older digest is
  a legitimate use. A week is enough for a one-reader digest and limits how long a forwarded or leaked link works.
- **Why:** the reader asked for a shorter life; the token is stateless, so expiry is the only revocation there is.

### D-052: GitHub repos as a source (and why the digest was all papers)
- **Problem:** the digest was almost all papers. The sources were arXiv, Hugging Face daily papers, Hacker News keyword
  searches, a blog feed and release feeds for four watched tools, so nothing could find a new repo that suddenly gets
  attention (e.g. a popular new agent skill).
- **Decision:** `collect/github.py` searches repos CREATED in the last 14 days that already have 100+ stars, per topic
  (`sources.github_queries` in `topics.yaml`; knobs under `global_sources.github`). For the 25 strongest it fetches the
  README and puts the cleaned first 1,200 characters in the snippet, so the judge and the editor read the README, not
  only the one-line description. Forks and archived repos are skipped. One failing query is logged and skipped; the
  source only fails if every query does. Pacing is 8 s per search without a token, 2.2 s with one (`GITHUB_TOKEN`,
  which the daily workflow supplies). `diversify.max_per_source: {github: 2}` caps repos in the core section. The deep
  dive reads a repo's README directly (`raw.githubusercontent.com`, plain text kept whole).
- **Why the cap:** the first live run put 5 of 8 items from GitHub and 1 paper, because new, starred repos score high on
  recency and popularity. With the cap: 3 repos (2 core + 1 exploration), 3 papers, 2 tool updates.
- **Verified:** live collector returned 25 repos with README text; dry runs before and after the cap; 90 offline tests;
  deep dive on a real repo answered "how do I install it" from its README.
- **Risks:** star counts can be inflated (one repo had 14k stars in a week), so stars only feed the existing log-capped
  popularity term; the judge still decides relevance. Repos in other languages appear (the judge writes English).
  The collector adds ~30 s in CI (about 2 minutes locally without a token).
- **Queries (probed live, 14 days / 100+ stars):** exact phrases return few repos ("deep research", "guardrails",
  "text-to-SQL", "document parsing" gave 0, so were left out); GitHub's `topic:` tags return many (`topic:claude-code` 46,
  `topic:ai-agents` 31, `topic:mcp` 26) but also off-topic repos that the relevance filter removes. Added claude code,
  coding agent, multi-agent, browser agent, three `topic:` tags (agentic-systems) and reverse engineering, jailbreak
  (agent-security): 21 queries, 39 repos, about 3.5 minutes locally and under a minute in CI. `max_repos` is now 40.
  `global_sources.github.exclude` drops adult and gambling repos (a 2,500-star NSFW skill appeared in the live probe).
  Unauthenticated README fetches are limited to 60 an hour, so local runs often lack README text; CI has a token.
- **Rejected:** GitHub "trending" page scraping (no API, brittle); searching old repos by recent pushes (returns the
  well-known giants, not what is new).

### D-053: Vote result page is a tick and a message that closes itself
- **Problem:** after a one-click vote the reader landed on a card page (brand, heading, headline, "close this tab"),
  which felt like an extra step. An in-place tick on the email button is not possible: email clients strip scripts and
  the message is fixed once sent (AMP for Email could, but needs sender registration with Google; rejected as too heavy).
- **Decision:** `tickPage` in `worker/src/index.js` shows only a large tick and the action message ("Noted. You'll see
  more items like this."). After 2.5 s it calls `window.close()`; browsers allow that only for some tabs, so 0.5 s later a
  small "You can close this tab." hint appears if the tab is still open. A repeated click shows the same page with
  "Already recorded." in front. The confirm page for unverified clients (D-047) is unchanged.
- **Not verified here:** whether the reader's browser actually closes the tab (depends on how the mail app opens links).
- **Rejected:** a blank 204 response (no confirmation at all); voting inside the deep-dive app (a different flow).
