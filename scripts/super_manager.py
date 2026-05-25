#!/usr/bin/env python3
"""
super_manager.py — главный менеджер 24/7 (Pavel 2026-05-21).

Pavel: «создать бота который каждые полчаса всё перепроверяет — ошибки, дизайн,
глюки в системе. Главный менеджер. Работает круглые сутки всегда. Потом пишет
мне репорт».

Запускается через launchd `ai.codex2.manager` каждые 1800 сек (30 минут).
Независим от Python-watcher / marathon / любых моих фоновых процессов —
работает пока Mac включён.

Каждый цикл:
1. Health-check всех процессов (server, marathon, watcher) — рестарт если мёртвы
2. Endpoint smoke (15 ключевых endpoint-ов) — проверка кодов и JSON
3. auto_bug_tester (JS undefined, broken IDs, dead routes)
4. visual_tech_audit (hardcoded colors, inconsistent buttons)
5. Проверка drafts на «№N» мусор-префиксы
6. Свежесть кэшей анализов глав (старше 7 дней → отметить)
7. Записывает живой отчёт MANAGER-REPORT.md (одна страница, перезаписывается)
8. Добавляет в MANAGER-LOG.md (append, история всех циклов)
9. Event `manager_cycle` в events.jsonl

Запуск:
  python3 scripts/super_manager.py        # один прогон
  Через launchd — каждые 30 мин автоматом
"""
import json
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
SCRIPTS = V2 / "scripts"
REPORTS = V2 / "reports"
EVENTS = V2 / ".codex/events.jsonl"
REPORT_LIVE = REPORTS / "MANAGER-REPORT.md"
LOG_APPEND = REPORTS / "MANAGER-LOG.md"
SERVER_URL = "http://127.0.0.1:7788"

(V2 / ".codex").mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_human() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ────────────────────────────────────────────────────
# 1. PROCESS HEALTH
# ────────────────────────────────────────────────────

def check_pid_file(pid_file: Path, cmd_substring: str) -> dict:
    if not pid_file.exists():
        return {"alive": False, "reason": "no PID file"}
    try:
        pid = int(pid_file.read_text().strip())
    except Exception:
        return {"alive": False, "reason": "bad PID file"}
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return {"alive": False, "reason": f"PID {pid} dead"}
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                       text=True, timeout=2).strip()
        if cmd_substring not in out:
            return {"alive": False, "reason": f"PID {pid} ≠ {cmd_substring}"}
    except Exception as e:
        return {"alive": False, "reason": str(e)}
    return {"alive": True, "pid": pid}


def server_alive() -> bool:
    try:
        out = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{SERVER_URL}/api/health", "--max-time", "3"],
            text=True, timeout=5,
        )
        return out.strip() == "200"
    except Exception:
        return False


def restart_server() -> bool:
    try:
        subprocess.run(["bash", "-c",
                        "lsof -ti tcp:7788 | xargs -r kill -9 2>/dev/null; sleep 1; "
                        "cd ~/Desktop/Codex2/app && nohup python3 server.py "
                        "> /tmp/codex2-server.log 2>&1 &"], timeout=10)
        time.sleep(3)
        return server_alive()
    except Exception:
        return False


def restart_marathon():
    try:
        subprocess.Popen(
            ["nohup", "python3", str(SCRIPTS / "night_marathon.py")],
            stdout=open("/tmp/marathon.log", "a"), stderr=subprocess.STDOUT,
            cwd=str(V2),
        )
    except Exception:
        pass


def restart_watcher():
    try:
        subprocess.Popen(
            ["nohup", "bash", str(SCRIPTS / "overnight_watcher.sh")],
            stdout=open(V2 / ".codex/watcher.log", "a"), stderr=subprocess.STDOUT,
            cwd=str(V2),
        )
    except Exception:
        pass


