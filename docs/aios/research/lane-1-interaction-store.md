# Lane 1: Interaction Store & Adaptive Memory — Prior Art Survey

Scope: how leading OSS LLM-observability/tracing tools and agent-memory frameworks capture
a single LLM interaction, model it, and (optionally) adapt over time. Goal: find something to
reuse/port into a self-hosted FastAPI + Postgres LiteLLM-proxy fork, rather than inventing a schema
from scratch.

---

## 1. Langfuse

- Repo: https://github.com/langfuse/langfuse — ~31,200 stars
- License: MIT for the core app; enterprise features gated behind a separate proprietary license
  in `ee/`, `web/src/ee/`, `worker/src/ee/` (open-core model, not a source-available restriction on
  the core).

**Data model** (from `packages/shared/prisma/schema.prisma`, the entity shapes are stable even
though storage moved to ClickHouse in v3):
- `Trace`: `id`, `externalId`, `timestamp`, `name`, `userId`, `metadata` (json), `release`,
  `version`, `projectId`, `public`, `bookmarked`, `tags[]`, `input`/`output` (json), `sessionId`.
- `Observation` (a span/generation inside a trace): `id`, `traceId`, `type` (GENERATION/SPAN/EVENT),
  `startTime`/`endTime`, `parentObservationId`, `level`, `model`, `modelParameters`, `input`/`output`,
  `promptTokens`/`completionTokens`/`totalTokens`, `inputCost`/`outputCost`/`totalCost`
  (calculated + raw), `promptId` (FK to a versioned `Prompt`).
- `Score`: `id`, `traceId`, `observationId?`, `name`, `value` (float) or `stringValue`, `source`
  (API/EVAL/ANNOTATION), `authorUserId`, `comment`, `dataType`, `configId` — this is the
  feedback/eval primitive.
- `Dataset` / `DatasetItem` / `DatasetRunItems`: curated input/expectedOutput pairs, each run
  linked back to a `traceId`/`observationId` — this is the "turn an interaction into a test case"
  loop.
- `Prompt`: versioned, labeled (`labels[]`, e.g. "production"), with `config` json — prompt
  management is a first-class entity, not bolted on.

**Storage backend**: v2 was Postgres-only. **v3 (current) mandates Postgres (transactional:
users/projects/prompts/datasets) + ClickHouse (traces/observations/scores, `ReplacingMergeTree`
engine) + Redis/Valkey (queue/cache) + S3-compatible blob store** for large payloads. The team
explicitly evaluated and rejected a Postgres-only adapter for v3, citing ingestion/query bottlenecks
at scale. Minimum footprint is 5 stateful/stateless services (web, worker, postgres, redis,
clickhouse).

**Adaptation**: Scores feed dashboards and can gate prompt promotion; Datasets let you replay
production traces as eval fixtures; no fully-automatic "memory" — adaptation is human/eval-loop
driven, not automatic context injection.

**Embeddable?** No. It's a full Next.js web app + background worker + 4 datastores. You'd call it
(via its OTel or REST ingestion API / Python or JS SDK) as a sidecar service, not import it into a
FastAPI process. Running only the pieces you need (e.g. just the ingestion path) is not supported;
v3 requires the full stack.

Sources: https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse ,
https://github.com/orgs/langfuse/discussions/5785 ,
https://github.com/orgs/langfuse/discussions/1902

---

## 2. Helicone

- Repo: https://github.com/Helicone/helicone — ~5,950 stars
- License: Apache-2.0

**Architecture**: 5 services — Web (Next.js), Worker (Cloudflare Workers, edge proxy logging),
Jawn (Express+Tsoa log-collection API), Supabase/Postgres (app metadata + auth), ClickHouse
(analytics), MinIO/S3 (request/response bodies). Table of record for analytics is
`request_response_rmt` (a ClickHouse "replacing merge tree" table); Postgres holds org/user/key
metadata; bodies live in object storage, not the DB, to keep row size small.

**Interaction capture — two integration modes, both directly relevant to a proxy fork**:
1. **Proxy mode** (closest analog to LiteLLM itself): point your `base_url` at Helicone, it
   forwards to the real provider and logs the request/response pair transparently, keyed by a
   `Helicone-Auth` header. Because it *is* the proxy, it also does caching/rate-limiting/key
   management at the edge — i.e., the same position LiteLLM already occupies.
2. **Async mode**: an OpenLLMetry-based SDK wrapper logs off the critical path, so the app never
   blocks on Helicone being up.

**Adaptation**: scoring/evaluators and "properties" (arbitrary tags) exist for filtering/alerting,
but Helicone does not do memory extraction or auto-adaptation — it's an observability/gateway
product, not a memory layer.

