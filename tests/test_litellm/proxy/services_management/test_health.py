import asyncio

import pytest

from litellm.proxy.services_management.health import probe_status
from litellm.types.services_management import ManagedServiceSpec


def _spec_for_port(port: int) -> ManagedServiceSpec:
    return ManagedServiceSpec(
        name="probe",
        display_name="Probe",
        kind="command",
        health_host="127.0.0.1",
        health_port=port,
        start_cmd=("true",),
        stop_cmd=("true",),
    )


@pytest.mark.asyncio
async def test_running_when_port_accepts_connections():
    server = await asyncio.start_server(lambda r, w: w.close(), host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await probe_status(_spec_for_port(port)) == "running"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_stopped_when_nothing_listening():
    # Bind to grab a free port, then release it so the probe hits a closed port.
    server = await asyncio.start_server(lambda r, w: w.close(), host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    assert await probe_status(_spec_for_port(port)) == "stopped"
