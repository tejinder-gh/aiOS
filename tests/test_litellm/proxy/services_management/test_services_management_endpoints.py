import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import litellm.proxy.management_endpoints.services_management_endpoints as ep
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.types.services_management import ManagedServiceSpec


def _spec(name="svc", port=3000, prevent_stop=False):
    return ManagedServiceSpec(
        name=name,
        display_name=name.title(),
        kind="command",
        health_port=port,
        start_cmd=("echo", name),
        stop_cmd=("echo", name),
        prevent_stop=prevent_stop,
    )


def _client(role=LitellmUserRoles.PROXY_ADMIN):
    app = FastAPI()
    app.include_router(ep.router)
    app.dependency_overrides[user_api_key_auth] = lambda: UserAPIKeyAuth(api_key="sk-test", user_role=role)
    return TestClient(app)


def _spec_payload(name="new", port=4321):
    return {
        "name": name,
        "display_name": name.title(),
        "kind": "command",
        "health_host": "localhost",
        "health_port": port,
        "start_cmd": ["echo", name],
        "stop_cmd": ["echo", name],
    }


def test_non_admin_is_forbidden(monkeypatch):
    monkeypatch.setattr(ep, "_active_specs", lambda: ())
    resp = _client(role=LitellmUserRoles.INTERNAL_USER).get("/services/list")
    assert resp.status_code == 403


def test_ports_lists_allocations(monkeypatch):
    monkeypatch.setattr(ep, "_active_specs", lambda: (_spec("a", 3000), _spec("b", 3001)))
    resp = _client().get("/services/ports")
    assert resp.status_code == 200
    ports = {row["name"]: row["port"] for row in resp.json()["allocations"]}
    assert ports == {"a": 3000, "b": 3001}


def test_import_preview_maps_error_to_400(monkeypatch):
    monkeypatch.setattr(ep, "_active_specs", lambda: ())
    resp = _client().post("/services/import/preview", json={"path": "relative/path"})
    assert resp.status_code == 400


def test_register_conflict_returns_409_with_suggestion(monkeypatch):
    monkeypatch.setattr(ep, "_active_specs", lambda: (_spec("taken", 4321),))
    monkeypatch.setattr(ep, "_require_prisma", lambda: object())
    resp = _client().post("/services/register", json={"spec": _spec_payload(port=4321), "generate_proxy_key": False})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["conflicts"] == ["taken"]
    assert detail["suggested_port"] != 4321


def test_register_persists_and_returns_state(monkeypatch):
    persisted = {}

    async def _fake_persist(prisma, services):
        persisted["names"] = [s.name for s in services]

    async def _fake_probe(spec):
        return "stopped"

    monkeypatch.setattr(ep, "_active_specs", lambda: ())
    monkeypatch.setattr(ep, "_require_prisma", lambda: object())
    monkeypatch.setattr(ep, "_proxy_config_or_raise", lambda: object())
    monkeypatch.setattr(ep, "persist_services", _fake_persist)
    monkeypatch.setattr(ep, "apply_in_memory", lambda cfg, services: None)
    monkeypatch.setattr(ep, "probe_status", _fake_probe)

    resp = _client().post("/services/register", json={"spec": _spec_payload("new"), "generate_proxy_key": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"]["name"] == "new"
    assert body["connection_info"] is None
    assert persisted["names"] == ["new"]


def test_stop_is_blocked_for_prevent_stop_service(monkeypatch):
    monkeypatch.setattr(ep, "_active_specs", lambda: (_spec("db", 5432, prevent_stop=True),))
    resp = _client().post("/services/db/action", json={"action": "stop"})
    assert resp.status_code == 400
    assert "prevented" in resp.json()["detail"].lower()


def test_command_unknown_service_is_404(monkeypatch):
    monkeypatch.setattr(ep, "_active_specs", lambda: ())
    resp = _client().post("/services/ghost/command/logs")
    assert resp.status_code == 404


def test_dashboard_only_service_is_status_only(monkeypatch):
    spec = ManagedServiceSpec(name="skills", display_name="Skills", kind="command", dashboard_only=True)
    monkeypatch.setattr(ep, "_active_specs", lambda: (spec,))

    async def _must_not_probe(_spec):
        raise AssertionError("dashboard_only services must not be probed")

    monkeypatch.setattr(ep, "probe_status", _must_not_probe)
    resp = _client().get("/services/list")
    assert resp.status_code == 200
    svc = resp.json()["services"][0]
    assert svc["dashboard_only"] is True
    assert svc["control_enabled"] is False
    assert svc["status"] == "unknown"
    assert svc["endpoint"] == "-"
    assert svc["detail"] == "status-only"


def test_action_blocked_for_dashboard_only(monkeypatch):
    spec = ManagedServiceSpec(
        name="skills",
        display_name="Skills",
        kind="command",
        dashboard_only=True,
        start_cmd=("echo", "x"),
        stop_cmd=("echo", "x"),
    )
    monkeypatch.setattr(ep, "_active_specs", lambda: (spec,))
    resp = _client().post("/services/skills/action", json={"action": "restart"})
    assert resp.status_code == 400
    assert "status-only" in resp.json()["detail"].lower()


def test_register_rejects_working_dir_outside_root(monkeypatch):
    monkeypatch.setattr(ep, "_active_specs", lambda: ())
    monkeypatch.setattr(ep, "_require_prisma", lambda: object())
    monkeypatch.setattr(ep, "_import_root", lambda: "/opt/allowed")
    payload = {**_spec_payload("evil"), "working_dir": "/etc"}
    resp = _client().post("/services/register", json={"spec": payload, "generate_proxy_key": False})
    assert resp.status_code == 400
    assert "import root" in resp.json()["detail"].lower()


def test_docs_rejects_working_dir_outside_root(monkeypatch):
    spec = ManagedServiceSpec(
        name="svc",
        display_name="Svc",
        kind="command",
        health_port=3000,
        working_dir="/etc",
        docs_path="passwd",
    )
    monkeypatch.setattr(ep, "_active_specs", lambda: (spec,))
    monkeypatch.setattr(ep, "_import_root", lambda: "/opt/allowed")
    resp = _client().get("/services/svc/docs")
    assert resp.status_code == 404
    assert "outside" in resp.json()["detail"].lower()
