#!/usr/bin/env python3
"""
glitch_detector.py — soft restart всего стека при зависании (UC-75).

Pavel 2026-05-21: «создай бота который будет перезапускать компьютер если глюк».
Я не могу перезагружать машину (sudo + пароль), но могу soft restart всех процессов:
- server :7788
- master_health_bot.py
- night_workshop.py (если ночь и не завершился)

Каждые 10 минут (launchd StartInterval=600).
Лог: reports/GLITCH-RECOVERY-LOG.md
"""
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
LOG = V2 / "reports/GLITCH-RECOVERY-LOG.md"
EVENTS = V2 / ".codex/events.jsonl"
SERVER_PORT = 7788

PIDS = {
    "server": None,  # detected via port
    "health_bot": V2 / ".codex/health-bot.pid",
    "marathon": V2 / ".codex/night-marathon.pid",
    "night_workshop": V2 / ".codex/night-workshop.pid",
}


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    try:
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts, "type": "glitch_detector", "target": "system",
                "payload": {"msg": msg},
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(msg)


def server_alive() -> bool:
    try:
        r = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://127.0.0.1:{SERVER_PORT}/api/health", "--max-time", "5"],
            text=True, timeout=8)
        return r.strip() == "200"
    except Exception:
        return False


def pid_alive(pid_file: Path, cmd_pattern: str) -> bool:
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                       text=True, timeout=2).strip()
        return cmd_pattern in out
    except Exception:
        return False


def restart_server():
    log("✗ server :7788 не отвечает — kill + restart")
    subprocess.run(["bash", "-c",
                    f"lsof -ti tcp:{SERVER_PORT} | xargs -r kill -9 2>/dev/null; "
                    f"sleep 1; cd ~/Desktop/Codex2/app && nohup python3 server.py "
                    "> /tmp/codex2-server.log 2>&1 &"], timeout=15)
    time.sleep(3)
    if server_alive():
        log("✓ server поднят")
    else:
        log("✗ server НЕ поднимается после рестарта — нужно ручное вмешательство")


def restart_health_bot():
    log("✗ master_health_bot мёртв — рестарт")
    subprocess.Popen(
        ["nohup", "python3", str(V2 / "scripts/master_health_bot.py")],
        stdout=open("/tmp/health-bot.log", "a"), stderr=subprocess.STDOUT,
        cwd=str(V2), start_new_session=True,
    )


def is_night_hours() -> bool:
    """Между 22:00 и 06:00 — должны работать night процессы."""
    hour = datetime.now().hour
    return hour >= 22 or hour < 6


def main():
    actions = 0
    log("─── glitch_detector cycle ───")

    if not server_alive():
        restart_server()
        actions += 1
    else:
        log("✓ server alive")

    if not pid_alive(PIDS["health_bot"], "master_health_bot.py"):
        restart_health_bot()
        actions += 1
    else:
        log("✓ health_bot alive")

    # night_workshop — только в ночное время
    if is_night_hours():
        if not pid_alive(PIDS["night_workshop"], "night_workshop.py"):
            log("⚠ ночь, но night_workshop не запущен — стартую")
            try:
                subprocess.Popen(
                    ["nohup", "python3", str(V2 / "scripts/night_workshop.py")],
                    stdout=open("/tmp/night-workshop.log", "a"), stderr=subprocess.STDOUT,
                    cwd=str(V2), start_new_session=True,
                )
                actions += 1
            except Exception as e:
                log(f"✗ night_workshop start failed: {e}")
        else:
            log("✓ night_workshop alive")

    log(f"   actions taken: {actions}")


if __name__ == "__main__":
    main()
