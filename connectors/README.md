# Hub connector (MCP)

`mcp_hub_connector.py` is an MCP server that exposes this LiteLLM hub's own data as tools, so Claude Desktop and ChatGPT can read from and interact with the hub. Tools:

- `hub_list_models` — every model the hub serves
- `hub_list_prompts` / `hub_get_prompt` — the reusable prompt templates (share them with the other app)
- `hub_list_mcp_servers` — the hub's MCP catalog
- `hub_list_skills` — skills (needs an Anthropic key + skills beta on the hub)
- `hub_recent_activity` / `hub_usage_summary` — monitoring: how you've been interacting (model, tokens, cost, time)
- `hub_chat(model, message)` — send a message to any hub model and get the reply

Write / CRUD (send data into the hub):

- `hub_create_prompt` / `hub_update_prompt` / `hub_delete_prompt` — manage prompt templates (created as deletable `db` prompts)
- `hub_create_mcp_server` / `hub_delete_mcp_server` — manage the MCP catalog
- `hub_set_user_preferences` / `hub_get_user` — user profile preferences (stored in LiteLLM user metadata)
- `hub_append_chat_message` / `hub_get_chat_history` / `hub_clear_chat_history` — chat history

Note on storage: prompts, MCP servers and user preferences use LiteLLM's own tables through the proxy API. Chat history has no native LiteLLM endpoint, so the connector owns a `hub_chat_history` table it creates on first use in the same Postgres (via `psycopg`, using `DATABASE_URL`). Run the connector with `DATABASE_URL` in the environment (the `llmhub-connector*` aliases source `.env`, which sets it).

The connector talks to the proxy with the master key, so keep the key private and run it where it can reach the hub.

## Claude Desktop (local, stdio — easiest)

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`, then restart Claude Desktop. The hub tools show up under the connector/plug icon.

```json
{
  "mcpServers": {
    "litellm-hub": {
      "command": "uv",
      "args": [
        "run", "--project", "/opt/Developer/SourceCode/infra/litellm",
        "python", "/opt/Developer/SourceCode/infra/litellm/connectors/mcp_hub_connector.py"
      ],
      "env": {
        "LITELLM_HUB_URL": "http://localhost:4000",
        "LITELLM_HUB_KEY": "sk-1234",
        "DATABASE_URL": "postgresql://admin@localhost:5432/litellm"
      }
    }
  }
}
```

## ChatGPT (remote, streamable-http)

ChatGPT connectors need a public HTTPS URL — ChatGPT can't reach `localhost`. So:

1. Start the connector in remote mode: `llmhub-connector-http` (serves `http://127.0.0.1:4100/mcp`).
2. Expose it over HTTPS with a tunnel, e.g. `cloudflared tunnel --url http://localhost:4100` (or ngrok). Copy the public `https://…` URL.
3. In ChatGPT: Settings -> Connectors -> add a custom/remote MCP connector, URL = `https://…/mcp`.

Caveats: this publishes a tool surface that can call your hub. The connector has no auth of its own yet, so only run the tunnel while you need it, and treat the public URL as a secret. Claude's remote connectors work the same way (public `/mcp` URL); Claude Desktop's local stdio path above avoids the tunnel entirely.

## Run manually

```bash
uv run python connectors/mcp_hub_connector.py        # stdio (Claude Desktop)
uv run python connectors/mcp_hub_connector.py http   # streamable-http on :4100 (ChatGPT/remote)
```
