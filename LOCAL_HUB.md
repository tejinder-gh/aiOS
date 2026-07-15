# LiteLLM Local Hub

Personal operations guide for running this LiteLLM checkout as a single local gateway for every LLM interaction (cloud providers + local open-source models via Ollama). This file is the source of truth; keep it updated when the setup changes.

## TL;DR

```bash
llmhub-start     # start the proxy on :4000 (loads .env, enables service control)
llmhub-ui        # start the dashboard dev server on :3000 (hot reload)
llmhub-status    # readiness + service statuses
llmhub-stop      # stop the proxy
```

Point any OpenAI-compatible client at `http://localhost:4000/v1` with key `sk-1234`.
Admin UI: `http://localhost:4000/ui/` (login `admin` / `sk-1234`).

## Endpoints and keys

| What | Value |
| --- | --- |
| OpenAI-compatible base URL | `http://localhost:4000/v1` |
| Anthropic-compatible base URL | `http://localhost:4000` (`/v1/messages`) |
| Master key | `sk-1234` (also `LITELLM_MASTER_KEY` in `.env`) |
| Admin UI (served by proxy) | `http://localhost:4000/ui/` |
| Dashboard dev server (hot reload) | `http://localhost:3000` |

Model selection (`model` field):
- Local OSS: `deepseek-coder`, `dolphin3`, `devstral`
- Anything pulled later: `ollama/<name>` (wildcard, no config edit)
- Cloud: `anthropic-haiku-4-5`, `openai/gpt-4o-mini`, ... (needs the key in `.env`)
- Global passthrough: any `provider/model`

## Configuration files

- `local_hub_config.yaml` — the hub config. `include`s `litellm/proxy/dev_config.yaml` (cloud models + settings) and adds local Ollama models, the `ollama/*` wildcard and the global `*` passthrough.
- `.env` (gitignored) — `DATABASE_URL`, `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `STORE_MODEL_IN_DB`, `REDIS_HOST`/`REDIS_PORT`, and provider key placeholders. Fill the keys you use. Change `LITELLM_SALT_KEY` before storing any real provider key in the DB; it encrypts stored secrets and can't be rotated afterward. `dev_config.yaml` enables a Redis response cache and usage-based routing, so Redis must be running (`brew services start redis`, or the Services page) and `REDIS_HOST`/`REDIS_PORT` set.
- Postgres: Homebrew `postgresql@18`, database `litellm`. The proxy runs Prisma migrations on boot.

## Running

Start the proxy (foreground so you see logs):

```bash
set -a; . ./.env; set +a
export LITELLM_ENABLE_SERVICE_CONTROL=true
uv run python litellm/proxy/proxy_cli.py --config local_hub_config.yaml --use_v2_migration_resolver 2>&1 | tee litellm.log
```

Dashboard dev server (separate terminal, for UI changes):

```bash
cd ui/litellm-dashboard && npm run dev
```

## Services page (custom feature)

A `Services` page (admin-only) in the dashboard shows the status of and controls the local services the hub depends on (Ollama, Postgres, Redis). Status comes from a TCP port probe; start/stop/restart run real commands.

Control is gated three ways, any one false makes it read-only:
1. `LITELLM_ENABLE_SERVICE_CONTROL=true` (off by default)
2. caller is a proxy admin
3. target is an allowlisted service; only its fixed argv runs (no shell)

Two per-service flags refine a card's behavior:
- `prevent_stop: true` keeps the start action but removes stop/restart, so you can't take down a store the proxy itself depends on (Postgres, Redis)
- `dashboard_only: true` makes the card status-only: no control actions and no port probe (status shows `unknown`). Use it for apps that expose no port and are launched by hand

Add more services (vLLM, LM Studio, ...) without code changes by adding a `service_management.services` block to `local_hub_config.yaml`:

```yaml
service_management:
  services:
    - name: vllm
      display_name: vLLM
      kind: command
      health_port: 8000
      start_cmd: ["vllm", "serve", "meta-llama/Llama-3.1-8B"]
      stop_cmd: ["pkill", "-f", "vllm serve"]
```

Backend: `litellm/proxy/services_management/` + `litellm/proxy/management_endpoints/services_management_endpoints.py`. Tests: `tests/test_litellm/proxy/services_management/`.

## Seeded catalogs

- MCP servers (dashboard -> MCP Servers): `memory`, `filesystem`, `fetch`, `git`, `sequential_thinking` (official reference servers, stdio via npx/uvx). They run on demand, so npx/uvx must be installed when a tool is called.
- Prompts (dashboard -> Prompts): `summarize`, `code_review`, `extract_json`, `rewrite_tone` (dotprompt templates with `{{variables}}`). Reseed or add with `POST /prompts`.
- Skills: NOT seeded. The Skills page / `POST /v1/skills` is a passthrough to Anthropic's remote Skills API; it needs a real `ANTHROPIC_API_KEY` with skills beta access and creates resources on Anthropic's side, so there is nothing to seed locally.

Reseed MCP example:

```bash
curl -X POST http://localhost:4000/v1/mcp/server -H "Authorization: Bearer sk-1234" -H "Content-Type: application/json" \
  -d '{"server_name":"time","alias":"time","description":"Time/timezone tools","transport":"stdio","command":"uvx","args":["mcp-server-time"]}'
```
Note: `server_name` and `alias` cannot contain `-`; use `_`.

## Connecting Claude Desktop / ChatGPT (MCP connector)

`connectors/mcp_hub_connector.py` exposes the hub's models, prompts, skills, MCP catalog and usage/spend monitoring as MCP tools so Claude Desktop and ChatGPT can read from and drive the hub. Claude Desktop connects locally over stdio; ChatGPT needs the remote (streamable-http) mode behind an HTTPS tunnel. Full setup and the Claude Desktop config JSON are in `connectors/README.md`.

```bash
llmhub-connector        # stdio, for Claude Desktop
llmhub-connector-http   # streamable-http on :4100, for ChatGPT/remote (tunnel required)
```

## Rebuilding the proxy-served UI

The proxy serves a prebuilt static export; dashboard code changes only appear at `:4000/ui/` after a rebuild (they appear immediately at `:3000`):

```bash
cd ui/litellm-dashboard && npm run build
cd /opt/Developer/SourceCode/infra/litellm
rm -rf litellm/proxy/_experimental/out && cp -r ui/litellm-dashboard/out/. litellm/proxy/_experimental/out/
```

## Automation (macOS launchd + backups)

Helper scripts under `scripts/` wrap the repetitive setup. They read `.env` without polluting the environment and never pipe remote scripts into a shell:
- `setup_launchd.sh` installs a launchd agent (`com.litellm.aios`) that starts the hub on login via `run_hub_launchd.sh`
- `backup_db.sh` dumps the `litellm` Postgres DB to `~/.litellm_backups` (gzip, atomic write); `setup_backup_launchd.sh` schedules it
- `setup_virtual_keys.sh` provisions a per-app virtual key against the running proxy for per-app budgets and spend tracking

## Provider keys vs. subscriptions

The proxy authenticates to providers with API keys (pay-as-you-go), set in `.env`. Consumer subscriptions (Claude Pro/Max, ChatGPT Plus/Go) are NOT API access and cannot be used as backend keys here; see the "Subscriptions" section notes kept with the setup. Use API keys for the proxy; use the subscription inside its own official app.

## Before turning any of this into a PR

- `npm run gen:api` (schema.d.ts is generated from the OpenAPI spec; routes changed)
- `make pre-commit` (formats/lints, generates types) with the relevant files staged
