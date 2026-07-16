<h1 align="center">aiOS</h1>
<p align="center">One control plane for every LLM interaction</p>

A self-hosted operating system for AI. Every app, agent, and tool talks to aiOS instead of calling model providers directly, so routing, logging, cost, access, and the reusable building blocks of AI work (prompts, skills, tools) live in one place, configured once and used anywhere.

## Start here

- [AIOS.md](./AIOS.md) is what aiOS is, with a capability map of what exists today
- [LOCAL_HUB.md](./LOCAL_HUB.md) is how to run it (endpoints, keys, seeded catalogs, the connector)
- [docs/aios/roadmap.md](./docs/aios/roadmap.md) is the interaction-layer plan
- [docs/aios/gap-analysis.md](./docs/aios/gap-analysis.md) is what is missing, misconfigured, or overlooked
- [ARCHITECTURE.md](./ARCHITECTURE.md) is the engine internals reference

## What you get today

One OpenAI-compatible endpoint for 100+ models, plus native Anthropic, Vertex, and Gemini pass-through. Routing, fallbacks, budgets, spend tracking, response caching, and an admin dashboard. A services control plane that starts, stops, and monitors the local OS services aiOS depends on. Catalogs for prompts and MCP tool servers, a skills surface, and an MCP connector so Claude Desktop and ChatGPT can read from and drive the hub.

## Quick start

```bash
set -a; . ./.env; set +a
export LITELLM_ENABLE_SERVICE_CONTROL=true
uv run python litellm/proxy/proxy_cli.py --config local_hub_config.yaml --use_v2_migration_resolver
```

Point any OpenAI-compatible client at `http://localhost:4000/v1`. The admin dashboard is at `http://localhost:4000/ui/`. See [LOCAL_HUB.md](./LOCAL_HUB.md) for keys, model names, the dashboard dev server, and the connector.

## Engine

aiOS runs on a vendored fork of the LiteLLM AI Gateway under `litellm/`, kept unmodified so upstream fixes keep merging cleanly. The `litellm` package name, its imports, the `LITELLM_*` config keys, and the `x-litellm-*` response headers are engine identifiers, not branding, and stay as they are. Everything aiOS adds lives alongside the engine (`litellm/proxy/services_management/`, `connectors/`, and the aiOS docs above). The engine is MIT licensed; see [LICENSE](./LICENSE).