def process_health() -> dict:
    actions = []
    # server
    s_alive = server_alive()
    if not s_alive:
        actions.append("server мёртв → рестарт")
        s_alive = restart_server()
        actions.append("server " + ("поднят" if s_alive else "НЕ поднимается"))

    # marathon
    m = check_pid_file(V2 / ".codex/night-marathon.pid", "night_marathon.py")
    if not m["alive"]:
        actions.append(f"marathon мёртв ({m['reason']}) → рестарт")
        restart_marathon()
        time.sleep(1)
        m = check_pid_file(V2 / ".codex/night-marathon.pid", "night_marathon.py")

    # watcher
    w = check_pid_file(V2 / ".codex/watcher.pid", "overnight_watcher.sh")
    if not w["alive"]:
        actions.append(f"watcher мёртв ({w['reason']}) → рестарт")
        restart_watcher()
        time.sleep(1)
        w = check_pid_file(V2 / ".codex/watcher.pid", "overnight_watcher.sh")

    return {
        "server_alive": s_alive,
        "marathon": m,
        "watcher": w,
        "actions": actions,
    }


# ────────────────────────────────────────────────────
# 2. ENDPOINTS SMOKE
# ────────────────────────────────────────────────────

def endpoint_smoke() -> dict:
    endpoints = [
        ("GET",  "/api/health"),
        ("GET",  "/api/toc"),
        ("GET",  "/api/heartbeat"),
        ("GET",  "/api/briefing"),
        ("GET",  "/api/chapter/book-obsession-ch-02/draft"),
        ("GET",  "/api/chapter/book-obsession-ch-02/style-coherence"),
        ("GET",  "/api/chapter/book-obsession-ch-02/logic-analysis"),
        ("GET",  "/api/chapter/book-obsession-ch-02/resonance"),
        ("GET",  "/api/chapter/book-obsession-ch-02/hook-cliff"),
        ("GET",  "/api/chapter/book-obsession-ch-02/coherence-in-book"),
        ("POST", "/api/chapter/book-obsession-ch-02/edited-paragraphs"),
        ("GET",  "/api/chapter/book-obsession-ch-02/notes"),
        ("GET",  "/api/chapter/book-obsession-ch-02/approvals"),
    ]
    ok = 0
    fails = []
    for method, path in endpoints:
        try:
            args = ["curl", "-s", "-o", "/tmp/mgr-out", "-w", "%{http_code}",
                    "-X", method, f"{SERVER_URL}{path}", "--max-time", "8"]
            if method == "POST":
                args.extend(["-H", "Content-Type: application/json", "-d", "{}"])
            code = subprocess.check_output(args, text=True, timeout=10).strip()
            if code.startswith("2"):
                ok += 1
            else:
                fails.append({"path": f"{method} {path}", "code": code})
        except Exception as e:
            fails.append({"path": f"{method} {path}", "code": f"exc {e}"})
    return {"ok": ok, "total": len(endpoints), "fails": fails}


# ────────────────────────────────────────────────────
# 3. AUTO-BUG-TESTER
# ────────────────────────────────────────────────────

def run_bug_audit() -> dict:
    try:
        subprocess.run(["python3", str(SCRIPTS / "auto_bug_tester.py")],
                       timeout=90, capture_output=True)
    except Exception:
        pass
    audit = REPORTS / "AUTO-BUG-AUDIT.md"
    if not audit.exists():
        return {"total": 0, "by_severity": {}}
    text = audit.read_text(encoding="utf-8")
    by_sev = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for sev in by_sev:
        m = re.search(rf"{sev}: (\d+)", text)
        if m:
            by_sev[sev] = int(m.group(1))
    m = re.search(r"\*\*Всего находок:\*\* (\d+)", text)
    return {"total": int(m.group(1)) if m else 0, "by_severity": by_sev}


# ────────────────────────────────────────────────────
# 4. VISUAL-TECH-AUDIT
# ────────────────────────────────────────────────────

def run_visual_audit() -> dict:
    try:
        subprocess.run(["python3", str(SCRIPTS / "visual_tech_audit.py")],
                       timeout=90, capture_output=True)
    except Exception:
        pass
    vta = REPORTS / "VISUAL-TECH-AUDIT.md"
    if not vta.exists():
        return {"total": 0}
    text = vta.read_text(encoding="utf-8")
    m = re.search(r"\*\*Всего находок:\*\* (\d+)", text)
    return {"total": int(m.group(1)) if m else 0}


