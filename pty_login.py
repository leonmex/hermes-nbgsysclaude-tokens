"""Drive `claude setup-token` under a pseudo-terminal that is wide enough never to wrap the token.

Why a pty: the CLI renders nothing without a TTY. Why 300 columns: a ~110 character token wrapped
on an 80-column terminal silently loses characters when copied, producing a token that Hermes
reports as "logged in" but Anthropic rejects with 401.

The user's keystrokes are relayed to the CLI so they can complete the browser login. Once the token
appears in the CLI output it is captured and withheld from the user's screen.
"""

from __future__ import annotations

import errno
import fcntl
import os
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import List, Optional

from . import constants, token_store

_MARKER = constants.TOKEN_PREFIX  # "sk-ant-oat"
_MIN_PARTIAL = 5


@dataclass
class LoginOutcome:
    token: Optional[str]
    error: Optional[str] = None


def find_claude_binary() -> Optional[str]:
    override = os.environ.get(constants.CLAUDE_BIN_ENV_VAR)
    if override and os.access(override, os.X_OK):
        return override
    return shutil.which("claude")


class OutputGate:
    """Relays CLI output to the user but never lets the token reach the screen.

    Chunks that might be the beginning of a token (the marker, or a trailing partial marker split
    across reads) are held back; once the marker is confirmed everything after it is suppressed.
    """

    def __init__(self) -> None:
        self.clean = ""
        self._held: List[str] = []
        self.hidden = False

    def _ends_with_partial_marker(self) -> bool:
        tail = self.clean[-(len(_MARKER) - 1):]
        return any(len(tail[-n:]) >= _MIN_PARTIAL and _MARKER.startswith(tail[-n:])
                   for n in range(_MIN_PARTIAL, len(tail) + 1))

    def feed(self, chunk: bytes) -> bytes:
        text = chunk.decode("utf-8", errors="replace")
        self.clean += token_store.strip_ansi(text)
        if self.hidden:
            return b""
        pending = "".join(self._held) + text
        if _MARKER in self.clean:
            self.hidden = True
            self._held.clear()
            idx = pending.find(_MARKER)
            # Show whatever precedes the token (e.g. the login URL); hide the token and all after it.
            return pending[:idx].encode("utf-8") if idx >= 0 else b""
        if self._ends_with_partial_marker():
            self._held.append(text)
            return b""
        self._held.clear()
        return pending.encode("utf-8")


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _child_env() -> dict:
    env = dict(os.environ)
    for key in (constants.TOKEN_ENV_VAR, "CLAUDE_CODE_OAUTH_TOKEN"):
        env.pop(key, None)  # setup-token must mint a fresh token, not reuse one
    env["TERM"] = env.get("TERM") or "xterm-256color"
    env["COLUMNS"] = str(constants.PTY_COLUMNS)
    env["LINES"] = str(constants.PTY_ROWS)
    return env


def run_setup_token(
    claude_bin: Optional[str] = None,
    *,
    cols: int = constants.PTY_COLUMNS,
    rows: int = constants.PTY_ROWS,
    timeout: float = constants.PTY_TIMEOUT_SECONDS,
    stdin_fd: Optional[int] = None,
    stdout_fd: int = 1,
    args: Optional[List[str]] = None,
) -> LoginOutcome:
    """Run `claude setup-token` in a wide pty and return the minted token."""
    binary = claude_bin or find_claude_binary()
    if not binary:
        return LoginOutcome(None, "the `claude` CLI was not found. Install it "
                                  "(npm install -g @anthropic-ai/claude-code), set "
                                  f"{constants.CLAUDE_BIN_ENV_VAR}, or use the paste method.")
    if stdin_fd is None:
        stdin_fd = sys.stdin.fileno() if sys.stdin and sys.stdin.isatty() else -1

    master, slave = os.openpty()
    _set_winsize(slave, rows, cols)
    try:
        proc = subprocess.Popen(
            [binary, *(args if args is not None else ["setup-token"])],
            stdin=slave, stdout=slave, stderr=slave,
            env=_child_env(), start_new_session=True, close_fds=True,
        )
    except OSError as exc:
        os.close(master)
        os.close(slave)
        return LoginOutcome(None, f"could not start {binary}: {exc}")
    os.close(slave)

    relay_input = stdin_fd >= 0 and os.isatty(stdin_fd)
    saved = termios.tcgetattr(stdin_fd) if relay_input else None
    gate = OutputGate()
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        if relay_input:
            tty.setcbreak(stdin_fd)
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                break
            watch = [master] + ([stdin_fd] if relay_input else [])
            ready, _, _ = select.select(watch, [], [], 0.2)
            if master in ready:
                try:
                    data = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:  # child closed its side
                        break
                    raise
                if not data:
                    break
                shown = gate.feed(data)
                if shown:
                    os.write(stdout_fd, shown)
            if relay_input and stdin_fd in ready:
                typed = os.read(stdin_fd, 1024)
                if typed:
                    os.write(master, typed)
            if proc.poll() is not None and master not in ready:
                break
    finally:
        if saved is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved)
        os.close(master)
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if timed_out:
        return LoginOutcome(None, f"timed out after {int(timeout)}s waiting for `claude setup-token`")
    token = token_store.extract_token(gate.clean)
    if gate.hidden:
        os.write(stdout_fd, b"\r\n[token captured and hidden]\r\n")
    if not token:
        return LoginOutcome(None, "no token appeared in the CLI output (login not completed?)")
    return LoginOutcome(token)
