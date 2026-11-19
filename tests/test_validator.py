import urllib.error

from conftest import GOOD_TOKEN, make_opener


def probe(sub, status, body=b"", headers=None, **kw):
    calls = []
    v = sub("validator")
    result = v.probe_token(GOOD_TOKEN, opener=make_opener(status, body, headers, calls), **kw)
    return result, calls


def err(msg):
    return {"type": "error", "error": {"type": "x", "message": msg}}


def test_200_is_valid(sub):
    result, _ = probe(sub, 200, {"content": []})
    assert result.status == "valid" and result.usable


def test_429_is_throttled_but_usable(sub):
    result, _ = probe(sub, 429, err("rate limited"), {"retry-after": "120"})
    assert result.status == "throttled" and result.usable
    assert result.retry_after == "120"


def test_401_is_invalid(sub):
    result, _ = probe(sub, 401, err("OAuth access token is invalid."))
    assert result.status == "invalid" and not result.usable


def test_400_credit_balance_means_api_key_without_credit(sub):
    result, _ = probe(sub, 400, err("Your credit balance is too low to access the Anthropic API"))
    assert result.status == "no_credit" and not result.usable


def test_400_extra_usage_lane(sub):
    result, _ = probe(sub, 400, err("You're out of extra usage"))
    assert result.status == "extra_usage"


def test_400_other_is_request_error(sub):
    result, _ = probe(sub, 400, err("max_tokens: invalid"))
    assert result.status == "request_error" and "max_tokens" in result.message


def test_403_forbidden(sub):
    assert probe(sub, 403, err("nope"))[0].status == "forbidden"


def test_404_points_to_probe_model_setting(sub):
    result, _ = probe(sub, 404, err("model not found"))
    assert result.status == "request_error" and "NBGSYSCLAUDE_PROBE_MODEL" in result.message


def test_5xx_is_server_error(sub):
    assert probe(sub, 529, err("overloaded"))[0].status == "server_error"
    assert probe(sub, 500, b"")[0].status == "server_error"


def test_network_error(sub):
    v = sub("validator")

    def boom(req, timeout):
        raise urllib.error.URLError("dns failure")

    result = v.probe_token(GOOD_TOKEN, opener=boom)
    assert result.status == "network_error" and result.http_status is None and not result.usable


def test_token_never_appears_in_result(sub):
    result, _ = probe(sub, 400, err(f"bad value {GOOD_TOKEN} supplied"))
    assert GOOD_TOKEN not in result.message


def test_request_uses_bearer_and_oauth_betas_not_api_key(sub):
    _, calls = probe(sub, 200, {})
    req = calls[0]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["authorization"] == f"Bearer {GOOD_TOKEN}"
    assert headers["anthropic-beta"] == "claude-code-20250219,oauth-2025-04-20"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["user-agent"].startswith("claude-code/")
    assert "x-api-key" not in headers
    assert req.full_url == "https://api.anthropic.com/v1/messages"
    assert req.get_method() == "POST"


def test_payload_is_minimal(sub):
    import json
    _, calls = probe(sub, 200, {})
    payload = json.loads(calls[0].data)
    assert payload["max_tokens"] == 1
    assert payload["messages"] == [{"role": "user", "content": "ping"}]


def test_probe_model_env_override(sub, monkeypatch):
    import json
    monkeypatch.setenv("NBGSYSCLAUDE_PROBE_MODEL", "claude-custom")
    _, calls = probe(sub, 200, {})
    assert json.loads(calls[0].data)["model"] == "claude-custom"


def test_redirects_are_never_followed(sub):
    v = sub("validator")
    assert v._NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://evil") is None
