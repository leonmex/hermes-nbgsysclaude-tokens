from conftest import StubProviderProfile


def test_guard_ok_when_bundled_anthropic_present(load_plugin):
    pkg = load_plugin(with_anthropic=True)
    assert pkg.GUARD.ok and pkg.GUARD.base_cls is not None


def test_guard_fails_cleanly_when_anthropic_missing(load_plugin):
    pkg = load_plugin(with_anthropic=False)
    assert not pkg.GUARD.ok
    assert "anthropic" in pkg.GUARD.reason


def test_guard_rejects_incompatible_base_class(load_plugin):
    class Incompatible:  # no fetch_models
        pass

    pkg = load_plugin(base_cls=Incompatible)
    assert not pkg.GUARD.ok and "fetch_models" in pkg.GUARD.reason


def test_guard_falls_back_to_provider_registry(load_plugin, monkeypatch):
    import sys
    pkg = load_plugin(with_anthropic=False)
    monkeypatch.setitem(sys.modules["providers"]._REGISTRY, "anthropic", StubProviderProfile(name="anthropic"))
    assert pkg.guard.resolve_anthropic_base().ok


def test_guard_runs_lazy_bundled_discovery_when_needed(load_plugin, monkeypatch):
    import sys
    pkg = load_plugin(with_anthropic=False)
    providers = sys.modules["providers"]
    called = []

    def discover():
        called.append(True)
        providers._REGISTRY["anthropic"] = StubProviderProfile(name="anthropic")

    monkeypatch.setattr(providers, "_discover_providers", discover, raising=False)
    assert pkg.guard.resolve_anthropic_base().ok and called


def test_guard_loads_bundled_class_from_directory_without_registering(load_plugin, monkeypatch, tmp_path):
    """Hermes can import us mid-discovery, before 'anthropic' is registered anywhere."""
    import sys
    pkg = load_plugin(with_anthropic=False)
    providers = sys.modules["providers"]
    bundled = tmp_path / "bundled"
    (bundled / "anthropic").mkdir(parents=True)
    (bundled / "anthropic" / "__init__.py").write_text(
        "from providers import register_provider\n"
        "class AnthropicProfile:\n"
        "    def fetch_models(self, **kw):\n        return []\n"
        "register_provider(AnthropicProfile())\n")
    monkeypatch.setattr(providers, "_BUNDLED_PLUGINS_DIR", bundled, raising=False)
    sys.modules.pop("_nbgsysclaude_bundled_anthropic", None)
    before = providers.register_provider
    providers._REGISTRY["other"] = "keep"
    result = pkg.guard.resolve_anthropic_base()
    assert result.ok and result.base_cls.__name__ == "AnthropicProfile"
    assert providers._REGISTRY == {"other": "keep"}  # registry restored: no second 'anthropic' left behind
    assert providers.register_provider is before  # Hermes core is never rebound
    sys.modules.pop("_nbgsysclaude_bundled_anthropic", None)
