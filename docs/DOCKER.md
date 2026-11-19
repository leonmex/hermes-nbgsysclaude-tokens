# Containerised Hermes

The plugin works the same inside a container. Three practical points.

## 1. Use `-it` for the interactive login

```bash
docker exec -it -u hermes hermes-gateway hermes auth add nbgsysclaude-tokens
```

The CLI renders nothing without a TTY, and the Docker client itself needs a real terminal on its side.

## 2. Make the plugin survive image updates

A plugin installed under the image's own filesystem is lost when the image is replaced. If
`HERMES_HOME` is a bind-mounted volume (for example `/opt/data`), the plugin lives on the volume and
survives. To also recover from an emptied volume, bind-mount
[`scripts/05-ensure-nbgsysclaude-tokens-plugin`](../scripts/05-ensure-nbgsysclaude-tokens-plugin) into
`/etc/cont-init.d/` on images that run those hooks:

```yaml
volumes:
  - "./docker/cont-init.d/05-ensure-nbgsysclaude-tokens-plugin:/etc/cont-init.d/05-ensure-nbgsysclaude-tokens-plugin:ro"
```

The script pins `HERMES_HOME` and `HOME` explicitly. `cont-init.d` does not inherit the environment a
`docker exec -u hermes` session has, and without the pin `hermes plugins install` can silently land in the
wrong directory and leave the plugin "not installed".

## 3. Restart after changing the token

```bash
docker compose restart hermes-gateway
```

## Smoke test

```bash
./scripts/smoke-test.sh hermes-gateway
```

Runs `hermes plugins validate`, the offline checks, and the live token check inside the container.
