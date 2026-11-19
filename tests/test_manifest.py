import re

import yaml

from conftest import PLUGIN_DIR


def manifest():
    return yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text())


def test_manifest_identity(load_plugin):
    m = manifest()
    pkg = load_plugin()
    assert m["name"] == pkg.constants.PLUGIN_NAME
    assert re.fullmatch(r"[a-z0-9_-]{1,64}", m["name"])
    assert m["kind"] == "model-provider"


def test_manifest_declares_anthropic_dependency(load_plugin):
    assert load_plugin().constants.BASE_PLUGIN_ID in manifest()["requires_plugins"]


def test_manifest_has_no_hidden_capabilities():
    m = manifest()
    assert m["provides_tools"] == [] and m["provides_hooks"] == []


def test_package_has_no_runtime_dependencies():
    tomllib = __import__("tomllib") if __import__("sys").version_info >= (3, 11) else __import__("tomli")
    data = tomllib.loads((PLUGIN_DIR / "pyproject.toml").read_text())
    assert not data["project"].get("dependencies")
