#!/bin/bash
# safe_restart.sh — рестарт сервера 7788 БЕЗ убийства активных Pavel-овских jobs.
#
# Pavel rule (2026-05-25): не убивать running master-audit / paragraph-writer /
# polish-plan posередине. Если есть — ждём пока завершатся или предупреждаем.
#
# Usage:
#   bash scripts/safe_restart.sh         — ждать всех активных, потом рестарт
#   bash scripts/safe_restart.sh --force — рестарт сразу, mark jobs failed (SIGTERM)
#   bash scripts/safe_restart.sh --check — только проверить, не делать ничего

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTIVE_DIR="$ROOT/.codex/active-jobs"
PORT=7788
MAX_WAIT_SEC=600  # 10 минут

count_active() {
    if [ ! -d "$ACTIVE_DIR" ]; then
        echo 0; return
    fi
    find "$ACTIVE_DIR" -maxdepth 1 -name "*.json" ! -name "*.done.json" -type f 2>/dev/null | wc -l | tr -d ' '
}

list_active() {
    if [ ! -d "$ACTIVE_DIR" ]; then return; fi
    for f in "$ACTIVE_DIR"/*.json; do
        [ -f "$f" ] || continue
        case "$f" in
            *.done.json) continue ;;
        esac
        python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(f\"  - {d.get('chapter_id','?')} · {d.get('op_type','?')} · running\")
" "$f" 2>/dev/null
    done
}

ACTIVE=$(count_active)

if [ "$1" = "--check" ]; then
    echo "Active jobs: $ACTIVE"
    list_active
    exit 0
fi

if [ "$ACTIVE" -gt 0 ] && [ "$1" != "--force" ]; then
    echo "⚠ Есть $ACTIVE активных job-ов на сервере:"
    list_active
    echo
    echo "Жду пока завершатся (max ${MAX_WAIT_SEC}с)... используй --force чтобы убить сразу."
    WAITED=0
    while [ "$(count_active)" -gt 0 ] && [ "$WAITED" -lt "$MAX_WAIT_SEC" ]; do
        sleep 5
        WAITED=$((WAITED + 5))
        REMAINING=$(count_active)
        if [ $((WAITED % 30)) = 0 ]; then
            echo "  …осталось $REMAINING (прошло ${WAITED}с)"
        fi
    done
    if [ "$(count_active)" -gt 0 ]; then
        echo "⚠ Timeout. Активных всё ещё $(count_active). Прерываю — используй --force если нужен жёсткий рестарт."
        exit 2
    fi
    echo "✓ Все jobs завершены, продолжаю рестарт."
fi

# Kill via SIGTERM (cleanup handler пометит любые оставшиеся как failed)
PID=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$PID" ]; then
    echo "Killing server PID $PID via SIGTERM..."
    kill -TERM "$PID" 2>/dev/null || true
    sleep 3
fi

# Start fresh
cd "$ROOT"
nohup python3 app/server.py > /tmp/codex2-server.log 2>&1 &
sleep 3

NEW_PID=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$NEW_PID" ]; then
    echo "✓ Server restarted, new PID: $NEW_PID"
    curl -s "http://127.0.0.1:$PORT/api/health" || echo "(health check failed)"
else
    echo "✗ Server failed to start. Check /tmp/codex2-server.log"
    exit 1
fi
