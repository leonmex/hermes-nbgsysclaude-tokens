import os
import stat

from conftest import GOOD_TOKEN


def test_normalize_joins_wrapped_token(sub):
    ts = sub("token_store")
    wrapped = GOOD_TOKEN[:80] + "\r\n" + GOOD_TOKEN[80:] + "\n"
    assert ts.normalize_token(wrapped) == GOOD_TOKEN


def test_normalize_strips_assignment_and_quotes(sub):
    ts = sub("token_store")
    assert ts.normalize_token(f'export NBGSYSCLAUDE_CODE_OAUTH_TOKEN="{GOOD_TOKEN}"') == GOOD_TOKEN
    assert ts.normalize_token(f"CLAUDE_CODE_OAUTH_TOKEN={GOOD_TOKEN}") == GOOD_TOKEN
    assert ts.normalize_token(None) == ""


def test_shape_accepts_full_token(sub):
    check = sub("token_store").check_shape(GOOD_TOKEN)
    assert check.ok and not check.warnings


def test_shape_rejects_api_key_with_clear_reason(sub):
    check = sub("token_store").check_shape("sk-ant-api03-" + "x" * 90)
    assert not check.ok and "API key" in check.problems[0]


def test_shape_rejects_wrong_prefix_and_empty(sub):
    ts = sub("token_store")
    assert not ts.check_shape("hello").ok
    assert not ts.check_shape("").ok
    assert not ts.check_shape("sk-ant-oat01-abc def").ok


def test_shape_warns_on_truncated_token(sub):
    check = sub("token_store").check_shape(GOOD_TOKEN[:79])
    assert check.ok and any("truncated" in w for w in check.warnings)


def test_mask_never_reveals_secret_characters(sub):
    masked = sub("token_store").mask(GOOD_TOKEN)
    assert GOOD_TOKEN[13:] not in masked and "108 chars" in masked
    assert GOOD_TOKEN[-6:] not in masked


def test_extract_picks_longest_run_ignoring_ansi(sub):
    ts = sub("token_store")
    out = f"\x1b[32mYour token:\x1b[0m {GOOD_TOKEN}\r\nStore it. sk-ant-oat01-short"
    assert ts.extract_token(out) == GOOD_TOKEN
    assert ts.extract_token("nothing here") is None


def test_save_read_remove_roundtrip(sub, hermes_home):
    ts = sub("token_store")
    env = hermes_home / ".env"
    env.write_text("OTHER=keep\n")
    ts.save_token(GOOD_TOKEN)
    content = env.read_text()
    assert "OTHER=keep" in content and f"NBGSYSCLAUDE_CODE_OAUTH_TOKEN={GOOD_TOKEN}" in content
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600
    os.environ["NBGSYSCLAUDE_CODE_OAUTH_TOKEN"] = GOOD_TOKEN
    assert ts.read_token() == GOOD_TOKEN
    ts.save_token(GOOD_TOKEN)  # idempotent: still exactly one line
    assert env.read_text().count("NBGSYSCLAUDE_CODE_OAUTH_TOKEN=") == 1
    assert ts.remove_token() is True
    assert "NBGSYSCLAUDE_CODE_OAUTH_TOKEN" not in env.read_text()
    assert "OTHER=keep" in env.read_text()


def test_expiry_estimate(sub, hermes_home):
    ts = sub("token_store")
    assert ts.days_until_expiry() is None
    ts.record_minted(now=1_000_000)
    assert ts.days_until_expiry(now=1_000_000 + 100 * 86400) == 265
    assert ts.days_until_expiry(now=1_000_000 + 400 * 86400) < 0
    ts.clear_state()
    assert ts.minted_at() is None