# ────────────────────────────────────────────────────
# 5. DRAFT JUNK CHECK (№N префиксы)
# ────────────────────────────────────────────────────

def check_draft_junk() -> list:
    dirty = []
    chapters = V2 / "chapters"
    if not chapters.exists():
        return dirty
    for book in chapters.iterdir():
        if not book.is_dir() or book.name.startswith("."):
            continue
        for ch in book.iterdir():
            draft = ch / "draft.md"
            if not draft.exists():
                continue
            try:
                text = draft.read_text(encoding="utf-8")
            except Exception:
                continue
            junk = re.findall(r"^\s*№\d+\s*$", text, re.MULTILINE)
            if len(junk) > 2:
                dirty.append({"chapter": ch.name, "junk_lines": len(junk)})
    return dirty


# ────────────────────────────────────────────────────
# 6. CACHE FRESHNESS
# ────────────────────────────────────────────────────

def check_cache_freshness() -> dict:
    """Какие кэши анализов глав старше 7 дней?"""
    stale = []
    week_ago = time.time() - 7 * 24 * 3600
    chapters = V2 / "chapters"
    if not chapters.exists():
        return {"stale": []}
    for book in chapters.iterdir():
        if not book.is_dir() or book.name.startswith("."):
            continue
        for ch in book.iterdir():
            for cache_name in ["logic-analysis.json", "style-coherence.json",
                               "resonance.json", "hook-cliff.json"]:
                f = ch / cache_name
                if f.exists() and f.stat().st_mtime < week_ago:
                    stale.append(f"{ch.name}/{cache_name}")
    return {"stale": stale[:20], "total_stale": len(stale)}


# ────────────────────────────────────────────────────
# RENDER REPORT
# ────────────────────────────────────────────────────

def render_report(data: dict) -> str:
    lines = []
    lines.append(f"# Менеджер · отчёт {now_human()}")
    lines.append("")
    lines.append("_живой документ — перезаписывается каждые 30 минут менеджером 24/7_")
    lines.append("")

    # Главное
    p = data["process"]
    server_ok = "✓" if p["server_alive"] else "✗"
    marathon_ok = "✓" if p["marathon"]["alive"] else "✗"
    watcher_ok = "✓" if p["watcher"]["alive"] else "✗"
    overall = "ВСЁ ХОРОШО" if (p["server_alive"] and p["marathon"]["alive"] and p["watcher"]["alive"]) else "ЕСТЬ ПРОБЛЕМЫ"
    lines.append(f"## Состояние: **{overall}**")
    lines.append("")
    lines.append(f"- {server_ok} **Server** :7788" + (f" (PID {p['marathon'].get('pid','?')})" if p["server_alive"] else " — НЕ ОТВЕЧАЕТ"))
    lines.append(f"- {marathon_ok} **Marathon** (ночной тестер)" + (f" PID {p['marathon'].get('pid','?')}" if p["marathon"]["alive"] else f" — {p['marathon'].get('reason','dead')}"))
    lines.append(f"- {watcher_ok} **Watcher** (фоновые задачи)" + (f" PID {p['watcher'].get('pid','?')}" if p["watcher"]["alive"] else f" — {p['watcher'].get('reason','dead')}"))
    if p["actions"]:
        lines.append("")
        lines.append("**Действия менеджера в этом цикле:**")
        for a in p["actions"]:
            lines.append(f"- {a}")
    lines.append("")

    # Endpoints
    e = data["endpoints"]
    lines.append(f"## Endpoints: {e['ok']}/{e['total']} здоровы")
    if e["fails"]:
        lines.append("")
        lines.append("Проблемные:")
        for f in e["fails"]:
            lines.append(f"- `{f['path']}` → {f['code']}")
    lines.append("")

    # Bug audit
    b = data["bug_audit"]
    lines.append(f"## Auto-bug-tester: {b['total']} находок")
    by_sev = b["by_severity"]
    if any(by_sev.values()):
        lines.append(f"- critical: {by_sev.get('critical',0)} · high: {by_sev.get('high',0)} · medium: {by_sev.get('medium',0)} · low: {by_sev.get('low',0)}")
    lines.append(f"- Подробно: `reports/AUTO-BUG-AUDIT.md`")
    lines.append("")

    # Visual audit
    v = data["visual_audit"]
    lines.append(f"## Visual-tech-audit: {v['total']} находок")
    lines.append(f"- Подробно: `reports/VISUAL-TECH-AUDIT.md`")
    lines.append("")

    # Draft junk
    d = data["draft_junk"]
    if d:
        lines.append(f"## ⚠ Draft.md с мусором «№N»: {len(d)} файлов")
        for item in d[:8]:
            lines.append(f"- `chapters/.../{item['chapter']}/draft.md` — {item['junk_lines']} мусорных строк")
        lines.append("")
        lines.append("**Чтобы почистить:** `python3 scripts/cleanup_draft_numbers.py --apply` (с бэкапом в history/)")
        lines.append("")
    else:
        lines.append("## ✓ Draft.md чисты от мусор-префиксов")
        lines.append("")

    # Cache freshness
    c = data["cache"]
    if c["total_stale"]:
        lines.append(f"## ⚠ Старые кэши (>7 дней): {c['total_stale']}")
        for s in c["stale"][:5]:
            lines.append(f"- `{s}`")
        if c["total_stale"] > 5:
            lines.append(f"- _...и ещё {c['total_stale']-5}_")
    else:
        lines.append("## ✓ Все кэши свежие")
    lines.append("")

    # Цикл
    lines.append("---")
    lines.append("")
    lines.append(f"**Цикл:** {data['cycle_sec']:.1f} сек · следующий через 30 минут (launchd `ai.codex2.manager`)")
    lines.append("")
    lines.append("**Хочешь подробнее?** → `reports/MORNING-DIGEST.md` · `reports/MORNING-BRIEFING.md` · `reports/MANAGER-LOG.md` (история циклов)")
    return "\n".join(lines)


