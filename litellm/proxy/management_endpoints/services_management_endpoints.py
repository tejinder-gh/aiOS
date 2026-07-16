"""
LOCAL SERVICE MANAGEMENT

Endpoints for viewing and controlling the OS-level services a local LiteLLM hub
depends on (Ollama, Postgres, Redis, ...), plus registering new ones from a
project directory.

GET    /services/list                     - status of every registered service
GET    /services/ports                    - port allocation map
POST   /services/import/preview           - propose a spec from a directory
POST   /services/register                 - persist a service (optionally mint a proxy key)
DELETE /services/{name}                   - unregister a service
POST   /services/{name}/action            - start | stop | restart (gated)
POST   /services/{name}/command/{command} - run a registered custom command (gated)
GET    /services/{name}/docs              - the service's README, rendered as markdown

Control actions run real commands, so they are admin-only and additionally gated
behind LITELLM_ENABLE_SERVICE_CONTROL (see services_management/control.py).
Reading status / registering is admin-only too, for parity with the admin surface.
"""

import asyncio
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from litellm.proxy._types import CommonProxyErrors, LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.services_management.control import (
    ALLOWED_EXECUTABLES,
    control_enabled,
    disallowed_executables,
    local_mode,
    run_action,
    run_command,
)
from litellm.proxy.services_management.health import probe_status
from litellm.proxy.services_management.importer import ImportErr, build_preview, is_within_root
from litellm.proxy.services_management.ports import (
    is_port_bindable,
    next_free_port,
    port_conflicts,
)
from litellm.proxy.services_management.registry import find_spec, load_service_specs
from litellm.proxy.services_management.store import (
    ConfigStateHolder,
    PrismaClientLike,
    apply_in_memory,
    persist_services,
    remove_spec,
    upsert_spec,
)
from litellm.types.services_management import (
    ConnectionInfo,
    ImportPreview,
    ImportRequest,
    ManagedServiceSpec,
    PortAllocation,
    PortsResponse,
    RegisterServiceRequest,
    RegisterServiceResponse,
    ServiceActionRequest,
    ServiceActionResult,
    ServiceCommandInfo,
    ServiceCommandResult,
    ServiceDocsResponse,
    ServiceListResponse,
    ServiceState,
    ServiceStatus,
)

router = APIRouter()

_DEFAULT_IMPORT_ROOT = "/opt/Developer/SourceCode/AI"

# Module-level singleton so the auth dependency isn't a function call in each
# handler's argument defaults (ruff B008); the value is identical to inlining
# ``Depends(user_api_key_auth)`` on every endpoint.
_AUTH_DEP = Depends(user_api_key_auth)


def _require_admin(user_api_key_dict: UserAPIKeyAuth) -> None:
    if user_api_key_dict.user_role != LitellmUserRoles.PROXY_ADMIN:
        raise HTTPException(status_code=403, detail="Only proxy admins can manage local services.")


def _config_state() -> dict[str, object] | None:
    from litellm.proxy.proxy_server import proxy_config

    if proxy_config is None:
        return None
    try:
        return proxy_config.get_config_state()
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _active_specs() -> tuple[ManagedServiceSpec, ...]:
    return load_service_specs(_config_state())


def _import_root() -> str:
    config = _config_state() or {}
    general = config.get("general_settings")
    if not isinstance(general, dict):
        return _DEFAULT_IMPORT_ROOT
    root = general.get("service_import_root")
    return root if isinstance(root, str) and root else _DEFAULT_IMPORT_ROOT


def _require_prisma() -> PrismaClientLike:
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=400, detail={"error": CommonProxyErrors.db_not_connected_error.value})
    return prisma_client


def _state_from(spec: ManagedServiceSpec, status: ServiceStatus, controllable: bool) -> ServiceState:
    detail = "status-only" if spec.dashboard_only else ("listening" if status == "running" else "not listening")
    endpoint = "-" if spec.health_port is None else f"{spec.health_host}:{spec.health_port}"
    return ServiceState(
        name=spec.name,
        display_name=spec.display_name,
        description=spec.description,
        docs_url=spec.docs_url,
        kind=spec.kind,
        status=status,
        healthy=status == "running",
        endpoint=endpoint,
        detail=detail,
        control_enabled=controllable and not spec.dashboard_only,
        prevent_stop=spec.prevent_stop,
        dashboard_only=spec.dashboard_only,
        web_url=spec.web_url,
        has_docs=spec.docs_path is not None,
        commands=tuple(
            ServiceCommandInfo(name=cmd.name, display_name=cmd.display_name, description=cmd.description)
            for cmd in spec.commands
        ),
    )


