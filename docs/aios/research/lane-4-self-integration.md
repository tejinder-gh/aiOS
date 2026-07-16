# Lane 4: Self-Integration Mechanisms — Prior Art Catalog

Ranked zero-touch → code-change, for a self-hosted LiteLLM-fork control plane that wants to be
drop-in for arbitrary existing/new projects ("configure once, use anywhere").

---

## Tier 0 — Zero code touch (env var / config only, no import changes)

### 0.1 OpenAI-compatible `base_url` swap
The dominant pattern in the ecosystem. Any project already using the `openai` SDK (or a
framework built on it) can be repointed at any OpenAI-shaped backend by changing exactly two
values: `base_url` and `api_key`. No new import, no wrapper class.

- **LiteLLM itself** — github.com/BerriAI/litellm, ~53.7k stars, MIT (enterprise/ dir separately
  licensed). Proxy translates `/chat/completions`-shaped calls to 100+ backends. This repo *is*
  the reference implementation of this pattern — worth noting since the fork already inherits it.
- **vLLM** — serves an OpenAI-compatible `/v1` server out of the box; same swap.
- **Ollama** — OpenAI-compatible endpoint at `/v1`; same swap for local models.
- **OpenRouter** — hosted version of the same idea, `base_url=https://openrouter.ai/api/v1`.
- Docs: docs.litellm.ai/docs/providers/openai_compatible — "put `openai/` in front of your
  model name" is the entire integration step for many callers.

**Exact developer action:** set two config values (often via env vars `OPENAI_API_BASE` /
`OPENAI_BASE_URL` and `OPENAI_API_KEY`). Zero code diff if the project already reads those env
vars, which most OpenAI-SDK-based code does by default.

**Limitation:** only works for code written against the OpenAI wire format. Anthropic SDK,
Google GenAI SDK, boto3/Bedrock, Vertex AI SDK calls do not speak this format and need Tier 0.2.

### 0.2 Native-SDK pass-through endpoints (same tier, wire-format-preserving)
LiteLLM proxy also exposes **pass-through endpoints** that accept a provider's *native* wire
format unmodified, so a project using the Anthropic SDK, Google GenAI SDK, or Vertex AI SDK
directly (not the OpenAI SDK) still only changes `base_url`, no shim/wrapper needed:

- Anthropic SDK → `base_url=http://proxy:4000/anthropic`, keep `anthropic.Anthropic(...)` calls
  unchanged. docs.litellm.ai/docs/pass_through/anthropic_completion
- Google GenAI SDK → point `baseUrl` at the proxy root (routes through native Gemini endpoint
  handling, still gets model aliasing / routing). docs.litellm.ai/docs/tutorials/google_genai_sdk
- Vertex AI SDK → `apiEndpoint` set to `proxy:4000/vertex_ai`. docs.litellm.ai/docs/pass_through/vertex_ai
- Rationale doc: docs.litellm.ai/docs/pass_through/intro ("why pass-through endpoints")

**Why this matters for the fork:** this is the mechanism that turns "OpenAI-compatible" into
"any-SDK-compatible" — it's what lets the proxy claim true drop-in status for teams standardized
on non-OpenAI vendor SDKs, without asking them to rewrite call sites.

### 0.3 Environment-variable injection at process launch (secrets/config layer)
A complementary zero-touch mechanism: inject `OPENAI_API_KEY` / `OPENAI_BASE_URL` (or per-service
equivalents) into a process's environment at launch time, with no `.env` file committed and no
code change, via a wrapper CLI:

- **Doppler** — `doppler run -- python app.py` / `doppler run -- node server.js`. Drop-in
  replacement for `dotenv -e .env <cmd>`. github.com/DopplerHQ (CLI + `doppler-env` PyPI package
  for pure-Python auto-inject via `sitecustomize`-style hook). docs.doppler.com/docs/cli
- **Infisical** — same shape, `infisical run -- <cmd>`, OSS (MIT), self-hostable — closer fit for
  a self-hosted control plane than Doppler (which is SaaS-first).
- **HashiCorp Vault Agent** — template-renders secrets to a file or env, sidecar pattern, heavier
  weight, Enterprise-grade.

**Exact developer action:** prefix the existing start command with the injector CLI. Zero lines
of application code change; the app still just reads `os.environ["OPENAI_API_KEY"]`.