**Embeddable?** No — meant to run as a standalone multi-container service (or use Helicone Cloud).
However, the *proxy-first capture pattern* is the most directly applicable prior art for this
project, since LiteLLM is already sitting in the request path: you don't need a second proxy hop,
just Helicone's insight that request/response bodies belong in cheap object/blob storage while
structured metadata goes in a fast analytical table.

Sources: https://docs.helicone.ai/references/proxy-vs-async ,
https://clickhouse.com/blog/helicones-migration-from-postgres-to-clickhouse-for-advanced-llm-monitoring ,
https://www.helicone.ai/blog/self-hosting-journey

---

## 3. Arize Phoenix

- Repo: https://github.com/Arize-ai/phoenix — ~10,580 stars
- License: **Elastic License 2.0 (ELv2)** — source-available, not OSI-approved. Key clause: "You
  may not provide the software to third parties as a hosted or managed service, where the service
  provides users with access to any substantial set of the features or functionality of the
  software." Self-hosting/internal embedding for your own use is fine; reselling Phoenix-as-a-service
  to others is not.
- Companion repo **Arize-ai/openinference** (semantic conventions + auto-instrumentors) is a
  separate, ~1,090-star repo under **Apache-2.0** — this part is safe to vendor/depend on without
  ELv2 concerns.

**Data model** (SQLAlchemy, `src/phoenix/db/models.py`):
- `Project` → `Trace` (`trace_id`, `start_time`, `end_time`, `project_session_rowid`) → `Span`
  (`span_id`, `parent_id`, `name`, `span_kind`, `start_time`/`end_time`, `attributes` JSON,
  `events` JSON list, `status_code`, `status_message`, `cumulative_llm_token_count_prompt`/
  `completion`, `llm_token_count_prompt`/`completion`).
- Annotations as first-class rows, decoupled from the span itself: `SpanAnnotation` /
  `TraceAnnotation` / `DocumentAnnotation`, each with `name`, `label`, `score` (float),
  `explanation`, `annotator_kind` (`LLM` | `CODE` | `HUMAN`), `source` (`API` | `APP`) — this is a
  clean "feedback/eval" shape worth copying directly: score + label + free-text explanation +
  who/what produced it.
- `Dataset` → `DatasetExample` → `DatasetExampleRevision` (versioned input/output/metadata via
  `content_hash`) → `Experiment` → `ExperimentRun` (`repetition_number`, `output`, token counts,
  `error`) — turns traces into replayable eval fixtures, same idea as Langfuse's datasets but with
  explicit example versioning.

**Span attribute vocabulary** (OpenInference semantic conventions, Apache-2.0, reusable regardless
of Phoenix itself): `openinference.span.kind` (LLM/CHAIN/RETRIEVER/TOOL/...), `input.value` /
`output.value`, `llm.input_messages.<i>.message.role|content`, `llm.output_messages.<i>.message.*`,
`llm.model_name`, `llm.token_count.prompt|completion|total`, `llm.tools.<i>.tool.json_schema`,
tool-call ids/function names, `embedding.model_name|vector|text`, `retrieval.documents`. This is
effectively a ready-made column/attribute naming convention for "one interaction."

**Storage backend**: SQLite by default (single file, zero config) or **Postgres for production** —
this is the only tool in the tracing group whose docs explicitly bless a Postgres-only deployment.
No ClickHouse/Kafka/Redis required.

**Adaptation**: built-in LLM-judge evaluators (Hallucination, QA, Relevance, Toxicity,
Summarization) write straight back onto spans as annotations; datasets/experiments close the loop
for regression testing. No conversational-memory feature — it's tracing + eval, not memory.

**Embeddable?** Yes, uniquely so among the tracing tools: `pip install arize-phoenix`, it's a
Python package (FastAPI/Starlette under the hood) that can be launched in-process
(`phoenix.launch_app()`) or as its own container, and it already speaks Postgres. Given the target
stack is Python/FastAPI/Postgres, Phoenix is the only tracing product here that could plausibly be
run *inside* the same deployment rather than bolted on as a separate multi-service stack — modulo
the ELv2 term above (fine for internal self-hosted use; would matter if this fork is ever resold
as a hosted product to third parties).

Sources: https://arize.com/docs/phoenix/self-hosting ,
https://community.arize.com/x/phoenix-support/3ykjs3i22fgv/does-phoenixsqldatabaseurl-replace-phoenixworkingd ,
https://github.com/Arize-ai/openinference

---

## 4. OpenLLMetry / Traceloop

- Repo: https://github.com/traceloop/openllmetry — ~7,300 stars
- License: Apache-2.0

