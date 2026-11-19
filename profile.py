"""The provider profile: the bundled Anthropic profile, specialised for subscription tokens.

The class is built at runtime from whatever base class the guard found, so upstream fixes to the
bundled profile flow through automatically and this plugin never copies its code.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional
from urllib.parse import urlencode

from . import constants, validator

logger = logging.getLogger(__name__)

_MAX_PAGES = 10


def _models_url(base_url: Optional[str], after_id: Optional[str]) -> str:
    root = (base_url or constants.BASE_URL).rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    query = {"limit": "100"}
    if after_id:
        query["after_id"] = after_id
    return f"{root}/v1/models?{urlencode(query)}"


def list_models(api_key: Optional[str], base_url: Optional[str] = None, timeout: float = 8.0,
                opener: Any = None) -> Optional[List[str]]:
    """Live model list using Bearer + beta headers (the inherited x-api-key call 401s for OAuth tokens)."""
    if not api_key:
        return None
    headers = validator.build_headers(api_key, json_body=False)
    models: List[str] = []
    cursor: Optional[str] = None
    seen = set()
    for _ in range(_MAX_PAGES):
        result = validator.request_json("GET", _models_url(base_url, cursor), headers,
                                        timeout=timeout, opener=opener)
        if result.status != 200 or result.body is None:
            logger.debug("%s model list failed: status=%s", constants.PLUGIN_NAME, result.status)
            return models or None
        data = result.body.get("data") or []
        models.extend(m["id"] for m in data if isinstance(m, dict) and "id" in m)
        cursor = result.body.get("last_id") if result.body.get("has_more") else None
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    return list(dict.fromkeys(models)) or None


def build_profile(base_cls: type, auth_handler: Any = None) -> Any:
    """Instantiate the subscription-token profile on top of the bundled Anthropic profile class."""

    class NbgsysClaudeTokensProfile(base_cls):  # type: ignore[misc, valid-type]
        def fetch_models(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None,
                         timeout: float = 8.0) -> Optional[List[str]]:
            try:
                return list_models(api_key, base_url, timeout)
            except Exception as exc:  # never break the model picker
                logger.debug("%s fetch_models: %s", constants.PLUGIN_NAME, exc)
                return None

    kwargs = dict(
        name=constants.PROVIDER_NAME,
        aliases=constants.PROVIDER_ALIASES,
        display_name=constants.DISPLAY_NAME,
        description="Claude via a Pro/Max subscription token (unofficial)",
        signup_url="https://claude.ai",
        api_mode="anthropic_messages",
        # Declared as api_key so Hermes reads the env var as the credential; the bundled adapter
        # then routes sk-ant-oat tokens down the OAuth path by prefix (Bearer + beta headers).
        auth_type="api_key",
        env_vars=(constants.TOKEN_ENV_VAR,),
        base_url=constants.BASE_URL,
        default_aux_model=constants.DEFAULT_AUX_MODEL,
        fallback_models=constants.FALLBACK_MODELS,
    )
    if auth_handler is not None:
        kwargs["auth_handler"] = auth_handler
    return NbgsysClaudeTokensProfile(**kwargs)
