# Flow

How the system works end to end, what runs when, and how far along the build is. Update the status tables as stages are built.

Legend: ✅ built and verified · 🔨 in progress · ⬜ planned

---

## 1. Daily run (the pipeline)

Triggered by GitHub Actions cron (and manually via `workflow_dispatch`).

```mermaid
flowchart TD
    T[Cron / manual trigger] --> L{Claim run<br/>runs.digest_date}
    L -- already sent today --> X[Exit: nothing to do]
    L -- claimed --> C[Collect<br/>arXiv · HF Papers · HN · RSS · GitHub]
    C --> D[Dedupe<br/>canonical URL · hash · embedding clusters · not recently sent]
    D --> F[Cheap filter<br/>keywords + cosine to anchors + recency + popularity + votes<br/>topic-balanced shortlist]
    F --> J[LLM judge<br/>5-10 items per call, typed scores + rationale + summary]
    J --> M[Diversify<br/>MMR + section quotas + 1 exploration slot]
    M --> PL[Editor pass<br/>make entries plain and distinct]
    PL --> P[Compose HTML<br/>signed feedback links]
    P --> S[Send email]
    S --> R[Mark run sent<br/>write digests, scores, counts, cost, trace id]
    R --> MT[radar-maintain<br/>slim 30d, delete 180d, keep digest/voted/labeled]
    C -. source fails .-> W[Log, skip source, continue]
    J -. all LLMs fail .-> G[Degraded mode:<br/>filter-score ranking, flagged in email]
    G --> M
```

Typical numbers from a live run: ~410 collected → ~395 unique → ~393 fresh → 33 judged → 8 in the digest (5 core, 2 watchlist, 1 exploration).

Rules that always hold:
- The run row is created first and is the lock. A retry or late duplicate cron cannot send a second digest (partial unique index on non-dry runs).
- A failed source or exhausted LLM chain degrades the digest instead of cancelling it.
- Dry runs (`is_dry_run`) execute everything except sending, and never take the lock.
- The whole run is one Langfuse trace; each stage is a nested span.

### Stage status

| Stage | Module | Status |
|---|---|---|
| Config + secrets | `config.py`, `topics.yaml`, `.env` | ✅ |
| DB + migrations + run lock | `db.py`, `db/migrations/` | ✅ |
| LLM router + structured output | `llm.py` | ✅ |
| Tracing | `tracing.py` | ✅ |
| Email adapter | `deliver/email.py` | ✅ |
| Collect (arXiv, HF papers, HN, blogs, tool releases, new GitHub repos) | `collect/` | ✅ |
| Dedupe + embed | `dedupe.py`, `embed.py` | ✅ |
| Cheap filter | `filter.py` | ✅ |
| Judge | `judge.py` | ✅ |
| Diversify | `diversify.py` | ✅ |
| Compose | `compose.py` | ✅ |
| Orchestrator | `pipeline.py` | ✅ |
| Scheduled workflow | `.github/workflows/daily-digest.yml` | ✅ |
| Editor pass (plain + distinct) | `plain.py`, `judge.edit_digest` | ✅ |
| Storage retention | `maintain.py`, `radar-maintain` | ✅ |
| Vote-based ranking | `personalize.py` (weights 0 until evals justify) | ✅ built, off |
| Feedback links | `feedback.py`, `worker/` (Cloudflare) | ✅ live |
| Evals | `evals/` package, `radar-eval`, `evals.yml` | ✅ (waiting for labels) |

---

## 2. One LLM call

Every model call, whatever the stage, goes through `llm.complete_structured`.

```mermaid
sequenceDiagram
    participant S as Stage (e.g. judge)
    participant L as llm.complete_structured
    participant R as LiteLLM Router
    participant G as Groq (primary)
    participant F as Gemini / OpenRouter (fallbacks)
    participant LF as Langfuse

    S->>L: prompt, Pydantic schema, generation name
    L->>L: build messages (schema embedded in system message)
    L->>LF: open generation (model, input messages)
    L->>R: completion(JSON mode, temperature 0)
    R->>G: try primary
    alt Groq ok
        G-->>R: JSON text
    else error / 429 / model gone
        R->>F: next fallback
        F-->>R: JSON text
    end
    R-->>L: response
    L->>LF: record actual model, tokens, output, reasoning
    L->>L: validate with Pydantic
    alt invalid
        L->>R: re-ask once with the validation error
    end
    L-->>S: typed object + model used
```

---

## 3. Feedback loop

