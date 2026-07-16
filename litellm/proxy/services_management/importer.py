"""
Auto-import a local project directory into a managed-service spec.

Parse-only: this module reads ``docker-compose`` / ``package.json`` / ``.env``
to *propose* a spec, and never executes anything. The proposed argv tuples are
what the control layer would later run (under its own gate), but nothing here
runs them. Every failure is returned as a value (``ImportErr``), never raised,
so the endpoint maps it to an HTTP status via an exhaustive match.

Security: the target directory must resolve to a location inside an allowlisted
root, so an admin cannot point the importer at arbitrary server paths.
"""

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import yaml

from litellm.proxy.services_management.ports import next_free_port, port_conflicts
from litellm.types.services_management import (
    DetectedCommand,
    ImportPreview,
    ManagedServiceSpec,
    ServiceKind,
)

_COMPOSE_FILENAMES: tuple[str, ...] = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)
_DOC_CANDIDATES: tuple[str, ...] = (
    "README.md",
    "README.MD",
    "README.rst",
    "README.txt",
    "README",
    "docs/README.md",
    "docs/index.md",
)
_ENV_PORT_RE = re.compile(r"^\s*PORT\s*=\s*['\"]?(\d{2,5})['\"]?\s*$", re.MULTILINE)
_VAR_WITH_DEFAULT_RE = re.compile(r"\$\{[^:}]+:-([^}]+)\}")
_VAR_NO_DEFAULT_RE = re.compile(r"\$\{[^}]+\}")


@dataclass(frozen=True, slots=True)
class ImportOk:
    preview: ImportPreview


@dataclass(frozen=True, slots=True)
class ImportErr:
    reason: str


ImportResult = ImportOk | ImportErr


@dataclass(frozen=True, slots=True)
class _Runner:
    kind: ServiceKind
    detected_port: int | None
    start_cmd: tuple[str, ...] | None
    stop_cmd: tuple[str, ...] | None
    restart_cmd: tuple[str, ...] | None
    commands: tuple[DetectedCommand, ...]


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "service"


def is_within_root(path: str, allowed_root: str) -> bool:
    """True if ``path`` resolves to a location inside ``allowed_root``."""
    root = os.path.realpath(allowed_root)
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:
        return False


def _expand_vars(text: str) -> str:
    """Resolve ``${VAR:-default}`` to its default and drop bare ``${VAR}``.

    Done before splitting on ':' because the ``:-`` in a default itself
    contains a colon and would otherwise corrupt the published:target split.
    """
    return _VAR_NO_DEFAULT_RE.sub("", _VAR_WITH_DEFAULT_RE.sub(r"\1", text))


def _resolve_port_token(token: object) -> int | None:
    candidate = _expand_vars(str(token)).strip().strip("'\"")
    return int(candidate) if candidate.isdigit() else None


def _published_port(port_entry: object) -> int | None:
    if isinstance(port_entry, Mapping):
        published = port_entry.get("published")
        return _resolve_port_token(published) if published is not None else None
    parts = _expand_vars(str(port_entry)).split(":")
    if len(parts) >= 3:
        return _resolve_port_token(parts[1])
    if len(parts) == 2:
        return _resolve_port_token(parts[0])
    return None


def _first_published(service: Mapping[str, object]) -> int | None:
    ports = service.get("ports")
    if not isinstance(ports, (list, tuple)):
        return None
    return next((p for p in (_published_port(entry) for entry in ports) if p is not None), None)


def _compose_file(directory: str) -> str | None:
    return next(
        (os.path.join(directory, name) for name in _COMPOSE_FILENAMES if os.path.isfile(os.path.join(directory, name))),
        None,
    )