**What it actually is**: not a store. It's an **OpenTelemetry instrumentation SDK** — patches
OpenAI/Anthropic/Bedrock/Ollama/LangChain/CrewAI/... clients to auto-emit spans using (an
extension of) the OTel GenAI semantic conventions: `gen_ai.request.model`,
`gen_ai.usage.input_tokens`/`output_tokens`, `gen_ai.response.finish_reasons`, plus (now
deprecated in upstream OTel v1.38 in favor of `gen_ai.output.messages`) `gen_ai.prompt` /
`gen_ai.completion` for full message capture. Traceloop (the company) leads the OTel GenAI
semantic-convention working group, so this vocabulary is trending toward becoming the vendor-neutral
standard, distinct from OpenInference's.

**Storage backend**: none — it emits to any OTel-compatible backend (their own Traceloop SaaS,
Phoenix, Langfuse, Jaeger, or a plain OTel Collector piping into your own Postgres/ClickHouse).

**Adaptation**: none, by design — it's purely the capture/instrumentation layer, adaptation is
someone else's problem downstream.

**Embeddable?** Yes, trivially — it's a pip/npm dependency, not a service. Directly relevant as
the "how do we instrument every outbound LLM call with minimal code" layer, decoupled from where
you eventually store the spans. Two competing attribute vocabularies exist right now
(OpenInference vs OTel GenAI/OpenLLMetry) and are not identical — worth picking one deliberately
rather than accreting both.

Sources: https://www.traceloop.com/docs/openllmetry/contributing/semantic-conventions ,
https://github.com/traceloop/openllmetry/issues/3515 , https://opentelemetry.io/blog/2026/genai-observability/

---

## 5. Laminar (lmnr)

- Repo: https://github.com/lmnr-ai/lmnr — ~3,090 stars
- License: Apache-2.0

**Architecture**: written in Rust; stack is **RabbitMQ (queue) + Postgres (transactional) +
ClickHouse (analytics) + Qdrant (semantic/full-text span search)**. An OTel/GenAI-convention Rust
ingestor accepts spans directly. Single-node docker-compose exists for small deployments;
Kubernetes/EKS/GKE path for scale with S3-backed ClickHouse.

**Adaptation**: traces + evals + datasets + "labels," same shape as Langfuse/Phoenix, no
memory-extraction feature.

**Embeddable?** No — 4-service Rust stack, heaviest infra footprint of the group relative to its
project size. Interesting mainly as evidence that even a from-scratch, performance-first rewrite
converges on the same Postgres+ClickHouse+queue pattern as Langfuse/Helicone/Pezzo — that
combination is the de facto standard once you need both durable storage and full-text/analytical
query over trace volume, not a Postgres-only design any of them chose voluntarily.

Sources: https://github.com/lmnr-ai/lmnr , https://laminar.sh/docs/self-hosting/overview

---

## 6. Pezzo

- Repo: https://github.com/pezzolabs/pezzo — ~3,250 stars
- License: Apache-2.0

**Architecture**: Postgres (transactional) + ClickHouse (observability data) + Redis + SuperTokens
(auth). SDK-based integration (Node.js/Python/LangChain clients call in), not a proxy.

**Focus**: prompt design/versioning/delivery is the primary product; request/response logging and
troubleshooting are secondary features riding on the same infra pattern as Langfuse/Pezzo/Laminar.

**Adaptation**: prompt iteration/versioning workflow only; no automatic feedback loop or memory.

