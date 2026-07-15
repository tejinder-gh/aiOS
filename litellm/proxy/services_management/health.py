"""
Health probing for managed services.

Status is derived from an actual TCP connect to the service's port, not from how
(or whether) we started it. That keeps status correct even when a service was
started outside LiteLLM (e.g. an already-running Homebrew Postgres).
"""

import asyncio

from litellm.types.services_management import ManagedServiceSpec, ServiceStatus

_PROBE_TIMEOUT_SECONDS = 1.5


async def probe_status(spec: ManagedServiceSpec) -> ServiceStatus:
    """Return 'running' if the service's port accepts a TCP connection, else 'stopped'.

    A connection refused / timeout means not listening -> stopped. We never
    return 'unknown' from a probe; 'unknown' is reserved for the brief window
    right after a control action before the next poll.
    """
    try:
        connect = asyncio.open_connection(host=spec.health_host, port=spec.health_port)
        reader, writer = await asyncio.wait_for(connect, timeout=_PROBE_TIMEOUT_SECONDS)
    except (OSError, asyncio.TimeoutError):
        return "stopped"

    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return "running"
