#!/bin/bash
# Запуск сервера Кодекс v2.
# Безопасно: если уже запущен — не дублирует, показывает PID.

set -e
PORT=7788
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/.server.log"
PID_FILE="$DIR/.server.pid"

# Проверяем, не висит ли уже что-то на порту
EXISTING=$(lsof -t -iTCP:$PORT 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
  echo "✓ Сервер уже работает (PID $EXISTING) на http://127.0.0.1:$PORT"
  exit 0
fi

# Запускаем в фоне
cd "$DIR"
nohup python3 server.py > "$LOG" 2>&1 &
PID=$!
echo $PID > "$PID_FILE"

# Ждём 1 сек и проверяем что поднялся
sleep 1
if curl -sf "http://127.0.0.1:$PORT/api/health" > /dev/null; then
  echo "✓ Кодекс v2 запущен (PID $PID) → http://127.0.0.1:$PORT"
  echo "  Лог: $LOG"
  echo "  Стоп: bash $DIR/stop.sh"
else
  echo "✗ Сервер не отвечает. Смотри лог: $LOG"
  exit 1
fi