**Embeddable?** No — same multi-service shape as the others. Doesn't add a new architectural idea
beyond "Postgres for config, ClickHouse for volume," but is useful confirmation that prompt
versioning-as-a-table (see Langfuse's `Prompt` model above) is a broadly convergent design, and a
candidate worth budgeting schema space for even in a leaner store.

Sources: https://github.com/pezzolabs/pezzo

---

## 7. LangSmith (proprietary — reference only)

- Not open source. Managed cloud, BYOC, or Enterprise-only self-host (custom pricing).
- **Data model** (documented via SDK/API, useful as prior art even though closed): every trace is
  a tree of `Run`s — one root run per top-level call, child runs per nested call/tool/retriever.
  `Feedback` is a separate scored/labeled object attached to a run (same "detach the eval from the
  interaction" pattern as Phoenix's annotations and Langfuse's scores). `Dataset` = named set of
  `Example`s, each an `input`/`(reference) output` pair, used for evaluation runs.
  Uses a LangChain-proprietary tracing format rather than OpenTelemetry.
- **Relevance here**: confirms the near-universal shape — trace/run tree + detached
  score/feedback objects + example/dataset for replay — appears independently in every tool
  surveyed (Langfuse, Phoenix, LangSmith). That convergence is itself a strong signal for what the
  interaction schema should look like. Not usable as code/infra since it's closed and
  enterprise-gated for self-hosting.

Sources: https://docs.langchain.com/langsmith/home , https://reference.langchain.com/javascript/langsmith/schemas

---

## 8. Mem0

- Repo: https://github.com/mem0ai/mem0 — ~60,900 stars (by far the most popular project in this
  survey)
- License: Apache-2.0

**What it is**: a Python/TS **library**, not a service — `pip install mem0ai`, instantiate a
`Memory` object with a config dict picking your vector store backend, call `memory.add(messages,
user_id=...)` / `memory.search(query, user_id=...)`.

**Storage backend — directly Postgres-compatible**: one of ~15 pluggable vector-store backends is
`PGVector`, whose schema (from `mem0/vector_stores/pgvector.py`) is deliberately minimal:

```sql
CREATE TABLE IF NOT EXISTS {collection_name} (
    id UUID PRIMARY KEY,
    vector vector({embedding_model_dims}),
    payload JSONB
);
```
with optional HNSW/DiskANN indexes on `vector` and a GIN index for full-text search over payload
text. Everything the memory needs (content, metadata, source ids) is folded into the `payload`
JSONB blob rather than a wide typed schema — deliberately schema-flexible, the opposite instinct
from Langfuse/Phoenix's typed-column approach. An optional graph-store add-on (was Neo4j-based;
recent versions have been trimming graph-store support) captures explicit entity relationships
("Alice — works_at — Google") alongside the vector store for relationship-aware retrieval.

**Adaptation — this is the one tool in the survey whose core loop *is* automatic adaptation**:
ingest conversation → LLM extracts candidate facts → embed + retrieve top-k similar existing
memories → a second LLM call classifies each candidate as `ADD` / `UPDATE` / `DELETE` / `NOOP`
against what's already stored → write the result. This is a genuine continuously-adapting store,
not just a log with an eval bolted on.

**Embeddable?** Yes, cleanly — it's a library call inside your existing FastAPI process, and with
the `PGVector` backend it uses the *same* Postgres instance the rest of the proxy already runs on
(needs the `pgvector` extension enabled). This is the strongest embedding fit of everything
surveyed, and the ADD/UPDATE/DELETE/NOOP fact-merge algorithm is concrete enough to port even if
you don't take the library as a dependency.

Sources: https://mem0.ai/blog/mem0-vs-building-your-own-vector-store-for-agent-memory ,
https://docs.mem0.ai/platform/features/graph-memory ,
https://github.com/mem0ai/mem0/blob/main/mem0/vector_stores/pgvector.py

---

## 9. Letta (formerly MemGPT)

- Repo: https://github.com/letta-ai/letta — ~23,800 stars
- License: Apache-2.0

**What it is**: a full **agent runtime/server**, not just a memory library — you run a Letta
server (Docker) and it owns the agent loop, not just its memory.

**Data model / memory tiers** (agent-scoped, backed by Postgres + pgvector):
- **Core memory**: small editable "blocks" (`persona`, `human`, ...) that live permanently inside
  the system prompt/context window — the agent reads/writes them directly via tool calls.
- **Recall memory**: the full conversation history, stored outside the context window, searchable.
- **Archival memory**: long-term vector-indexed storage, queried by the agent via explicit tool
  calls (`POST/GET/DELETE /v1/agents/{id}/archival-memory`) rather than automatically injected.

**Adaptation**: the agent itself decides, via tool calls, what to promote from a conversation into
core/archival memory — adaptation is agent-driven and explicit (an LLM tool-calling loop), not a
background classifier like Mem0's.

**Embeddable?** Not cleanly — it wants to be the agent orchestrator, and you'd be fighting it to
use only its memory tiers. The three-tier taxonomy (context-resident / recall / archival) is
useful as an interaction-store *design pattern* to port conceptually — e.g., "recent interactions
inline, older ones searchable, oldest ones vector-archived" — but not as a dependency to embed
given LiteLLM already owns the proxy loop this project needs.

Sources: https://www.leoniemonigatti.com/blog/memgpt.html ,
https://sureprompts.com/blog/letta-memgpt-walkthrough

---

## 10. Zep / Graphiti

- Repo (Zep client/examples): https://github.com/getzep/zep — ~4,760 stars
- Repo (Graphiti, the actual engine): https://github.com/getzep/graphiti — ~28,780 stars
- License: Apache-2.0 (Graphiti)

