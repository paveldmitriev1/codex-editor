#!/bin/bash
# Остановка сервера Кодекс v2.

PORT=7788
PIDS=$(lsof -t -iTCP:$PORT 2>/dev/null || true)

if [ -z "$PIDS" ]; then
  echo "✓ Сервер не запущен (порт $PORT свободен)"
  exit 0
fi

for PID in $PIDS; do
  kill "$PID" 2>/dev/null && echo "✓ Остановлен PID $PID"
done

# Если кто-то выжил — kill -9
sleep 1
SURVIVORS=$(lsof -t -iTCP:$PORT 2>/dev/null || true)
if [ -n "$SURVIVORS" ]; then
  for PID in $SURVIVORS; do
    kill -9 "$PID" 2>/dev/null && echo "✗ Принудительно убит PID $PID"
  done
fi

rm -f "$(dirname "$0")/.server.pid"
echo "✓ Сервер остановлен"
