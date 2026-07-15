"""
LiteLLM Hub connector — an MCP server that exposes this local hub's own data
(models, prompts, skills, MCP catalog, and usage/spend monitoring) as tools, so
Claude Desktop and ChatGPT can read and interact with the hub.

Transports:
  stdio            -> Claude Desktop (local).      python mcp_hub_connector.py
  streamable-http  -> ChatGPT / remote connectors. python mcp_hub_connector.py http
  sse              -> older remote clients.         python mcp_hub_connector.py sse

Config via env:
  LITELLM_HUB_URL   (default http://localhost:4000)
  LITELLM_HUB_KEY   (default sk-1234)
  MCP_CONNECTOR_HOST / MCP_CONNECTOR_PORT  (remote transports; default 127.0.0.1:4100)

The connector talks to the proxy admin API with the master key, so run it where
it can reach the hub and keep the master key private.
"""

import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

import httpx
import psycopg
from mcp.server.fastmcp import FastMCP

HUB_URL = os.getenv("LITELLM_HUB_URL", "http://localhost:4000").rstrip("/")
HUB_KEY = os.getenv("LITELLM_HUB_KEY", "sk-1234")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin@localhost:5432/litellm")

mcp = FastMCP("litellm-hub")

# Chat history has no native LiteLLM endpoint, so the connector owns this table.
# Created on first use; keeps hub-specific data decoupled from LiteLLM's schema.
_CHAT_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS hub_chat_history (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hub_chat_history_session_idx ON hub_chat_history (session_id, id);
"""


async def _db() -> psycopg.AsyncConnection:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True)
    await conn.execute(_CHAT_HISTORY_DDL)
    return conn


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {HUB_KEY}", "Content-Type": "application/json"}


async def _get(path: str, params: Dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{HUB_URL}{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def _post(path: str, body: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{HUB_URL}{path}", headers=_headers(), json=body)
        resp.raise_for_status()
        return resp.json()


async def _request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.request(method, f"{HUB_URL}{path}", headers=_headers(), json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else {"status": "ok"}


def _as_list(payload: Any, key: str) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get(key) or payload.get("data")
        if isinstance(value, list):
            return value
    return []


@mcp.tool()
async def hub_list_models() -> List[str]:
    """List every model id served by the LiteLLM hub (local + cloud)."""
    data = await _get("/v1/models")
    return [m["id"] for m in _as_list(data, "data")]


@mcp.tool()
async def hub_list_prompts() -> List[Dict[str, Any]]:
    """List the reusable prompt templates registered on the hub, with their content."""
    data = await _get("/prompts/list")
    prompts = _as_list(data, "prompts")
    out: List[Dict[str, Any]] = []
    for p in prompts:
        params = p.get("litellm_params", {}) if isinstance(p, dict) else {}
        prompt_data = params.get("prompt_data") or {}
        content = next((v.get("content") for v in prompt_data.values() if isinstance(v, dict)), None)
        out.append({"prompt_id": p.get("prompt_id"), "content": content})
    return out


@mcp.tool()
async def hub_get_prompt(prompt_id: str) -> Dict[str, Any]:
    """Get one prompt template's content by id. Shareable with the calling app."""
    for p in await hub_list_prompts():
        if p.get("prompt_id") == prompt_id or str(p.get("prompt_id", "")).startswith(f"{prompt_id}."):
            return p
    return {"error": f"prompt {prompt_id!r} not found"}


@mcp.tool()
async def hub_list_mcp_servers() -> List[Dict[str, Any]]:
    """List the MCP servers registered in the hub's catalog (shareable connectors)."""
    data = await _get("/v1/mcp/server")
    servers = _as_list(data, "data")
    return [
        {
            "alias": s.get("alias") or s.get("server_name"),
            "transport": s.get("transport"),
            "description": s.get("description"),
            "command": s.get("command"),
            "url": s.get("url"),
        }
        for s in servers
        if isinstance(s, dict)
    ]


@mcp.tool()
async def hub_list_skills() -> Any:
    """List skills available on the hub. Requires an Anthropic key with skills beta on the hub."""
    try:
        return await _get("/v1/skills", params={"beta": "true"})
    except httpx.HTTPStatusError as e:
        return {"error": f"skills unavailable: {e.response.status_code}. Needs ANTHROPIC_API_KEY + skills beta on the hub."}


@mcp.tool()
async def hub_recent_activity(limit: int = 20) -> List[Dict[str, Any]]:
    """Recent requests through the hub — see how you are interacting (model, tokens, cost, time)."""
    data = await _get("/spend/logs")
    logs = data if isinstance(data, list) else _as_list(data, "logs")
    recent = logs[-limit:] if isinstance(logs, list) else []
    return [
        {
            "time": row.get("startTime") or row.get("startTimeUTC"),
            "model": row.get("model"),
            "tokens": row.get("total_tokens"),
            "cost_usd": row.get("spend"),
            "status": row.get("status"),
        }
        for row in recent
        if isinstance(row, dict)
    ]


@mcp.tool()
async def hub_usage_summary() -> Dict[str, Any]:
    """Aggregate hub usage by model (request count, total tokens, total cost) from recent logs."""
    data = await _get("/spend/logs")
    logs = data if isinstance(data, list) else _as_list(data, "logs")
    by_model: Dict[str, Dict[str, float]] = defaultdict(lambda: {"requests": 0, "tokens": 0, "cost_usd": 0.0})
    for row in logs if isinstance(logs, list) else []:
        if not isinstance(row, dict):
            continue
        stats = by_model[row.get("model") or "unknown"]
        stats["requests"] += 1
        stats["tokens"] += row.get("total_tokens") or 0
        stats["cost_usd"] += row.get("spend") or 0.0
    return {"models": dict(by_model), "total_requests": sum(m["requests"] for m in by_model.values())}


@mcp.tool()
async def hub_chat(model: str, message: str) -> str:
    """Send a single message to a hub model (any model from hub_list_models) and return the reply."""
    result = await _post("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": message}]})
    choices = result.get("choices") if isinstance(result, dict) else None
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return str(result)