async def _status_for(spec: ManagedServiceSpec) -> ServiceStatus:
    if spec.dashboard_only:
        return "unknown"
    return await probe_status(spec)


async def _list_response(specs: tuple[ManagedServiceSpec, ...]) -> ServiceListResponse:
    controllable = control_enabled()
    statuses = await asyncio.gather(*(_status_for(spec) for spec in specs))
    states = tuple(_state_from(spec, status, controllable) for spec, status in zip(specs, statuses))
    return ServiceListResponse(control_enabled=controllable, services=states)


@router.get(
    "/services/list",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ServiceListResponse,
)
async def list_services(
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> ServiceListResponse:
    """Return the status of every registered local service."""
    _require_admin(user_api_key_dict)
    return await _list_response(_active_specs())


@router.get(
    "/services/ports",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=PortsResponse,
)
async def list_ports(
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> PortsResponse:
    """Return the host port claimed by each registered service."""
    _require_admin(user_api_key_dict)
    allocations = tuple(
        sorted(
            (
                PortAllocation(name=spec.name, port=spec.health_port)
                for spec in _active_specs()
                if spec.health_port is not None and not spec.dashboard_only
            ),
            key=lambda alloc: alloc.port,
        )
    )
    return PortsResponse(allocations=allocations)


@router.post(
    "/services/import/preview",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ImportPreview,
)
async def import_preview(
    request: ImportRequest,
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> ImportPreview:
    """Propose a service spec by reading the config in a project directory."""
    _require_admin(user_api_key_dict)
    result = build_preview(
        path=request.path,
        allowed_root=_import_root(),
        specs=_active_specs(),
        is_bindable=is_port_bindable,
    )
    if isinstance(result, ImportErr):
        raise HTTPException(status_code=400, detail=result.reason)
    return result.preview


def _connection_info(base_url: str, api_key: str) -> ConnectionInfo:
    env_snippet = f"OPENAI_BASE_URL={base_url}\nOPENAI_API_KEY={api_key}"
    return ConnectionInfo(base_url=base_url, api_key=api_key, env_snippet=env_snippet)


@router.post(
    "/services/register",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=RegisterServiceResponse,
)
async def register_service(
    body: RegisterServiceRequest,
    request: Request,
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> RegisterServiceResponse:
    """Persist a new (or updated) service, optionally minting a proxy-routing key."""
    _require_admin(user_api_key_dict)
    prisma_client = _require_prisma()
    specs = _active_specs()
    spec = body.spec

    if spec.working_dir is not None and not is_within_root(spec.working_dir, _import_root()):
        raise HTTPException(status_code=400, detail="working_dir must be inside the allowed import root.")

    if not local_mode():
        blocked = disallowed_executables(spec)
        if blocked:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Executables not allowed in hosted mode: {', '.join(blocked)}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_EXECUTABLES))}. "
                    "Set LITELLM_SERVICE_LOCAL_MODE=true only on a trusted local host to allow arbitrary commands."
                ),
            )

    if spec.health_port is not None:
        conflicts = port_conflicts(spec.health_port, specs, exclude_name=spec.name)
        if conflicts:
            suggested = next_free_port(spec.health_port, specs, is_port_bindable, exclude_name=spec.name)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": f"Port {spec.health_port} is already used by: {', '.join(conflicts)}.",
                    "conflicts": list(conflicts),
                    "suggested_port": suggested,
                },
            )

    connection_info: ConnectionInfo | None = None
    if body.generate_proxy_key:
        from litellm.proxy.management_endpoints.key_management_endpoints import generate_key_helper_fn
        from litellm.proxy.utils import get_proxy_base_url

        alias = f"service-{spec.name}-{secrets.token_hex(3)}"
        key_data = await generate_key_helper_fn(
            request_type="key",
            table_name="key",
            key_alias=alias,
            metadata={"service": spec.name},
            created_by=user_api_key_dict.user_id,
        )
        base_url = get_proxy_base_url() or str(request.base_url).rstrip("/")
        connection_info = _connection_info(base_url, key_data["token"])
        spec = spec.model_copy(update={"proxy_key_alias": alias})

    new_specs = upsert_spec(specs, spec)
    await persist_services(prisma_client, new_specs)
    apply_in_memory(_proxy_config_or_raise(), new_specs)

    status = await probe_status(spec)
    state = _state_from(spec, status, control_enabled())
    return RegisterServiceResponse(service=state, connection_info=connection_info)


