"""Token normalisation, shape checks, and storage in Hermes's .env (never logged or echoed)."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import constants

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_TOKEN_RUN_RE = re.compile(r"sk-ant-oat[A-Za-z0-9_\-]*")
_VALID_TOKEN_RE = re.compile(r"^sk-ant-oat\d{2}-[A-Za-z0-9_\-]+$")


# ── normalisation / shape ────────────────────────────────────────────────────

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def normalize_token(raw: Optional[str]) -> str:
    """Make a pasted value safe: drop whitespace/newlines (terminal wrapping), quotes, `KEY=` prefixes."""
    if not raw:
        return ""
    text = strip_ansi(raw)
    text = "".join(text.split())
    for prefix in (f"export{constants.TOKEN_ENV_VAR}=", f"{constants.TOKEN_ENV_VAR}=",
                   "exportCLAUDE_CODE_OAUTH_TOKEN=", "CLAUDE_CODE_OAUTH_TOKEN="):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.strip("'\"`")


def extract_token(text: str) -> Optional[str]:
    """Pull the longest token-looking run out of captured terminal output."""
    runs = _TOKEN_RUN_RE.findall(strip_ansi(text or ""))
    return max(runs, key=len) if runs else None


@dataclass
class ShapeCheck:
    ok: bool
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def check_shape(token: str) -> ShapeCheck:
    """Cheap offline checks. Only the live probe can prove a token works."""
    out = ShapeCheck(True)
    if not token:
        out.ok = False
        out.problems.append("empty token")
        return out
    if token.startswith("sk-ant-api"):
        out.ok = False
        out.problems.append("this is a pay-per-token API key (sk-ant-api...), not a subscription token "
                            "(sk-ant-oat01-...)")
        return out
    if not token.startswith(constants.TOKEN_PREFIX):
        out.ok = False
        out.problems.append(f"does not start with {constants.TOKEN_PREFIX}...")
        return out
    if not _VALID_TOKEN_RE.match(token):
        out.ok = False
        out.problems.append("contains characters that cannot occur in a token (stray whitespace or quotes?)")
        return out
    if len(token) < constants.TOKEN_SUSPECT_MIN_LEN:
        out.warnings.append(f"only {len(token)} characters; a full token is usually "
                            f"{constants.TOKEN_SUSPECT_MIN_LEN}+. It may have been truncated by terminal wrapping")
    return out


def mask(token: str) -> str:
    """Safe description of a token: the public prefix and the length, never any secret characters."""
    if not token:
        return "(none)"
    head = token[:13] if token.startswith(constants.TOKEN_PREFIX) else token[:4]
    return f"{head}... ({len(token)} chars)"


# ── Hermes paths / credential access ─────────────────────────────────────────

def hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def env_file() -> Path:
    try:
        from hermes_cli.config import get_env_path

        return Path(get_env_path())
    except Exception:
        return hermes_home() / ".env"


def read_env_var(name: str) -> str:
    """A credential from Hermes's scoped secret store (falls back to the process environment)."""
    try:
        from agent.secret_scope import get_secret_str

        return get_secret_str(name, "").strip()
    except Exception:
        return (os.environ.get(name) or "").strip()


def read_token() -> str:
    """Current NBGSYSCLAUDE_CODE_OAUTH_TOKEN value, or ''."""
    return read_env_var(constants.TOKEN_ENV_VAR)


def _fallback_write(path: Path, key: str, value: Optional[str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    keep = [ln for ln in lines if not re.match(rf"\s*(export\s+)?{re.escape(key)}\s*=", ln)]
    if value is not None:
        if keep and not keep[-1].endswith("\n"):
            keep[-1] += "\n"
        keep.append(f"{key}={value}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(keep), encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def save_token(token: str) -> Path:
    """Persist the token as NBGSYSCLAUDE_CODE_OAUTH_TOKEN in Hermes's .env."""
    try:
        from hermes_cli.config import save_env_value

        save_env_value(constants.TOKEN_ENV_VAR, token)
    except ImportError:
        _fallback_write(env_file(), constants.TOKEN_ENV_VAR, token)
    return env_file()


def remove_token() -> bool:
    removed = bool(read_token())
    try:
        from hermes_cli.config import remove_env_value

        remove_env_value(constants.TOKEN_ENV_VAR)
    except ImportError:
        _fallback_write(env_file(), constants.TOKEN_ENV_VAR, None)
    os.environ.pop(constants.TOKEN_ENV_VAR, None)
    return removed


# ── mint-date sidecar (no secrets) ───────────────────────────────────────────

def state_path() -> Path:
    return hermes_home() / constants.STATE_FILE_NAME


def record_minted(now: Optional[float] = None) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"minted_at": int(now if now is not None else time.time())}), encoding="utf-8")


def clear_state() -> None:
    try:
        state_path().unlink()
    except FileNotFoundError:
        pass


def minted_at() -> Optional[float]:
    try:
        data: Dict[str, Any] = json.loads(state_path().read_text(encoding="utf-8"))
        return float(data["minted_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def days_until_expiry(now: Optional[float] = None) -> Optional[int]:
    minted = minted_at()
    if minted is None:
        return None
    age_days = ((now if now is not None else time.time()) - minted) / 86400
    return int(constants.TOKEN_LIFETIME_DAYS - age_days)
