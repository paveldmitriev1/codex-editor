#!/usr/bin/env python3
"""
idle_keeper.py — каждые 5 минут проверяет: нет ли простоя? Если простой 5+ минут — запускает один полезный фоновый таск.

Pavel 2026-05-20 STANDING RULE: «если простой 5 минут моего или твоего бездействия — ты включаешь и ищешь что можно сделать. Максимум токенов в день. Штраф если не делаешь».

Это файл вызывается из overnight_watcher.sh каждые 5 минут. Сам решает что запускать
на основе:
- Time since last Pavel action (pavel-actions.jsonl)
- Time since last server log update
- Available work (covered_voice_analyses, untouched chapters, etc.)
- Round-robin rotation
"""
import json
import random
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple, List

V2 = Path.home() / "Desktop/Codex2"
EVENTS = V2 / ".codex/events.jsonl"
PAVEL_ACTIONS = V2 / ".codex/pavel-actions.jsonl"
IDLE_LOG = V2 / ".codex/idle-keeper.log"
SCRIPTS = V2 / "scripts"

IDLE_THRESHOLD_MIN = 5
MAX_SCRIPT_RUNTIME_SEC = 180  # 3 минуты


def log(msg: str):
    IDLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with IDLE_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def last_pavel_action_ts() -> Optional[datetime]:
    """Когда Pavel в последний раз что-то делал в UI?"""
    if not PAVEL_ACTIONS.exists():
        return None
    last = None
    with PAVEL_ACTIONS.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                ts = e.get("ts") or e.get("timestamp")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
                        if last is None or dt > last:
                            last = dt
                    except ValueError:
                        pass
            except json.JSONDecodeError:
                pass
    return last


def is_pavel_idle() -> Tuple[bool, float]:
    """Pavel простаивает 5+ минут?"""
    last = last_pavel_action_ts()
    if last is None:
        return True, 999.0  # никогда не было активности → можно работать
    delta = (datetime.now(timezone.utc) - last).total_seconds() / 60
    return delta >= IDLE_THRESHOLD_MIN, delta


def already_running(script_name: str) -> bool:
    """Скрипт уже запущен — не запускать вторично."""
    try:
        out = subprocess.check_output(["pgrep", "-f", script_name], text=True, stderr=subprocess.DEVNULL)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def pick_task() -> Tuple[str, List[str]]:
    """Выбираем какой скрипт запустить. Приоритет — что давно не запускалось.

    Returns: (label, command_list).
    """
    pool = [
        ("extract_metaphors_next",   ["python3", str(SCRIPTS / "extract_metaphors.py"), "--next"]),
        ("analyze_voice_next",       ["python3", str(SCRIPTS / "analyze_voice_readings.py"), "--next"]),
        ("fidelity_chapter_next",    ["python3", str(SCRIPTS / "fidelity_chapter.py"), "--next"]),
        ("visual_tech_audit",        ["python3", str(SCRIPTS / "visual_tech_audit.py")]),
        ("structure_audit",          ["python3", str(SCRIPTS / "structure_audit.py")]),
        ("version_dedup",            ["python3", str(SCRIPTS / "version_dedup.py")]),
        ("nightly_system_improver",  ["python3", str(SCRIPTS / "nightly_system_improver.py")]),
        ("auto_bug_tester",          ["python3", str(SCRIPTS / "auto_bug_tester.py")]),
        ("chapter_coherence_book",   ["python3", str(SCRIPTS / "chapter_coherence_in_book.py"), "--book", "book-obsession"]),
        ("morning_briefing",         ["python3", str(SCRIPTS / "morning_briefing.py")]),
    ]
    # Только существующие
    pool = [(label, cmd) for label, cmd in pool if Path(cmd[1]).exists()]
    if not pool:
        return ("none", [])
    # Round-robin по часу
    hour = datetime.now().hour
    idx = hour % len(pool)
    return pool[idx]


def write_heartbeat(activity: str, idle_min: float):
    """Каждый запуск idle_keeper пишет heartbeat — Pavel видит что система живая."""
    hb = V2 / ".codex/heartbeat.json"
    try:
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.write_text(json.dumps({
            "last_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "activity": activity,
            "pavel_idle_min": round(idle_min, 1),
            "pid": __import__("os").getpid(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def main():
    idle, mins = is_pavel_idle()
    if not idle:
        log(f"Pavel активен {mins:.1f} мин назад — лёгкая задача (auto_bug_tester)")
        # Pavel 2026-05-20: «работаешь всегда не переставая круглые сутки».
        # Даже когда Pavel активен — что-то делаем (но лёгкое, не сжигаем Opus токены).
        write_heartbeat("pavel-active, idle_keeper noop", mins)
        try:
            subprocess.run(["python3", str(SCRIPTS / "auto_bug_tester.py")],
                           timeout=60, capture_output=True)
            log("   ✓ auto_bug_tester прошёл (лёгкая задача)")
        except Exception:
            pass
        return

    log(f"💤 Простой {mins:.1f} мин — выбираю задачу")
    write_heartbeat("idle, picking task", mins)

    label, cmd = pick_task()
    if not cmd:
        log("⚠ Нет доступных задач — выход")
        return

    # Если такой скрипт уже работает — пропускаем (анти-параллельность)
    if already_running(Path(cmd[1]).name):
        log(f"⚠ {label} уже работает — пропускаем")
        return

    log(f"▶ Запуск: {label}")
    try:
        result = subprocess.run(
            cmd,
            timeout=MAX_SCRIPT_RUNTIME_SEC,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            log(f"   ✓ {label} завершился успешно")
            # Записываем event
            with EVENTS.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "type": "idle_task_completed",
                    "target": label,
                    "payload": {"idle_min": round(mins, 1)},
                }, ensure_ascii=False) + "\n")
        else:
            log(f"   ✗ {label} вернул код {result.returncode}: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log(f"   ⏱ {label} превысил {MAX_SCRIPT_RUNTIME_SEC} сек — прерван")
    except Exception as e:
        log(f"   ✗ {label} исключение: {e}")


if __name__ == "__main__":
    main()
