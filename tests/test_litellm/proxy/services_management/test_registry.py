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
