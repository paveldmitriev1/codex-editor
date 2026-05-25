#!/usr/bin/env python3
"""
master_health_bot.py — главный health-bot (Pavel 2026-05-21).

Pavel: «бот который каждые 5 минут проверяет чтобы все процессы работали.
Если что-то не работает — чинит. 3 часа моих потерял — больше не делай».

ЭТО ИНФИНИТНЫЙ ЦИКЛ. Запускается через nohup из shell (TCC-права).
Если умирает — watcher_keeper.sh его рестартует через launchd.

Каждые 300 сек:
1. Server :7788 alive? — рестарт если нет
2. Marathon (PID file) alive? — рестарт если нет
3. Watcher (PID file) alive? — рестарт если нет
4. Manager last run < 35 мин? — запустить вручную если нет
5. Improver last run < 7 мин? — запустить вручную если нет
6. Heartbeat freshness — alert если > 7 мин
7. Записать состояние в reports/HEALTH-BOT.md (живой)
8. Записать в reports/HEALTH-BOT-LOG.md (history, append)
9. Heartbeat для самого бота в .codex/health-bot.json

Запуск: `cd ~/Desktop/Codex2 && nohup python3 scripts/master_health_bot.py > /tmp/health-bot.log 2>&1 &`
Стоп:   `kill $(cat ~/Desktop/Codex2/.codex/health-bot.pid)`
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
SCRIPTS = V2 / "scripts"
REPORTS = V2 / "reports"
EVENTS = V2 / ".codex/events.jsonl"
PID_FILE = V2 / ".codex/health-bot.pid"
HEARTBEAT_FILE = V2 / ".codex/health-bot.json"
LIVE_REPORT = REPORTS / "HEALTH-BOT.md"
HISTORY_LOG = REPORTS / "HEALTH-BOT-LOG.md"
SERVER_URL = "http://127.0.0.1:7788"

INTERVAL_SEC = 300  # 5 минут
MANAGER_MAX_AGE_MIN = 35
IMPROVER_MAX_AGE_MIN = 7

(V2 / ".codex").mkdir(parents=True, exist_ok=True)
PID_FILE.write_text(str(os.getpid()))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_human() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str):
    REPORTS.mkdir(parents=True, exist_ok=True)
    line = f"[{now_human()}] {msg}"
    print(line)
    try:
        with HISTORY_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def event(kind: str, payload: dict = None):
    try:
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now_iso(), "type": kind, "target": "health_bot",
                "payload": payload or {},
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ────────────────────────────────────────────────
# CHECKS
# ────────────────────────────────────────────────

def server_alive() -> bool:
    try:
        out = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{SERVER_URL}/api/health", "--max-time", "3"],
            text=True, timeout=5)
        return out.strip() == "200"
    except Exception:
        return False


def check_pid_file(pid_file: Path, cmd_substring: str) -> dict:
    if not pid_file.exists():
        return {"alive": False, "reason": "no PID file"}
    try:
        pid = int(pid_file.read_text().strip())
    except Exception:
        return {"alive": False, "reason": "bad PID"}
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return {"alive": False, "reason": f"PID {pid} dead"}
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                       text=True, timeout=2).strip()
        if cmd_substring not in out:
            return {"alive": False, "reason": f"PID {pid} mismatch"}
    except Exception as e:
        return {"alive": False, "reason": str(e)}
    return {"alive": True, "pid": pid}


def file_age_min(p: Path) -> float:
    if not p.exists():
        return 9999.0
    return (time.time() - p.stat().st_mtime) / 60


# ────────────────────────────────────────────────
# RESTART ACTIONS
# ────────────────────────────────────────────────

def restart_server() -> bool:
    log("→ restart server")
    try:
        subprocess.run(["bash", "-c",
                        "lsof -ti tcp:7788 | xargs -r kill -9 2>/dev/null; sleep 1; "
                        "cd ~/Desktop/Codex2/app && nohup python3 server.py "
                        "> /tmp/codex2-server.log 2>&1 &"], timeout=10)
        time.sleep(3)
        return server_alive()
    except Exception as e:
        log(f"  server restart err: {e}")
        return False


def restart_marathon():
    log("→ restart marathon")
    try:
        subprocess.Popen(
            ["nohup", "python3", str(SCRIPTS / "night_marathon.py")],
            stdout=open("/tmp/marathon.log", "a"), stderr=subprocess.STDOUT,
            cwd=str(V2),
        )
    except Exception as e:
        log(f"  marathon restart err: {e}")


def restart_watcher():
    log("→ restart overnight_watcher")
    try:
        subprocess.Popen(
            ["nohup", "bash", str(SCRIPTS / "overnight_watcher.sh")],
            stdout=open(V2 / ".codex/watcher.log", "a"), stderr=subprocess.STDOUT,
            cwd=str(V2),
        )
    except Exception as e:
        log(f"  watcher restart err: {e}")


def force_manager():
    log("→ запускаем super_manager вручную")
    try:
        subprocess.run(["python3", str(SCRIPTS / "super_manager.py")],
                       timeout=180, capture_output=True)
    except Exception as e:
        log(f"  manager err: {e}")


def force_improver():
    log("→ запускаем improver_loop вручную")
    try:
        subprocess.run(["python3", str(SCRIPTS / "improver_loop.py")],
                       timeout=200, capture_output=True)
    except Exception as e:
        log(f"  improver err: {e}")


# ────────────────────────────────────────────────
# CYCLE
# ────────────────────────────────────────────────

def cycle(cycle_num: int) -> dict:
    state = {
        "ts": now_iso(),
        "cycle": cycle_num,
        "actions": [],
    }

    # 1. Server
    if not server_alive():
        state["actions"].append("server рестарт")
        ok = restart_server()
        state["actions"].append(f"server " + ("поднят" if ok else "НЕ поднимается"))
    state["server"] = server_alive()

    # 2. Marathon
    m = check_pid_file(V2 / ".codex/night-marathon.pid", "night_marathon.py")
    state["marathon"] = m
    if not m["alive"]:
        state["actions"].append(f"marathon мёртв ({m['reason']}) → рестарт")
        restart_marathon()
        time.sleep(2)

    # 3. Watcher
    w = check_pid_file(V2 / ".codex/watcher.pid", "overnight_watcher.sh")
    state["watcher"] = w
    if not w["alive"]:
        state["actions"].append(f"watcher мёртв → рестарт")
        restart_watcher()
        time.sleep(1)

    # 4. Manager freshness — последний REPORT обновлялся < 35 мин назад?
    mgr_age = file_age_min(REPORTS / "MANAGER-REPORT.md")
    state["manager_age_min"] = round(mgr_age, 1)
    if mgr_age > MANAGER_MAX_AGE_MIN:
        state["actions"].append(f"manager не запускался {mgr_age:.0f} мин → форсим")
        force_manager()
        time.sleep(2)

    # 5. Improver freshness — последний IMPROVER-LOG обновлялся < 7 мин назад?
    imp_age = file_age_min(REPORTS / "IMPROVER-LOG.md")
    state["improver_age_min"] = round(imp_age, 1)
    if imp_age > IMPROVER_MAX_AGE_MIN:
        state["actions"].append(f"improver не запускался {imp_age:.0f} мин → форсим")
        force_improver()

    # 6. Heartbeat freshness (idle_keeper)
    hb_age = file_age_min(V2 / ".codex/heartbeat.json")
    state["heartbeat_age_min"] = round(hb_age, 1)

    return state


# ────────────────────────────────────────────────
# REPORT
# ────────────────────────────────────────────────

def render_live(state: dict, total_cycles: int, started_at: float) -> str:
    uptime_h = (time.time() - started_at) / 3600
    lines = []
    lines.append(f"# Health Bot · {now_human()}")
    lines.append("")
    lines.append(f"_живой отчёт · бот работает {uptime_h:.1f} ч · цикл {total_cycles}_")
    lines.append("")
    server_ok = "✓" if state["server"] else "✗"
    m_ok = "✓" if state["marathon"]["alive"] else "✗"
    w_ok = "✓" if state["watcher"]["alive"] else "✗"
    overall = "ВСЁ РАБОТАЕТ" if (state["server"] and state["marathon"]["alive"] and state["watcher"]["alive"]) else "ЕСТЬ ПРОБЛЕМЫ"
    lines.append(f"## {overall}")
    lines.append("")
    lines.append(f"- {server_ok} **Server :7788**")
    lines.append(f"- {m_ok} **Marathon** (5-мин циклы)" + (f" PID {state['marathon'].get('pid')}" if state["marathon"]["alive"] else f" — {state['marathon'].get('reason')}"))
    lines.append(f"- {w_ok} **Watcher** (фоновые)" + (f" PID {state['watcher'].get('pid')}" if state["watcher"]["alive"] else f" — {state['watcher'].get('reason')}"))
    lines.append("")
    lines.append(f"**Свежесть:**")
    lines.append(f"- manager: {state['manager_age_min']} мин назад (лимит {MANAGER_MAX_AGE_MIN})")
    lines.append(f"- improver: {state['improver_age_min']} мин назад (лимит {IMPROVER_MAX_AGE_MIN})")
    lines.append(f"- heartbeat (idle_keeper): {state['heartbeat_age_min']} мин назад")
    lines.append("")
    if state["actions"]:
        lines.append("**Действия в этом цикле:**")
        for a in state["actions"]:
            lines.append(f"- {a}")
        lines.append("")
    lines.append("---")
    lines.append(f"Следующая проверка через {INTERVAL_SEC} сек.")
    lines.append(f"PID бота: {os.getpid()}")
    return "\n".join(lines)


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────

def main():
    log("══════════════════════════════════════════════")
    log(f"🤖 MASTER HEALTH BOT запущен (PID {os.getpid()})")
    log(f"   Цикл: {INTERVAL_SEC} сек · бесконечный")
    log("══════════════════════════════════════════════")
    event("health_bot_started", {"pid": os.getpid()})

    started = time.time()
    cycle_num = 0
    while True:
        cycle_num += 1
        try:
            state = cycle(cycle_num)
            log(f"цикл {cycle_num}: server={state['server']} "
                f"marathon={state['marathon']['alive']} "
                f"watcher={state['watcher']['alive']} "
                f"mgr_age={state['manager_age_min']} "
                f"imp_age={state['improver_age_min']} "
                f"hb_age={state['heartbeat_age_min']} "
                f"actions={len(state['actions'])}")
            event("health_bot_cycle", state)

            # Live report
            REPORT_LIVE = LIVE_REPORT
            REPORT_LIVE.write_text(render_live(state, cycle_num, started), encoding="utf-8")

            # Self-heartbeat
            HEARTBEAT_FILE.write_text(json.dumps({
                "last_cycle": now_iso(),
                "cycle_num": cycle_num,
                "pid": os.getpid(),
                "uptime_h": round((time.time() - started) / 3600, 2),
            }, indent=2), encoding="utf-8")

        except Exception as e:
            log(f"  ✗ cycle exception: {e}")
            event("health_bot_cycle_error", {"cycle": cycle_num, "error": str(e)})

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
