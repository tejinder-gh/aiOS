# Lane 3: Adaptive Routing, Model Substitution & Optimization — Prior Art

Scope: what LiteLLM's own router already does vs. what would be genuinely new, for the
two vision goals "substitute one model for another when limits are exhausted" and
"refine constantly."

## 0. Headline finding

This repo (a fork of `BerriAI/litellm`, currently synced to upstream as of 2026-07-15)
already ships **five distinct routing strategies plus the full fallback/cooldown/budget
stack**, authored by the real LiteLLM core team (verified via `git log`/`git show` —
authors `Krrish Dholakia`, `Sameer Kankute`, `Mateo Wang`, `ryan-crabbe-berri`, all
LiteLLM/BerriAI maintainers, not this fork). Nothing in this lane needs to be built from
scratch; the work is wiring/config/policy on top of what's already in
`litellm/router.py`, `litellm/router_utils/`, and `litellm/router_strategy/`.

Confirmed via `git show -s --format="%h %ad %an %s"` on the introducing commits:
- `dd4a1d2be2` / `924fa6a3bc` (2026-04-18, Krrish Dholakia) — adaptive_router
- `26ab730bfa` (2026-07-11, Krrish Dholakia) — complexity router soft-floor mode
- `133da06aa3` (2026-06-26, Sameer Kankute) — LAR-1 routing strategy
- `48b5a5a0cc` (2026-06-27, Mateo Wang) — repo-wide format pass touching same dirs

## 1. What LiteLLM's Router already provides (read from source in this repo)

### 1a. Fallbacks (`litellm/router.py`, `router_utils/fallback_event_handlers.py`)

`Router.async_function_with_fallbacks` (router.py:6266) wraps every call. Three
independent fallback lists, all configurable per-router or per-request:
- `fallbacks` — general fallback, triggered on any unhandled exception after retries
  are exhausted (includes rate-limit / `RateLimitError`, `InternalServerError`, etc.)
- `context_window_fallbacks` — triggered specifically on `ContextWindowExceededError`
- `content_policy_fallbacks` — triggered specifically on `ContentPolicyViolationError`

`get_fallback_model_group()` (`router_utils/fallback_event_handlers.py`) resolves the
right fallback list entry for a model group, handling wildcard/provider-prefixed model
names (e.g. `openai/gpt-3.5-turbo` matching a `gpt-3.5-turbo` fallback key) and a
"generic" (`*`) fallback entry. Fallback attempts are capped and headers
(`x-litellm-attempted-fallbacks` etc.) are added to the response via
`add_retry_fallback_headers.py` so callers can see what happened.

Mock-testing hooks exist (`mock_testing_fallbacks`, `mock_testing_context_fallbacks`,
`mock_testing_content_policy_fallbacks`) to deterministically exercise each fallback
path without hitting real rate limits — useful for the "refine constantly" test harness
mentioned in the parent task.

### 1b. Retries (`router.py` `async_function_with_retries`)

Per-call `num_retries` (falls back to router-level `self.num_retries`, default 0), plus
a `model_group_retry_policy` that can override retry count per exception type per model
group (e.g. more retries on `RateLimitError` than on `BadRequestError`). Retry-after is
cooldown-aware — see 1c.

### 1c. Cooldowns (`router_utils/cooldown_handlers.py`, `cooldown_cache.py`,
`cooldown_callbacks.py`)

A deployment that fails (rate limit, timeout, 5xx) enough times within a rolling window
is put in a cooldown cache (`CooldownCache`, Redis-backed for multi-instance
deployments) for a configurable duration, so subsequent requests skip straight past it
to another deployment of the same `model_name` (load-balanced group) without waiting
for another failure. `async_raise_no_deployment_exception` /
`_async_get_cooldown_deployments_with_debug_info`
(`router_utils/handle_error.py`) raise `RouterRateLimitError` with the cooldown list and
minimum cooldown time when literally everything in a group is cooling down — this *is*
the "no capacity left, need to substitute" signal already surfaced to callers.

### 1d. Usage-based routing v2 / cost-based routing
(`router_strategy/lowest_tpm_rpm_v2.py`, `LowestTPMLoggingHandler_v2`)

