"""Dependency guard: this plugin only activates when the bundled Anthropic provider is present.

It never raises. The result carries the base profile class to extend, or a human-readable reason
why the plugin must stay inert.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import constants

# Module name Hermes gives the bundled provider while importing it (providers/__init__.py).
_BUNDLED_MODULE_NAMES = ("plugins.model_providers.anthropic",)


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str
    base_cls: Optional[type] = None


def _from_bundled_module() -> Optional[type]:
    for name in _BUNDLED_MODULE_NAMES:
        mod = sys.modules.get(name)
        cls = getattr(mod, "AnthropicProfile", None) if mod is not None else None
        if isinstance(cls, type):
            return cls
    return None


def _from_registry() -> Optional[type]:
    providers = sys.modules.get("providers")
    registry = getattr(providers, "_REGISTRY", None)
    if not isinstance(registry, dict):
        return None
    profile = registry.get(constants.BASE_PROVIDER_NAME)
    return type(profile) if profile is not None else None


_PRIVATE_MODULE = "_nbgsysclaude_bundled_anthropic"


_REGISTRY_ATTRS = ("_REGISTRY", "_ALIASES")


def _snapshot_registries(providers) -> list:
    snaps = []
    for attr in _REGISTRY_ATTRS:
        reg = getattr(providers, attr, None)
        if isinstance(reg, dict):
            snaps.append((reg, dict(reg)))
    return snaps


def _restore_registries(snaps: list) -> None:
    for reg, saved in snaps:
        reg.clear()
        reg.update(saved)


def _from_bundled_dir() -> Optional[type]:
    """Load the bundled profile class straight from its directory, WITHOUT registering it.

    Needed because Hermes can import this plugin while bundled discovery is still running (an
    earlier bundled provider imports hermes_cli.config, which scans user plugins), at which point
    'anthropic' is neither in sys.modules nor in the registry yet. Importing the bundled file runs
    its module-level register_provider(); the provider registry is snapshotted before the import
    and restored afterwards so no second 'anthropic' profile is left behind. Hermes core is never
    rebound or monkeypatched. Startup imports are single-threaded.
    """
    providers = sys.modules.get("providers")
    root = getattr(providers, "_BUNDLED_PLUGINS_DIR", None)
    if root is None:
        return None
    init = Path(root) / constants.BASE_PROVIDER_NAME / "__init__.py"
    if not init.is_file():
        return None
    cached = sys.modules.get(_PRIVATE_MODULE)
    if cached is not None:
        cls = getattr(cached, "AnthropicProfile", None)
        return cls if isinstance(cls, type) else None
    snapshots = _snapshot_registries(providers)
    try:
        spec = importlib.util.spec_from_file_location(
            _PRIVATE_MODULE, init, submodule_search_locations=[str(init.parent)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[_PRIVATE_MODULE] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(_PRIVATE_MODULE, None)
        return None
    finally:
        _restore_registries(snapshots)
    cls = getattr(module, "AnthropicProfile", None)
    return cls if isinstance(cls, type) else None


def resolve_anthropic_base() -> GuardResult:
    """Locate the bundled Anthropic profile class without triggering provider discovery."""
    if "providers" not in sys.modules:
        try:
            import providers  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on host
            return GuardResult(False, f"Hermes 'providers' package is not importable ({type(exc).__name__}).")

    cls = _from_bundled_module() or _from_registry() or _from_bundled_dir()
    if cls is None:
        # Bundled discovery is lazy in Hermes; it has not run yet when a plugin is imported early
        # (for example by `hermes plugins validate`). It is idempotent, so run it and look again.
        discover = getattr(sys.modules.get("providers"), "_discover_providers", None)
        if callable(discover):
            try:
                discover()
            except Exception:
                pass
            cls = _from_bundled_module() or _from_registry() or _from_bundled_dir()
    if cls is None:
        return GuardResult(
            False,
            "bundled provider 'anthropic' (plugins/model-providers/anthropic) was not found; "
            f"{constants.PLUGIN_NAME} stays inactive until it is available.",
        )

    required = ("fetch_models",)
    missing = [attr for attr in required if not hasattr(cls, attr)]
    if missing:
        return GuardResult(
            False,
            f"bundled Anthropic profile no longer exposes {', '.join(missing)}; "
            f"this Hermes version is incompatible with {constants.PLUGIN_NAME}.",
        )
    return GuardResult(True, "bundled Anthropic provider found", cls)
