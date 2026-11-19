#!/usr/bin/env bash
# smoke-test.sh -- verify the installed nbgsysclaude-tokens plugin inside a running Hermes container.
#
# Usage: ./scripts/smoke-test.sh [container-name]     (default: hermes-gateway)
#
# Read-only: validates the plugin, runs the offline checks, then the live token check. It does not
# change any configuration and never prints the token. Exit code is the worst of the steps.
set -euo pipefail

CONTAINER="${1:-hermes-gateway}"
PLUGIN="/opt/data/plugins/nbgsysclaude-tokens"
PY="/opt/hermes/.venv/bin/python"
worst=0

run() {
    echo "== $1"; shift
    set +e; "$@"; local rc=$?; set -e
    [ "$rc" -gt "$worst" ] && worst=$rc
    echo "   (exit $rc)"
}

docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "container '$CONTAINER' not found" >&2; exit 2; }
docker exec "$CONTAINER" test -d "$PLUGIN" || { echo "plugin not installed at $PLUGIN" >&2; exit 2; }

run "plugins validate"  docker exec -u hermes -e HERMES_HOME=/opt/data "$CONTAINER" hermes plugins validate "$PLUGIN"
run "doctor (offline)"  docker exec -u hermes -e HERMES_HOME=/opt/data "$CONTAINER" "$PY" "$PLUGIN/cli.py" doctor --offline
run "doctor (live)"     docker exec -u hermes -e HERMES_HOME=/opt/data "$CONTAINER" "$PY" "$PLUGIN/cli.py" doctor

echo "overall exit: $worst  (0 healthy, 1 warnings, 2 failure)"
exit "$worst"