**Relevance to this proxy:** this is exactly the shape of "mint a virtual key, hand back an env
snippet" that a services-management/API-key-minting feature already gives for free (see Tier 0.4
below) — the proxy doesn't need to reimplement a secrets manager, it needs to be a good citizen
of the `.env` / `doppler run` / `infisical run` convention (i.e., emit `KEY=VALUE` lines its own
users can paste into whichever injector they already run).

### 0.4 What "mint a per-service OpenAI-compatible key + env snippet" gives you for free
This is the composition point across 0.1–0.3. A proxy that can generate, per calling service:
- a `base_url` (e.g. `http://localhost:4000` or a per-service path),
- a scoped virtual API key,
- a ready-to-paste env snippet (`OPENAI_API_KEY=sk-...` / `OPENAI_BASE_URL=...`),

...gets the *entire* Tier 0 integration surface for zero additional engineering: every OpenAI-SDK
project (0.1), every native-SDK project via pass-through (0.2), and every secrets-injector
workflow (0.3) all consume the exact same three artifacts. The developer-facing integration step
in all three cases collapses to "paste this snippet into your `.env` / secrets manager." This is
the single highest-leverage capability to have polished, because it's the shared foundation under
every other tier — nothing downstream (SDK shims, auto-instrumentation, MCP, IDE agents) reduces
the need for it; they all still need a base_url+key to point at.

---

## Tier 1 — Config-file touch, no source-code change

### 1.1 IDE / coding-agent tool configs (Continue, Cline, aider)
These tools are themselves OpenAI-compatible clients, so integrating *them* with the proxy is a
config-file edit, not a source change to the target project — but it's a distinct integration
surface from Tier 0 because the "project" being integrated is the developer's tool, not the
app's runtime.

- **Continue** — github.com/continuedev/continue, ~34.9k stars, Apache-2.0 (repo now archived/
  read-only per recent search, community forks active). Config: `config.yaml`, set
  `provider: openai`, `apiBase: http://localhost:4000/v1`, custom `apiKey`. One YAML block.
  docs.continue.dev/reference
- **Cline** — github.com/cline/cline, ~58.1k stars, Apache-2.0. Settings UI: "OpenAI Compatible"
  provider, paste Base URL + API key + model ID. No file edit needed at all if done via the
  extension UI. docs.cline.bot/provider-config/openai-compatible
- **aider** — github.com/Aider-AI/aider, ~45.9k stars, Apache-2.0. Three equivalent integration
  points, in order of persistence: env vars (`OPENAI_API_BASE`, `OPENAI_API_KEY`), CLI flags
  (`aider --openai-api-base http://0.0.0.0:4000 --openai-api-key fake-key`), or
  `.aider.conf.yml` (`openai-api-base: http://...`). aider internally uses litellm as its model
  routing library already, so pointing it at this fork's proxy is a first-class supported path,
  not a workaround. aider.chat/docs/llms/openai-compat.html

**Exact developer action:** paste base_url + key into one settings panel or one YAML key. Under
five minutes, no restart of the target project needed (only the IDE tool).

