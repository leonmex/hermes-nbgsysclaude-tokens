# Troubleshooting

Start with `doctor`:

```bash
docker exec -u hermes hermes-gateway /opt/hermes/.venv/bin/python \
  /opt/data/plugins/nbgsysclaude-tokens/cli.py doctor
```

## HTTP 401 when adding a token

The token was rejected. The most common cause is **truncation**: a ~110 character token copied from a
terminal narrower than the token wraps, and the copy loses characters. The plugin warns when a token is
shorter than 100 characters.

- Use the **mint** option (runs the CLI in a 300-column terminal) instead of copying by hand.
- If pasting, paste into the hidden prompt; line breaks are removed for you.
- A revoked or expired token also returns 401. Mint a new one.

Note that `hermes auth status anthropic` reporting "logged in" proves nothing: it only means a value
shaped like a credential exists.

## HTTP 429

The token is valid and your plan's usage window is exhausted. Wait for the window to reset. The plugin
saves a token that returns 429 because the credential itself is fine.

## "credit balance is too low"

You supplied a pay-per-token API key (`sk-ant-api03-...`) whose Console account has no prepaid credit.
A Pro/Max subscription does not fund API usage. Get a subscription token with `claude setup-token`.

## "the input device is not a TTY"

Docker needs a real terminal for the interactive flow: `docker exec -it`. Without one, use
`cli.py login --stdin` and pipe the token in.

## `claude` CLI not found

Only minting needs it. Install with `npm install -g @anthropic-ai/claude-code`, point
`NBGSYSCLAUDE_CLAUDE_BIN` at the binary, or use the paste option.

## Provider does not appear

Check the gateway log for a line starting `nbgsysclaude-tokens: inactive`. It states the reason, for
example that the bundled Anthropic provider was not found. Then run `hermes plugins validate` on the
plugin directory.

## Works in `doctor` but not in chat

Hermes reads `.env` at start-up. Restart the gateway after adding, replacing or removing the token.

## 404 / model not found during validation

The probe model is not available on your plan. Set another with
`NBGSYSCLAUDE_PROBE_MODEL=<model id>`.

## 400 "out of extra usage"

The token authenticates, but Anthropic routed the request to a metered lane. This is an Anthropic-side
classification of the request, not a plugin fault.
