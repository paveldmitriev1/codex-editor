#!/usr/bin/env python3
"""UC-131: автономный агент Codex2.

Pavel: «создай робота агента который каждые 5 минут будет компьютер
перезапускать и включать тебя».

Каждый прогон (через launchd StartInterval=300):
  1. Проверить что server 7788 жив. Если нет — запустить.
  2. Найти главы где есть critics но нет reconciled — запустить.
  3. Найти главы где есть critics но нет personas — запустить.
  4. Найти главы где есть critics но нет sequence — запустить.
  5. Найти главы где нет voice-analysis — запустить.
  6. Если уже 5+ задач в работе — пропустить (не штормить proxy).
  7. Записать отчёт в /tmp/codex2-auto-agent.log.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
LOG = Path("/tmp/codex2-auto-agent.log")
MAX_PARALLEL = 5  # не более 5 параллельных задач


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}\n"
    with LOG.open("a") as f:
        f.write(line)
    print(line, end="", flush=True)


def count_active_processes():
    """Сколько наших скриптов сейчас крутится."""
    try:
        out = subprocess.check_output(["ps", "ax"], text=True)
    except Exception:
        return 0
    n = 0
    for line in out.splitlines():
        if any(s in line for s in [
            "scripts/reconciler.py",
            "scripts/personas.py",
            "scripts/sequence_analyzer.py",
            "scripts/critic_council.py",
            "scripts/analyze_voice_readings.py",
        ]):
            n += 1
    return n


def server_alive():
    try:
        with urllib.request.urlopen("http://127.0.0.1:7788/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def start_server():
    log("Server upping…")
    log_path = Path("/tmp/server.log")
    subprocess.Popen(
        ["python3", str(V2 / "app/server.py")],
        stdout=log_path.open("a"),
        stderr=subprocess.STDOUT,
        cwd=str(V2),
        start_new_session=True,
    )
    time.sleep(2)


def chapters_with_critics():
    reports = V2 / "reports"
    if not reports.exists():
        return []
    seen = set()
    for f in reports.glob("CRITICS-*.json"):
        # Имя: CRITICS-<chapter_id>-<ts>.json
        name = f.stem
        try:
            parts = name.split("-")
            ts_idx = next(i for i, p in enumerate(parts) if p.startswith("20") and "T" in p)
            ch = "-".join(parts[1:ts_idx])
            seen.add(ch)
        except Exception:
            continue
    return sorted(seen)


def has_cache(kind, ch):
    return (V2 / f"data/{kind}/{ch}.json").exists()


def has_voice_analysis(ch):
    import re
    m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", ch)
    if not m:
        return False
    book_id = m.group(1)
    return (V2 / f"chapters/{book_id}/{ch}/voice-analysis.json").exists()


def has_draft(ch):
    import re
    m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", ch)
    if not m:
        return False
    book_id = m.group(1)
    return (V2 / f"chapters/{book_id}/{ch}/draft.md").exists()


def launch_bg(script, args):
    log_path = Path(f"/tmp/codex2-auto-{script}-{int(time.time())}.log")
    subprocess.Popen(
        ["python3", str(V2 / "scripts" / script)] + args,
        stdout=log_path.open("a"),
        stderr=subprocess.STDOUT,
        cwd=str(V2),
        start_new_session=True,
    )


def main():
    log("════════ AUTO-AGENT TICK ════════")
    # 1. Server check
    if not server_alive():
        start_server()
        if server_alive():
            log("✓ Server поднят")
        else:
            log("✗ Server не отвечает после рестарта")
    else:
        log("✓ Server жив")

    active = count_active_processes()
    log(f"Активных скриптов: {active}/{MAX_PARALLEL}")
    if active >= MAX_PARALLEL:
        log("→ Лимит достигнут, пропускаю запуск новых задач")
        return

    slots = MAX_PARALLEL - active

    # 2. Найти gaps
    crit_chs = chapters_with_critics()
    log(f"Глав с CRITICS: {len(crit_chs)}")

    gaps = {
        "reconciler.py": [],
        "personas.py": [],
        "sequence_analyzer.py": [],
        "analyze_voice_readings.py": [],
    }
    for ch in crit_chs:
        if not has_draft(ch):
            continue
        if not has_cache("reconciled", ch):
            gaps["reconciler.py"].append(ch)
        if not has_cache("personas", ch):
            gaps["personas.py"].append(ch)
        if not has_cache("sequence", ch):
            gaps["sequence_analyzer.py"].append(ch)
        if not has_voice_analysis(ch):
            gaps["analyze_voice_readings.py"].append(ch)

    # 3. Запустить что не хватает (по 1 на тип чтобы не штормить)
    launched = 0
    for script, chs in gaps.items():
        if launched >= slots:
            break
        if not chs:
            continue
        ch = chs[0]  # самая первая
        log(f"→ Запускаю {script} для {ch}")
        if script == "reconciler.py":
            launch_bg(script, ["--chapter-id", ch, "--force"])
        elif script == "personas.py":
            launch_bg(script, ["--chapter-id", ch])
        elif script == "sequence_analyzer.py":
            launch_bg(script, ["--chapter-id", ch, "--force"])
        elif script == "analyze_voice_readings.py":
            launch_bg(script, ["--chapter", ch])
        launched += 1

    if launched == 0:
        log("✓ Все главы покрыты, запускать нечего")

    # 4. Сводка кэшей
    rec = len(list((V2 / "data/reconciled").glob("*.json"))) if (V2 / "data/reconciled").exists() else 0
    per = len(list((V2 / "data/personas").glob("*.json"))) if (V2 / "data/personas").exists() else 0
    seq = len(list((V2 / "data/sequence").glob("*.json"))) if (V2 / "data/sequence").exists() else 0
    log(f"Cache: reconciled={rec} personas={per} sequence={seq}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {e}")
        sys.exit(1)
