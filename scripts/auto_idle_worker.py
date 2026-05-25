#!/usr/bin/env python3
"""Auto idle worker — launchd job, запускается каждые 5 минут.

Pavel 2026-05-25: «бот должен каждые 5 минут тебя не будет» — постоянная
работа в фоне даже когда Pavel offline.

Что делает per tick:
1. Проверяет что сервер 7788 жив. Если нет — поднимает.
2. Если есть главы без свежего master-audit cache — запускает async master-audit
   для одной (не больше — чтобы не нагрузить proxy).
3. Логирует в /tmp/codex2-auto-agent.log
"""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
SERVER = "http://127.0.0.1:7788"
CACHE_MAX_AGE_HOURS = 168  # неделя — после этого можно перезапустить


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def server_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{SERVER}/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def find_stale_chapter() -> str:
    """Найти одну главу у которой нет свежего master-audit cache."""
    chapters_dir = ROOT / "chapters"
    if not chapters_dir.exists():
        return None
    candidates = []
    for book_dir in sorted(chapters_dir.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or "-ch-" not in ch_dir.name:
                continue
            draft = ch_dir / "draft.md"
            if not draft.exists() or draft.stat().st_size < 500:
                continue
            cache = ROOT / "data" / "master-audit" / f"{ch_dir.name}.json"
            if not cache.exists():
                candidates.append(ch_dir.name)
                continue
            age_hours = (time.time() - cache.stat().st_mtime) / 3600
            if age_hours > CACHE_MAX_AGE_HOURS:
                candidates.append(ch_dir.name)
    return candidates[0] if candidates else None


def trigger_master_audit(chapter_id: str) -> bool:
    """Запустить master-audit-start async. Worker thread сам всё сделает."""
    try:
        req = urllib.request.Request(
            f"{SERVER}/api/chapter/master-audit-start",
            data=json.dumps({"chapter_id": chapter_id}).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("ok", False)
    except Exception as e:
        log(f"  ERROR trigger {chapter_id}: {e}")
        return False


def main():
    log("=== auto_idle_worker tick ===")
    if not server_alive():
        log("server DOWN — watchdog должен поднять, выхожу")
        return 1
    log("server alive")

    # Сколько активных jobs?
    active_dir = ROOT / ".codex/active-jobs"
    if active_dir.exists():
        active = [f for f in active_dir.glob("*.json") if not f.name.endswith(".done.json")]
        if len(active) >= 2:
            log(f"уже {len(active)} active jobs — пропускаю запуск нового")
            return 0

    stale = find_stale_chapter()
    if not stale:
        log("все главы имеют свежий cache, нечего делать")
        return 0

    log(f"запускаю master-audit для {stale}")
    if trigger_master_audit(stale):
        log(f"  → started в фоне")
    else:
        log(f"  → failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
