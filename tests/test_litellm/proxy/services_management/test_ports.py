import socket

from litellm.proxy.services_management import ports
from litellm.types.services_management import ManagedServiceSpec


def _spec(name: str, port: int) -> ManagedServiceSpec:
    return ManagedServiceSpec(
        name=name,
        display_name=name,
        kind="command",
        health_port=port,
        start_cmd=("echo", name),
        stop_cmd=("echo", name),
    )


_SPECS = (_spec("a", 3000), _spec("b", 3001))


def test_claimed_ports_collects_health_ports():
    assert ports.claimed_ports(_SPECS) == frozenset({3000, 3001})


def test_claimed_ports_excludes_named():
    assert ports.claimed_ports(_SPECS, exclude_name="a") == frozenset({3001})


def test_port_conflicts_lists_only_same_port():
    assert ports.port_conflicts(3000, _SPECS) == ("a",)
    assert ports.port_conflicts(3999, _SPECS) == ()


def test_port_conflicts_excludes_self():
    assert ports.port_conflicts(3000, _SPECS, exclude_name="a") == ()


def test_next_free_port_skips_claimed_and_unbindable():
    # 3000/3001 claimed; pretend 3002 is bound at the OS level -> first free is 3003.
    free = ports.next_free_port(3000, _SPECS, is_bindable=lambda p: p != 3002)
    assert free == 3003


def test_next_free_port_returns_preferred_when_free():
    assert ports.next_free_port(4100, _SPECS, is_bindable=lambda p: True) == 4100


def test_next_free_port_none_when_exhausted():
    assert ports.next_free_port(3000, _SPECS, is_bindable=lambda p: False, max_port=3005) is None


def test_claimed_ports_excludes_portless_specs():
    portless = ManagedServiceSpec(name="c", display_name="C", kind="command", dashboard_only=True)
    assert ports.claimed_ports((*_SPECS, portless)) == frozenset({3000, 3001})


def test_is_port_bindable_false_while_held():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        held_port = held.getsockname()[1]
        # A second bind of a listening port without REUSEADDR semantics must fail.
        assert ports.is_port_bindable(held_port) is False
