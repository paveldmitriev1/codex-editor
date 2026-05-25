#!/bin/bash
# Codex2 Server Watchdog (Pavel 2026-05-25: «проверь чтобы тебя не отключило ночью»)
# Каждые 30 сек проверяет порт 7788. Если сервер упал — рестартует.
# launchd под Desktop не работает из-за TCC, поэтому используется bash-loop через nohup.
#
# Запуск: nohup bash /Users/kingofhealers/Desktop/Codex2/scripts/server_watchdog.sh > /tmp/codex2-watchdog.log 2>&1 &
# Стоп:   pkill -f server_watchdog.sh

CODEX_DIR="/Users/kingofhealers/Desktop/Codex2"
PYTHON="/usr/bin/python3"
PORT=7788
LOG="/tmp/codex2-watchdog.log"
SERVER_LOG="/tmp/codex2-server.log"

log() {
    echo "[$(date '+%Y-%m-%dT%H:%M:%SZ')] $1" >> "$LOG"
}

log "watchdog started, monitoring port $PORT"

while true; do
    if ! lsof -ti :$PORT >/dev/null 2>&1; then
        log "PORT $PORT IS DOWN — restarting server"
        cd "$CODEX_DIR" || { log "ERROR: cd $CODEX_DIR failed"; sleep 30; continue; }
        nohup "$PYTHON" app/server.py >> "$SERVER_LOG" 2>&1 &
        log "server restarted, new PID: $!"
        sleep 10  # let it bind port
    fi
    sleep 30
done
