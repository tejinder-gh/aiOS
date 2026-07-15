import asyncio

import pytest

from litellm.proxy.services_management import control
from litellm.proxy.services_management.control import _argv_for, control_enabled, run_action
from litellm.types.services_management import ManagedServiceSpec

_SPEC = ManagedServiceSpec(
    name="demo",
    display_name="Demo",
    kind="brew",
    health_port=9999,
    start_cmd=("brew", "services", "start", "demo"),
    stop_cmd=("brew", "services", "stop", "demo"),
    restart_cmd=("brew", "services", "restart", "demo"),
)


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True), ("0", False), ("", False), ("nope", False)],
)
def test_control_enabled_reads_env(monkeypatch, value, expected):
    monkeypatch.setenv("LITELLM_ENABLE_SERVICE_CONTROL", value)
    assert control_enabled() is expected


def test_control_enabled_defaults_off(monkeypatch):
    monkeypatch.delenv("LITELLM_ENABLE_SERVICE_CONTROL", raising=False)
    assert control_enabled() is False


def test_argv_for_maps_each_action():
    assert _argv_for(_SPEC, "start") == ("brew", "services", "start", "demo")
    assert _argv_for(_SPEC, "stop") == ("brew", "services", "stop", "demo")
    assert _argv_for(_SPEC, "restart") == ("brew", "services", "restart", "demo")


@pytest.mark.asyncio
async def test_disabled_flag_never_executes(monkeypatch):
    monkeypatch.delenv("LITELLM_ENABLE_SERVICE_CONTROL", raising=False)

    async def _boom(*args, **kwargs):
        raise AssertionError("subprocess must not run while control is disabled")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)

    result = await run_action(_SPEC, "start")
    assert result.success is False
    assert "disabled" in result.message.lower()


@pytest.mark.asyncio
async def test_enabled_runs_only_spec_argv(monkeypatch):
    monkeypatch.setenv("LITELLM_ENABLE_SERVICE_CONTROL", "true")
    recorded = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"started", b"")

    async def _fake_exec(*argv, **kwargs):
        recorded["argv"] = argv
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await run_action(_SPEC, "stop")
    assert recorded["argv"] == ("brew", "services", "stop", "demo")
    assert result.success is True
    assert result.message == "started"


@pytest.mark.asyncio
async def test_missing_binary_is_reported_as_value(monkeypatch):
    monkeypatch.setenv("LITELLM_ENABLE_SERVICE_CONTROL", "true")

    async def _raise_not_found(*argv, **kwargs):
        raise FileNotFoundError("brew")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_not_found)

    result = await run_action(_SPEC, "start")
    assert result.success is False
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
async def test_nonzero_exit_is_failure(monkeypatch):
    monkeypatch.setenv("LITELLM_ENABLE_SERVICE_CONTROL", "true")

    class _FailProc:
        returncode = 1

        async def communicate(self):
            return (b"Error: not installed", b"")

    async def _fake_exec(*argv, **kwargs):
        return _FailProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await run_action(_SPEC, "start")
    assert result.success is False
    assert "not installed" in result.message
