"""
Control actions (start/stop/restart and custom commands) for managed services.

Security posture: these run real OS commands, so control is gated three ways
and any one being false makes control a no-op:

  1. env flag ``LITELLM_ENABLE_SERVICE_CONTROL`` must be truthy (off by default)
  2. the caller must be a proxy admin (enforced at the endpoint layer)
  3. the target must be a registered spec, and only that spec's fixed argv is run

Commands are executed with ``create_subprocess_exec`` (no shell), so the argv
tuple on the spec is the entire attack surface; there is no string to inject
into. Failures are returned as values, never raised. Status reads never execute
anything (see health.py); ``starting`` is only ever a transient value returned
right after a successful start/restart, before the next status poll.
"""

import asyncio
import os

from litellm._logging import verbose_proxy_logger
from litellm.types.services_management import (
    ManagedServiceSpec,
    ServiceAction,
    ServiceActionResult,
    ServiceCommandResult,
    ServiceStatus,
)

_ENABLE_ENV_VAR = "LITELLM_ENABLE_SERVICE_CONTROL"
_COMMAND_TIMEOUT_SECONDS = 30.0

_TRUTHY = frozenset({"1", "true", "yes", "on"})

_SUCCESS_STATUS: dict[ServiceAction, ServiceStatus] = {
    "start": "starting",
    "restart": "starting",
    "stop": "stopped",
}


def control_enabled() -> bool:
    return os.getenv(_ENABLE_ENV_VAR, "").strip().lower() in _TRUTHY


def _argv_for(spec: ManagedServiceSpec, action: ServiceAction) -> tuple[str, ...] | None:
    if action == "start":
        return spec.start_cmd
    if action == "stop":
        return spec.stop_cmd
    return spec.restart_cmd


async def _execute(argv: tuple[str, ...], label: str) -> tuple[bool, str]:
    """Run one fixed argv, returning (succeeded, message) as a value."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=_COMMAND_TIMEOUT_SECONDS)
    except FileNotFoundError:
        return False, f"Command not found: {argv[0]!r}. Is it installed and on PATH?"
    except asyncio.TimeoutError:
        return False, f"'{label}' timed out after {_COMMAND_TIMEOUT_SECONDS:.0f}s."

    output = stdout_bytes.decode(errors="replace").strip()
    succeeded = process.returncode == 0
    if not succeeded:
        verbose_proxy_logger.warning("service control %s failed (rc=%s): %s", label, process.returncode, output)
    message = output if output else (f"{label} succeeded" if succeeded else f"{label} failed")
    return succeeded, message


async def _restart_via_stop_then_start(
    spec: ManagedServiceSpec, stop_cmd: tuple[str, ...], start_cmd: tuple[str, ...]
) -> ServiceActionResult:
    """Restart a service that has no restart_cmd by running its stop, then its start."""
    stopped, stop_message = await _execute(stop_cmd, f"stop {spec.name}")
    if not stopped:
        return ServiceActionResult(
            name=spec.name, action="restart", success=False, message=stop_message, status="unknown"
        )
    started, start_message = await _execute(start_cmd, f"start {spec.name}")
    return ServiceActionResult(
        name=spec.name,
        action="restart",
        success=started,
        message=start_message,
        status="starting" if started else "unknown",
    )


async def run_action(spec: ManagedServiceSpec, action: ServiceAction) -> ServiceActionResult:
    """Execute a lifecycle action for one service, returning the outcome as a value."""
    if not control_enabled():
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"Service control is disabled. Set {_ENABLE_ENV_VAR}=true to enable.",
            status="unknown",
        )

    if action == "restart" and spec.restart_cmd is None and spec.stop_cmd and spec.start_cmd:
        return await _restart_via_stop_then_start(spec, spec.stop_cmd, spec.start_cmd)

    argv = _argv_for(spec, action)
    if argv is None or len(argv) == 0:
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"No '{action}' command configured for {spec.name}.",
            status="unknown",
        )

    succeeded, message = await _execute(argv, f"{action} {spec.name}")
    return ServiceActionResult(
        name=spec.name,
        action=action,
        success=succeeded,
        message=message,
        status=_SUCCESS_STATUS[action] if succeeded else "unknown",
    )


async def run_command(spec: ManagedServiceSpec, command_name: str) -> ServiceCommandResult:
    """Execute one of a service's registered custom commands, by name."""
    if not control_enabled():
        return ServiceCommandResult(
            name=spec.name,
            command=command_name,
            success=False,
            message=f"Service control is disabled. Set {_ENABLE_ENV_VAR}=true to enable.",
        )

    command = next((cmd for cmd in spec.commands if cmd.name == command_name), None)
    if command is None:
        return ServiceCommandResult(
            name=spec.name,
            command=command_name,
            success=False,
            message=f"Unknown command {command_name!r} for {spec.name}.",
        )

    succeeded, message = await _execute(command.argv, f"{command_name} {spec.name}")
    return ServiceCommandResult(name=spec.name, command=command_name, success=succeeded, message=message)
