# AI Visibility Intelligence API

A Flask REST API that registers a business profile, runs a 3-agent AI pipeline
to discover high-value AI-search queries in that business's competitive
space, scores them for opportunity, and generates content recommendations to
close visibility gaps.

Built for the "AI Visibility & Search Intelligence API" technical assessment.

## Contents

- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Agent design](#agent-design)
- [Prompt engineering](#prompt-engineering)
- [Opportunity score formula](#opportunity-score-formula)
- [Real data vs. heuristic fallback (tradeoff)](#real-data-vs-heuristic-fallback-tradeoff)
- [Data model](#data-model)
- [API reference](#api-reference)
- [Testing](#testing)
- [Other tradeoffs & known limitations](#other-tradeoffs--known-limitations)
- [AI tool usage disclosure](#ai-tool-usage-disclosure)

## Quick start

### Option A: Docker Compose (recommended)

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...
docker compose up --build
```

The entrypoint runs `flask db upgrade` automatically before starting
`gunicorn`. The API is then live at `http://localhost:5000`.

```bash
curl http://localhost:5000/api/v1/health
```

### Option B: Local setup script

```bash
# macOS/Linux
./setup.sh

# Windows (PowerShell)
./setup.ps1
```

Both scripts create `.env` from `.env.example` (if missing), create a
virtualenv, install dependencies, and run migrations. Then:

```bash
# macOS/Linux
source .venv/bin/activate && python run.py

# Windows
.\.venv\Scripts\python.exe run.py
```

### Try it

```bash
curl -X POST http://localhost:5000/api/v1/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Frase",
    "domain": "frase.io",
    "industry": "SEO Content Tools",
    "description": "AI-powered content briefs and SEO research",
    "competitors": ["surferseo.com", "marketmuse.com", "clearscope.io"]
  }'

curl -X POST http://localhost:5000/api/v1/profiles/<profile_uuid>/run
curl "http://localhost:5000/api/v1/profiles/<profile_uuid>/queries?min_score=0.6"
curl http://localhost:5000/api/v1/profiles/<profile_uuid>/recommendations
```

Without `OPENAI_API_KEY` set, the API still runs and returns valid, well-formed
responses -- Agent 1 falls back to a deterministic query template set, and
Agent 2 records a `scoring_error` per query instead of crashing. This is
deliberate (see [Agent design](#agent-design)) and is a quick way to confirm
the plumbing works before spending API credits.

### Optional demo UI

Open **http://localhost:5000/** in a browser for a minimal, dependency-free
HTML/JS page (`app/static/index.html`, served directly by Flask at `/`) that
drives the same endpoints -- create/load a profile, run the pipeline, browse
queries and recommendations -- without needing `curl`. This is **not part of
the graded API surface** (the spec explicitly excludes a frontend, see "What
We Are Not Looking For"); it's included purely as a convenience for manually
exercising the API. No build step, no JS framework, no extra dependencies --
it's one static file using `fetch()` against `/api/v1/...` on the same origin.

## Architecture

```
ai_visibility_api/
├── app/
│   ├── __init__.py            # create_app() factory
│   ├── config.py               # Config / TestingConfig / DevelopmentConfig / ProductionConfig
│   ├── extensions.py            # db, migrate, limiter singletons
│   ├── models/                  # SQLAlchemy models (one file per entity)
│   ├── agents/                  # Agent 1/2/3, each a standalone class + its own prompts
│   │   ├── base.py               # shared BaseAgent (llm_client, model)
│   │   ├── discovery.py          # Agent 1 -- Query Discovery
│   │   ├── scoring.py            # Agent 2 -- Visibility Scoring
│   │   └── recommendation.py     # Agent 3 -- Content Recommendation
│   ├── services/
│   │   ├── llm_client.py         # OpenAI wrapper: JSON mode + schema validation + 1 retry
│   │   ├── data_provider.py       # DataForSEO / heuristic-fallback abstraction
│   │   ├── opportunity_score.py   # pure scoring formula (no I/O, fully unit-testable)
│   │   ├── pipeline.py            # PipelineOrchestrator -- runs agents 1->2->3, isolates failures
│   │   └── container.py           # wires config -> LLMClient/DataProvider/agents/orchestrator
│   ├── api/                      # Flask blueprints + consistent error handling
│   ├── schemas/                  # Pydantic schemas: agent JSON output + request validation
│   └── static/index.html         # optional demo UI, served at "/" -- not graded, see below
├── tests/                        # pytest, fully offline (fake LLM client + fake data provider)
├── migrations/                   # Flask-Migrate/Alembic
├── Dockerfile / docker-compose.yml / docker-entrypoint.sh
├── setup.sh / setup.ps1
└── run.py                        # entrypoint: app = create_app()
```

**Why this layout.** Each agent is a standalone class with its own prompts
and its own fallback policy, so they're independently testable (see
`tests/test_agents.py`) without booting Flask or a database. The orchestrator
(`services/pipeline.py`) is the only place that knows the three agents run in
sequence and how failures in one stage should affect the others -- that
policy doesn't leak into the agents themselves or into the API layer.
`services/container.py` is the single seam where config becomes concrete
objects (`LLMClient`, `DataProvider`, the three agents, the orchestrator) --
tests replace it entirely with fakes rather than monkeypatching internals.

### Request flow for `POST /profiles/{uuid}/run`

```
Flask route (api/profiles.py)
  -> current_app.pipeline_orchestrator.run(profile)
       -> QueryDiscoveryAgent.run(profile)                    [1 LLM call]
       -> for each discovered query:
            VisibilityScoringAgent.run(query, profile)         [1 DataProvider call + 1 LLM call]
       -> ContentRecommendationAgent.run(gap_queries, profile)  [1 LLM call]
  -> PipelineOutcome(run, queries, recommendations)
  -> JSON response
```

## Agent design

Each agent is a small class (`app/agents/*.py`) that takes an `LLMClient` +
model name in its constructor and exposes one `run(...)` method. None of them
know about Flask, SQLAlchemy sessions, or each other -- the orchestrator is
the only thing that sequences them and persists their output.

| Agent | Class | Real-world data used | LLM output |
|---|---|---|---|
| 1. Query Discovery | `QueryDiscoveryAgent` | profile fields only | 10-20 natural-language queries, each labeled with an intent |
| 2. Visibility Scoring | `VisibilityScoringAgent` | search volume + competitive difficulty via `DataProvider` | simulated AI-answer visibility (mentioned? at what rank?) |
| 3. Content Recommendation | `ContentRecommendationAgent` | top opportunity-score queries where the domain is absent | 3-5 recommendations, each pinned to one query |

**Agent 2's "simulation" is a real LLM call, not a coin flip.** It asks the
model to actually answer the discovered question the way a general-purpose AI
assistant would -- listing the specific companies/products it would mention,
in order -- then checks whether the target domain shows up and at what rank.
This is the same idea "AI visibility" tools use in production: you can't
query ChatGPT's real answer distribution from a test harness, but you can get
a serviceable, cheaper proxy for it from the same class of model.

### Failure isolation (the part the rubric calls out explicitly)

The spec requires that "if Agent 2 fails for one query, continue processing
the rest." This is implemented at three levels, deliberately not all in the
same place:

1. **`LLMClient.complete_json`** (services/llm_client.py) already retries
   once with a corrective follow-up prompt if the model returns invalid JSON
   or JSON that fails the pydantic schema. This is the first line of defense
   and catches the common case (a slightly malformed response) without ever
   surfacing an error to the agent.
2. **Agent 1 and Agent 3** catch anything that still escapes step 1 (e.g. no
   API key, network failure, still-malformed after retry) and return a
   `degraded=True` result built from a local deterministic fallback --
   template queries for Agent 1, template recommendations for Agent 3 --
   instead of raising. These are whole-pipeline-scope agents: if Agent 1 has
   nothing, there's nothing to score, so it self-heals rather than aborting.
3. **Agent 2 deliberately does not catch its own exceptions.** Per-query
   failure isolation is an orchestrator concern, not an agent concern --
   `PipelineOrchestrator.run` wraps each individual `scoring_agent.run(...)`
   call in its own `try/except`, records `scoring_error` on that one
   `DiscoveredQuery` row, and moves on to the next query. One bad query never
   stops the batch (verified in `tests/test_agents.py::test_scoring_agent_propagates_llm_failure_for_orchestrator_to_isolate`
   and `tests/test_api.py` via the live no-API-key smoke test described above).

If Agent 1 or Agent 3 raise anyway (a genuine bug, not an LLM hiccup), the
orchestrator has one more safety-net `try/except` around each that marks the
whole `PipelineRun` `failed` (Agent 1) or degrades to zero recommendations
without touching already-scored queries (Agent 3) -- the API never 500s
because of an agent failure.

## Prompt engineering

Every agent's system prompt (in full, in the source -- `app/agents/*.py`)
follows the same shape:

1. **Persona + scope** -- what this agent is and, just as importantly, what
   it is *not* (e.g. Agent 1 is told explicitly not to generate SEO keyword
   fragments or questions about the business's internal operations).
2. **Concrete rules**, not vibes -- e.g. Agent 1 requires a specific mix of
   4 intent categories with examples of each, and requires competitor names
   to appear in roughly a third of comparison/transactional queries so the
   discovered set isn't generic. Agent 3 requires the `content_type` to match
   the query's intent (comparison queries -> `comparison_page`), not just
   "pick one."
3. **The exact JSON schema, inlined in the prompt itself** -- every system
   prompt ends with a literal `{ ... }` example showing every key and its
   allowed values, plus "Output ONLY a single JSON object... no prose, no
   markdown code fences." This is paired with OpenAI's `response_format:
   {"type": "json_object"}` (JSON mode) so malformed JSON is already rare
   before validation even runs.
4. **A pydantic schema that mirrors the prompt exactly**
   (`app/schemas/agent_io.py`) -- `min_length`/`max_length` on lists,
   `Literal` types for enums like intent/content_type/priority, bounded
   `ge`/`le` on `mention_position`. This is what actually decides
   "malformed" -- if the JSON parses but violates the schema (wrong enum
   value, too few queries, missing key), `LLMClient` treats it identically
   to a JSON parse failure and retries with the validation error included in
   the corrective follow-up message, so the model sees exactly what it got
   wrong.

**Reference-key design for Agent 3.** Rather than asking the model to echo
back full query text (fragile to match against the DB afterwards, especially
if the model paraphrases) or a UUID (models routinely truncate/mangle long
IDs), each gap query is given a short `Q1`, `Q2`, ... label directly in the
prompt. The model is instructed to respond with that label
(`target_query_ref`), which is looked up in a local dict to recover the real
`query_uuid` -- string-matching-free and deterministic. If the model
references a label that doesn't exist (rare, but happens), that one
recommendation is dropped rather than mis-attributed; if *every* reference
turns out invalid, the agent falls back to templated recommendations for the
top gap queries rather than silently returning nothing for a query set that
demonstrably has real gaps.

### Model selection

All three agents call **OpenAI**, chosen because the user already had usage
available (see `.env.example`). Two different models are used across
agents, controlled independently via `OPENAI_MODEL_DISCOVERY` /
`OPENAI_MODEL_SCORING` / `OPENAI_MODEL_RECOMMENDATION`:

- **`gpt-4o`** for Discovery and Recommendation -- both are one-shot,
  higher-value calls per pipeline run (1 each) where output quality
  (creative-but-realistic queries; specific, non-generic recommendations)
  matters more than marginal cost.
- **`gpt-4o-mini`** for Scoring -- this is the call made once *per discovered
  query* (up to `MAX_DISCOVERY_QUERIES`, default 18), so it dominates total
  token spend. The task itself (simulate an answer, extract a structured
  mention/rank) is more mechanical and tolerates a smaller model well.

`LLMClient` is a thin, provider-agnostic wrapper around the OpenAI SDK
(`app/services/llm_client.py`); swapping an individual agent to Anthropic
would mean adding an `AnthropicLLMClient` with the same `complete_json(...)`
signature and passing it into that agent's constructor in
`services/container.py` -- no changes needed anywhere else, since agents only
depend on the `complete_json` interface, not a concrete provider.

## Opportunity score formula

```
score = 0.30 * volume_norm
      + 0.20 * ease_of_ranking       (= 1 - difficulty/100)
      + 0.35 * visibility_gap
      + 0.15 * intent_weight
```

All four components are normalised to `[0, 1]` before weighting; the sum is
clamped to `[0, 1]` as a defensive measure against float drift. Implementation
and full inline rationale: `app/services/opportunity_score.py`.

| Component | Weight | Why this weight |
|---|---|---|
| `visibility_gap` | **0.35** (largest) | This product exists to find where the target domain is *absent* from AI answers. A query the domain already dominates isn't an opportunity no matter how big or easy -- so absence has to dominate the score. Not-visible = 1.0; visible ranked 1-3 = 0.05; visible 4-6 = 0.25; visible >6 or rank-unknown = 0.3-0.5; not-yet-scored = 0.6 (a neutral placeholder so a partial scoring failure doesn't silently zero out the score). |
| `volume_norm` | 0.30 | **Log-scaled**, not linear: `log10(volume+1) / log10(10_000+1)`, clamped to 1.0. Raw monthly volume for these queries realistically spans ~10 to 50,000+; a linear blend would let one viral head-term drown out difficulty/gap/intent entirely. Log-scaling means a 10x volume difference matters, but not 10x as much as going from invisible to visible. |
| `ease_of_ranking` | 0.20 | `1 - difficulty/100`. Rewards queries that are realistically winnable soon, not just theoretically valuable. |
| `intent_weight` | 0.15 (smallest) | comparison=1.0, transactional=0.9, informational=0.6, navigational=0.5. Useful as a tie-breaker (a comparison query converts better than a purely informational one) but deliberately weighted lowest since intent is LLM-assigned, not measured -- the least reliable of the four inputs shouldn't be able to outweigh the three that are grounded in real numbers or a direct yes/no visibility check. |

This is a design decision, not the only valid one -- e.g. a team optimizing
purely for quick wins might weight `ease_of_ranking` higher than `volume_norm`.
Unit tests in `tests/test_opportunity_score.py` pin down the *ordering*
properties that should hold regardless of exact weights (not-visible always
beats visible-top-position; higher volume always beats lower volume all else
equal; etc.) rather than exact numeric outputs, so the weights can be tuned
without rewriting the test suite.

## Real data vs. heuristic fallback (tradeoff)

The spec requires real third-party data (e.g. DataForSEO) for search volume
and competitive difficulty. This assessment was completed without a
DataForSEO trial account provisioned, so:

- **`app/services/data_provider.py`** defines a `DataProvider` interface with
  two implementations: `DataForSEOProvider` (calls DataForSEO's real
  `keywords_data/google_ads/search_volume/live` endpoint) and
  `HeuristicDataProvider` (a **deterministic**, hash-seeded estimator --
  never random, so the same query text always yields the same numbers, which
  matters for `/recheck` semantics).
- **`get_data_provider(config)`** picks `DataForSEOProvider` automatically
  the moment `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` are set in `.env` --
  no code changes required. If the live call fails at runtime (rate limit,
  network, credentials expired), `DataForSEOProvider` catches it and falls
  back to the heuristic **for that one query only**, logging a warning, so a
  DataForSEO outage degrades scoring quality rather than crashing the run.
- Every `DiscoveredQuery` row records **`data_source`** (`"dataforseo"` or
  `"heuristic"`) so it's always visible, per-row, which numbers are real and
  which are estimates -- nothing is silently presented as real data it isn't.
- The heuristic itself isn't a random number generator: it seeds off
  `sha256(query_text)` and shapes the result with two real priors (shorter/
  broader queries skew higher-volume than long-tail phrasing; queries with
  commercial markers like "best"/"vs"/"compare" skew both volume and
  difficulty upward, since those SERPs are genuinely more contested) so
  opportunity-score *ordering* stays sane even without live data.

**To switch to real data:** set `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD`
in `.env` (a free DataForSEO trial provides both) and restart -- nothing else
changes.

## Data model

Four tables, all with UUID string primary keys (matching the `*_uuid` fields
the spec's JSON examples use directly, avoiding an internal-id/external-uuid
split), full SQLAlchemy relationships with `cascade="all, delete-orphan"`,
and Alembic migrations under `migrations/`.

- **`BusinessProfile`** -- as specified, plus `status` transitions
  (`created` -> `analyzed` once a pipeline run completes).
- **`PipelineRun`** -- as specified, plus `recommendations_generated` (mirrors
  `queries_discovered`/`queries_scored` for symmetry in the run summary).
- **`DiscoveredQuery`** -- as specified, plus: `query_intent` (drives both
  Agent 3's `content_type` choice and the opportunity score's intent
  weighting), `ai_answer_snippet` (the simulated answer text, for
  transparency/debugging), `data_source`, `scoring_error` (non-null exactly
  when Agent 2 failed for this row -- this is what makes partial-failure
  handling inspectable via the API, not just internal), `last_checked_at`
  (distinct from `discovered_at`, set by `/recheck`).
- **`ContentRecommendation`** -- as specified, plus `run_uuid` for
  traceability back to the pipeline run that generated it.

One deliberate denormalization: `DiscoveredQuery.query_intent` is a plain
string, not a foreign key to an enum table -- the intent set is small,
closed, and defined once in code (`app/models/query.py::VALID_INTENTS`);
a lookup table would add a join for no real benefit at this scale.

## API reference

All endpoints are under `/api/v1`. Every error response has the same shape:

```json
{"error": {"code": "profile_not_found", "message": "...", "details": null}}
```

| Method | Path | Notes |
|---|---|---|
| `POST` | `/profiles` | Validates via pydantic (`ProfileCreateRequest`); normalises domains (`https://www.frase.io/` -> `frase.io`). |
| `GET` | `/profiles/{uuid}` | Includes a `stats` block (query/recommendation counts, avg opportunity score). |
| `POST` | `/profiles/{uuid}/run` | Runs Discovery -> Scoring -> Recommendation in sequence. Rate-limited (`PIPELINE_RUN_RATE_LIMIT`, default 10/hour/IP). Always returns 201 with a `status` of `completed` or `failed` -- HTTP-level success and pipeline-level outcome are intentionally separate. |
| `GET` | `/profiles/{uuid}/queries` | `?min_score=`, `?status=visible\|not_visible\|unknown`, `?page=`, `?per_page=` (max 100). Sorted by `opportunity_score` descending, nulls last. |
| `GET` | `/profiles/{uuid}/recommendations` | Newest first. |
| `POST` | `/queries/{uuid}/recheck` | Re-runs Agent 2 only, for one query; updates `last_checked_at`. |
| `GET` | `/health` | Liveness check (used by the Docker healthcheck). |

## Testing

```bash
pytest -q
```

24 tests, all fully offline -- no network calls, no API key required. Two
test doubles (`tests/fakes.py`) make this possible: `FakeLLMClient` returns
pre-programmed pydantic model instances keyed by schema class (so a test can
stage exactly what "the model said" without touching the network), and
`FakeDataProvider` returns fixed metrics. This is why the tests can assert
on real behavior (schema validation, fallback triggering, per-query failure
isolation, ref-to-uuid mapping) rather than just "the function didn't crash."

- `test_opportunity_score.py` -- pure formula, no mocking needed: bounds,
  monotonicity per factor, unknown-intent doesn't crash.
- `test_agents.py` -- each agent in isolation: happy path, LLM-failure
  fallback (Agents 1/3), failure propagation (Agent 2), invalid-reference
  handling (Agent 3).
- `test_api.py` -- full Flask test client against an in-memory SQLite DB:
  create/get profile, validation errors, 404s, a full pipeline run wired to
  fakes, query filtering/pagination, recommendations, recheck.

## Other tradeoffs & known limitations

- **Synchronous pipeline execution.** Per the spec's explicit note that this
  is acceptable, `POST /run` runs all three agents in-request. For
  `MAX_DISCOVERY_QUERIES=18` (default), that's up to 20 sequential LLM calls,
  which is why gunicorn's worker timeout is raised to 180s in `Dockerfile`.
  Async/background execution with a polling endpoint (Celery, RQ) would be
  the natural next step for production use.
- **No auth layer**, per the spec ("out of scope").
- **SQLite by default.** `DATABASE_URL` swaps to Postgres with no code
  changes (`SQLALCHEMY_DATABASE_URI` is just the env var), but SQLite keeps
  `docker compose up` a one-command experience with no extra service.
- **Rate limiting is in-memory** (`flask-limiter` with `memory://`), so it
  resets on restart and doesn't share state across multiple worker
  processes/replicas. Fine for a single-instance assessment deployment; a
  real deployment would point `RATELIMIT_STORAGE_URI` at Redis.
- **Recommendation-to-query is many-to-one at most** (each recommendation
  targets exactly one query, per the spec's `target_query_uuid` field), so a
  single content piece that would realistically address 3 related gap
  queries still gets logged against just one. Acceptable simplification for
  this scope.

## AI tool usage disclosure

This project was built with **Claude Code** (Anthropic), used directly for
the full implementation: the Flask app-factory structure, all SQLAlchemy
models and migrations, the three agent classes and their prompts, the
pipeline orchestrator, the API layer, the pytest suite (including the fake
LLM client/data provider test doubles), and this README.

What wasn't automatic: the open-ended design decisions the spec calls out as
part of the evaluation were made deliberately, not left as defaults --
the opportunity score's weighting and reasoning, the DataProvider fallback
strategy (real DataForSEO vs. a documented deterministic heuristic, discussed
below), the choice to use OpenAI only with two different models split by
agent cost/quality tradeoff, the agent failure-isolation boundaries (which
failures self-heal inside an agent vs. get isolated per-query by the
orchestrator), and the Q1/Q2 reference-key scheme for Agent 3. Each was a
specific choice made in conversation with the assistant, not accepted as a
default suggestion.

The build was also verified, not just generated: the full pytest suite was
run to green, the live dev server was exercised end-to-end against the real
OpenAI API (confirming real query discovery, scoring, and recommendations,
not just mocked output), and two real bugs were caught this way -- a
Flask-SQLAlchemy `.query` attribute collision from a poorly named
relationship backref, and an `openai`/`httpx` version incompatibility that
would have silently broken every LLM call regardless of API key validity.
