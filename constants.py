"""Single source of truth for every name and protocol constant in this plugin.

Brand-sensitive names (plugin, provider, env var) live here so renaming is a one-file change.
Protocol strings (URLs, beta headers) must match what the Anthropic API expects verbatim.
"""

from __future__ import annotations

PLUGIN_NAME = "nbgsysclaude-tokens"
PROVIDER_NAME = "nbgsysclaude-tokens"
# Deliberately does NOT reuse "claude" / "claude-code": those belong to the bundled provider
# and register_provider() is last-writer-wins.
PROVIDER_ALIASES = ("nbgsysclaude", "nbgsysclaude-sub")
DISPLAY_NAME = "Claude subscription (nbgsys)"

# The credential this plugin owns. Intentionally different from CLAUDE_CODE_OAUTH_TOKEN so it never
# shadows the bundled provider's credential and is never picked up by an unrelated `claude` run.
TOKEN_ENV_VAR = "NBGSYSCLAUDE_CODE_OAUTH_TOKEN"
CLAUDE_BIN_ENV_VAR = "NBGSYSCLAUDE_CLAUDE_BIN"
PROBE_MODEL_ENV_VAR = "NBGSYSCLAUDE_PROBE_MODEL"

# Bundled provider this plugin extends.
BASE_PROVIDER_NAME = "anthropic"
BASE_PLUGIN_ID = "anthropic-provider"

# Anthropic API (protocol, verbatim).
BASE_URL = "https://api.anthropic.com"
MESSAGES_URL = BASE_URL + "/v1/messages"
MODELS_URL = BASE_URL + "/v1/models"
ANTHROPIC_VERSION = "2023-06-01"
OAUTH_BETAS = ("claude-code-20250219", "oauth-2025-04-20")
# Fallback only; the bundled adapter's detected version is preferred when importable.
FALLBACK_CLIENT_VERSION = "2.1.74"
CLIENT_IDENTITY_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."

DEFAULT_PROBE_MODEL = "claude-haiku-4-5"
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5")
DEFAULT_AUX_MODEL = "claude-haiku-4-5-20251001"

# Token shape. `claude setup-token` yields sk-ant-oat01-... of roughly 100+ characters.
TOKEN_PREFIX = "sk-ant-oat"
TOKEN_BODY_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
TOKEN_SUSPECT_MIN_LEN = 100  # shorter is almost certainly a truncated paste (a 79-char one was seen)
TOKEN_REDACTION_PATTERN = r"sk-ant-oat\d{2}-[A-Za-z0-9_\-]{20,}"

# Lifetime handling: the token is long-lived (~1 year), so there is no refresh, only warnings.
TOKEN_LIFETIME_DAYS = 365
TOKEN_WARN_BEFORE_DAYS = 30
STATE_FILE_NAME = "nbgsysclaude-tokens.state.json"

# Terminal geometry for `claude setup-token`. Wide enough that a 100+ character token never wraps.
PTY_COLUMNS = 300
PTY_ROWS = 50
PTY_TIMEOUT_SECONDS = 900
