from conftest import GOOD_TOKEN, StubAnthropicProfile, make_opener


def profile(load_plugin):
    pkg = load_plugin()
    return pkg.PROFILE


def test_profile_extends_bundled_anthropic(load_plugin):
    p = profile(load_plugin)
    assert isinstance(p, StubAnthropicProfile)
    assert p.api_mode == "anthropic_messages"
    assert p.base_url == "https://api.anthropic.com"


def test_profile_owns_its_own_credential_variable(load_plugin):
    p = profile(load_plugin)
    assert p.env_vars == ("NBGSYSCLAUDE_CODE_OAUTH_TOKEN",)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in p.env_vars and "ANTHROPIC_API_KEY" not in p.env_vars


def test_aliases_never_collide_with_bundled_provider(load_plugin):
    p = profile(load_plugin)
    reserved = {"anthropic", "claude", "claude-oauth", "claude-code"}
    assert p.name not in reserved and not (set(p.aliases) & reserved)
    assert all(a.startswith("nbgsysclaude") for a in p.aliases)


def test_profile_has_auth_handler(load_plugin):
    assert callable(profile(load_plugin).auth_handler)


def test_list_models_uses_bearer_and_paginates(sub):
    prof = sub("profile")
    pages = [
        {"data": [{"id": "m1"}, {"id": "m2"}], "has_more": True, "last_id": "m2"},
        {"data": [{"id": "m2"}, {"id": "m3"}], "has_more": False, "last_id": "m3"},
    ]
    calls = []
    responses = iter(pages)

    def opener(req, timeout):
        calls.append(req)
        return make_opener(200, next(responses))(req, timeout)

    assert prof.list_models(GOOD_TOKEN, opener=opener) == ["m1", "m2", "m3"]
    first = {k.lower(): v for k, v in calls[0].header_items()}
    assert first["authorization"] == f"Bearer {GOOD_TOKEN}" and "x-api-key" not in first
    assert "after_id=m2" in calls[1].full_url


def test_list_models_returns_none_on_401_or_no_key(sub):
    prof = sub("profile")
    assert prof.list_models(GOOD_TOKEN, opener=make_opener(401, {"error": {}})) is None
    assert prof.list_models(None) is None


def test_fetch_models_never_raises(load_plugin, monkeypatch):
    pkg = load_plugin()
    import importlib
    profile_mod = importlib.import_module(pkg.__name__ + ".profile")
    monkeypatch.setattr(profile_mod, "list_models", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert pkg.PROFILE.fetch_models(api_key=GOOD_TOKEN) is None