def append_log(data: dict):
    """Короткая строка в MANAGER-LOG.md."""
    p = data["process"]
    e = data["endpoints"]
    line = (f"[{now_human()}] "
            f"server={'✓' if p['server_alive'] else '✗'} "
            f"marathon={'✓' if p['marathon']['alive'] else '✗'} "
            f"watcher={'✓' if p['watcher']['alive'] else '✗'} "
            f"endpoints={e['ok']}/{e['total']} "
            f"bugs={data['bug_audit']['total']} "
            f"vta={data['visual_audit']['total']} "
            f"junk={len(data['draft_junk'])} "
            f"stale={data['cache']['total_stale']} "
            f"actions={len(p['actions'])}")
    REPORTS.mkdir(parents=True, exist_ok=True)
    with LOG_APPEND.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    t0 = time.time()
    data = {}
    data["process"] = process_health()
    data["endpoints"] = endpoint_smoke()
    data["bug_audit"] = run_bug_audit()
    data["visual_audit"] = run_visual_audit()
    data["draft_junk"] = check_draft_junk()
    data["cache"] = check_cache_freshness()
    data["cycle_sec"] = time.time() - t0
    data["ts"] = now_iso()

    REPORTS.mkdir(parents=True, exist_ok=True)
    REPORT_LIVE.write_text(render_report(data), encoding="utf-8")
    append_log(data)

    # Event
    try:
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": data["ts"],
                "type": "manager_cycle",
                "target": "system",
                "payload": {
                    "server_alive": data["process"]["server_alive"],
                    "endpoints_ok": data["endpoints"]["ok"],
                    "bugs": data["bug_audit"]["total"],
                    "actions": data["process"]["actions"],
                },
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    print(f"✓ Менеджер: {data['cycle_sec']:.1f}s · "
          f"server={data['process']['server_alive']} · "
          f"endpoints={data['endpoints']['ok']}/{data['endpoints']['total']} · "
          f"bugs={data['bug_audit']['total']}")


if __name__ == "__main__":
    main()
