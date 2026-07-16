# Lane 2: Prompt & Skill Corpus — Prior Art Survey

Scope: reusable interactive elements (prompts, skills, tools) that a self-hosted LiteLLM proxy fork should store, version, retrieve, and share across projects ("layer 2" of a personal control plane).

---

## Part 1 — Prompt management / versioning OSS

### Comparison table

| Project | Stars | License | Prompt data model | Retrieval API | Linked to traces/evals? | Embeddable in existing FastAPI+Postgres proxy? |
|---|---|---|---|---|---|---|
| **Langfuse** ([repo](https://github.com/langfuse/langfuse)) | ~31.2k | MIT (core; `ee/` folders are commercial) | Prompt = name + (text template or chat-message array) + optional model config. Every edit creates an immutable numbered **version** (1,2,3…). **Labels** are mutable pointers to a version (`production`, `staging`, `tenant-1`, experiment names). Variables are `{{mustache}}` placeholders resolved at fetch time. | REST: `GET /api/public/v2/prompts/:name?version=N` or `?label=production`; Python/JS SDK `get_prompt(name, label=...)`, cached client-side with TTL. | Yes — first-class. SDK attaches the fetched `Prompt` object to a `generation`/`trace`, so cost, latency and eval scores roll up per prompt-version automatically in the UI. | **No, not as a library.** v3 architecture requires Postgres (OLTP) **+ ClickHouse (OLAP, mandatory)** + Redis/Valkey + S3-compatible blob store, running as its own web+worker containers. Would have to run as a sidecar service, not embed into the proxy process/schema. |
| **PromptLayer** ([site](https://www.promptlayer.com/), [thin client lib](https://github.com/MagnivOrg/prompt-layer-library)) | n/a (SaaS; client lib only, low stars) | **Proprietary** — not open source. Self-hosting exists but is Enterprise-only/paid. | "Prompt Registry": named prompt with versions + labels (similar shape to Langfuse), plus release labels and A/B tags. | REST API + Python/JS client; publish and fetch by name/label at runtime. | Yes, tracing/evals product is core to the offering. | **No** — closed source, cannot be embedded or forked; only usable as an external SaaS/enterprise-licensed dependency. Disqualifies it for a self-hosted control plane unless paying for enterprise self-host. |
| **Agenta** ([repo](https://github.com/agenta-ai/agenta)) | ~4.3k | MIT (all functional features now fully OSS; enterprise add-ons are the paid tier) | Git-like model: an **app** has **variants** (branches); each edit to a variant creates an immutable **version** with a commit id; **environments** (`development`/`staging`/`production`) are deployable pointers to a specific variant+version, versioned independently so environment deploys can themselves be rolled back. Prompt payload = messages array + `llm_config` (model, temperature, max_tokens, etc). | SDK: `ConfigManager.get_from_registry()` by variant ref (`app_slug`, `variant_slug`, `variant_version`) or by environment ref (`app_slug`, `environment_slug`); REST equivalents. | Yes — playground, evaluations and observability share the same project; evals can be tied to a variant/version. | Self-host via `docker-compose` (Postgres + Redis + own API/UI containers) — a full platform, not a library. Same "sidecar service" story as Langfuse, but a lighter stack (no ClickHouse requirement). Most realistic of the full platforms to run alongside the proxy if a second service is acceptable. |
| **Promptfoo** ([repo](https://github.com/promptfoo/promptfoo)) | ~23.3k | MIT | **Not a hosted prompt store.** A prompt is just a value inside `promptfooconfig.yaml`, version-controlled in git alongside app code — no server-side version/label/deployment concept at all. Its real strength is the declarative eval/red-team config format (prompts × providers × test cases × asserts) consumed by a CLI. | None (file-based; CLI reads local YAML). Has a hosted "Promptfoo Cloud" for teams, out of scope for self-host. | Yes, but the opposite direction from Langfuse: evals are the product, and prompts are eval inputs, not observability outputs. No trace linkage. | Not applicable as a prompt store; it *is* embeddable as a **CI/eval tool** (`npm i -g promptfoo`, run against the proxy's OpenAI-compatible endpoint) rather than as infra to run. Worth adopting only for regression-testing prompts, not for storing/versioning them. |
| **BAML (BoundaryML)** ([repo](https://github.com/BoundaryML/baml)) | ~8.6k | Apache-2.0 | Radically different: prompts are **not data**, they're **code**. A `.baml` file declares a typed `function` (params in, typed struct out) with one or more prompt `impl`s; the BAML compiler generates typed client code (Python/TS/Ruby/Java/Go/Rust) plus a VSCode "prompt playground." Versioning is whatever git does to the `.baml` files; there's no runtime version/label registry. | No network retrieval API by design — prompts compile into your codebase as typed functions you call directly; nothing to "fetch" at runtime. | No trace/eval product; tracing is a bolt-on via OTel-style hooks, not the point of the project. | **Embeds well as a build-time toolchain**, not a runtime service — could be used to type-check/generate the tool-call and prompt-template code the proxy ships with, but doesn't give you a runtime, database-backed, cross-project prompt registry, which is what this lane is scoping. |
| **Latitude** ([repo](https://github.com/latitude-dev/latitude-llm)) | ~4.4k | MIT (core) — note some secondary sources list LGPL-3.0, GitHub's own license badge on the repo currently reads MIT | Prompts are called **"documents"**, written in `PromptL` (a superset of Jinja-like templating with variables/conditionals/loops). Each save is a **commit**, forming a linear version history per document/project; a **live/draft** distinction gates what's deployed. Deployed prompts are exposed as API endpoints via an "AI Gateway" that always serves the latest published commit for its route. | REST/SDK: run a document by path, get results; Gateway auto-updates on publish so callers don't need to know the version id. | Yes — evaluations, datasets (batch eval inputs) and logs are first-class and tied to documents/commits. | Self-host via Docker Compose or a Helm chart (k8s); needs Postgres + Redis + its own web/worker services — same "separate platform" shape as Langfuse/Agenta, but explicitly designed for single-host Docker Compose so it's the lightest of the three full platforms to stand up next to the proxy. |
| **Pezzo** ([repo](https://github.com/pezzolabs/pezzo)) | ~3.3k | Apache-2.0 | Prompt = name + versions + **environment labels** (dev/staging/prod), instant "publish" pushes a version live without redeploying the calling app — conceptually the earliest OSS project to popularize this label-pointer model (predates Langfuse's current design). | REST + SDKs; fetch by name+environment. | Yes, observability + prompt management were bundled together from the start. | **Caution: appears largely unmaintained** — latest tagged release is v0.9.2 (May 2024), no material sign of newer activity found. Given a healthier/actively-maintained alternative (Agenta, Latitude, Langfuse) implements the same label-pointer model, don't build on Pezzo. |

### Cross-cutting takeaways for prompt management

1. **The dominant data model is the same across every serious OSS project** (Langfuse, Agenta, Latitude, Pezzo): `prompt name → immutable numbered versions → mutable named labels/environments that point at a version`. Variables are simple `{{mustache}}`/Jinja-style placeholders resolved at fetch time. This is a converged, de-facto standard shape worth copying directly into the proxy's own Postgres schema rather than inventing new terms.
2. **None of the full-featured OSS options embed as a library into an existing FastAPI+Postgres process.** They are all separate deployable platforms (own web/worker containers, and in Langfuse's case a hard ClickHouse dependency). Given the proxy already owns Postgres and is meant to be *the* control plane, the highest-leverage move is to **port the data model and REST shape (versions + labels + variables), not the software** — implement prompt CRUD/versioning as new tables + endpoints in the existing proxy, mirroring Langfuse's `GET /api/public/v2/prompts/:name?label=` contract for compatibility with existing SDKs/tooling that already speak that shape.
3. **Promptfoo** is worth adopting as-is for CI/regression testing of prompts (it's a CLI, MIT-licensed, and can point straight at the proxy's OpenAI-compatible endpoint) — not as a system to run permanently.
4. **BAML** is worth a look later if/when the fork wants typed, compiled prompt-functions rather than string templates, but it solves a different problem (compile-time typed prompt code) than "store/version/retrieve prompts across projects at runtime," so it's out of scope for the retrieval-API part of this lane.
5. **PromptLayer is disqualified** outright: not open source, self-host is enterprise-paid-only, cannot be embedded or forked.

---

## Part 2 — Skill / tool packaging standards

### Claude Agent Skills (SKILL.md)

- Origin: Anthropic, open-sourced at [anthropics/skills](https://github.com/anthropics/skills); formal spec now maintained as an independent open standard at **[agentskills.io/specification](https://agentskills.io/specification)** (repo: [agentskills/agentskills](https://github.com/agentskills/agentskills)), explicitly designed to be portable beyond Claude products.
- **On-disk format**: a skill is a directory whose name matches the skill's `name`:
  ```
  skill-name/
  ├── SKILL.md          # required: YAML frontmatter + Markdown instructions
  ├── scripts/          # optional: executable code (py/bash/js), agent may run these
  ├── references/       # optional: docs loaded on demand (REFERENCE.md, domain files)
  └── assets/           # optional: templates, images, data/lookup files
  ```
- **Frontmatter fields** (all in `SKILL.md`'s YAML header):
  | Field | Required | Notes |
  |---|---|---|
  | `name` | yes | ≤64 chars, lowercase/digits/hyphens, must match directory name |
  | `description` | yes | ≤1024 chars; must state what it does *and when to use it* — this is the only thing preloaded into the agent's system prompt (~100 tokens/skill) before activation |
  | `license` | no | license name or pointer to bundled LICENSE file |
  | `compatibility` | no | ≤500 chars; free text on env requirements (e.g. "Requires git, docker, jq") |
  | `metadata` | no | arbitrary string→string map; **this is where `version`, `author`, etc. live** — there is no first-class top-level `version` field, by convention it's `metadata.version` |
  | `allowed-tools` | no | space-separated pre-approved tool list, e.g. `Bash(git:*) Bash(jq:*) Read`; marked experimental, support varies by host |
- **Versioning/distribution**: the spec itself defines **no registry, no version-resolution algorithm, and no package manifest beyond the free-text `metadata.version` string** — it only standardizes the folder shape and progressive-disclosure loading contract (name+description always loaded → full SKILL.md body loaded on activation → scripts/references/assets loaded on demand, capped at 500 lines/~5000 tokens recommended for the body). A reference validator (`skills-ref validate ./my-skill`) checks structural conformance only.
- **License**: the spec/reference implementation is openly licensed (Anthropic's `anthropics/skills` repo and `agentskills/agentskills` are both open source, MIT-style); individual skills carry their own `license` field.

### Model Context Protocol (MCP)

- Spec home: [modelcontextprotocol.io](https://modelcontextprotocol.io), reference repo [modelcontextprotocol/modelcontextprotocol](https://github.com/modelcontextprotocol/modelcontextprotocol) (Anthropic + community, MIT). Actively evolving — a 2026-07-28 release candidate is in flight (stateless core, Extensions framework, Tasks, MCP Apps, tightened auth).
- Three server-exposed **primitives**, all independently listable: **tools** (model-invoked functions), **resources** (data the client can attach to context), and **prompts** (user-invoked reusable templates — directly relevant here). Wire format is JSON-RPC 2.0.
  - `prompts/list` → array of `{ name, description?, arguments?: [{name, description?, required?}] }`.
  - `prompts/get` → typed args injected into a message-array template; **the protocol itself has no version/label/environment concept for a prompt** — a given server exposes exactly one current definition per name, so MCP's "prompts" primitive is a *transport/discovery* mechanism, not a prompt-management system. It does not replace what Langfuse/Agenta do; it's the wire protocol you'd put in front of whichever store you build.
  - `tools/list` / `tools/call`: tool `inputSchema`/`outputSchema` now full JSON Schema 2020-12 (composition, `$ref`/`$defs` allowed) as of the pending SEP-2106 change.
- **Versioning**: the protocol version itself is a date string (e.g. `2025-06-18`) negotiated during `initialize` — coarse, protocol-level versioning, not per-tool/per-prompt semantic versioning. Individual server/tool versioning is left to the server implementer.
- **Registry / discovery**: the **official MCP Registry** ([registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io), repo [modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry), currently in preview) is a *metadata* index, not a code host — actual packages still live on npm/PyPI/Docker Hub/etc. Each server publishes a **`server.json`** conforming to a published [JSON Schema](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/draft/server.schema.json) with: a reverse-DNS unique name (`io.github.user/server-name`), package/location info (npm name, remote URL), execution instructions (args/env), and capability/description metadata. Namespace ownership is verified via GitHub/DNS/HTTP challenge.
  - Important for this use case: **the official registry explicitly documents that it is not designed for self-hosting** — but it does publish an OpenAPI spec that other registries (including private/internal ones) are encouraged to implement, so a proxy-owned "internal MCP registry" is an explicitly sanctioned pattern, just not a fork of the official codebase.

### OSS skill registries / marketplaces (community layer on top of the spec)

No single dominant registry exists yet (comparable to npm circa 2011) — instead a crop of community catalogs has appeared on top of the open `SKILL.md` spec:
- [dukelyuu/skills-marketplace](https://github.com/dukelyuu/skills-marketplace) — cross-tool (Claude Code, Cursor, Windsurf, Copilot, Cline) skill catalog.
- [agent-skills-hub/agent-skills-hub](https://github.com/agent-skills-hub/agent-skills-hub) — ~790+ skills, cross-agent.
- [aiskillstore/marketplace](https://github.com/aiskillstore/marketplace) — security-audited skills, one-click install.
- [netresearch/claude-code-marketplace](https://github.com/netresearch/claude-code-marketplace) — explicitly built on the agentskills.io open standard, portable across 30+ agent products.
- [claude-market/marketplace](https://github.com/claude-market/marketplace) — hand-curated.

None of these are large/canonical enough (low hundreds–low thousands of stars each, fragmented) to adopt as *the* registry; they confirm the **format** (`SKILL.md` + folder) is the interchange standard, while the **registry/distribution layer is still greenfield** — exactly the gap a self-hosted proxy-as-control-plane could fill for one person/team without waiting on ecosystem consolidation.

### Is there a de-facto interchange format worth adopting?

Yes, two complementary ones, not competing:
- **For skills** (multi-step instructions + bundled scripts/assets, loaded progressively into an agent's context): the **`SKILL.md` folder format** is already a genuine open standard (Anthropic-originated, formalized at agentskills.io, adopted by Cursor/Cline/Copilot/others per the marketplaces above). Adopt it verbatim — folder-per-skill, YAML frontmatter, `scripts/`/`references/`/`assets/` subfolders — and the proxy just needs storage (blob or Postgres `bytea`/object store) + a version field convention (`metadata.version`) + Git-style commit history, since the spec itself is silent on versioning/registry.
- **For tools** (single callable functions with typed schemas, servers that expose them): **MCP** is the de-facto wire protocol (JSON-RPC 2.0, `tools/list`+`tools/call`, JSON Schema 2020-12 typed I/O) and its `server.json` shape is the emerging de-facto **manifest** format for describing/discovering a tool server. Adopt both: expose the proxy's own tools as an MCP server, and consume/aggregate third-party MCP servers by indexing their `server.json` in the proxy's own Postgres-backed internal registry (implementing the Registry's public OpenAPI spec, which is the sanctioned way to run a private registry).

---

## Sources (representative, not exhaustive — see inline links above for all)

- Langfuse: https://langfuse.com/docs/prompt-management/data-model , https://langfuse.com/self-hosting , https://github.com/langfuse/langfuse
- PromptLayer: https://docs.promptlayer.com/features/prompt-registry/overview , https://github.com/MagnivOrg/prompt-layer-library
- Agenta: https://github.com/agenta-ai/agenta , https://agenta.ai/docs/concepts/concepts , https://agenta.ai/docs/misc/opensource
- Promptfoo: https://github.com/promptfoo/promptfoo , https://www.promptfoo.dev/docs/getting-started/
- BAML: https://github.com/BoundaryML/baml , https://docs.boundaryml.com/home
- Latitude: https://github.com/latitude-dev/latitude-llm , https://latitude.so/blog/how-to-integrate-prompt-versioning-with-llm-workflows
- Pezzo: https://github.com/pezzolabs/pezzo
- Claude Agent Skills: https://github.com/anthropics/skills , https://agentskills.io/specification , https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- MCP spec: https://modelcontextprotocol.io/specification/2025-06-18/server/prompts , https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/
- MCP Registry: https://modelcontextprotocol.io/registry/about , https://github.com/modelcontextprotocol/registry
- Skill marketplaces: https://github.com/dukelyuu/skills-marketplace , https://github.com/agent-skills-hub/agent-skills-hub , https://github.com/netresearch/claude-code-marketplace
