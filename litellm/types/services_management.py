"""
Types for local dependent-service management (Ollama, Postgres, Redis, ...).

This surface lets the dashboard show the status of, and optionally start/stop,
the OS-level services a local LiteLLM hub depends on. Control actions execute
real commands, so they are admin-only, localhost-only and gated behind an env
flag (see services_management/control.py). These types are intentionally free
of any behaviour; the registry/health/control modules act on them.
"""

from typing import Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

ServiceKind = Literal["brew", "docker_compose", "command"]
ServiceStatus = Literal["running", "stopped", "unknown"]
ServiceAction = Literal["start", "stop", "restart"]


class ManagedServiceSpec(BaseModel):
    """Immutable description of one controllable local service.

    ``health_host``/``health_port`` are the source of truth for status (a TCP
    connect), independent of how the service was started. The command tuples are
    the only thing ever executed, so control can never run an arbitrary string.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Stable id used in URLs, e.g. 'ollama'")
    display_name: str
    description: str = ""
    docs_url: Optional[str] = None
    kind: ServiceKind
    health_host: str = "localhost"
    health_port: int
    start_cmd: Tuple[str, ...]
    stop_cmd: Tuple[str, ...]
    restart_cmd: Optional[Tuple[str, ...]] = None
    prevent_stop: bool = Field(
        default=False,
        description="If true, the service can start but never stop/restart (e.g. the proxy's own Postgres/Redis).",
    )
    dashboard_only: bool = Field(
        default=False,
        description="If true, the card is status-only: no control actions, no TCP probe (status is 'unknown').",
    )


class ServiceState(BaseModel):
    """Status of one service as returned to the dashboard."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    description: str
    docs_url: Optional[str]
    kind: ServiceKind
    status: ServiceStatus
    healthy: bool
    endpoint: str
    detail: str
    control_enabled: bool
    prevent_stop: bool
    dashboard_only: bool


class ServiceActionRequest(BaseModel):
    action: ServiceAction


class ServiceActionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    action: ServiceAction
    success: bool
    message: str
    status: ServiceStatus


class ServiceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_enabled: bool
    services: Tuple[ServiceState, ...]
