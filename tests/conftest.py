"""Test harness: stubs the pieces of Hermes the plugin imports and loads the plugin the way
Hermes's provider loader does (spec_from_file_location with the plugin dir as a package)."""

from __future__ import annotations

import dataclasses
import email.message
import importlib
import importlib.util
import io
import sys
import types
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PKG = "nbgsysclaude_tokens_under_test"

# A syntactically valid, obviously fake token (never a real credential).
GOOD_TOKEN = "sk-ant-oat01-" + "Ab1_-" * 19  # 13 + 95 = 108 chars


@dataclasses.dataclass
class StubProviderProfile:
    name: str
    api_mode: str = "chat_completions"
    aliases: tuple = ()
    display_name: str = ""
    description: str = ""
    signup_url: str = ""
    env_vars: tuple = ()
    base_url: str = ""
    auth_type: str = "api_key"
    default_aux_model: str = ""
    fallback_models: tuple = ()
    auth_handler: Any = None

    def fetch_models(self, *, api_key=None, base_url=None, timeout=8.0):
        return ["inherited"]


class StubAnthropicProfile(StubProviderProfile):
    pass


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: Optional[Dict[str, str]] = None):
        self.status = status
        self._body = body
        self.headers = email.message.Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def read(self, n: int = -1) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_opener(status: int, body: Any = b"", headers: Optional[Dict[str, str]] = None,
                calls: Optional[List[Any]] = None) -> Callable[..., Any]:
    """Opener that behaves like urllib: 2xx returns a response, other codes raise HTTPError."""
    if not isinstance(body, bytes):
        import json
        body = json.dumps(body).encode()

    def opener(req, timeout):
        if calls is not None:
            calls.append(req)
        if status >= 400:
            hdrs = email.message.Message()
            for k, v in (headers or {}).items():
                hdrs[k] = v
            raise urllib.error.HTTPError(req.full_url, status, "err", hdrs, io.BytesIO(body))
        return FakeResponse(status, body, headers)

    return opener


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("NBGSYSCLAUDE_PROBE_MODEL", raising=False)
    return home


@pytest.fixture
def load_plugin(monkeypatch):
    """Factory: load the plugin package against stubbed Hermes modules."""

    def _load(with_anthropic: bool = True, base_cls: type = StubAnthropicProfile, register=None):
        registered: List[Any] = []
        redaction: List[Any] = []

        providers = types.ModuleType("providers")
        providers.register_provider = register or registered.append
        providers._REGISTRY = {}
        monkeypatch.setitem(sys.modules, "providers", providers)

        agent = types.ModuleType("agent")
        redact = types.ModuleType("agent.redact")
        redact.register_redaction_patterns = lambda patterns, source="plugin": (
            redaction.extend(patterns) or len(patterns))
        monkeypatch.setitem(sys.modules, "agent", agent)
        monkeypatch.setitem(sys.modules, "agent.redact", redact)

        for name in ("plugins", "plugins.model_providers", "plugins.model_providers.anthropic"):
            monkeypatch.delitem(sys.modules, name, raising=False)
        if with_anthropic:
            mod = types.ModuleType("plugins.model_providers.anthropic")
            mod.AnthropicProfile = base_cls
            monkeypatch.setitem(sys.modules, "plugins.model_providers.anthropic", mod)

        for name in [n for n in sys.modules if n == PKG or n.startswith(PKG + ".")]:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(
            PKG, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[PKG] = module
        spec.loader.exec_module(module)
        module.registered = registered
        module.redaction = redaction
        return module

    yield _load
    for name in [n for n in sys.modules if n == PKG or n.startswith(PKG + ".")]:
        del sys.modules[name]


@pytest.fixture
def sub(load_plugin):
    """Import a plugin submodule (validator, token_store, ...) with Hermes stubs in place."""
    load_plugin()

    def _get(name: str):
        return importlib.import_module(f"{PKG}.{name}")

    return _get
