import textwrap

from litellm.proxy.services_management import importer
from litellm.types.services_management import ManagedServiceSpec


def _write(directory, name, content):
    path = directory / name
    path.write_text(textwrap.dedent(content))
    return path


def _preview(directory, root, specs=()):
    return importer.build_preview(str(directory), str(root), specs, is_bindable=lambda p: True)


def test_compose_resolves_var_default_and_builds_argv(tmp_path):
    app = tmp_path / "MyApp"
    app.mkdir()
    _write(app, "docker-compose.yaml", """
        services:
          web:
            ports:
              - "${PORT:-8088}:8088"
          db:
            image: postgres
    """)
    _write(app, "README.md", "# docs")

    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportOk)
    preview = result.preview
    assert preview.name == "myapp"
    assert preview.kind == "docker_compose"
    assert preview.detected_port == 8088
    assert preview.start_cmd is not None and preview.start_cmd[-2:] == ("up", "-d")
    assert preview.stop_cmd is not None and preview.stop_cmd[-1] == "down"
    assert preview.web_url == "http://localhost:8088"
    assert preview.docs_path == "README.md"
    assert {cmd.name for cmd in preview.commands} == {"logs", "ps"}


def test_compose_picks_first_service_with_a_published_port(tmp_path):
    app = tmp_path / "Multi"
    app.mkdir()
    _write(app, "docker-compose.yml", """
        services:
          worker:
            image: worker
          web:
            ports:
              - "127.0.0.1:4321:80"
    """)
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportOk)
    # host port from a 3-part mapping is the middle field
    assert result.preview.detected_port == 4321


def test_compose_includes_single_profile(tmp_path):
    app = tmp_path / "Profiled"
    app.mkdir()
    _write(app, "docker-compose.yml", """
        services:
          web:
            profiles: ["web"]
            ports:
              - "5000:5000"
    """)
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportOk)
    assert result.preview.start_cmd is not None
    assert "--profile" in result.preview.start_cmd
    assert "web" in result.preview.start_cmd


def test_node_next_defaults_to_3000_and_has_no_stop(tmp_path):
    app = tmp_path / "Web"
    app.mkdir()
    _write(app, "package.json", '{"dependencies": {"next": "14"}, "scripts": {"dev": "next dev"}}')
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportOk)
    assert result.preview.kind == "command"
    assert result.preview.detected_port == 3000
    assert result.preview.start_cmd == ("npm", "run", "dev", "--prefix", str(app))
    assert result.preview.stop_cmd is None


def test_node_vite_defaults_to_5173(tmp_path):
    app = tmp_path / "Vite"
    app.mkdir()
    _write(app, "package.json", '{"devDependencies": {"vite": "5"}, "scripts": {"dev": "vite"}}')
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportOk)
    assert result.preview.detected_port == 5173


def test_node_falls_back_to_env_port(tmp_path):
    app = tmp_path / "Plain"
    app.mkdir()
    _write(app, "package.json", '{"scripts": {"start": "node server.js"}}')
    _write(app, ".env", "FOO=bar\nPORT=6070\n")
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportOk)
    assert result.preview.detected_port == 6070


def test_port_conflict_suggests_a_free_port(tmp_path):
    app = tmp_path / "Clash"
    app.mkdir()
    _write(app, "docker-compose.yml", 'services:\n  web:\n    ports:\n      - "3000:3000"\n')
    existing = (
        ManagedServiceSpec(
            name="taken", display_name="Taken", kind="command", health_port=3000,
            start_cmd=("echo",), stop_cmd=("echo",),
        ),
    )
    result = _preview(app, tmp_path, specs=existing)
    assert isinstance(result, importer.ImportOk)
    assert result.preview.detected_port == 3000
    assert result.preview.conflicts == ("taken",)
    assert result.preview.suggested_port != 3000


def test_rejects_path_outside_root(tmp_path):
    outside = tmp_path.parent
    result = importer.build_preview(str(outside), str(tmp_path), (), is_bindable=lambda p: True)
    assert isinstance(result, importer.ImportErr)
    assert "allowed import root" in result.reason


def test_rejects_relative_path(tmp_path):
    result = importer.build_preview("relative/dir", str(tmp_path), (), is_bindable=lambda p: True)
    assert isinstance(result, importer.ImportErr)
    assert "absolute" in result.reason.lower()


def test_no_runner_is_an_error_value(tmp_path):
    app = tmp_path / "Empty"
    app.mkdir()
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportErr)


def test_malformed_compose_returns_error_not_raise(tmp_path):
    app = tmp_path / "Broken"
    app.mkdir()
    _write(app, "docker-compose.yml", "services: [this is: not valid: yaml")
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportErr)


def test_compose_without_ports_and_without_env_cannot_determine_port(tmp_path):
    app = tmp_path / "NoPorts"
    app.mkdir()
    _write(app, "docker-compose.yml", "services:\n  web:\n    image: nginx\n")
    result = _preview(app, tmp_path)
    assert isinstance(result, importer.ImportErr)
    assert "port" in result.reason.lower()
