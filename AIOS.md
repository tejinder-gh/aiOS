# aiOS

One control plane for every LLM interaction. aiOS is a self-hosted gateway that every app, agent, and tool talks to instead of calling model providers directly, so routing, logging, cost, access, and the reusable building blocks of AI work (prompts, skills, tools) live in one place and are configured once and used anywhere.

## Two layers

aiOS is deliberately built as a thin layer on top of a vendored engine, not as a rewrite.

The engine is a fork of LiteLLM under `litellm/`. It provides the OpenAI-compatible gateway, provider translation for 100+ models, routing, fallbacks, budgets, spend tracking, caching, and the admin dashboard. We keep the `litellm` package name, imports, and config keys unchanged so upstream fixes keep merging cleanly. Renaming the engine would turn every future upstream merge into a conflict and buy nothing.

The aiOS layer is everything that turns that gateway into a personal operating system for AI: the services control plane (`litellm/proxy/services_management/`), the local hub config (`local_hub_config.yaml`), the prompt / MCP / skill catalogs, the external connector (`connectors/`), and, next, the interaction store and adaptive corpus described in the roadmap.

The rebrand is a project-identity layer (this file, the README hero, the dashboard title, the docs), not a source-level rename.

## Capability map

Status of each vision pillar against what is actually in the tree today.

| Pillar | Status | Where |
| --- | --- | --- |
| Single OpenAI-compatible entry point for every model | done (engine) | `http://localhost:4000/v1` |
| Native pass-through (Anthropic `/v1/messages`, Vertex, Gemini) | done (engine) | `proxy/anthropic_endpoints`, `proxy/vertex_ai_endpoints`, `proxy/google_endpoints` |
| Log and monitor every call | partial | spend logs + prometheus + otel; full request/response content is not stored |
| Substitute a model when limits or budget are exhausted | partial | router fallbacks exist but only two are configured |
| Refine routing continuously | available, not enabled | `router_strategy/adaptive_router` (bandit); config uses `usage-based-routing-v2` |
| Configure once, use anywhere | done, room to polish | virtual keys; `register_service` mints a scoped key + env snippet |
| Share tools across projects | done | MCP servers catalog (dashboard) |
| Prompt corpus | partial | dotprompt templates via `POST /prompts` |
| Skill corpus | gap | Skills page is a passthrough to Anthropic's remote API, not a local corpus |
| Services control plane (start / stop / monitor OS services) | done | dashboard Services, `services_management/` |
| Store and adapt every interaction | missing | roadmap Phase 1 and Phase 3 |

The short read: the control-plane half of the vision is largely done and just needs configuration. The differentiated half (a stored, adaptive interaction record and a self-sufficient prompt/skill corpus) is the real build, and it is scoped in the roadmap.

## Documentation

- `LOCAL_HUB.md` is the day-to-day operations guide (start, stop, endpoints, seeded catalogs, connector)
- `ARCHITECTURE.md` is the engine internals reference (request flow, translation layer, data access)
- `docs/aios/roadmap.md` is the interaction-layer plan, ordered by dependency
- `docs/aios/gap-analysis.md` lists what is currently missing, misconfigured, or overlooked
- `docs/aios/research/` holds the prior-art research the roadmap decisions are based on
