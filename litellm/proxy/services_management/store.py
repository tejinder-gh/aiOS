"""
Persistence for UI-registered managed services.

The list lives as a single ``LiteLLM_Config`` row (``param_name="service_management"``),
mirroring how ``update_config_general_settings`` stores a config section. It is
merged back into the in-memory config on load / the 30s reload loop (see the
``service_management`` entry added to ``_update_config_from_db``), so the
registry keeps reading from ``get_config_state()`` as before.

Writes are full-list replacements: the caller reads the current *effective*
specs, applies its change, and hands the whole tuple here. That seeds the DB
from whatever the yaml currently shows on the first UI write, so nothing is
lost, and matches the merge semantics (the DB list replaces the yaml list).
"""

import json
from typing import Protocol

from litellm.repositories.config_repository import ConfigRepository
from litellm.types.services_management import ManagedServiceSpec

_PARAM_NAME = "service_management"


class ConfigStateHolder(Protocol):
    def get_config_state(self) -> dict: ...
    def update_config_state(self, config: dict) -> None: ...


class _ConfigTable(Protocol):
    async def upsert(self, *, where: dict[str, object], data: dict[str, object]) -> object: ...


class _PrismaDB(Protocol):
    litellm_config: _ConfigTable


class PrismaClientLike(Protocol):
    db: _PrismaDB


def upsert_spec(specs: tuple[ManagedServiceSpec, ...], spec: ManagedServiceSpec) -> tuple[ManagedServiceSpec, ...]:
    """Return ``specs`` with ``spec`` added, or replaced in place if the name exists."""
    return (*(existing for existing in specs if existing.name != spec.name), spec)


def remove_spec(specs: tuple[ManagedServiceSpec, ...], name: str) -> tuple[ManagedServiceSpec, ...]:
    return tuple(existing for existing in specs if existing.name != name)


def _serialize(services: tuple[ManagedServiceSpec, ...]) -> dict:
    return {"services": [service.model_dump(mode="json") for service in services]}


async def persist_services(prisma_client: PrismaClientLike, services: tuple[ManagedServiceSpec, ...]) -> None:
    """Write the full service list to the DB config row and evict the cache."""
    payload = json.dumps(_serialize(services))
    await ConfigRepository(prisma_client).table.upsert(
        where={"param_name": _PARAM_NAME},
        data={
            "create": {"param_name": _PARAM_NAME, "param_value": payload},
            "update": {"param_value": payload},
        },
    )
    from litellm.proxy.utils import invalidate_config_param

    await invalidate_config_param(_PARAM_NAME)


def apply_in_memory(proxy_config: ConfigStateHolder, services: tuple[ManagedServiceSpec, ...]) -> None:
    """Reflect the new list in the running config immediately (no 30s wait)."""
    config = proxy_config.get_config_state()
    proxy_config.update_config_state({**config, _PARAM_NAME: _serialize(services)})
