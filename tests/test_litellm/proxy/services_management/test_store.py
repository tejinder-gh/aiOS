import json

import pytest

import litellm.proxy.utils as proxy_utils
from litellm.proxy.services_management import store
from litellm.types.services_management import ManagedServiceSpec


def _spec(name: str, port: int) -> ManagedServiceSpec:
    return ManagedServiceSpec(
        name=name, display_name=name, kind="command", health_port=port, start_cmd=("echo", name), stop_cmd=("echo", name)
    )


def test_upsert_spec_appends_new_without_mutating():
    base = (_spec("a", 1), _spec("b", 2))
    result = store.upsert_spec(base, _spec("c", 3))
    assert [s.name for s in result] == ["a", "b", "c"]
    assert [s.name for s in base] == ["a", "b"]  # original untouched


def test_upsert_spec_replaces_existing_by_name():
    base = (_spec("a", 1), _spec("b", 2))
    result = store.upsert_spec(base, _spec("a", 9))
    assert [s.name for s in result] == ["b", "a"]
    assert result[-1].health_port == 9


def test_remove_spec_drops_only_target():
    base = (_spec("a", 1), _spec("b", 2))
    assert [s.name for s in store.remove_spec(base, "a")] == ["b"]
    assert [s.name for s in store.remove_spec(base, "missing")] == ["a", "b"]


class _FakeTable:
    def __init__(self):
        self.upserts = []

    async def upsert(self, where, data):
        self.upserts.append((where, data))


class _FakePrisma:
    def __init__(self):
        self.db = type("_DB", (), {"litellm_config": _FakeTable()})()


@pytest.mark.asyncio
async def test_persist_services_writes_full_list_and_invalidates(monkeypatch):
    invalidated = []

    async def _fake_invalidate(param_name):
        invalidated.append(param_name)

    monkeypatch.setattr(proxy_utils, "invalidate_config_param", _fake_invalidate)
    prisma = _FakePrisma()

    await store.persist_services(prisma, (_spec("a", 1), _spec("b", 2)))

    where, data = prisma.db.litellm_config.upserts[0]
    assert where == {"param_name": "service_management"}
    payload = json.loads(data["update"]["param_value"])
    assert [s["name"] for s in payload["services"]] == ["a", "b"]
    assert data["create"]["param_name"] == "service_management"
    assert invalidated == ["service_management"]


class _FakeConfigHolder:
    def __init__(self, config):
        self._config = config
        self.updated = None

    def get_config_state(self):
        return dict(self._config)

    def update_config_state(self, config):
        self.updated = config


def test_apply_in_memory_sets_services_and_preserves_other_keys():
    holder = _FakeConfigHolder({"general_settings": {"x": 1}})
    store.apply_in_memory(holder, (_spec("a", 1),))
    assert holder.updated["general_settings"] == {"x": 1}
    assert [s["name"] for s in holder.updated["service_management"]["services"]] == ["a"]