Tracks real-time TPM/RPM per deployment in the router cache (in-memory or Redis).
`async_get_available_deployments` filters out deployments at/over their configured
`rpm`/`tpm` limit and ranks the rest by lowest current utilization, i.e. it already load
balances a request across N deployments of the same logical model, automatically
diverting traffic away from a deployment that has hit its per-minute limit. This is
registered as `routing_strategy: "usage-based-routing-v2"` (aliased to
`"cost-based-routing"` in router.py:1048) — same code path handles both names.

### 1e. Budget limiting (`router_strategy/budget_limiter.py`, `RouterBudgetLimiting`)

Tracks $ spend per provider / deployment / tag against a `GenericBudgetInfo` budget
config, synced to Redis (`periodic_sync_in_memory_spend_with_redis`) so multi-instance
deployments share one spend counter. `async_filter_deployments` /
`_filter_out_deployments_above_budget` remove any deployment whose current-window spend
exceeds its configured budget from the candidate pool before the routing strategy even
runs — i.e. **"substitute model when budget exhausted" is already implemented**, at the
provider, deployment, or tag granularity, with automatic budget-window rollover.

### 1f. Adaptive Router — the actual "refine constantly" engine
(`router_strategy/adaptive_router/`: `adaptive_router.py`, `bandit.py`, `classifier.py`,
`signals.py`, `hooks.py`, `update_queue.py`, `config.py`)

This is the one piece that most directly answers "refine constantly," and it's already
fully built (currently versioned "v0" per its own README):

- **Classification** (`classifier.py`): regex classifies each prompt into one of 7
  `RequestType` buckets (code generation, code understanding, technical design,
  analytical reasoning, writing, factual lookup, general) — zero API calls.
- **Selection** (`bandit.py`): a Thompson-sampling multi-armed bandit — one
  `Beta(alpha, beta)` posterior per `(request_type, model)` cell. Score =
  `quality_weight * thompson_sample + cost_weight * normalized_cost`. Cold-start prior
  is seeded from admin-declared `quality_tier` + `strengths` in `model_info`, with
  informative mass `COLD_START_MASS=10` so ~10 real observations move it.
- **Feedback loop** (`signals.py`, `hooks.py`): a post-call hook classifies each turn
  into signals — `satisfaction`, `misalignment`, `stagnation`, `disengagement`,
  `failure`, `loop`, `exhaustion` — using regex on user/assistant text (Jaccard
  similarity for near-duplicate/rephrase detection), tool-call signature repetition for
  loop detection, and HTTP-status/keyword detection for exhaustion (429/503/504,
  "rate limit", "context window", etc). These map to bandit deltas
  (`satisfaction → +alpha`, `failure/misalignment/stagnation/disengagement → +beta`,
  `loop → +0.5beta`) applied via `apply_delta()`.
- **Persistence** (`update_queue.py`): hot path is fully in-memory (non-blocking
  append), a background flusher batches deltas to Postgres every ~10s
  (`AdaptiveRouterStateRepository` / `AdaptiveRouterSessionRepository`).
- **Loop closure: fully closed, no human in the loop.** Every request updates the
  posterior that the very next request of the same type reads from. There is no
  approval step, no shadow-mode diffing, no human review gate in v0.

Known v0 gaps (from the module's own README, worth inheriting as a punch list rather
than rediscovering): latency isn't in the score; hard sample cap at 200 with silent
drop (no decay/rescaling); signals are regex-only (no LLM-judge, no embedding
similarity); one AdaptiveRouter per Router instance; bandit-delta constants are
acknowledged as an unvalidated v0 guess.

### 1g. Complexity Router, Quality Router, Auto Router, LAR-1 (siblings, not v0)

- **Complexity Router** (`complexity_router/complexity_router.py`): deterministic
  weighted-keyword scoring (7 dimensions: token count, code presence, reasoning
  markers, technical terms, etc.) mapping to SIMPLE/MEDIUM/COMPLEX/REASONING tiers,
  each tier bound to a model in config. Sub-millisecond, zero API calls, fully
  admin-configurable weights/thresholds/keywords.
- **Quality Router** (`quality_router/quality_router.py`): reuses the Complexity Router
  as an internal scorer, maps complexity tier → target `quality_tier`, resolves to the
  cheapest/highest-priority model at that tier (rounding up/down gracefully if the
  exact tier has no model), with a keyword override that short-circuits classification.
