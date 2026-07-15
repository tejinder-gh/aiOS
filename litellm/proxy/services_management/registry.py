"""
Registry of controllable local services.

Defaults cover the dependencies a local LiteLLM hub typically runs (Ollama for
open-source models, Postgres for the proxy DB, Redis for caching). The set is
overridable from the proxy config under a top-level ``service_management`` key
so a user can point at a different Postgres formula, add vLLM, etc. Everything
here is immutable: build the full tuple in one shot, never mutate.
"""

from typing import Any, Mapping, Optional, Tuple

from litellm.types.services_management import ManagedServiceSpec

_DEFAULT_SPECS: Tuple[ManagedServiceSpec, ...] = (
    ManagedServiceSpec(
        name="ollama",
        display_name="Ollama",
        description="Local open-source model runtime. Serves models on :11434.",
        docs_url="https://ollama.com",
        kind="brew",
        health_port=11434,
        start_cmd=("brew", "services", "start", "ollama"),
        stop_cmd=("brew", "services", "stop", "ollama"),
        restart_cmd=("brew", "services", "restart", "ollama"),
    ),
    ManagedServiceSpec(
        name="postgres",
        display_name="PostgreSQL",
        description="Proxy database (virtual keys, teams, spend, logs).",
        docs_url="https://www.postgresql.org",
        kind="brew",
        health_port=5432,
        start_cmd=("brew", "services", "start", "postgresql@18"),
        stop_cmd=("brew", "services", "stop", "postgresql@18"),
        restart_cmd=("brew", "services", "restart", "postgresql@18"),
    ),
    ManagedServiceSpec(
        name="redis",
        display_name="Redis",
        description="Optional cache / coordination backend for the proxy.",
        docs_url="https://redis.io",
        kind="brew",
        health_port=6379,
        start_cmd=("brew", "services", "start", "redis"),
        stop_cmd=("brew", "services", "stop", "redis"),
        restart_cmd=("brew", "services", "restart", "redis"),
    ),
)


def _spec_from_config(entry: Mapping[str, Any]) -> ManagedServiceSpec:
    """Validate one config entry into a spec, raising on malformed input."""
    return ManagedServiceSpec.model_validate(entry)


def load_service_specs(config: Optional[Mapping[str, Any]]) -> Tuple[ManagedServiceSpec, ...]:
    """Return the active service specs.

    A ``service_management.services`` list in the proxy config, when present,
    fully replaces the defaults so the operator has explicit control over what
    can be started. Absent config -> the built-in defaults.
    """
    if config is None:
        return _DEFAULT_SPECS
    section = config.get("service_management")
    if not isinstance(section, Mapping):
        return _DEFAULT_SPECS
    services = section.get("services")
    if not isinstance(services, (list, tuple)) or len(services) == 0:
        return _DEFAULT_SPECS
    return tuple(_spec_from_config(entry) for entry in services)


def find_spec(specs: Tuple[ManagedServiceSpec, ...], name: str) -> Optional[ManagedServiceSpec]:
    return next((spec for spec in specs if spec.name == name), None)
