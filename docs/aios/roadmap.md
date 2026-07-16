# aiOS interaction-layer roadmap

The control-plane half of aiOS already exists in the engine. This roadmap covers the part that is genuinely new: storing every interaction, adapting from it, and turning prompts, skills, and tools into a self-sufficient corpus. Phases are ordered by dependency; each one is usable on its own.

## Decisions already locked

Local now, possibly hosted later, so avoid license traps. The interaction store uses the OpenInference span vocabulary (Apache-2.0) plus our own Postgres tables rather than an embedded Arize Phoenix (Elastic License 2.0, which forbids reselling as a hosted service). This keeps a future hosted offering clean.

Adopt the Claude Agent Skills format (a `SKILL.md` folder plus `scripts/` / `references/` / `assets/`) and MCP as the interchange for skills and tools, and build our own versioned registry on top. Neither format ships a registry or version resolution, so that layer is ours to build.

Reuse the engine's router for substitution and self-tuning. The research confirmed the LiteLLM router already implements fallbacks, cooldowns, budget-aware routing, and a Thompson-sampling adaptive strategy. We enable and tune it; we do not rebuild it.

## Phase 0: configuration, no build

Two of the vision pillars are one config change away and should ship before any new code.

Enable the adaptive router. Switch `routing_strategy` to the adaptive strategy so routing self-tunes on live traffic instead of the static `usage-based-routing-v2`.

Fill in fallbacks for every model family. Today only two fallback chains exist. Every family that a client can call needs a substitution chain so "swap the model when limits are exhausted" actually holds. Prefer same-capability targets (a cloud Opus falling back to Bedrock or Vertex Opus, not to a small local model).

## Phase 1: interaction store (the foundation)

Everything downstream reads from this, so it comes first. Capture each interaction as a trace/span tree plus a detached annotation/score table (name, label, score, explanation, annotator kind). Every tool surveyed converged on keeping evaluation separate from the span rather than folding score fields into it.

Use the OpenInference attribute names for spans so the schema is a known standard, and write to our own Postgres tables next to the existing spend logs. Feed it from a proxy success/failure callback that records the full request and response, which the current prometheus and otel callbacks do not do.

## Phase 2: prompt and skill corpus

Prompts already exist as dotprompt templates behind `POST /prompts`. Add immutable numbered versions plus mutable labels (production, staging, per-project) that point at a version, mirroring the widely-supported `GET /prompts/:name?label=` retrieval shape. Do not stand up Langfuse or Agenta; they now require ClickHouse or extra services, and the data model is small enough to own in our Postgres.

Skills are the real gap. Today the Skills page proxies Anthropic's remote Skills API, so the corpus is neither local nor self-sufficient. Move to a local `SKILL.md` store with a versioned registry, keeping the Anthropic path as one optional backend rather than the only one.

## Phase 3: adaptation and integration

Adaptation is Mem0 (Apache-2.0, Postgres plus pgvector, an LLM-driven add/update/delete fact-merge loop) reading the Phase 1 store, which is the only surveyed approach that adapts rather than just logs. Optionally add DSPy for human-gated offline prompt optimization, using the Phase 1 annotations as its eval set; that is a separate loop from the live routing bandit, not a competitor to it.

Integration is mostly polish. The base_url swap and native pass-through already make aiOS close to drop-in for existing projects. The highest-leverage remaining build is to productize the per-service key-minting and env-snippet flow that `register_service` already scaffolds, since every other onboarding path (IDE agents, secret injectors, auto-instrumentation) consumes that same artifact.

## Sequencing summary

| Phase | Deliverable | Type |
| --- | --- | --- |
| 0 | Adaptive routing on, fallbacks filled | config |
| 1 | Interaction store (OpenInference tables + content callback) | build, foundation |
| 2 | Versioned prompts, local skill corpus | build |
| 3 | Mem0 adaptation, DSPy optimization, onboarding polish | build |

Phase 1 is the first agent-routable work item once the store's table design is drafted.
