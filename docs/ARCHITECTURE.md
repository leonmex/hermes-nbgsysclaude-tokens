# Architecture

## Why a separate provider instead of editing the bundled one

The bundled `anthropic` provider already accepts OAuth tokens: its adapter sends `Authorization: Bearer`,
the `claude-code-20250219` and `oauth-2025-04-20` beta headers, and a `claude-code/<version>` user agent,
choosing the OAuth path from the token prefix (`sk-ant-oat`). Re-implementing that would duplicate code
and, because provider registration is last-writer-wins, could override it for API-key users.

So this plugin registers a **second profile** under its own name and aliases and leaves `anthropic`,
`claude`, `claude-oauth` and `claude-code` alone.

## Load sequence

```
Hermes imports the plugin directory (kind: model-provider)
  __init__.py
    guard.resolve_anthropic_base()      locate the bundled AnthropicProfile class
        1. sys.modules  "plugins.model_providers.anthropic"
        2. providers._REGISTRY["anthropic"]
        3. the bundled directory, imported with registration suppressed
        4. providers._discover_providers(), then 1-3 again
        none found -> inert: log one warning, register nothing, never raise
    profile.build_profile(base_cls)      subclass it at runtime
    providers.register_provider(...)     register "nbgsysclaude-tokens"
    agent.redact.register_redaction_patterns(...)
```

Step 3 exists because Hermes can import user plugins *during* bundled discovery (an earlier bundled
provider imports `hermes_cli.config`, which scans user plugins). At that moment `anthropic` is not
registered yet, so steps 1 and 2 find nothing. The bundled file is therefore loaded under a private
module name with its `register_provider` call neutralised, which yields the real class without creating a
second `anthropic` profile.

The subclass is built at runtime from whatever class was found, so fixes to the bundled profile flow
through without copying its code.

## What the profile overrides

| Field | Value | Why |
|---|---|---|
| `name`, `aliases` | `nbgsysclaude-tokens`, `nbgsysclaude`, `nbgsysclaude-sub` | Never reuse the bundled names |
| `env_vars` | `NBGSYSCLAUDE_CODE_OAUTH_TOKEN` | Own credential; cannot shadow `CLAUDE_CODE_OAUTH_TOKEN` and is not read by an unrelated `claude` run |
| `auth_type` | `api_key` | Makes Hermes read the env var as the credential. The adapter still routes `sk-ant-oat` tokens down the OAuth path by prefix |
| `fetch_models` | Bearer + beta headers | The inherited call sends `x-api-key`, which returns 401 for OAuth tokens |
| `auth_handler` | `cli.auth_handler` | Powers `hermes auth add|status|logout` |

## Why there is no `hermes nbgsysclaude-tokens` command

Hermes imports `kind: model-provider` plugins itself and never calls `register(ctx)` on them, so
`ctx.register_cli_command`, slash commands and tools are unavailable. The supported hook for a provider's
own login is `ProviderProfile.auth_handler`, which is what `hermes auth add|status|logout` call. The same
functions are exposed as `cli.py` for diagnostics (`doctor`) that have no `hermes auth` verb.

## Modules

| File | Responsibility |
|---|---|
| `constants.py` | Every name and protocol string, in one place |
| `guard.py` | Find the bundled Anthropic class, or stay inert |
| `profile.py` | Build the profile; live model list |
| `validator.py` | The one-token probe and HTTP status classification |
| `token_store.py` | Normalise, shape-check, read, save, remove; mint-date sidecar |
| `pty_login.py` | `claude setup-token` in a 300-column pty; output gate that hides the token |
| `cli.py` | `login`, `status`, `doctor`, `logout`; `auth_handler`; script entry point |

## Security properties (each has tests)

- The token never appears in output, logs, or exception messages.
- Credentials are never forwarded across origins (redirects are not followed with the token attached).
- The child `claude` process starts without any token in its environment.
- A wrong credential type (API key) is rejected without any network call.
- A failed registration or missing dependency never breaks Hermes provider discovery.
