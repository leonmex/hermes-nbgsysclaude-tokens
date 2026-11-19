"""nbgsysclaude-tokens: Claude Pro/Max subscription tokens for Hermes (unofficial).

Loaded by Hermes's provider loader as a ``kind: model-provider`` plugin. Import-time behaviour:

1. Ask the guard for the bundled Anthropic provider class. If it is missing the plugin stays
   inert: it registers nothing, logs one warning, and never raises.
2. Otherwise build a profile that extends it and register it under its own name, leaving the
   bundled ``anthropic`` provider (and API-key users) untouched.
3. Register a redaction pattern so the token never reaches logs.
"""

from __future__ import annotations

import logging

from . import constants, guard

logger = logging.getLogger(__name__)

PROFILE = None
GUARD = guard.resolve_anthropic_base()


def _register_redaction() -> None:
    try:
        from agent.redact import register_redaction_patterns

        register_redaction_patterns([constants.TOKEN_REDACTION_PATTERN], source=f"plugin:{constants.PLUGIN_NAME}")
    except Exception as exc:  # redaction is best effort; never block provider registration
        logger.debug("%s: redaction pattern not registered: %s", constants.PLUGIN_NAME, exc)


def _activate() -> None:
    global PROFILE
    from providers import register_provider  # noqa: WPS433 - only importable inside Hermes

    from . import cli, profile

    PROFILE = profile.build_profile(GUARD.base_cls, auth_handler=cli.auth_handler)
    register_provider(PROFILE)
    _register_redaction()


if GUARD.ok:
    try:
        _activate()
    except Exception as exc:
        PROFILE = None
        logger.warning("%s: could not register provider (%s: %s); plugin inactive",
                       constants.PLUGIN_NAME, type(exc).__name__, exc)
else:
    logger.warning("%s: inactive - %s", constants.PLUGIN_NAME, GUARD.reason)
