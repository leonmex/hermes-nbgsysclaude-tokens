import os
from types import SimpleNamespace

import pytest

from conftest import GOOD_TOKEN, make_opener

API_KEY = "sk-ant-api03-" + "x" * 90


def env_text(home):
    path = home / ".env"
    return path.read_text() if path.exists() else ""


def test_valid_token_is_saved(sub, hermes_home, capsys):
    cli = sub("cli")
    code = cli.validate_and_store(GOOD_TOKEN, opener=make_opener(200, {}))
    assert code == cli.EXIT_OK
    assert f"NBGSYSCLAUDE_CODE_OAUTH_TOKEN={GOOD_TOKEN}" in env_text(hermes_home)
    assert sub("token_store").days_until_expiry() >= 364


def test_throttled_token_is_saved_with_warning_exit(sub, hermes_home):
    cli = sub("cli")
    code = cli.validate_and_store(GOOD_TOKEN, opener=make_opener(429, {"error": {"message": "slow"}}))
    assert code == cli.EXIT_WARN
    assert GOOD_TOKEN in env_text(hermes_home)


def test_invalid_token_is_not_saved(sub, hermes_home):
    cli = sub("cli")
    code = cli.validate_and_store(GOOD_TOKEN, opener=make_opener(401, {"error": {"message": "bad"}}))
    assert code == cli.EXIT_FAIL
    assert GOOD_TOKEN not in env_text(hermes_home)


def test_api_key_rejected_without_any_network_call(sub, hermes_home):
    cli = sub("cli")

    def must_not_be_called(req, timeout):
        raise AssertionError("network used for an obviously wrong credential")

    assert cli.validate_and_store(API_KEY, opener=must_not_be_called) == cli.EXIT_FAIL


def test_network_failure_needs_force(sub, hermes_home):
    import urllib.error
    cli = sub("cli")

    def down(req, timeout):
        raise urllib.error.URLError("offline")

    assert cli.validate_and_store(GOOD_TOKEN, opener=down) == cli.EXIT_FAIL
    assert GOOD_TOKEN not in env_text(hermes_home)
    assert cli.validate_and_store(GOOD_TOKEN, force=True, opener=down) == cli.EXIT_WARN
    assert GOOD_TOKEN in env_text(hermes_home)


def test_token_never_printed(sub, hermes_home, capsys, caplog):
    cli = sub("cli")
    cli.validate_and_store(GOOD_TOKEN, opener=make_opener(200, {}))
    cli.validate_and_store(GOOD_TOKEN, opener=make_opener(401, {"error": {"message": GOOD_TOKEN}}))
    seen = capsys.readouterr()
    assert GOOD_TOKEN not in seen.out + seen.err + caplog.text


def test_login_accepts_wrapped_paste_via_token_arg(sub, hermes_home, monkeypatch):
    cli = sub("cli")
    validator = sub("validator")
    monkeypatch.setattr(validator, "default_open", make_opener(200, {}))
    wrapped = GOOD_TOKEN[:50] + "\n" + GOOD_TOKEN[50:]
    assert cli.cmd_login(SimpleNamespace(token=wrapped, method=None, stdin=False, force=False)) == cli.EXIT_OK
    assert f"={GOOD_TOKEN}" in env_text(hermes_home)


def test_login_without_terminal_explains_how_to_proceed(sub, hermes_home, capsys, monkeypatch):
    cli = sub("cli")
    monkeypatch.setattr("sys.stdin", open(os.devnull))
    code = cli.cmd_login(SimpleNamespace(token=None, method=None, stdin=False, force=False))
    assert code == cli.EXIT_FAIL and "docker exec -it" in capsys.readouterr().out


def test_status_without_token_fails(sub, hermes_home, capsys):
    cli = sub("cli")
    assert cli.cmd_status(SimpleNamespace(offline=True)) == cli.EXIT_FAIL


def test_status_live_check(sub, hermes_home, monkeypatch, capsys):
    cli, validator = sub("cli"), sub("validator")
    monkeypatch.setenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    monkeypatch.setattr(validator, "default_open", make_opener(200, {}))
    assert cli.cmd_status(SimpleNamespace(offline=False)) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "valid" in out and GOOD_TOKEN not in out


def test_doctor_reports_each_failure_class(sub, hermes_home, monkeypatch, capsys):
    cli, validator = sub("cli"), sub("validator")
    assert cli.cmd_doctor(SimpleNamespace(offline=True)) == cli.EXIT_FAIL  # no token
    monkeypatch.setenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    monkeypatch.setattr(validator, "default_open", make_opener(401, {"error": {"message": "x"}}))
    assert cli.cmd_doctor(SimpleNamespace(offline=False)) == cli.EXIT_FAIL
    monkeypatch.setattr(validator, "default_open", make_opener(429, {}))
    assert cli.cmd_doctor(SimpleNamespace(offline=False)) == cli.EXIT_WARN
    out = capsys.readouterr().out
    assert "throttled" in out and GOOD_TOKEN not in out


def test_doctor_warns_when_token_is_shared_with_bundled_provider(sub, hermes_home, monkeypatch, capsys):
    cli, validator = sub("cli"), sub("validator")
    monkeypatch.setenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    monkeypatch.setattr(validator, "default_open", make_opener(200, {}))
    cli.cmd_doctor(SimpleNamespace(offline=False))
    assert "one dedicated token per consumer" in capsys.readouterr().out


def test_doctor_flags_expired_token(sub, hermes_home, monkeypatch, capsys):
    cli, ts = sub("cli"), sub("token_store")
    monkeypatch.setenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    ts.record_minted(now=1)  # ancient
    assert cli.cmd_doctor(SimpleNamespace(offline=True)) == cli.EXIT_FAIL
    assert "one-year lifetime" in capsys.readouterr().out


def test_logout_removes_token_and_state(sub, hermes_home, monkeypatch):
    cli, ts = sub("cli"), sub("token_store")
    ts.save_token(GOOD_TOKEN)
    ts.record_minted()
    monkeypatch.setenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    assert cli.cmd_logout(SimpleNamespace()) == cli.EXIT_OK
    assert GOOD_TOKEN not in env_text(hermes_home) and ts.minted_at() is None


def test_auth_handler_contract(sub, hermes_home, monkeypatch):
    cli, validator = sub("cli"), sub("validator")
    assert cli.auth_handler("refresh", SimpleNamespace()) is False  # long-lived token: nothing to refresh
    monkeypatch.setattr(validator, "default_open", make_opener(200, {}))
    assert cli.auth_handler("add", SimpleNamespace(api_key=GOOD_TOKEN)) is True
    monkeypatch.setenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    assert cli.auth_handler("status", SimpleNamespace()) is True
    monkeypatch.setattr(validator, "default_open", make_opener(401, {"error": {"message": "x"}}))
    with pytest.raises(SystemExit) as exc:
        cli.auth_handler("add", SimpleNamespace(api_key=GOOD_TOKEN))
    assert exc.value.code == cli.EXIT_FAIL


def test_parser_exposes_all_commands(sub):
    cli = sub("cli")
    for cmd in ("login", "status", "doctor", "logout"):
        assert cli.build_parser().parse_args([cmd]).command == cmd