```mermaid
sequenceDiagram
    participant U as Me (email client)
    participant W as Cloudflare Worker
    participant DB as Supabase
    participant P as Next day's pipeline

    U->>W: GET /f/{signed token}
    W-->>U: confirm page (no state change; scanners stop here)
    U->>W: POST /f/{signed token}
    W->>W: verify HMAC, expiry, nonce unused
    W->>DB: upsert feedback (idempotent), mark nonce used
    P->>DB: read feedback for revealed-interest score
    P->>P: rank = stated interests (anchors) blended with revealed interests (kNN)
```

One click on a button records the vote and shows a message for that action (D-047); unverified clients (scanners, previews) get a confirm page instead. Buttons in the email: **More like this** (`up`), **Less like this** (`down`), **Save for later** (`save`). Status: ✅ live at `research-radar-feedback.<your-subdomain>.workers.dev`; votes are stored and scored, but only influence ranking once the evals justify a non-zero weight.

### Evals loop

```mermaid
flowchart LR
    L[Labeling page<br/>relevant / not] --> G[(golden_labels)]
    S[(item_scores per day)] --> E[radar-eval<br/>offline replay]
    G --> E
    V[(feedback votes)] --> E
    E --> T[Ablation table · judge calibration<br/>plain-language · faithfulness · model IDs]
    T --> W[Change weights in topics.yaml] --> E
    T --> CI[evals.yml gate]
```

---

## 4. Deep dive

```mermaid
flowchart LR
    E[Email Deep-dive link<br/>signed token] --> A[Streamlit app]
    A -->|validate token + rate limit| G[LangGraph graph]
    G --> FT[Fetch full text<br/>arXiv HTML · PyMuPDF · trafilatura]
    FT --> IX[Throwaway index<br/>chunk + embed]
    IX --> AN[Cited answer]
    AN --> CH[(Saved chat<br/>per item, Postgres)]
    CH --> FU[Follow-up question] --> G
```

Safety: read-only tools only; fetched text is untrusted; private-network URLs are blocked. Status: ✅ live on Streamlit Community Cloud (D-049); an "Explain in depth" button in each email item opens it with a signed link (D-050). Chats are saved per item in Postgres (D-054), so a reopened link shows the earlier conversation. Pending: blog-post fixture check.

---

## 5. Tracing flow

```mermaid
flowchart TD
    R["radar-digest-run (trace root)<br/>session = digest-YYYY-MM-DD<br/>tags: digest, dry-run | scheduled"]
    R --> C1[collect-sources]
    R --> C2[dedupe-items]
    R --> C3[filter-candidates]
    R --> C4[judge-items]
    C4 --> GEN["generation: judge-batch<br/>model · messages · tokens · reasoning"]
    R --> C4b[edit-digest]
    R --> C5[compose-digest]
    R --> C6[send-email]
```

Audited against a real run: root `radar-digest-run` → `collect-sources`, `dedupe-items`, `filter-candidates`, `judge-items` (→ one `judge-batch` generation per batch, with model and token usage), `diversify-items`, `compose-digest`, `send-email`. Keep these names stable; dashboards and evaluators will depend on them.

---

## 6. How a change moves through the repo

```mermaid
flowchart LR
    I[Pick next task in plan.md] --> B[Build + unit tests<br/>fakes, no network]
    B --> V[Verify for real<br/>radar-smoke / dry run / Langfuse trace audit]
    V --> DL[Record choices in decision.md<br/>update flow.md status]
    DL --> CM[Secret scan on staged diff]
    CM --> PU[Commit + push]
    PU --> CI[GitHub Actions: ruff + pytest]
```

Environments:
- **Local:** `.env`, dry runs, the dashboard's Labeling page.
- **GitHub Actions:** secrets from repo settings (set via `gh`), scheduled daily run, CI.
- **Hosted services:** Supabase (data), Langfuse (traces), Groq/Gemini/OpenRouter (LLMs), Gmail SMTP (email); Cloudflare Worker (vote links) and Streamlit Community Cloud (deep dive).

---

## 7. Phase map

| Phase | Outcome | Status |
|---|---|---|
| 0 Foundations | LLM, DB, email, tracing, CI, secrets | ✅ |
| 1 Digest MVP | Daily email (papers, blogs, tool releases, new repos) | ✅ built; a week of unattended mornings pending |
| 2 Feedback + evals | Votes flow back, precision@5 table | 🔨 built; waiting for ~250 labels to produce the table |
| 3 Deep dive | Cited, follow-up-capable chat per item | ✅ live; email button added; polish pending |
| 4 Polish | Watchlist, dashboard, missed-digest alarm, README, dev console removed | ✅ (dashboard not deployed yet) |
| 5 Stretch | Optional extras | ⬜ |
