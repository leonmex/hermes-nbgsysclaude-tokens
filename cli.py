"""Onboarding and diagnostics.

Model-provider plugins are imported by Hermes's provider loader and never receive `register(ctx)`,
so the user-facing commands hook in through the provider's `auth_handler`:

    hermes auth add     nbgsysclaude-tokens     # mint or paste a token, validate, save
    hermes auth status  nbgsysclaude-tokens     # live check
    hermes auth logout  nbgsysclaude-tokens     # remove the token

and the same functions are available as a standalone script (works inside the container too):

    python <plugin dir>/cli.py {login,status,doctor,logout}

Nothing here ever prints a token.
"""

from __future__ import annotations

if __name__ == "__main__" and not __package__:  # pragma: no cover - script mode
    # `python <plugin dir>/cli.py ...`: load the plugin as a package so relative imports work.
    import importlib
    import importlib.util
    import pathlib
    import sys as _sys

    _here = pathlib.Path(__file__).resolve().parent
    _spec = importlib.util.spec_from_file_location(
        "nbgsysclaude_tokens", _here / "__init__.py", submodule_search_locations=[str(_here)])
    _module = importlib.util.module_from_spec(_spec)
    _sys.modules["nbgsysclaude_tokens"] = _module
    _spec.loader.exec_module(_module)  # type: ignore[union-attr]
    raise SystemExit(importlib.import_module("nbgsysclaude_tokens.cli").main())

import argparse
import getpass
import sys
from types import SimpleNamespace
from typing import Any, List, Optional

from . import constants, guard, pty_login, token_store, validator

EXIT_OK, EXIT_WARN, EXIT_FAIL = 0, 1, 2


def _say(msg: str = "") -> None:
    print(msg, flush=True)


# ── login ────────────────────────────────────────────────────────────────────

def _obtain_token(method: Optional[str], use_stdin: bool, provided: Optional[str]) -> Optional[str]:
    if provided:
        return provided
    if use_stdin:
        return sys.stdin.read()
    if not sys.stdin or not sys.stdin.isatty():
        _say("No terminal available. Re-run with an allocated TTY "
             "(docker exec -it ...) or pipe the token with --stdin.")
        return None
    claude_bin = pty_login.find_claude_binary()
    if method is None:
        if claude_bin:
            answer = input("Mint a new token with the claude CLI (m) or paste an existing one (p)? [m/p] ")
            method = "paste" if answer.strip().lower().startswith("p") else "cli"
        else:
            _say("The `claude` CLI was not found, so the paste method is used.")
            method = "paste"
    if method == "paste":
        return getpass.getpass("Paste the token (input is hidden): ")
    _say(f"Running `claude setup-token` in a {constants.PTY_COLUMNS}-column terminal. "
         "Follow the browser steps; the token will be captured and hidden.")
    outcome = pty_login.run_setup_token(claude_bin)
    if outcome.error:
        _say(f"Login failed: {outcome.error}")
        return None
    return outcome.token


def validate_and_store(token: str, *, force: bool = False, timeout: float = 15.0,
                       opener: Any = None) -> int:
    shape = token_store.check_shape(token)
    for warning in shape.warnings:
        _say(f"WARN  {warning}")
    if not shape.ok:
        for problem in shape.problems:
            _say(f"FAIL  {problem}")
        return EXIT_FAIL

    _say(f"Validating {token_store.mask(token)} against {constants.MESSAGES_URL} ...")
    result = validator.probe_token(token, timeout=timeout, opener=opener)
    _say(f"      HTTP {result.http_status or '-'}: {result.status} - {result.message}")
    if result.retry_after:
        _say(f"      Retry-After: {result.retry_after}")

    if result.usable:
        path = token_store.save_token(token)
        token_store.record_minted()
        _say(f"Saved as {constants.TOKEN_ENV_VAR} in {path}.")
        _say("Restart the gateway so it picks the credential up "
             "(docker compose restart hermes-gateway), then select provider "
             f"'{constants.PROVIDER_NAME}'.")
        return EXIT_OK if result.status == validator.STATUS_VALID else EXIT_WARN
    if result.status in (validator.STATUS_NETWORK_ERROR, validator.STATUS_SERVER_ERROR) and force:
        token_store.save_token(token)
        token_store.record_minted()
        _say("Saved WITHOUT validation because --force was given.")
        return EXIT_WARN
    _say("Not saved." + (" Use --force to save anyway when the network is the problem."
                         if result.status in (validator.STATUS_NETWORK_ERROR,
                                              validator.STATUS_SERVER_ERROR) else ""))
    return EXIT_FAIL


def cmd_login(args: Any) -> int:
    provided = token_store.normalize_token(getattr(args, "token", None)) or None
    raw = _obtain_token(getattr(args, "method", None), bool(getattr(args, "stdin", False)), provided)
    token = token_store.normalize_token(raw)
    if not token:
        _say("No token received.")
        return EXIT_FAIL
    return validate_and_store(token, force=bool(getattr(args, "force", False)))


