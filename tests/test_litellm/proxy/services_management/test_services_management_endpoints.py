import pytest

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.management_endpoints import services_management_endpoints as endpoints
from litellm.types.services_management import ManagedServiceSpec

_ADMIN = UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN)

_POSTGRES = ManagedServiceSpec(
    name="postgres",
    display_name="PostgreSQL",
    kind="brew",
    health_port=5432,
    start_cmd=("brew", "services", "start", "postgresql@18"),
    stop_cmd=("brew", "services", "stop", "postgresql@18"),
    prevent_stop=True,
)
_ADK = ManagedServiceSpec(
    name="adk",
    display_name="ADK",
    kind="command",
    health_port=1,
    start_cmd=("echo", "adk"),
    stop_cmd=("echo", "adk"),
    dashboard_only=True,
)


@pytest.mark.asyncio
async def test_dashboard_only_is_never_probed_and_not_controllable(monkeypatch):
    probed = []

    async def _fake_probe(spec):
        probed.append(spec.name)
        return "running"

    monkeypatch.setattr(endpoints, "_active_specs", lambda: (_POSTGRES, _ADK))
    monkeypatch.setattr(endpoints, "probe_status", _fake_probe)
    monkeypatch.setattr(endpoints, "control_enabled", lambda: True)

    response = await endpoints.list_services(user_api_key_dict=_ADMIN)
    by_name = {s.name: s for s in response.services}

    assert probed == ["postgres"]

    adk = by_name["adk"]
    assert adk.dashboard_only is True
    assert adk.status == "unknown"
    assert adk.control_enabled is False
    assert adk.detail == "status-only"

    postgres = by_name["postgres"]
    assert postgres.prevent_stop is True
    assert postgres.dashboard_only is False
    assert postgres.control_enabled is True
    assert postgres.status == "running"


@pytest.mark.asyncio
async def test_control_disabled_makes_everything_read_only(monkeypatch):
    async def _fake_probe(spec):
        return "running"

    monkeypatch.setattr(endpoints, "_active_specs", lambda: (_POSTGRES,))
    monkeypatch.setattr(endpoints, "probe_status", _fake_probe)
    monkeypatch.setattr(endpoints, "control_enabled", lambda: False)

    response = await endpoints.list_services(user_api_key_dict=_ADMIN)
    assert response.control_enabled is False
    assert response.services[0].control_enabled is False


@pytest.mark.asyncio
async def test_non_admin_is_rejected(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(endpoints, "_active_specs", lambda: (_POSTGRES,))
    non_admin = UserAPIKeyAuth(user_role=LitellmUserRoles.INTERNAL_USER)

    with pytest.raises(HTTPException) as exc:
        await endpoints.list_services(user_api_key_dict=non_admin)
    assert exc.value.status_code == 403