**Leverage note:** all three tools are themselves consumers of Tier 0.1/0.2 — they add zero new
integration code to build, only documentation ("here's the base_url/key for your `.continue`,
Cline settings, or `.aider.conf.yml`").

### 1.2 Scaffolding / codegen starters
Lower priority for a control-plane pivot, but worth cataloging as "how new projects get wired
in from day one" rather than retrofitted:

- **create-llama** — github.com/run-llama/create-llama, LlamaIndex's `npx`-style generator;
  interactive CLI asks for backend (FastAPI/Next.js) and use case, emits a project pre-wired to
  read `OPENAI_BASE_URL`/`OPENAI_API_KEY` from env — i.e., it's a Tier-0-consumer scaffold, not
  a new integration mechanism.
- **cookiecutter** — github.com/cookiecutter/cookiecutter, generic template engine; several
  community LLM-app cookiecutters exist (e.g. `simonw/llm-plugin` for the `llm` CLI's own plugin
  system) but nothing LiteLLM-specific and mature.
- Verdict: scaffolding is a good place to *bake in* the proxy's env-var convention for new
  projects, but building a bespoke `create-<this-proxy>-app` generator is low leverage compared
  to Tier 0 — most target codebases already exist and won't be re-scaffolded.

---

## Tier 2 — Dependency added, but existing call sites untouched (auto-instrumentation)

This tier is about **observability/telemetry self-integration**, not routing — it answers "how
do we see what a project is already doing with LLMs" without editing its call sites. Relevant to
the control-plane vision because the same runtime-patch technique could in principle be reused to
auto-*route* calls too, not just observe them (see note at end of tier).

### 2.1 OpenTelemetry zero-code auto-instrumentation (the general mechanism)
- opentelemetry.io/docs/zero-code/python/ — install `opentelemetry-distro` +
  `opentelemetry-instrumentation`, run `opentelemetry-bootstrap -a install` (introspects
  installed packages, installs matching instrumentors), then launch the app via
  `opentelemetry-instrument python app.py` instead of `python app.py`.
- **Mechanism**: `opentelemetry-instrument` prepends its own `sitecustomize` module to
  `PYTHONPATH` so it loads before the target app; at import time it monkey-patches the target
  libraries' client classes (e.g. wraps `openai.OpenAI.chat.completions.create`) to emit spans.
  Config entirely via env vars (`OTEL_PYTHON_DISTRO`, `OTEL_EXPORTER_OTLP_ENDPOINT`, etc.).
- **Exact developer action:** change the process launch command (`python` → `opentelemetry-
  instrument python`) or set `PYTHONSTARTUP`/`PYTHONPATH`. Zero source edits. Closest thing to
  Tier 0 that still requires a new dependency + launch-command change.

### 2.2 OpenLLMetry / Traceloop
- github.com/traceloop/openllmetry, ~7k stars, Apache-2.0. Purpose-built OTel instrumentation
  for LLM-specific spans (prompts, completions, token counts, model/version, temperature).
  Covers OpenAI, Anthropic, Cohere, LangChain, Haystack, plus vector DBs (Pinecone).
  traceloop.com/docs/openllmetry/introduction
- **Integration step:** `pip install traceloop-sdk` + one line, `Traceloop.init()`, at process
  start — this is the one place in this tier that isn't fully zero-code (one init call), but it
  auto-patches every subsequent SDK call in the process, so existing call sites need no changes.
  Sister projects: openllmetry-js, openllmetry-ruby, go-openllmetry.

### 2.3 OpenInference (Arize)
- github.com/Arize-ai/openinference, ~900+ stars, spec repo Arize-ai/open-inference-spec.
  Same category as OpenLLMetry: OTel-based instrumentation packages per SDK/framework (OpenAI,
  Anthropic, Claude Agent SDK, LangChain, LlamaIndex, CrewAI, Vercel AI SDK, Mastra, DSPy,
  Bedrock, Vertex, OpenRouter, LiteLLM). Feeds Arize Phoenix (github.com/Arize-ai/phoenix) or any
  OTel collector. Same integration shape as 2.2: import + init, then all calls auto-traced.

**Relevance to the control plane:** the monkey-patch-at-import technique these projects use is
the technical proof that a lightweight shim library *can* rewrite outbound LLM calls in-process
without touching call sites. If this fork ever wants a true "zero base_url edit" story (e.g. for
projects that hardcode `https://api.openai.com`), an OpenLLMetry-style patch package that
rewrites the target host at the HTTP client layer is the precedent to copy — today's tools do
this for tracing only, not for rerouting, but nothing in the mechanism prevents reuse for routing.

---

## Tier 3 — SDK-level shim/wrapper (import swapped, call sites mostly unchanged)

### 3.1 Portkey
- github.com/Portkey-AI/gateway, ~12.4k stars, MIT. github.com/Portkey-AI/portkey-python-sdk.
  SDK is "built on top of the OpenAI SDK" — you `pip install portkey-ai` and swap the client
  constructor (`OpenAI(...)` → `Portkey(...)`) while keeping every `.chat.completions.create(...)`
  call-site line identical. Positions itself as "under 2 minutes to integrate any model."

### 3.2 Helicone
- github.com/Helicone/ai-gateway, ~480 stars, Apache-2.0 (newer, narrower gateway); older/larger
  github.com/Helicone/helicone (full observability platform, YC W23). "One line of code to
  monitor" — typically a `base_url` change plus a header, so in practice it straddles Tier 0/3
  depending on whether you use the proxy mode or the SDK-wrapper mode.

**Why this tier ranks below Tier 0/1/2 for this proxy specifically:** a bespoke shim package is
only needed when the target SDK *doesn't* support a configurable base_url at all (rare — most
modern LLM SDKs do). Since this proxy already gets OpenAI-SDK and native-SDK coverage for free
via Tier 0, building/maintaining a Portkey-style wrapper package would be duplicate effort unless
a specific popular SDK is found that hard-codes its endpoint.

