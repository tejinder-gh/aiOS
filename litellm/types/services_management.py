"""
Types for local dependent-service management (Ollama, Postgres, Redis, ...).

This surface lets the dashboard show the status of, and optionally start/stop,
the OS-level services a local LiteLLM hub depends on. Control actions execute
real commands, so they are admin-only, localhost-only and gated behind an env
flag (see services_management/control.py). These types are intentionally free
of any behaviour; the registry/health/control modules act on them.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceKind = Literal["brew", "docker_compose", "command"]
ServiceStatus = Literal["running", "starting", "stopped", "unknown"]
ServiceAction = Literal["start", "stop", "restart"]


class ServiceCommand(BaseModel):
    """One extra capability exposed on a service's detail page.

    Like the lifecycle commands, ``argv`` is the only thing ever executed, so a
    custom command can never run an arbitrary interpolated string.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Stable id used in URLs, e.g. 'seed-db'")
    display_name: str
    description: str = ""
    argv: tuple[str, ...]


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
    docs_url: str | None = None
    kind: ServiceKind
    health_host: str = "localhost"
    health_port: int | None = None
    dashboard_only: bool = False
    start_cmd: tuple[str, ...] | None = None
    stop_cmd: tuple[str, ...] | None = None
    restart_cmd: tuple[str, ...] | None = None
    prevent_stop: bool = False
    commands: tuple[ServiceCommand, ...] = ()
    web_url: str | None = None
    docs_path: str | None = None
    working_dir: str | None = None
    proxy_key_alias: str | None = None


class ServiceCommandInfo(BaseModel):
    """A custom command as advertised to the dashboard (argv omitted)."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    description: str


class ServiceState(BaseModel):
    """Status of one service as returned to the dashboard."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    description: str
    docs_url: str | None
    kind: ServiceKind
    status: ServiceStatus
    healthy: bool
    endpoint: str
    detail: str
    control_enabled: bool
    prevent_stop: bool
    dashboard_only: bool
    web_url: str | None
    has_docs: bool
    commands: tuple[ServiceCommandInfo, ...] = ()


class ServiceActionRequest(BaseModel):
    action: ServiceAction


class ServiceActionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    action: ServiceAction
    success: bool
    message: str
    status: ServiceStatus


class ServiceCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    command: str
    success: bool
    message: str


class ServiceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_enabled: bool
    services: tuple[ServiceState, ...]


class PortAllocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    port: int


class PortsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    allocations: tuple[PortAllocation, ...]


class ImportRequest(BaseModel):
    path: str


class DetectedCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    description: str
    argv: tuple[str, ...]


class ImportPreview(BaseModel):
    """A proposed service spec derived from a directory, plus conflict info.

    The UI prefills a form from this and always lets the operator edit the port
    before registering; ``suggested_port`` is the next free port when
    ``detected_port`` is already claimed.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    description: str
    kind: ServiceKind
    health_host: str
    detected_port: int
    suggested_port: int
    conflicts: tuple[str, ...]
    start_cmd: tuple[str, ...] | None
    stop_cmd: tuple[str, ...] | None
    restart_cmd: tuple[str, ...] | None
    commands: tuple[DetectedCommand, ...]
    web_url: str | None
    docs_path: str | None
    working_dir: str


class RegisterServiceRequest(BaseModel):
    spec: ManagedServiceSpec
    generate_proxy_key: bool = False


class ConnectionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: str
    api_key: str
    env_snippet: str


class RegisterServiceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: ServiceState
    connection_info: ConnectionInfo | None


class ServiceDocsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    markdown: str
    source_path: str
