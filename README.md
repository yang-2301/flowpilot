# FlowPilot

**A config-driven automation engine: webhook/interval triggers, HTTP/LLM/transform/condition steps, retries with exponential backoff, dead-lettered run history and one-click replay.**

The third piece of a three-repo portfolio ([docmind-rag](https://github.com/jeffyang-ai/docmind-rag) · [triagedesk](https://github.com/jeffyang-ai/triagedesk)). This one demonstrates the systems skills the other two don't: idempotent execution, retry semantics, observability, and the operational discipline that keeps a workflow engine from lying to you.

## What it does

```
POST /hooks/{workflow_id}/{secret}          ──►  Run created
        │
        ▼
  step 1  transform      {{ trigger.email }} → normalised context
  step 2  http_request   POST https://crm.example/…   (retries ×3, backoff)
  step 3  llm            draft outreach               (retries ×2)
  step 4  condition      company_size > 100 ?  ──false──►  remaining steps skipped
  step 5  transform      flag_priority
        │
        ▼
  Run log: per-step status · attempts · duration · output · replay
```

Workflows are **declarative JSON**. The engine validates them at save time (unknown step types, missing required config, duplicate names, out-of-range retry budgets all get 422 — broken configs never enter the database).

## The reliability surface (what this repo is actually about)

- **Retries with exponential backoff** per step (`max_attempts` 1–5, jittered backoff capped at 10s). The run log shows the attempt count per step — you can *see* a retry policy working instead of trusting it.
- **Deterministic failure demo**: the seed includes a `/demo/flaky` endpoint that fails the first N calls per bucket. Fire the demo workflow and watch a run go `failed → failed → failed → ok` across 4 attempts. Reliability demos shouldn't depend on luck.
- **Dead-lettering**: runs that exhaust retries are marked `dead` and stay queryable — every failure is replayable with the exact original payload.
- **Replay**: one click reruns a historical run against the same payload, linked back to the original (`replay_of`).
- **Conditions skip forward, not sideways**: a false condition marks the run `skipped` and short-circuits the remaining steps — no half-executed branches.
- **Strict templates**: `{{ steps.enrich.output.id }}` resolves via dotted paths; unknown paths raise at run time instead of silently rendering empty strings.
- **Never 500 on a failing step**: the retry loop catches everything a step can throw; failures land in the run log, not the client's lap.

## Two bugs the build process caught (kept honest, documented)

1. **Event-loop deadlock**: webhook handlers originally executed runs synchronously on the async event loop. A workflow that called back into the *same* API (as the flaky demo does) deadlocked: the run waited on an endpoint the blocked loop could never serve. Fixed by executing runs in the threadpool — the kind of bug that only shows up when a workflow's target is the engine itself, which is exactly what the demo exercises.
2. **Retry state not cleared on success**: an earlier failed attempt's error survived into a later successful attempt, marking a fully-successful run as `failed`. Caught by the retry unit test, fixed, and pinned by the test suite.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + SQLite. `engine.py` is a pure function over `(steps, payload)` — the API layer just persists what it returns. Scheduler is a single polling thread with the DB as source of truth.
- **Step types**: `transform` · `http_request` (urllib, timeout, template body) · `llm` (OpenAI when `OPENAI_API_KEY` is set, documented mock mode otherwise) · `condition`.
- **Auth**: management API behind a bearer admin token; webhook URLs carry a per-workflow secret compared in constant time.
- **Frontend**: Vue 3 + TypeScript + Vite. Workflow list with step chips (retry budget shown as `×3`), JSON editor with server-side validation, runs list with status filter, run detail with the full step timeline and replay.

## API surface (abridged)

```
POST /hooks/{workflow_id}/{secret}     fire a webhook workflow → { run_id }
GET  /api/workflows                    admin token required
POST /api/workflows                    server validates steps (422 on bad config)
PUT  /api/workflows/{id}               edits keep the webhook secret stable
GET  /api/runs                         ?status=&workflow_id=
GET  /api/runs/{id}                    full step timeline
POST /api/runs/{id}/replay             rerun with the original payload
GET  /demo/echo  /demo/flaky           deterministic demo targets
```

## Run it

```bash
make setup          # pip + npm install
make seed           # 3 demo workflows (lead enrichment, retry demo, health watchdog)
make api            # engine on :8123
make web            # console on :5174
make test           # 13 tests: engine semantics, retry math, webhook auth, replay, interval firing
```

Then open the console, hit **Fire test event** on the retry demo, and watch the attempt count in the run timeline.

## Stack decisions

- **Declarative JSON over DSL**: workflows are data, so validation, diffing and storage stay trivial. A visual builder would render to the same JSON.
- **SQLite** — a demo engine doesn't need Postgres, and single-file storage makes the repo instantly runnable. Models are plain SQLAlchemy.
- **Threadpool execution** — the engine's steps are blocking calls by design (urllib); isolating them from the event loop is the load-bearing decision. A production version would swap the threadpool for a queue worker; the run-log contract wouldn't change.
- **Mock LLM mode** — the `llm` step runs offline with an explicitly-labelled mock so the demo needs no credentials; production config flips it to real completions with zero code change.

---

Part of my portfolio: [docmind-rag](https://github.com/jeffyang-ai/docmind-rag) (retrieval with citations + evaluation harness) and [triagedesk](https://github.com/jeffyang-ai/triagedesk) (full-stack AI support desk). I build automation that survives contact with production.