def _compose_runner(compose_path: str) -> _Runner | ImportErr:
    try:
        with open(compose_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        return ImportErr(f"Could not parse {os.path.basename(compose_path)}: {exc}")
    services = data.get("services") if isinstance(data, Mapping) else None
    if not isinstance(services, Mapping) or len(services) == 0:
        return ImportErr("Compose file declares no services.")

    _primary_name, primary = next(
        (
            (name, svc)
            for name, svc in services.items()
            if isinstance(svc, Mapping) and _first_published(svc) is not None
        ),
        (next(iter(services)), None),
    )
    primary = primary if isinstance(primary, Mapping) else {}
    port = _first_published(primary)
    profiles = primary.get("profiles") if isinstance(primary.get("profiles"), (list, tuple)) else ()
    profile_args: tuple[str, ...] = ("--profile", str(profiles[0])) if profiles else ()

    base = ("docker", "compose", "-f", compose_path, *profile_args)
    commands = (
        DetectedCommand(
            name="logs",
            display_name="Logs",
            description="Tail the last 200 log lines",
            argv=(*base, "logs", "--tail", "200"),
        ),
        DetectedCommand(
            name="ps", display_name="Status", description="Show compose service status", argv=(*base, "ps")
        ),
    )
    return _Runner(
        kind="docker_compose",
        detected_port=port,
        start_cmd=(*base, "up", "-d"),
        stop_cmd=(*base, "down"),
        restart_cmd=(*base, "restart"),
        commands=commands,
    )


def _node_port(pkg: Mapping[str, object], script: str) -> int | None:
    deps = {
        **(pkg.get("dependencies") if isinstance(pkg.get("dependencies"), Mapping) else {}),
        **(pkg.get("devDependencies") if isinstance(pkg.get("devDependencies"), Mapping) else {}),
    }
    if "next" in deps or "next" in script:
        return 3000
    if "vite" in deps or "vite" in script:
        return 5173
    return None


def _node_runner(directory: str) -> _Runner | ImportErr:
    try:
        with open(os.path.join(directory, "package.json"), "r", encoding="utf-8") as handle:
            pkg = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return ImportErr(f"Could not parse package.json: {exc}")
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), Mapping) else {}
    script_name = next((name for name in ("dev", "start") if name in scripts), None)
    if script_name is None:
        return ImportErr("package.json has no 'dev' or 'start' script to run.")
    return _Runner(
        kind="command",
        detected_port=_node_port(pkg, str(scripts.get(script_name, ""))),
        start_cmd=("npm", "run", script_name, "--prefix", directory),
        stop_cmd=None,
        restart_cmd=None,
        commands=(),
    )


def _env_port(directory: str) -> int | None:
    env_path = os.path.join(directory, ".env")
    if not os.path.isfile(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8") as handle:
            match = _ENV_PORT_RE.search(handle.read())
    except OSError:
        return None
    return int(match.group(1)) if match else None


def _docs_path(directory: str) -> str | None:
    explicit = next((rel for rel in _DOC_CANDIDATES if os.path.isfile(os.path.join(directory, rel))), None)
    if explicit is not None:
        return explicit
    return "docs" if os.path.isdir(os.path.join(directory, "docs")) else None


def _detect_runner(directory: str) -> _Runner | ImportErr:
    compose_path = _compose_file(directory)
    if compose_path is not None:
        return _compose_runner(compose_path)
    if os.path.isfile(os.path.join(directory, "package.json")):
        return _node_runner(directory)
    return ImportErr("No docker-compose file or package.json found; cannot auto-import this directory.")


def build_preview(
    path: str,
    allowed_root: str,
    specs: tuple[ManagedServiceSpec, ...],
    is_bindable: Callable[[int], bool],
    health_host: str = "localhost",
) -> ImportResult:
    """Propose a service spec for ``path`` or explain why it can't be imported."""
    if not os.path.isabs(path):
        return ImportErr("Path must be absolute.")
    resolved = os.path.realpath(path)
    if not os.path.isdir(resolved):
        return ImportErr(f"Not a directory: {path}")
    if not is_within_root(resolved, allowed_root):
        return ImportErr(f"Path must be inside the allowed import root ({allowed_root}).")

    runner = _detect_runner(resolved)
    if isinstance(runner, ImportErr):
        return runner

    name = _slugify(os.path.basename(resolved))
    detected_port = runner.detected_port or _env_port(resolved)
    if detected_port is None:
        return ImportErr("Could not determine a port; add ports to compose, set PORT in .env, or register manually.")

    conflicts = port_conflicts(detected_port, specs, exclude_name=name)
    suggested = (
        detected_port
        if not conflicts
        else (next_free_port(detected_port, specs, is_bindable, exclude_name=name) or detected_port)
    )
    return ImportOk(
        ImportPreview(
            name=name,
            display_name=os.path.basename(resolved),
            description=f"Auto-imported from {resolved}",
            kind=runner.kind,
            health_host=health_host,
            detected_port=detected_port,
            suggested_port=suggested,
            conflicts=conflicts,
            start_cmd=runner.start_cmd,
            stop_cmd=runner.stop_cmd,
            restart_cmd=runner.restart_cmd,
            commands=runner.commands,
            web_url=f"http://{health_host}:{detected_port}",
            docs_path=_docs_path(resolved),
            working_dir=resolved,
        )
    )
