"""
Port bookkeeping for managed services.

Every service claims one ``health_port``. These helpers answer three questions
without side effects: which ports are already claimed, whether a candidate port
collides, and what the next free port is. ``next_free_port`` takes an injected
``is_bindable`` predicate so it is deterministic under test; the production
predicate (``is_port_bindable``) actually probes the OS.
"""

import socket
from collections.abc import Callable

from litellm.types.services_management import ManagedServiceSpec

_MAX_PORT = 65535


def claimed_ports(specs: tuple[ManagedServiceSpec, ...], exclude_name: str | None = None) -> frozenset[int]:
    return frozenset(spec.health_port for spec in specs if spec.name != exclude_name and spec.health_port is not None)


def port_conflicts(
    port: int, specs: tuple[ManagedServiceSpec, ...], exclude_name: str | None = None
) -> tuple[str, ...]:
    """Names of services already registered on ``port`` (excluding ``exclude_name``)."""
    return tuple(spec.name for spec in specs if spec.health_port == port and spec.name != exclude_name)


def next_free_port(
    preferred: int,
    specs: tuple[ManagedServiceSpec, ...],
    is_bindable: Callable[[int], bool],
    exclude_name: str | None = None,
    max_port: int = _MAX_PORT,
) -> int | None:
    """Lowest port >= ``preferred`` that is neither claimed nor OS-bound.

    Returns ``None`` if every port up to ``max_port`` is taken (practically
    impossible, modelled as a value rather than an exception).
    """
    claimed = claimed_ports(specs, exclude_name)
    return next(
        (port for port in range(preferred, max_port + 1) if port not in claimed and is_bindable(port)),
        None,
    )


def is_port_bindable(port: int, host: str = "127.0.0.1") -> bool:
    """True if a TCP socket can bind ``host:port`` right now (i.e. it is free)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True
