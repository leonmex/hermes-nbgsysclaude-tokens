# Changelog

## 0.1.0 - unreleased

- Provider `nbgsysclaude-tokens` (aliases `nbgsysclaude`, `nbgsysclaude-sub`) built on the bundled
  Anthropic provider, using its own credential `NBGSYSCLAUDE_CODE_OAUTH_TOKEN`.
- Dependency guard: inert unless the bundled Anthropic provider is available; safe when Hermes imports
  the plugin during bundled provider discovery.
- Live token validation with explicit handling of 200, 429, 401 and the API-key credit-balance 400.
- `hermes auth add|status|logout nbgsysclaude-tokens`; `cli.py doctor` diagnostics.
- `claude setup-token` driven in a 300-column pty with the token hidden from the screen.
- Expiry tracking and warnings; log redaction for `sk-ant-oat...`.
