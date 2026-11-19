import os
import stat
import sys
import textwrap

import pytest

from conftest import GOOD_TOKEN

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX only")


def fake_claude(tmp_path, body: str):
    script = tmp_path / "claude"
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def run(sub, claude, **kw):
    pl = sub("pty_login")
    r, w = os.pipe()
    outcome = pl.run_setup_token(claude, stdin_fd=-1, stdout_fd=w, timeout=20, **kw)
    os.close(w)
    shown = b""
    while True:
        chunk = os.read(r, 4096)
        if not chunk:
            break
        shown += chunk
    os.close(r)
    return outcome, shown.decode(errors="replace")


PRINT_WRAPPING_TOKEN = f"""
import os, sys
cols = os.get_terminal_size().columns
print("COLS=%d" % cols)
print("Visit https://example.invalid/oauth to log in")
token = "{GOOD_TOKEN}"
# Behave like a terminal UI: hard-wrap output at the terminal width.
for i in range(0, len(token), cols):
    print(token[i:i + cols])
print("Store this token securely.")
"""


def test_token_survives_because_pty_is_300_columns(sub, tmp_path):
    outcome, shown = run(sub, fake_claude(tmp_path, PRINT_WRAPPING_TOKEN))
    assert outcome.error is None
    assert outcome.token == GOOD_TOKEN
    assert "COLS=300" in shown


def test_narrow_terminal_would_have_truncated_the_token(sub, tmp_path):
    """Regression for the 79-character token: at 80 columns the output wraps and extraction is short."""
    outcome, _ = run(sub, fake_claude(tmp_path, PRINT_WRAPPING_TOKEN), cols=80)
    ts = sub("token_store")
    assert outcome.token is not None and len(outcome.token) < len(GOOD_TOKEN)
    assert ts.check_shape(outcome.token).warnings  # and the shape check flags it


def test_token_is_never_shown_to_the_user(sub, tmp_path):
    outcome, shown = run(sub, fake_claude(tmp_path, PRINT_WRAPPING_TOKEN))
    assert GOOD_TOKEN[13:40] not in shown
    assert "sk-ant-oat" not in shown
    assert "[token captured and hidden]" in shown
    assert "https://example.invalid/oauth" in shown  # the login URL stays visible


def test_missing_cli_reports_clear_error(sub, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    pl = sub("pty_login")
    outcome = pl.run_setup_token(None, stdin_fd=-1)
    assert outcome.token is None and "npm install" in outcome.error


def test_no_token_in_output_is_an_error(sub, tmp_path):
    outcome, _ = run(sub, fake_claude(tmp_path, "print('login cancelled')\n"))
    assert outcome.token is None and "no token" in outcome.error


def test_child_does_not_inherit_existing_tokens(sub, tmp_path, monkeypatch):
    monkeypatch.setenv("NBGSYSCLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", GOOD_TOKEN)
    script = """
        import os
        print("LEAK" if os.environ.get("NBGSYSCLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") else "CLEAN")
    """
    _, shown = run(sub, fake_claude(tmp_path, script))
    assert "CLEAN" in shown


def test_output_gate_hides_marker_split_across_chunks(sub):
    gate = sub("pty_login").OutputGate()
    shown = gate.feed(b"token: sk-ant")
    shown += gate.feed(b"-oat01-SECRETPART")
    shown += gate.feed(b"MORESECRET\r\n")
    assert b"SECRET" not in shown and b"oat01" not in shown and b"sk-ant" not in shown
    assert shown == b"token: " and gate.hidden


def test_output_gate_releases_held_chunk_when_not_a_token(sub):
    gate = sub("pty_login").OutputGate()
    shown = gate.feed(b"see sk-an")  # ends like a marker prefix: held back
    shown += gate.feed(b"other words here")
    assert shown == b"see sk-another words here" and not gate.hidden