# ── status / doctor / logout ─────────────────────────────────────────────────

def cmd_status(args: Any) -> int:
    token = token_store.read_token()
    if not token:
        _say(f"{constants.TOKEN_ENV_VAR}: not set. Run `hermes auth add {constants.PROVIDER_NAME}`.")
        return EXIT_FAIL
    _say(f"{constants.TOKEN_ENV_VAR}: {token_store.mask(token)}")
    left = token_store.days_until_expiry()
    if left is not None:
        _say(f"Estimated days until expiry: {left}")
    if getattr(args, "offline", False):
        _say("Offline mode: token not validated.")
        return EXIT_OK
    result = validator.probe_token(token)
    _say(f"Live check: HTTP {result.http_status or '-'} {result.status} - {result.message}")
    if result.status == validator.STATUS_VALID:
        return EXIT_OK
    return EXIT_WARN if result.usable else EXIT_FAIL


def _line(level: str, msg: str) -> None:
    _say(f"[{level:^4}] {msg}")


def cmd_doctor(args: Any) -> int:
    worst = EXIT_OK

    def note(level: str, msg: str) -> None:
        nonlocal worst
        _line(level, msg)
        worst = max(worst, {"OK": EXIT_OK, "WARN": EXIT_WARN, "FAIL": EXIT_FAIL}[level])

    base = guard.resolve_anthropic_base()
    note("OK" if base.ok else "FAIL", base.reason)

    claude_bin = pty_login.find_claude_binary()
    note("OK" if claude_bin else "WARN",
         f"claude CLI: {claude_bin}" if claude_bin else
         "claude CLI not found (only needed to mint tokens; pasting works without it)")

    token = token_store.read_token()
    if not token:
        note("FAIL", f"{constants.TOKEN_ENV_VAR} is not set")
        return worst
    shape = token_store.check_shape(token)
    note("OK" if shape.ok else "FAIL", f"token: {token_store.mask(token)}")
    for problem in shape.problems:
        note("FAIL", problem)
    for warning in shape.warnings:
        note("WARN", warning)

    other = token_store.read_env_var("CLAUDE_CODE_OAUTH_TOKEN")
    if other and other == token:
        note("WARN", "the same token is also set as CLAUDE_CODE_OAUTH_TOKEN; "
                     "use one dedicated token per consumer so one can be revoked independently")

    left = token_store.days_until_expiry()
    if left is None:
        note("WARN", "mint date unknown (token not created through this plugin); cannot estimate expiry")
    elif left <= 0:
        note("FAIL", "token is past its expected one-year lifetime; mint a new one")
    elif left <= constants.TOKEN_WARN_BEFORE_DAYS:
        note("WARN", f"token expires in about {left} days")
    else:
        note("OK", f"about {left} days until expiry")

    if shape.ok and not getattr(args, "offline", False):
        result = validator.probe_token(token)
        level = "OK" if result.status == validator.STATUS_VALID else ("WARN" if result.usable else "FAIL")
        note(level, f"live check: HTTP {result.http_status or '-'} {result.status} - {result.message}")
    return worst


def cmd_logout(args: Any) -> int:
    removed = token_store.remove_token()
    token_store.clear_state()
    _say(f"{constants.TOKEN_ENV_VAR} removed." if removed else f"{constants.TOKEN_ENV_VAR} was not set.")
    _say("Restart the gateway for the change to take effect.")
    return EXIT_OK


# ── entry points ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=constants.PLUGIN_NAME,
                                     description="Claude subscription token onboarding for Hermes.")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login", help="mint or paste a token, validate it, save it")
    login.add_argument("--method", choices=("cli", "paste"))
    login.add_argument("--stdin", action="store_true", help="read the token from standard input")
    login.add_argument("--force", action="store_true", help="save even if the network check failed")
    status = sub.add_parser("status", help="show and live-check the stored token")
    status.add_argument("--offline", action="store_true")
    doctor = sub.add_parser("doctor", help="run all diagnostics")
    doctor.add_argument("--offline", action="store_true")
    sub.add_parser("logout", help="remove the stored token")
    return parser


_COMMANDS = {"login": cmd_login, "status": cmd_status, "doctor": cmd_doctor, "logout": cmd_logout}


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return _COMMANDS[args.command](args)


def auth_handler(action: str, args: Any) -> bool:
    """`hermes auth add|status|logout nbgsysclaude-tokens`. Returns True when the action was handled."""
    if action == "add":
        ns = SimpleNamespace(token=getattr(args, "api_key", None), method=None, stdin=False, force=False)
        code = cmd_login(ns)
    elif action == "status":
        code = cmd_status(SimpleNamespace(offline=False))
    elif action == "logout":
        code = cmd_logout(SimpleNamespace())
    else:
        return False  # no refresh: the token is long-lived
    if code == EXIT_FAIL:
        raise SystemExit(EXIT_FAIL)
    return True