# ---------------------------------------------------------------------------
# Write / CRUD tools — let Claude/ChatGPT send data into the hub
# ---------------------------------------------------------------------------


@mcp.tool()
async def hub_create_prompt(prompt_id: str, content: str, model: str = "gpt-4o-mini") -> Dict[str, Any]:
    """Create a reusable prompt template on the hub. `content` may use {{variables}}."""
    body = {
        "prompt_id": prompt_id,
        "litellm_params": {
            "prompt_id": prompt_id,
            "prompt_integration": "dotprompt",
            "prompt_data": {prompt_id: {"content": content, "metadata": {"model": model}}},
        },
        "prompt_info": {"prompt_type": "db"},
    }
    return await _post("/prompts", body)


@mcp.tool()
async def hub_update_prompt(prompt_id: str, content: str, model: str = "gpt-4o-mini") -> Dict[str, Any]:
    """Replace the content of an existing prompt template."""
    body = {
        "prompt_id": prompt_id,
        "litellm_params": {
            "prompt_id": prompt_id,
            "prompt_integration": "dotprompt",
            "prompt_data": {prompt_id: {"content": content, "metadata": {"model": model}}},
        },
        "prompt_info": {"prompt_type": "db"},
    }
    return await _request("PUT", f"/prompts/{prompt_id}", body)


@mcp.tool()
async def hub_delete_prompt(prompt_id: str) -> Dict[str, Any]:
    """Delete a prompt template by id."""
    return await _request("DELETE", f"/prompts/{prompt_id}")


@mcp.tool()
async def hub_create_mcp_server(
    alias: str,
    description: str = "",
    transport: str = "stdio",
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new MCP server in the hub catalog. Names/aliases cannot contain '-'."""
    body: Dict[str, Any] = {
        "server_name": alias.replace("-", "_"),
        "alias": alias.replace("-", "_"),
        "description": description,
        "transport": transport,
    }
    if command:
        body["command"] = command
        body["args"] = args or []
    if url:
        body["url"] = url
    return await _post("/v1/mcp/server", body)


@mcp.tool()
async def hub_delete_mcp_server(alias_or_id: str) -> Dict[str, Any]:
    """Delete an MCP server from the catalog by alias or server_id."""
    servers = await _get("/v1/mcp/server")
    for s in _as_list(servers, "data"):
        if not isinstance(s, dict):
            continue
        if alias_or_id in (s.get("alias"), s.get("server_name"), s.get("server_id")):
            return await _request("DELETE", f"/v1/mcp/server/{s.get('server_id')}")
    return {"error": f"mcp server {alias_or_id!r} not found"}


@mcp.tool()
async def hub_get_user(user_id: str) -> Dict[str, Any]:
    """Get a user's profile and metadata (preferences live in metadata)."""
    return await _get("/user/info", params={"user_id": user_id})


@mcp.tool()
async def hub_set_user_preferences(user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
    """Set/merge a user's profile preferences (stored in the user's metadata). Creates the user if missing."""
    try:
        await _post("/user/new", {"user_id": user_id})
    except httpx.HTTPStatusError:
        pass  # already exists
    return await _post("/user/update", {"user_id": user_id, "metadata": {"preferences": preferences}})


@mcp.tool()
async def hub_append_chat_message(session_id: str, role: str, content: str) -> Dict[str, Any]:
    """Append a message to a chat-history session stored in the hub (connector-owned store)."""
    conn = await _db()
    try:
        await conn.execute(
            "INSERT INTO hub_chat_history (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, role, content),
        )
    finally:
        await conn.close()
    return {"session_id": session_id, "stored": {"role": role, "content": content}}


@mcp.tool()
async def hub_get_chat_history(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Read the stored chat history for a session (oldest first)."""
    conn = await _db()
    try:
        cur = await conn.execute(
            "SELECT role, content, created_at FROM hub_chat_history WHERE session_id = %s ORDER BY id DESC LIMIT %s",
            (session_id, limit),
        )
        rows = await cur.fetchall()
    finally:
        await conn.close()
    return [{"role": r[0], "content": r[1], "created_at": r[2].isoformat()} for r in reversed(rows)]


@mcp.tool()
async def hub_clear_chat_history(session_id: str) -> Dict[str, Any]:
    """Delete all stored messages for a chat-history session."""
    conn = await _db()
    try:
        cur = await conn.execute("DELETE FROM hub_chat_history WHERE session_id = %s", (session_id,))
        deleted = cur.rowcount
    finally:
        await conn.close()
    return {"session_id": session_id, "deleted": deleted}


def _run() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if mode in ("http", "streamable-http", "sse"):
        mcp.settings.host = os.getenv("MCP_CONNECTOR_HOST", "127.0.0.1")
        mcp.settings.port = int(os.getenv("MCP_CONNECTOR_PORT", "4100"))
        mcp.run(transport="streamable-http" if mode == "http" else mode)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    _run()