**Important caveat**: **Zep Community Edition (the self-hostable server) has been deprecated.**
What remains self-hostable is the underlying engine, **Graphiti**, directly — meaning you take on
running and migrating the graph database yourself.

**Data model**: Graphiti ingests "episodes" (messages/events/documents), extracts entities and
relationships via LLM, and resolves them against an existing **temporal knowledge graph**. The
standout idea: **bi-temporal facts** — every edge/fact carries both `t_valid` (when it was true in
the world) and the ingestion time (when Graphiti learned it). A contradicted fact is never deleted,
only closed out (its validity window ends) — full historical auditability of "what did we believe,
and when did that change" for free.

**Storage backend**: a graph database — Neo4j 5.26, FalkorDB 1.1.2, Amazon Neptune, or **Kuzu**
(an embedded, SQLite-like graph DB with no separate server process) — **not Postgres**. Kuzu is
the one option that avoids standing up a new stateful service, at the cost of not being the
Postgres this project already runs.

**Adaptation**: this *is* the adaptation mechanism — every new interaction updates the graph,
superseding or corroborating prior facts; retrieval is graph-traversal + semantic search combined,
not just log replay.

**Embeddable?** As a Python library, yes (pip install `graphiti-core`), but it requires a graph
backend that is not Postgres (Kuzu, being embedded/serverless, is the least-bad option if this
matters). The bi-temporal fact model is the single most novel "adaptation" idea in this whole
survey and is worth porting conceptually into a Postgres schema (e.g., `valid_from`/`valid_to`
columns on a `facts` table) even without adopting Graphiti/Kuzu itself.

Sources: https://github.com/getzep/graphiti , https://www.getzep.com/platform/graphiti/ ,
https://medium.com/@whynesspower/complete-guide-to-knowledge-context-graphs-via-zep-graphiti-c6da7ce8b13b

---

## Comparison table

| Tool | Stars | License | Storage backend | Adaptation mechanism | Embed into FastAPI+Postgres? |
|---|---|---|---|---|---|
| Langfuse | ~31.2k | MIT (+proprietary `ee/`) | Postgres + ClickHouse + Redis + S3 (v3; Postgres-only only in unsupported v2) | Scores + datasets (human/eval-loop) | No — standalone multi-service |
| Helicone | ~5.9k | Apache-2.0 | Postgres (Supabase) + ClickHouse + S3/MinIO | Scoring/properties only | No — but proxy-capture pattern is directly reusable |
| Arize Phoenix | ~10.6k | **ELv2** (source-available; OpenInference conventions repo is Apache-2.0) | **SQLite or Postgres** | LLM-judge evaluators write back as annotations; datasets/experiments | **Yes** — pip-installable Python package, Postgres-native |
| OpenLLMetry/Traceloop | ~7.3k | Apache-2.0 | none (instrumentation only) | none (capture layer only) | Yes — it's a dependency, not a service |
| Laminar | ~3.1k | Apache-2.0 | Postgres + ClickHouse + RabbitMQ + Qdrant | Evals/datasets/labels | No |
| Pezzo | ~3.3k | Apache-2.0 | Postgres + ClickHouse + Redis | Prompt versioning only | No |
| LangSmith | n/a (proprietary) | Proprietary; self-host = Enterprise only | Undisclosed managed infra | Feedback + datasets | No (closed, expensive) |
| Mem0 | ~60.9k | Apache-2.0 | **Pluggable — Postgres+pgvector supported directly** | **LLM-driven ADD/UPDATE/DELETE/NOOP fact merge (true adaptation)** | **Yes** — pip library, same Postgres instance |
| Letta/MemGPT | ~23.8k | Apache-2.0 | Postgres + pgvector | Agent-driven tool-call promotion across 3 memory tiers | No — wants to own the agent loop |
| Zep/Graphiti | ~4.8k / ~28.8k | Apache-2.0 (Graphiti); Zep CE deprecated | Neo4j/FalkorDB/Neptune/**Kuzu** (not Postgres) | **Bi-temporal fact graph** (best-in-class "adaptation" idea) | Partial — library yes, backend no (unless Kuzu) |

---

## Bottom line for scoping layer 2

No single tool is a drop-in "store + adapt" solution for a Postgres-only, embedded-in-FastAPI
constraint. The pattern that recurs everywhere (Langfuse, Phoenix, LangSmith) — trace/span tree +
detached score/feedback objects + dataset/example for replay — is the right shape for the
*logging* half. For the *adaptive* half, Mem0's fact-extraction/merge loop and Graphiti's
bi-temporal fact model are the two genuinely novel ideas worth porting (not just cloning a schema,
but the actual ADD/UPDATE/DELETE/NOOP-and-bitemporal-validity logic).