def _proxy_config_or_raise() -> ConfigStateHolder:
    from litellm.proxy.proxy_server import proxy_config

    if proxy_config is None:
        raise HTTPException(status_code=500, detail="Proxy config is not initialised.")
    return proxy_config


@router.delete(
    "/services/{name}",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ServiceListResponse,
)
async def unregister_service(
    name: str = Path(description="Registered service name"),
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> ServiceListResponse:
    """Remove a service from the registry and return the updated list."""
    _require_admin(user_api_key_dict)
    prisma_client = _require_prisma()
    specs = _active_specs()
    if find_spec(specs, name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {name!r}")

    new_specs = remove_spec(specs, name)
    await persist_services(prisma_client, new_specs)
    apply_in_memory(_proxy_config_or_raise(), new_specs)
    return await _list_response(new_specs)


@router.post(
    "/services/{name}/action",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ServiceActionResult,
)
async def service_action(
    request: ServiceActionRequest,
    name: str = Path(description="Registered service name, e.g. 'ollama'"),
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> ServiceActionResult:
    """Start, stop or restart one registered service."""
    _require_admin(user_api_key_dict)

    spec = find_spec(_active_specs(), name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {name!r}")
    if spec.dashboard_only:
        raise HTTPException(status_code=400, detail=f"{spec.display_name} is status-only and cannot be controlled.")
    if request.action == "stop" and spec.prevent_stop:
        raise HTTPException(status_code=400, detail=f"Stopping {spec.display_name} is prevented by configuration.")

    return await run_action(spec, request.action)


@router.post(
    "/services/{name}/command/{command_name}",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ServiceCommandResult,
)
async def service_command(
    name: str = Path(description="Registered service name"),
    command_name: str = Path(description="Registered command name"),
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> ServiceCommandResult:
    """Run one of a service's registered custom commands."""
    _require_admin(user_api_key_dict)
    spec = find_spec(_active_specs(), name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {name!r}")
    return await run_command(spec, command_name)


@router.get(
    "/services/{name}/docs",
    tags=["Service Management"],
    dependencies=[Depends(user_api_key_auth)],
    response_model=ServiceDocsResponse,
)
async def service_docs(
    name: str = Path(description="Registered service name"),
    user_api_key_dict: UserAPIKeyAuth = _AUTH_DEP,
) -> ServiceDocsResponse:
    """Return the service's README/docs, read from its working directory."""
    _require_admin(user_api_key_dict)
    spec = find_spec(_active_specs(), name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {name!r}")
    if spec.working_dir is None or spec.docs_path is None:
        raise HTTPException(status_code=404, detail="No documentation registered for this service.")
    if not is_within_root(spec.working_dir, _import_root()):
        raise HTTPException(status_code=404, detail="Documentation is outside the allowed import root.")

    doc_file = _resolve_doc_file(spec.working_dir, spec.docs_path)
    if doc_file is None:
        raise HTTPException(status_code=404, detail="Documentation file not found.")
    try:
        markdown = await asyncio.to_thread(_read_text, doc_file)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read documentation: {exc}")
    return ServiceDocsResponse(markdown=markdown, source_path=doc_file)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _resolve_doc_file(working_dir: str, docs_path: str) -> str | None:
    """Resolve docs_path under working_dir, guarding against traversal; a dir -> its README."""
    root = os.path.realpath(working_dir)
    candidate = os.path.realpath(os.path.join(root, docs_path))
    try:
        if os.path.commonpath([candidate, root]) != root:
            return None
    except ValueError:
        return None
    if os.path.isdir(candidate):
        readme = os.path.join(candidate, "README.md")
        return readme if os.path.isfile(readme) else None
    return candidate if os.path.isfile(candidate) else None
