# hermes-nbgsysclaude-tokens

Use your **Claude Pro / Max subscription** with [Hermes Agent](https://github.com/NousResearch/hermes-agent)
through a long-lived Claude Code OAuth token (`sk-ant-oat01-...`), instead of paying per token with an
Anthropic API key.

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by Anthropic or Nous
> Research. "Claude" and "Anthropic" are trademarks of their owners. See
> [Account boundaries and terms](#account-boundaries-and-terms) before using it.

## What it does

Hermes already knows how to talk to Anthropic with an OAuth token. What it does not do is help you
*get* a working token or tell you when it is broken. This plugin adds that.

| Problem you hit without it | What this plugin does |
|---|---|
| `claude setup-token` prints nothing without a TTY | Drives it in a pseudo-terminal for you |
| The ~110 character token wraps on a narrow terminal and is silently truncated, so every call returns 401 | Runs the CLI in a **300-column** terminal and strips stray whitespace from pasted tokens |
| `hermes auth status` says "logged in" for a dead token | Validates against the real API before saving and on every `status` |
| 401 and 429 look alike | Tells them apart: 401 means a bad token, 429 means a good token whose plan window is used up |
| An API key with no credit looks like a Claude failure | Detects "credit balance too low" and says you pasted an API key |
| Tokens expire silently after about a year | Records the mint date and warns 30 days ahead |

It registers its own provider, `nbgsysclaude-tokens` (aliases `nbgsysclaude`, `nbgsysclaude-sub`),
built on top of the **bundled `anthropic` provider**. The bundled provider, its aliases (`claude`,
`claude-code`) and your API-key setup are never modified, so you can switch between a subscription
token and an API key at will.

## Requirements

- Hermes Agent 0.21 or newer (the bundled `anthropic` provider must be present; otherwise the plugin
  stays inactive and logs why).
- A Claude Pro or Max subscription.
- To mint a token: the `claude` CLI (`npm install -g @anthropic-ai/claude-code`). Pasting an existing
  token works without it.

No Python dependencies. The plugin uses only the standard library and modules Hermes provides.

## Install

```bash
hermes plugins install leonmex/hermes-nbgsysclaude-tokens --enable
```

Inside a Docker deployment:

```bash
docker exec -u hermes hermes-gateway hermes plugins install leonmex/hermes-nbgsysclaude-tokens --enable
```

This installs straight from GitHub (an "unreviewed source" in Hermes terms) and works before, and
independently of, any listing in the official catalog. Use `hermes plugins disable nbgsysclaude-tokens`
to turn it off and `hermes plugins update nbgsysclaude-tokens` to update.

If the plugin is installed on the image's filesystem instead of the data volume, an image update will
drop it. See [docs/DOCKER.md](docs/DOCKER.md) for a start-up hook that reinstalls it automatically.

## Log in

Hermes calls the provider's own login for `hermes auth`:

```bash
hermes auth add nbgsysclaude-tokens        # mint a token or paste one, validate, save
hermes auth status nbgsysclaude-tokens     # live check against the API
hermes auth logout nbgsysclaude-tokens     # remove it
```

In a container you need a real terminal, so use `-it`:

```bash
docker exec -it -u hermes hermes-gateway hermes auth add nbgsysclaude-tokens
```

`add` offers two ways in:

1. **Mint** runs `claude setup-token` for you. Open the printed URL, sign in, paste the code back. The
   token is captured and **never shown on your screen**.
2. **Paste** an existing token (input is hidden). Line breaks and quotes are removed automatically.

Before anything is saved, the token is checked with a one-token request to
`https://api.anthropic.com/v1/messages`:

| HTTP | Meaning | Saved? |
|---|---|---|
| 200 | Token works | yes |
| 429 | Token works, your plan is currently throttled | yes, with a warning |
| 401 | Token rejected (truncated, revoked, expired) | no |
| 400 "credit balance" | You pasted a pay-per-token API key | no |
| network / 5xx | Could not decide | no, unless `--force` |

The value is stored as `NBGSYSCLAUDE_CODE_OAUTH_TOKEN` in Hermes's `.env` (file mode 600).
**Restart the gateway afterwards**, because Hermes reads `.env` at start-up.

Then select the provider, for example `hermes model` and choose `nbgsysclaude-tokens`, or use
`nbgsysclaude-tokens` as the provider in your config.

### Diagnostics

```bash
# Hermes's own interpreter, so the plugin can see Hermes
docker exec -u hermes hermes-gateway /opt/hermes/.venv/bin/python \
  /opt/data/plugins/nbgsysclaude-tokens/cli.py doctor
```

`doctor` checks the bundled Anthropic provider, the `claude` CLI, the token's shape, its estimated
expiry, whether the same token is also used as `CLAUDE_CODE_OAUTH_TOKEN`, and a live request. Use
`--offline` to skip the network check. Exit codes: 0 healthy, 1 warnings, 2 failure.

`login`, `status` and `logout` are available the same way (`cli.py login --stdin` reads a token from
standard input for scripting).

## Security

- The token is only ever held in memory, sent to `api.anthropic.com`, and saved to Hermes's `.env`.
- It is never printed, logged, or put in an error message. Output shows only the public prefix and the
  length. A redaction pattern for `sk-ant-oat...` is registered with Hermes so it is scrubbed from logs.
- Credentials are never forwarded to another host: redirects are not followed with the token attached.
- The `claude` CLI is started without any existing token in its environment.
- The plugin has no self-updater, no telemetry and no network calls other than to `api.anthropic.com`.
- Use **one dedicated token per consuming service**. Do not reuse the token you gave Hermes elsewhere
  (for example in another tool), so you can revoke one without breaking the other. `doctor` warns if the
  plugin's token equals `CLAUDE_CODE_OAUTH_TOKEN`.
- Passing a token as `--api-key` on a command line leaves it in shell history. Prefer the interactive
  prompt or `--stdin`.

## Subscription tokens versus API keys

| | Console API key `sk-ant-api03-...` | Subscription token `sk-ant-oat01-...` |
|---|---|---|
| Billing | Pay per token, prepaid credit | Your Pro/Max plan |
| Created by | console.anthropic.com | `claude setup-token` |
| Sent as | `x-api-key` header | `Authorization: Bearer` plus Claude Code beta headers |
| When it runs out | `credit balance is too low` (400) | Rate limit (429) until the window resets |
| Lifetime | Until revoked | About one year, no refresh |

A claude.ai subscription and an API Console account are **separate products with separate billing**.
Having a subscription does not fund API calls, which is the usual reason people reach for this plugin.

## Account boundaries and terms

Please read this honestly before relying on it.

- **Anthropic's terms govern this, not this plugin.** A subscription token is intended for use with
  Anthropic's own Claude Code client. This plugin sends the same client headers Claude Code does so the
  API accepts the token. Whether using a subscription token in a third-party agent is permitted, and
  whether Anthropic restricts or blocks it, is Anthropic's decision and may change without notice. Review
  the current Consumer and Usage terms yourself. You use this at your own risk, and a token could stop
  working at any time.
- **The quota is shared.** Requests count against the same plan usage as claude.ai and Claude Code on
  your account. Heavy agent use can exhaust your window and leave your interactive Claude unavailable
  until it resets.
- **Rate limits are the plan's, not Hermes's.** Pro and Max have rolling usage windows whose size and
  reset timing are set by Anthropic and can change. A 429 means "valid token, plan throttled": wait and
  retry. It does not mean the token is broken.
- **Personal use.** A subscription belongs to one person. Do not share a token between people or put it
  in a multi-user service.
- **No refresh logic.** The token lives about a year. The plugin warns before it ends; you mint a new one.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Short version:

| Symptom | Likely cause | Fix |
|---|---|---|
| `HTTP 401` on add | Truncated or revoked token | Mint again; do not copy from a narrow terminal |
| `HTTP 429` | Plan window used up | Wait; the token is fine |
| `credit balance is too low` | You pasted an API key | Use the `sk-ant-oat01-` token from `claude setup-token` |
| `the input device is not a TTY` | Missing `-it` | `docker exec -it ...` |
| Provider missing in `hermes model` | Plugin inactive | Run `doctor`; check the gateway log for "nbgsysclaude-tokens: inactive" |
| Works in `doctor`, not in chat | Gateway not restarted | Restart it so `.env` is re-read |

## Development

```bash
python -m pytest            # 70+ tests, no Hermes installation needed (Hermes is stubbed)
hermes plugins validate .   # the admission checks Hermes runs
```

The layout and design are described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT, see [LICENSE](LICENSE).