- **Auto Router** (`auto_router/auto_router.py`): wraps the third-party
  `semantic-router` package (`aurelio-labs/semantic-router`, MIT, ~3.1k stars) —
  embedding-based intent classification against admin-declared example utterances per
  route.
- **LAR-1 routing** (`lar1_routing.py`): confidence-threshold-based routing driven by
  caller-supplied metadata (`metadata.lar1.confidence`, `evidence`, `time`), mapping
  confidence bands to deployment "type" tags (`cloud-smart`, `cloud-fast`, `local`,
  `deep`). This looks like an internally-designed protocol (not a published external
  standard) for agent harnesses that already estimate their own confidence and want the
  router to pick capability tier accordingly.

All five strategies are pluggable via `model_list[].litellm_params.model:
"auto_router/<strategy>"` and coexist; `routing_strategy_init()` in `router.py:889`
is the single switch statement dispatching to whichever logger/strategy is configured.

## 2. External routing/substitution projects

| Project | Mechanism | Signal needed | License | Stars (approx) | Embeddability into LiteLLM |
|---|---|---|---|---|---|
| [RouteLLM](https://github.com/lm-sys/RouteLLM) (LMSYS) | Trained classifier (BERT-style or LLM-as-judge distilled into a lightweight matrix-factorization/similarity-weighted router) predicts whether a strong or weak model is "good enough" per query | Human/GPT-4-judged preference data (Chatbot Arena) to train the router offline; no online signal needed at inference | Apache 2.0 | ~5.2k | Ships an OpenAI-compatible proxy already; LiteLLM's own `auto_router`/`quality_router` cover the same "route to cheap vs. expensive tier" job natively — RouteLLM's edge is its pre-trained router *weights*, which could in principle seed the Adaptive Router's cold-start priors instead of the flat `BASE_TIER_WEIGHT` guesses currently in `config.py` |
| [NotDiamond](https://www.notdiamond.ai/) | Hosted classifier API, call-by-call recommendation (which model to call) returned to your own gateway | Proprietary training signal (their own labeled dataset); you send them the prompt, get a model recommendation back | Proprietary SaaS, $0.05/M tokens routed | N/A (closed) | External HTTP call per request — same integration point as any other `PreRoutingHookResponse`-returning strategy (mirrors what `QualityRouter.async_pre_routing_hook` already does), but adds a paid third-party dependency and latency for something the Adaptive/Complexity/Quality routers already do in-process at near-zero cost |
| [Martian](https://withmartian.com/) | Proprietary "model mapping" router, patent-pending, OpenAI-API-compatible drop-in | Proprietary; claims to work from prompt + model performance data they've collected, no customer signal required | Proprietary SaaS | N/A (closed) | Same shape as NotDiamond — drop-in OpenAI-compatible endpoint, so integration is trivial (`base_url` swap) but opaque; no visibility into why a model was picked, no on-prem option, contradicts the self-hosted control-plane goal |
| [GPTCache](https://github.com/zilliztech/GPTCache) | Semantic cache: embed the incoming prompt, similarity-search a vector store for a near-duplicate prior prompt, return the cached response if similarity exceeds threshold — skips the model call entirely | An embedding model + vector store (FAISS/Milvus/etc.); no eval/quality signal, purely similarity-based | MIT | ~7.8k | Different problem than routing (it's a cache-or-call decision upstream of routing, not model-selection). Could sit in front of any LiteLLM router as a pre-call hook (`CustomLogger.async_pre_call_hook`), returning a cached response before the router picks a deployment. Not currently present in this repo — the closest analog is LiteLLM's own `prompt_caching_cache.py`, which caches at the provider-native prompt-caching level, not semantic-similarity level, so GPTCache-style semantic caching is a genuine gap if exact-match caching isn't enough |

Note: `semantic-router` (aurelio-labs, MIT, ~3.1k stars) is already vendored as the
engine behind `auto_router` — it is the actual embeddability precedent for anything
embedding-based in this lane.

## 3. "Refine constantly" — external optimization loops

| Project | What it optimizes | Eval/outcome signal required | Loop closure | License | Stars (approx) |
|---|---|---|---|---|---|
| [DSPy](https://github.com/stanfordnlp/dspy) (Stanford NLP) | Prompts, few-shot demonstrations, and (via `BootstrapFinetune`) model weights, for a declared "program" of chained LM calls | A metric function scoring program output against labeled/held-out examples (accuracy, exact-match, an LLM-judge score, or any custom scorer) — needs a labeled or judge-scorable eval set, not implicit production feedback | **Human-in-the-loop by convention, mechanically closed-loop.** `MIPROv2`/`BootstrapFewShot`/`GEPA` optimizers run offline against your eval set and produce a new compiled program; nothing auto-applies to production without a human re-deploying the compiled artifact. Some teams wire it to run on a schedule against a growing eval set, but LiteLLM has no native DSPy integration today | MIT | ~22-34k (sources disagree; actively growing) |
| [TextGrad](https://github.com/zou-group/textgrad) (Stanford, Zou group) | Any "textual" variable — prompts, code, agent instructions — via LLM-generated natural-language "gradients" (critique text) backpropagated through a computation graph, PyTorch-style | An LLM-as-judge or loss-function textual critique per forward pass; needs at least one evaluator call per optimization step (more expensive per-step than DSPy's numeric metrics) | Same as DSPy: the optimization loop itself is automatic (`.backward()` + `.step()` runs unattended), but it's run offline/experimentally against a fixed task; nothing in the library auto-promotes an optimized prompt into a live production router | MIT | ~3.6k | Notably: TextGrad's engine layer already includes a LiteLLM-based backend (Bedrock/Together/Gemini via litellm), so it can already call through this proxy without new integration code |
| [GEPA](https://github.com/gepa-ai/gepa) (also merged into `dspy.GEPA`, ICLR 2026 Oral) | Prompts, via genetic/evolutionary search over a Pareto frontier of candidates, using LLM natural-language reflection on failures instead of numeric gradient descent | Same as DSPy: a scorable eval set (metric per candidate rollout); reflection additionally needs the raw trajectory (reasoning/tool calls/outputs), not just a score, since it diagnoses *why* a candidate failed in natural language | Same pattern: fully automated *search*, but the artifact (a new prompt) is an offline output a human/CI step deploys; not wired to auto-promote in production | MIT (both `gepa-ai/gepa` and `dspy` integration) | GEPA standalone is new/small; DSPy itself ~22-34k |
| Eval-driven route optimization (general pattern, no single canonical repo) | Which *model*, not which *prompt*, to route to — i.e. optimizing the Adaptive Router's bandit priors/weights instead of a prompt string | Exactly what LiteLLM's Adaptive Router signals already produce: per-turn satisfaction/failure/loop/exhaustion deltas, or an offline eval-set pass | This is the one place a **fully closed, auto-applying** loop already exists in this codebase (see 1f) — production traffic itself is the eval signal, no separate human deploy step | n/a (native) | n/a |

## 4. Recommendation

The Adaptive Router (1f) is the only piece in this lane that is *already* a closed,
auto-applying self-refinement loop running on live production signal, no separate
eval-set curation, no human redeploy step. DSPy/TextGrad/GEPA are the right tools if
the goal becomes optimizing a *prompt template* against a *curated eval set*
(different unit of optimization, different signal, human-gated), but they don't
compete with the Adaptive Router for the "swap models based on real usage" goal — they'd
sit downstream of it, optimizing what each model is asked to do, not which model is
asked.

Genuinely new work for this lane, given everything above already exists:
1. Fix the v0 gaps the module's own README already flags (latency in the score, sample
   decay past the 200 cap, LLM-judge signals in addition to regex).
2. Decide whether NotDiamond/Martian-style external judgment is worth paying for on top
   of the in-process Adaptive/Quality/Complexity routers already here — likely not,
   given the self-hosted/control-plane goal and that the in-repo routers are free and
   already closed-loop.
3. If prompt-level (not model-level) self-refinement is wanted later, DSPy is the
   better-supported choice (larger ecosystem, numeric-metric-first, cheaper per
   optimization step than TextGrad) and slots in as an offline job reading the same
   Postgres-logged spend/session data the Adaptive Router already writes.
