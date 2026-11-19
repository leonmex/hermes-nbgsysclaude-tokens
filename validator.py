"""Live token validation against the real Anthropic Messages endpoint.

Hermes's "logged in" only means a credential-shaped string exists. The only proof a token works is
a real request, so this module sends a minimal one-token message and classifies the HTTP status:

    200  valid        token works
    429  throttled    token works, the plan's usage window is exhausted (NOT a bad token)
    401  invalid      token rejected (truncated, revoked, expired, or an API key)
    400  no_credit    an API key (sk-ant-api...) whose Console account has no credit
    ...

The token is never included in any returned message.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from . import constants

Opener = Callable[[urllib.request.Request, float], Any]

STATUS_VALID = "valid"
STATUS_THROTTLED = "throttled"
STATUS_INVALID = "invalid"
STATUS_FORBIDDEN = "forbidden"
STATUS_NO_CREDIT = "no_credit"
STATUS_EXTRA_USAGE = "extra_usage"
STATUS_REQUEST_ERROR = "request_error"
STATUS_SERVER_ERROR = "server_error"
STATUS_NETWORK_ERROR = "network_error"
STATUS_UNEXPECTED = "unexpected"

_USABLE = {STATUS_VALID, STATUS_THROTTLED}


@dataclass(frozen=True)
class ProbeResult:
    status: str
    http_status: Optional[int]
    message: str
    retry_after: Optional[str] = None

    @property
    def usable(self) -> bool:
        """True when the token authenticates (200 or 429)."""
        return self.status in _USABLE


@dataclass
class HttpResult:
    status: Optional[int]
    body: Optional[Dict[str, Any]]
    text: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None


# ── HTTP plumbing ────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: a credentialed request must not leave api.anthropic.com."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        return None


def default_open(req: urllib.request.Request, timeout: float) -> Any:
    try:
        from hermes_cli.urllib_security import open_credentialed_url
    except Exception:
        open_credentialed_url = None  # type: ignore[assignment]
    if open_credentialed_url is not None:
        return open_credentialed_url(req, timeout=timeout)
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)


def request_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
    *,
    timeout: float = 15.0,
    opener: Optional[Opener] = None,
) -> HttpResult:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    open_fn = opener or default_open
    try:
        with open_fn(req, timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            raw = resp.read(65536)
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read(65536) if hasattr(exc, "read") else b""
        hdrs = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return HttpResult(None, None, error=f"{type(exc).__name__}: {reason}")

    text = raw.decode("utf-8", errors="replace")
    body: Optional[Dict[str, Any]]
    try:
        parsed = json.loads(text)
        body = parsed if isinstance(parsed, dict) else None
    except ValueError:
        body = None
    return HttpResult(status, body, text, hdrs)


# ── headers / probe ──────────────────────────────────────────────────────────

def client_version() -> str:
    """Prefer the version the bundled adapter detected; Anthropic rejects stale OAuth user agents."""
    try:
        from agent.anthropic_adapter import _get_claude_code_version

        version = _get_claude_code_version()
        if version:
            return str(version)
    except Exception:
        pass
    return constants.FALLBACK_CLIENT_VERSION


def build_headers(token: str, *, json_body: bool = True) -> Dict[str, str]:
    """Headers Anthropic requires for an OAuth/subscription token (Bearer, not x-api-key)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-version": constants.ANTHROPIC_VERSION,
        "anthropic-beta": ",".join(constants.OAUTH_BETAS),
        "User-Agent": f"claude-code/{client_version()} (external, cli)",
        "Accept": "application/json",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "[token]") if token else text


def _api_message(result: HttpResult, token: str) -> str:
    err = (result.body or {}).get("error")
    msg = err.get("message") if isinstance(err, dict) else None
    return _scrub(str(msg or result.text or "").strip(), token)[:240]


def classify(result: HttpResult, token: str = "") -> ProbeResult:
    if result.status is None:
        return ProbeResult(STATUS_NETWORK_ERROR, None,
                           _scrub(result.error or "network error", token)[:240])
    code = result.status
    api_msg = _api_message(result, token)
    retry = result.headers.get("retry-after")
    if code == 200:
        return ProbeResult(STATUS_VALID, code, "token accepted")
    if code == 429:
        return ProbeResult(STATUS_THROTTLED, code,
                           "token is valid but the plan's usage window is exhausted; retry later", retry)
    if code == 401:
        return ProbeResult(STATUS_INVALID, code,
                           "token rejected (truncated, expired, revoked, or not a subscription token)")
    if code == 403:
        return ProbeResult(STATUS_FORBIDDEN, code, f"access forbidden: {api_msg}")
    if code == 400:
        low = api_msg.lower()
        if "credit balance" in low:
            return ProbeResult(STATUS_NO_CREDIT, code,
                               "this looks like a pay-per-token API key with no credit, "
                               "not a subscription token")
        if "extra usage" in low:
            return ProbeResult(STATUS_EXTRA_USAGE, code,
                               f"subscription token accepted but request hit the extra-usage lane: {api_msg}")
        return ProbeResult(STATUS_REQUEST_ERROR, code, f"request rejected: {api_msg}")
    if code == 404:
        return ProbeResult(STATUS_REQUEST_ERROR, code,
                           f"model not found for this plan; set {constants.PROBE_MODEL_ENV_VAR}: {api_msg}")
    if code >= 500:
        return ProbeResult(STATUS_SERVER_ERROR, code, "Anthropic API error or overloaded; try again")
    return ProbeResult(STATUS_UNEXPECTED, code, f"unexpected response: {api_msg}")


def probe_token(
    token: str,
    *,
    model: Optional[str] = None,
    timeout: float = 15.0,
    opener: Optional[Opener] = None,
) -> ProbeResult:
    """Send a one-token message with the OAuth headers and classify the outcome."""
    chosen = model or os.environ.get(constants.PROBE_MODEL_ENV_VAR) or constants.DEFAULT_PROBE_MODEL
    payload = {
        "model": chosen,
        "max_tokens": 1,
        "system": constants.CLIENT_IDENTITY_PREFIX,
        "messages": [{"role": "user", "content": "ping"}],
    }
    result = request_json("POST", constants.MESSAGES_URL, build_headers(token), payload,
                          timeout=timeout, opener=opener)
    return classify(result, token)
