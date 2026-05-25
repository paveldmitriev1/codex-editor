#!/bin/bash
# watcher_keeper.sh — каждые 10 минут проверяет жив ли overnight_watcher, если нет — рестартует.
# Запускается через launchd ai.codex2.watcher-keeper.plist каждые 600 секунд.
#
# Pavel 2026-05-20: «каждые 5 минут проверяешь работает компьютер или нет
# работаешь всегда не переставая круглые сутки».
#
# launchd гарантирует что keeper срабатывает даже если bash watcher умрёт.

CODEX2="$HOME/Desktop/Codex2"
WATCHER_PIDFILE="$CODEX2/.codex/watcher.pid"
MARATHON_PIDFILE="$CODEX2/.codex/night-marathon.pid"
HEALTHBOT_PIDFILE="$CODEX2/.codex/health-bot.pid"
SERVER_PORT=7788
LOG="$CODEX2/.codex/watcher.log"
KEEPER_LOG="$CODEX2/.codex/watcher-keeper.log"

mkdir -p "$CODEX2/.codex"

log_keeper() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$KEEPER_LOG"
}

# ─── 1. Server (port 7788) ───────────────────────────
SERVER_ALIVE=0
if [ -n "$(lsof -ti tcp:$SERVER_PORT 2>/dev/null)" ]; then
    if curl -s -o /dev/null -w "%{http_code}" --max-time 3 \
         "http://127.0.0.1:$SERVER_PORT/api/health" | grep -q "200"; then
        SERVER_ALIVE=1
    fi
fi
if [ $SERVER_ALIVE -eq 0 ]; then
    log_keeper "✗ server :$SERVER_PORT мёртв → рестарт"
    lsof -ti tcp:$SERVER_PORT | xargs -r kill -9 2>/dev/null
    sleep 1
    cd "$CODEX2/app" || exit 1
    nohup python3 server.py > /tmp/codex2-server.log 2>&1 &
    log_keeper "▶ запущен server (PID $!)"
else
    log_keeper "✓ server alive"
fi

# ─── 2. Overnight watcher ────────────────────────────
WATCHER_ALIVE=0
if [ -f "$WATCHER_PIDFILE" ]; then
    PID=$(cat "$WATCHER_PIDFILE" 2>/dev/null)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        if ps -p "$PID" -o command= 2>/dev/null | grep -q "overnight_watcher.sh"; then
            WATCHER_ALIVE=1
        fi
    fi
fi
if [ $WATCHER_ALIVE -eq 0 ]; then
    log_keeper "✗ watcher мёртв → рестарт"
    cd "$CODEX2" || exit 1
    nohup bash scripts/overnight_watcher.sh >> "$LOG" 2>&1 &
    log_keeper "▶ запущен watcher (PID $!)"
else
    log_keeper "✓ watcher alive (PID $PID)"
fi

# ─── 3. Night marathon (Pavel 2026-05-21: «куда делся за ночь») ─────
MARATHON_ALIVE=0
if [ -f "$MARATHON_PIDFILE" ]; then
    PID=$(cat "$MARATHON_PIDFILE" 2>/dev/null)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        if ps -p "$PID" -o command= 2>/dev/null | grep -q "night_marathon.py"; then
            MARATHON_ALIVE=1
        fi
    fi
fi
if [ $MARATHON_ALIVE -eq 0 ]; then
    log_keeper "✗ marathon мёртв → рестарт"
    cd "$CODEX2" || exit 1
    nohup python3 scripts/night_marathon.py > /tmp/marathon.log 2>&1 &
    log_keeper "▶ запущен marathon (PID $!)"
else
    log_keeper "✓ marathon alive (PID $PID)"
fi

# ─── 4. Master Health Bot (Pavel 2026-05-21: «3 часа меня потерял») ─────
HEALTHBOT_ALIVE=0
if [ -f "$HEALTHBOT_PIDFILE" ]; then
    PID=$(cat "$HEALTHBOT_PIDFILE" 2>/dev/null)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        if ps -p "$PID" -o command= 2>/dev/null | grep -q "master_health_bot.py"; then
            HEALTHBOT_ALIVE=1
        fi
    fi
fi
if [ $HEALTHBOT_ALIVE -eq 0 ]; then
    log_keeper "✗ health-bot мёртв → рестарт"
    cd "$CODEX2" || exit 1
    nohup python3 scripts/master_health_bot.py > /tmp/health-bot.log 2>&1 &
    log_keeper "▶ запущен health-bot (PID $!)"
else
    log_keeper "✓ health-bot alive (PID $PID)"
fi

exit 0