---

## Tier 4 — Standing service / protocol surface (MCP)

### 4.1 Model Context Protocol (MCP)
- Spec + org: github.com/modelcontextprotocol, spec repo modelcontextprotocol.io/specification.
  Reference servers repo github.com/modelcontextprotocol/servers, ~88.5k stars, Apache-2.0 (MIT
  for legacy code). Official Python SDK github.com/modelcontextprotocol/python-sdk, ~23.6k stars,
  MIT.
- **Architecture**: Host (Claude Desktop, Cursor, VS Code+Copilot, ChatGPT, this proxy's own
  agent surface) instantiates one Client per Server; Server exposes tools/prompts/resources over
  JSON-RPC 2.0 (stdio or HTTP transport).
- **This proxy's own repo already implements the relevant half of this**: docs.litellm.ai/docs/
  mcp describes LiteLLM Proxy as a dual-role MCP Gateway — MCP *client* to upstream tool servers,
  MCP *server* to downstream LLMs/IDEs, aggregating tools/prompts/resources from many registered
  servers behind one authenticated endpoint with key/team/org-scoped access
  (docs.litellm.ai/docs/mcp_usage, docs.litellm.ai/docs/mcp_deployment,
  docs.litellm.ai/docs/mcp_public_internet).

**Exact developer action (as an integration surface, not a routing surface):** point an MCP-aware
host (Cursor, Claude Desktop, this proxy's own future agent UI) at the proxy's MCP endpoint URL +
key. This is a different axis from Tiers 0-3 — it's not "how does a project call an LLM through
us," it's "how does an agentic client discover *tools* through us." For the "integrate with any
new/existing project" vision, MCP matters less for backend services (they don't speak MCP) and
more for exposing the control plane's own capabilities (spend data, service registry, logs) *to*
coding agents and chat hosts as callable tools — i.e., MCP server is the mechanism by which this
proxy becomes something Claude/Cursor/etc. can introspect and drive, complementary to, not a
replacement for, the base_url swap.

---

## Tier 5 — Actual source-code change (last resort, not recommended as a first build target)

Framework-level integrations (LangChain `ChatOpenAI(base_url=...)`, LlamaIndex `OpenAILike`,
Vercel AI SDK `createOpenAI({baseURL})`) still fall back to Tier 0 config once the framework
object is constructed — true Tier 5 (hand-editing call sites) is essentially never required for
OpenAI-shaped frameworks today. This tier is effectively empty in 2026 for mainstream stacks;
noting it mainly to confirm there's no gap the proxy needs to solve here.

---

## Summary table

| Tier | Mechanism | Developer touches | Example projects (stars, license) |
|---|---|---|---|
| 0.1 | base_url + key swap | env vars only | vLLM, Ollama, OpenRouter, LiteLLM itself (53.7k, MIT) |
| 0.2 | native-SDK pass-through | base_url only | LiteLLM `/anthropic`, `/vertex_ai`, `/gemini` passthrough |
| 0.3 | env injector CLI | launch command prefix | Doppler (SaaS), Infisical (OSS/MIT, self-hostable) |
| 0.4 | minted key + snippet | paste into .env | — (this proxy's own services-management feature) |
| 1.1 | IDE agent config | one settings panel / YAML block | Continue (34.9k, Apache-2.0), Cline (58.1k, Apache-2.0), aider (45.9k, Apache-2.0) |
| 1.2 | scaffolding/codegen | pick a template | create-llama, cookiecutter |
| 2.1 | OTel zero-code auto-instrument | launch command wrapper | opentelemetry-instrument (CNCF) |
| 2.2 | OpenLLMetry | one init() call | traceloop/openllmetry (~7k, Apache-2.0) |
| 2.3 | OpenInference | one init() call | Arize-ai/openinference (~900+, spec + Apache) |
| 3.1 | SDK wrapper/shim | swap client constructor | Portkey-AI/gateway (12.4k, MIT) |
| 3.2 | SDK wrapper/shim | swap client or base_url | Helicone/ai-gateway (480, Apache-2.0) |
| 4.1 | MCP server/client | point host at MCP endpoint | modelcontextprotocol/servers (88.5k), python-sdk (23.6k, MIT) — already partially built in this repo |
| 5 | hand-edit call sites | — | effectively obsolete for OpenAI-shaped frameworks |
