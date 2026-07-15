"""
Control actions (start/stop/restart) for managed services.

Security posture: these run real OS commands, so control is gated three ways
and any one being false makes control a no-op:

  1. env flag ``LITELLM_ENABLE_SERVICE_CONTROL`` must be truthy (off by default)
  2. the caller must be a proxy admin (enforced at the endpoint layer)
  3. the target must be a registered spec, and only that spec's fixed argv is run

Commands are executed with ``create_subprocess_exec`` (no shell), so the argv
tuple on the spec is the entire attack surface; there is no string to inject
into. Failures are returned as values, never raised.
"""

import asyncio
import os
from typing import Optional, Tuple

from litellm._logging import verbose_proxy_logger
from litellm.types.services_management import (
    ManagedServiceSpec,
    ServiceAction,
    ServiceActionResult,
)

_ENABLE_ENV_VAR = "LITELLM_ENABLE_SERVICE_CONTROL"
_COMMAND_TIMEOUT_SECONDS = 30.0

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def control_enabled() -> bool:
    return os.getenv(_ENABLE_ENV_VAR, "").strip().lower() in _TRUTHY


def _argv_for(spec: ManagedServiceSpec, action: ServiceAction) -> Optional[Tuple[str, ...]]:
    if action == "start":
        return spec.start_cmd
    if action == "stop":
        return spec.stop_cmd
    return spec.restart_cmd if spec.restart_cmd is not None else (*spec.stop_cmd, *spec.start_cmd[-1:])


async def run_action(spec: ManagedServiceSpec, action: ServiceAction) -> ServiceActionResult:
    """Execute a control action for one service, returning the outcome as a value."""
    if not control_enabled():
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"Service control is disabled. Set {_ENABLE_ENV_VAR}=true to enable.",
            status="unknown",
        )

    if spec.dashboard_only:
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"{spec.name} is a status-only service and cannot be controlled from the hub.",
            status="unknown",
        )

    if spec.prevent_stop and action in ("stop", "restart"):
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"{spec.name} is protected; stop/restart is disabled to keep the hub's own backing store up.",
            status="unknown",
        )

    argv = _argv_for(spec, action)
    if argv is None or len(argv) == 0:
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"No '{action}' command configured for {spec.name}.",
            status="unknown",
        )

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=_COMMAND_TIMEOUT_SECONDS)
    except FileNotFoundError:
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"Command not found: {argv[0]!r}. Is it installed and on PATH?",
            status="unknown",
        )
    except asyncio.TimeoutError:
        return ServiceActionResult(
            name=spec.name,
            action=action,
            success=False,
            message=f"'{action}' timed out after {_COMMAND_TIMEOUT_SECONDS:.0f}s.",
            status="unknown",
        )

    output = stdout_bytes.decode(errors="replace").strip()
    succeeded = process.returncode == 0
    if not succeeded:
        verbose_proxy_logger.warning(
            "service control %s %s failed (rc=%s): %s", action, spec.name, process.returncode, output
        )

    return ServiceActionResult(
        name=spec.name,
        action=action,
        success=succeeded,
        message=output if output else (f"{action} succeeded" if succeeded else f"{action} failed"),
        status="unknown",
    )
