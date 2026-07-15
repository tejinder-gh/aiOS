from litellm.proxy.services_management.registry import find_spec, load_service_specs

_OVERRIDE = {
    "service_management": {
        "services": [
            {
                "name": "vllm",
                "display_name": "vLLM",
                "kind": "command",
                "health_port": 8000,
                "start_cmd": ["vllm", "serve"],
                "stop_cmd": ["pkill", "-f", "vllm"],
            }
        ]
    }
}


def test_defaults_when_no_config():
    specs = load_service_specs(None)
    names = {s.name for s in specs}
    assert {"ollama", "postgres", "redis"} <= names


def test_defaults_when_section_absent():
    assert load_service_specs({"model_list": []}) == load_service_specs(None)


def test_empty_services_falls_back_to_defaults():
    assert load_service_specs({"service_management": {"services": []}}) == load_service_specs(None)


def test_override_replaces_defaults():
    specs = load_service_specs(_OVERRIDE)
    assert [s.name for s in specs] == ["vllm"]
    assert specs[0].start_cmd == ("vllm", "serve")


def test_find_spec():
    specs = load_service_specs(None)
    assert find_spec(specs, "ollama") is not None
    assert find_spec(specs, "does-not-exist") is None


def test_flags_default_false_when_absent():
    spec = load_service_specs(_OVERRIDE)[0]
    assert spec.prevent_stop is False
    assert spec.dashboard_only is False


def test_flags_round_trip_from_config():
    config = {
        "service_management": {
            "services": [
                {
                    "name": "postgres",
                    "display_name": "PostgreSQL",
                    "kind": "brew",
                    "health_port": 5432,
                    "start_cmd": ["brew", "services", "start", "postgresql@18"],
                    "stop_cmd": ["brew", "services", "stop", "postgresql@18"],
                    "prevent_stop": True,
                },
                {
                    "name": "adk",
                    "display_name": "ADK",
                    "kind": "command",
                    "health_port": 1,
                    "start_cmd": ["echo", "adk"],
                    "stop_cmd": ["echo", "adk"],
                    "dashboard_only": True,
                },
            ]
        }
    }
    specs = load_service_specs(config)
    by_name = {s.name: s for s in specs}
    assert by_name["postgres"].prevent_stop is True
    assert by_name["postgres"].dashboard_only is False
    assert by_name["adk"].dashboard_only is True
    assert by_name["adk"].prevent_stop is False
