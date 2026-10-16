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
| D-013 | 0 | Pin model IDs from live provider lists | Accepted |
| D-014 | 0 | Direct psycopg, SQL migrations, partial unique index lock | Accepted |
| D-015 | 0 | Python 3.11 and uv via pip | Accepted |
| D-016 | 0 | Temporary read-only dev console | Accepted |
| D-017 | 0 | Private repo; secrets via gh from .env | Accepted |

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

### D-008: Feedback links are signed, single-use and POST-confirmed
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
