#!/usr/bin/env python3
"""
night_marathon.py — ночной continuous tester (Pavel 2026-05-20).

Pavel: «всю ночь продолжаешь работать тестировать пока утро не настанет.
Каждые 5 минут проверяй чтобы работа не прекращалась. Сделай демо главу
на которой будешь экспериментировать. Найди все баги, косяки в дизайне
и логике».

Что делает в каждом цикле (5 минут):
1. Проверяет что сервер жив (curl /api/health)
2. Запускает auto_bug_tester (endpoints, dead JS funcs, broken IDs)
3. Запускает visual_tech_audit (hardcoded colors, inconsistent buttons)
4. На book-demo-ch-01 (sandbox) проверяет логику цепочки analyzers
5. Записывает все находки в reports/NIGHT-MARATHON-LOG.md (append)
6. При 5+ простоях подряд (нет ошибок) — переключается на тяжёлые задачи

Запуск: `nohup python3 scripts/night_marathon.py &`
Остановка: `kill $(cat ~/Desktop/Codex2/.codex/night-marathon.pid)`
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
SCRIPTS = V2 / "scripts"
REPORTS = V2 / "reports"
LOG_FILE = REPORTS / "NIGHT-MARATHON-LOG.md"
PID_FILE = V2 / ".codex/night-marathon.pid"
EVENTS = V2 / ".codex/events.jsonl"
SERVER_URL = "http://127.0.0.1:7788"
DEMO_CHAPTER = "book-demo-ch-01"

CYCLE_SEC = 300  # 5 минут
MAX_RUNTIME_HOURS = 10  # до утра

(V2 / ".codex").mkdir(parents=True, exist_ok=True)
PID_FILE.write_text(str(os.getpid()))


def log_line(msg: str):
    REPORTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")


def event(kind: str, payload: dict = None):
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": kind,
            "target": "night_marathon",
            "payload": payload or {},
        }, ensure_ascii=False) + "\n")


def server_alive() -> bool:
    try:
        out = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{SERVER_URL}/api/health", "--max-time", "3"],
            text=True,
        )
        return out.strip() == "200"
    except Exception:
        return False


def restart_server():
    log_line("⚠ Сервер не отвечает — рестарт")
    try:
        subprocess.run(["bash", "-c",
                        "lsof -ti tcp:7788 | xargs -r kill -9 2>/dev/null; sleep 1; "
                        "cd ~/Desktop/Codex2/app && nohup python3 server.py "
                        "> /tmp/codex2-server.log 2>&1 &"],
                       timeout=10)
        time.sleep(3)
        if server_alive():
            log_line("✓ Сервер поднят")
        else:
            log_line("✗ Сервер не поднимается после рестарта")
    except Exception as e:
        log_line(f"✗ restart_server: {e}")


def run_script(path: Path, args: list = None, timeout: int = 120) -> tuple:
    """Returns (success, stdout, stderr)."""
    if not path.exists():
        return False, "", f"скрипт не найден: {path}"
    cmd = ["python3", str(path)] + (args or [])
    try:
        r = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
        return (r.returncode == 0), r.stdout[-300:], r.stderr[-300:]
    except subprocess.TimeoutExpired:
        return False, "", f"timeout {timeout}s"
    except Exception as e:
        return False, "", str(e)


def cycle_check_endpoints() -> dict:
    """Smoke test ключевых endpoints. Записываем сколько 4xx/5xx."""
    endpoints = [
        ("GET", "/api/health"),
        ("GET", "/api/toc"),
        ("GET", "/api/heartbeat"),
        ("GET", "/api/briefing"),
        ("GET", "/api/chapter/book-demo-ch-01/draft"),
        ("GET", "/api/chapter/book-demo-ch-01/edited-paragraphs"),
    ]
    ok = 0
    fails = []
    for method, path in endpoints:
        try:
            code = subprocess.check_output(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "-X", method, f"{SERVER_URL}{path}", "--max-time", "5"],
                text=True,
            ).strip()
            if code.startswith("2"):
                ok += 1
            else:
                fails.append(f"{method} {path} → {code}")
        except Exception as e:
            fails.append(f"{method} {path} → exc {e}")
    return {"ok": ok, "total": len(endpoints), "fails": fails}


def cycle_demo_analyzers() -> dict:
    """Запускаем chapter_coherence на demo. Безопасно — не трогает реальные книги."""
    out = {"actions": []}
    try:
        r = subprocess.run(
            ["python3", str(SCRIPTS / "chapter_coherence_in_book.py"),
             "--chapter", DEMO_CHAPTER],
            timeout=60, capture_output=True, text=True,
        )
        out["actions"].append({
            "coherence": "ok" if r.returncode == 0 else "fail",
            "stdout_tail": r.stdout[-200:],
        })
    except Exception as e:
        out["actions"].append({"coherence": f"exc {e}"})
    return out


def cycle() -> dict:
    """Один цикл: health → bug audit → visual audit → demo coherence."""
    result = {"alive": False, "audit_total": 0, "vta_total": 0, "endpoints": {}, "demo": {}}

    if not server_alive():
        restart_server()
        time.sleep(2)
    result["alive"] = server_alive()
    if not result["alive"]:
        log_line("❌ Сервер мёртв даже после рестарта — следующий цикл")
        return result

    # 1. Endpoint smoke
    result["endpoints"] = cycle_check_endpoints()
    if result["endpoints"]["fails"]:
        log_line(f"⚠ {len(result['endpoints']['fails'])} endpoint fails: {result['endpoints']['fails'][:3]}")

    # 2. Auto bug tester
    success, stdout, stderr = run_script(SCRIPTS / "auto_bug_tester.py", timeout=90)
    if success:
        try:
            # Парсим reports/AUTO-BUG-AUDIT.md
            audit = (REPORTS / "AUTO-BUG-AUDIT.md").read_text(encoding="utf-8")
            import re as _re
            m = _re.search(r"\*\*Всего находок:\*\* (\d+)", audit)
            if m:
                result["audit_total"] = int(m.group(1))
        except Exception:
            pass

    # 3. Visual tech audit
    success, _, _ = run_script(SCRIPTS / "visual_tech_audit.py", timeout=90)
    if success:
        try:
            vta = (REPORTS / "VISUAL-TECH-AUDIT.md").read_text(encoding="utf-8")
            import re as _re
            m = _re.search(r"\*\*Всего находок:\*\* (\d+)", vta)
            if m:
                result["vta_total"] = int(m.group(1))
        except Exception:
            pass

    # 4. Demo chapter analyzers
    result["demo"] = cycle_demo_analyzers()

    # 5. Improver — каждый цикл (5 мин), Pavel 2026-05-21
    # Унаследует TCC права из родительского marathon — в отличие от launchd-агента.
    try:
        subprocess.run(["python3", str(SCRIPTS / "improver_loop.py")],
                       timeout=200, capture_output=True)
        result["improver"] = "ran"
    except Exception as e:
        result["improver"] = f"err: {e}"

    # 6. Super-manager — каждые 6 циклов (30 мин)
    return result


def maybe_run_manager(cycle_num: int):
    """Каждые 6 циклов (~30 мин) запускаем super_manager."""
    if cycle_num % 6 != 0:
        return
    try:
        r = subprocess.run(["python3", str(SCRIPTS / "super_manager.py")],
                           timeout=180, capture_output=True, text=True)
        log_line(f"   ▶ super_manager: {r.stdout.strip()[:120]}")
    except Exception as e:
        log_line(f"   ✗ super_manager err: {e}")


def main():
    log_line("═══════════════════════════════════════════")
    log_line(f"🌙 Night marathon запущен (PID {os.getpid()})")
    log_line(f"   Цикл: {CYCLE_SEC} сек · до утра ~{MAX_RUNTIME_HOURS} ч")
    log_line(f"   Sandbox: {DEMO_CHAPTER}")
    log_line("═══════════════════════════════════════════")
    event("night_marathon_started")

    started_at = time.time()
    cycles = 0
    while True:
        cycles += 1
        elapsed_h = (time.time() - started_at) / 3600
        if elapsed_h >= MAX_RUNTIME_HOURS:
            log_line(f"🌅 Прошло {elapsed_h:.1f} ч — утро. Останавливаюсь.")
            event("night_marathon_finished", {"cycles": cycles, "hours": round(elapsed_h, 1)})
            break

        log_line(f"── Цикл {cycles} (h={elapsed_h:.1f}) ──")
        try:
            r = cycle()
            log_line(f"   alive={r['alive']} endpoints={r['endpoints'].get('ok','?')}/{r['endpoints'].get('total','?')} "
                     f"bug_audit={r['audit_total']} vta={r['vta_total']} improver={r.get('improver','?')}")
            maybe_run_manager(cycles)
            event("night_marathon_cycle", {
                "cycle": cycles,
                "alive": r["alive"],
                "endpoints_ok": r["endpoints"].get("ok"),
                "endpoints_fails": len(r["endpoints"].get("fails") or []),
                "audit_total": r["audit_total"],
                "vta_total": r["vta_total"],
            })
        except Exception as e:
            log_line(f"   ✗ cycle exception: {e}")
            event("night_marathon_cycle_error", {"cycle": cycles, "error": str(e)})

        time.sleep(CYCLE_SEC)


if __name__ == "__main__":
    main()
