#!/bin/bash
# Start, stop or restart the three local servers.
#   ./scripts/servers.sh start|stop|restart|status
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
LOGS="$ROOT/logs/servers"
mkdir -p "$LOGS"

stop() {
    pkill -f "adapters.web_chat" 2>/dev/null
    pkill -f "uvicorn bank_api.main" 2>/dev/null
    pkill -f "next dev" 2>/dev/null
    pkill -f "next-server" 2>/dev/null
    sleep 2
    echo "stopped"
}

start() {
    cd "$ROOT" || exit 1
    nohup "$PY" -m uvicorn bank_api.main:create_app --factory --host 127.0.0.1 --port 8001 \
        > "$LOGS/bank_api.log" 2>&1 & disown
    nohup "$PY" -m adapters.web_chat > "$LOGS/web_adapter.log" 2>&1 & disown
    nohup pnpm --dir "$ROOT/web" dev > "$LOGS/frontend.log" 2>&1 & disown
    echo "starting..."
}

status() {
    local rc=0
    for hp in 8001/health 8002/health 3000/; do
        local port=${hp%%/*}
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://localhost:$hp")
        printf "%-5s %s\n" "$port" "$code"
        [ "$code" = "200" ] || rc=1
    done
    return $rc
}

wait_ready() {
    for _ in $(seq 1 30); do
        status > /dev/null 2>&1 && { status; echo "ready: http://localhost:3000"; return 0; }
        sleep 1
    done
    status; echo "not ready after 30s (see logs/servers/)" >&2
    return 1
}

case "${1:-}" in
    start)   start; wait_ready ;;
    stop)    stop ;;
    restart) stop; start; wait_ready ;;
    status)  status ;;
    *)       echo "usage: $0 start|stop|restart|status" >&2; exit 2 ;;
esac
