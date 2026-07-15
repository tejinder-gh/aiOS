"""
LOCAL SERVICE MANAGEMENT

Endpoints for viewing and controlling the OS-level services a local LiteLLM hub
depends on (Ollama, Postgres, Redis, ...).

GET  /services/list             - status of every registered service
POST /services/{name}/action    - start | stop | restart a service (gated)

Control actions run real commands, so they are admin-only and additionally
gated behind LITELLM_ENABLE_SERVICE_CONTROL (see services_management/control.py).
Reading status is admin-only too, for parity with the rest of the admin surface.
"""

import asyncio
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Path

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.services_management.control import control_enabled, run_action
from litellm.proxy.services_management.health import probe_status
from litellm.proxy.services_management.registry import find_spec, load_service_specs
from litellm.types.services_management import (
    ManagedServiceSpec,
    ServiceActionRequest,
    ServiceActionResult,
    ServiceListResponse,
    ServiceState,
    ServiceStatus,
)

router = APIRouter()


def _require_admin(user_api_key_dict: UserAPIKeyAuth) -> None:
    if user_api_key_dict.user_role != LitellmUserRoles.PROXY_ADMIN:
        raise HTTPException(status_code=403, detail="Only proxy admins can manage local services.")


def _active_specs() -> Tuple[ManagedServiceSpec, ...]:
    from litellm.proxy.proxy_server import proxy_config

    config: Optional[Dict[str, Any]] = None
    if proxy_config is not None:
        try:
            config = proxy_config.get_config_state()
        except Exception:
            config = None
    return load_service_specs(config)


def _state_from(spec: ManagedServiceSpec, status: ServiceStatus, controllable: bool) -> ServiceState:
    detail = "listening" if status == "running" else "not listening"
    return ServiceState(
        name=spec.name,
        display_name=spec.display_name,
        description=spec.description,
        docs_url=spec.docs_url,
        kind=spec.kind,
        status=status,
        healthy=status == "running",
        endpoint=f"{spec.health_host}:{spec.health_port}",
        detail=detail,
        control_enabled=controllable,
    )


@router.get(
    "/services/list",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ServiceListResponse,
)
async def list_services(
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
) -> ServiceListResponse:
    """Return the status of every registered local service."""
    _require_admin(user_api_key_dict)
    specs = _active_specs()
    controllable = control_enabled()

    statuses = await asyncio.gather(*(probe_status(spec) for spec in specs))
    states = tuple(_state_from(spec, status, controllable) for spec, status in zip(specs, statuses))
    return ServiceListResponse(control_enabled=controllable, services=states)


@router.post(
    "/services/{name}/action",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ServiceActionResult,
)
async def service_action(
    request: ServiceActionRequest,
    name: str = Path(description="Registered service name, e.g. 'ollama'"),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
) -> ServiceActionResult:
    """Start, stop or restart one registered service."""
    _require_admin(user_api_key_dict)

    spec = find_spec(_active_specs(), name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {name!r}")

    return await run_action(spec, request.action)
