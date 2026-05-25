#!/usr/bin/env python3
"""
timesheet.py — авто-отчёт о работе ночью.

Читает:
- .codex/events.jsonl       — все события системы (упаковка, fidelity, scope-decisions, ...)
- .codex/watcher.log        — лог watcher-а (итерации, время, обработанные файлы)
- reports/fidelity/*.md     — fidelity-отчёты с tokens usage
- reports/competitors/*.md  — отчёты конкурент-агентов
- reports/research/*.md     — research отчёты
- reports/lessons-from-past.md
- reports/MORNING-PLAN.md

Генерирует:
- reports/TIMESHEET.md — «сколько часов работал, что сделал, сколько токенов»

Запуск:
    python3 timesheet.py
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path


HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
EVENTS = V2 / ".codex/events.jsonl"
WATCHER_LOG = V2 / ".codex/watcher.log"
REPORTS = V2 / "reports"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_events() -> list:
    if not EVENTS.exists():
        return []
    out = []
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def parse_tokens_from_report(md_path: Path) -> dict:
    """Достать tokens in/out из шапки fidelity-отчёта."""
    if not md_path.exists():
        return {"in": 0, "out": 0}
    text = md_path.read_text(encoding="utf-8")[:2000]
    m_in = re.search(r"in\s+(\d+)", text)
    m_out = re.search(r"out\s+(\d+)", text)
    return {
        "in": int(m_in.group(1)) if m_in else 0,
        "out": int(m_out.group(1)) if m_out else 0,
    }


def parse_watcher_iterations() -> dict:
    """Подсчитать сколько итераций было."""
    if not WATCHER_LOG.exists():
        return {"iterations": 0, "first": None, "last": None}
    text = WATCHER_LOG.read_text(encoding="utf-8")
    iter_lines = re.findall(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] ── Iteration (\d+)", text)
    if not iter_lines:
        return {"iterations": 0, "first": None, "last": None}
    return {
        "iterations": len(iter_lines),
        "first": iter_lines[0][0],
        "last": iter_lines[-1][0],
    }


def gather_stats() -> dict:
    events = parse_events()
    watcher = parse_watcher_iterations()
    # Время работы — от первого события до последнего
    if events:
        first_ts = events[0].get("ts", "")
        last_ts = events[-1].get("ts", "")
    else:
        first_ts = last_ts = ""
    # Tokens
    fid_dir = REPORTS / "fidelity"
    fid_files = sorted(fid_dir.glob("*.md")) if fid_dir.exists() else []
    total_in = total_out = 0
    fid_tokens = []
    for f in fid_files:
        t = parse_tokens_from_report(f)
        total_in += t["in"]
        total_out += t["out"]
        fid_tokens.append({"chapter": f.stem, "in": t["in"], "out": t["out"]})
    # Counts
    by_type = {}
    for e in events:
        t = e.get("type", "?")
        by_type[t] = by_type.get(t, 0) + 1
    # Reports
    comp_dir = REPORTS / "competitors"
    competitors = sorted(comp_dir.glob("*.md")) if comp_dir.exists() else []
    research_dir = REPORTS / "research"
    research = sorted(research_dir.glob("*.md")) if research_dir.exists() else []
    return {
        "first_event": first_ts,
        "last_event": last_ts,
        "watcher": watcher,
        "events_total": len(events),
        "events_by_type": by_type,
        "fidelity_reports": len(fid_files),
        "fidelity_tokens": fid_tokens,
        "total_opus_tokens_in": total_in,
        "total_opus_tokens_out": total_out,
        "competitor_reports": [c.name for c in competitors],
        "research_reports": [r.name for r in research],
    }


def elapsed_hours(start: str, end: str) -> float:
    if not start or not end:
        return 0
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return round((e - s).total_seconds() / 3600, 2)
    except Exception:
        return 0


def render(stats: dict) -> str:
    hours = elapsed_hours(stats["first_event"], stats["last_event"])
    out = [
        f"# 🕐 TIMESHEET — Codex v2 рабочая ночь",
        "",
        f"**Сгенерировано:** {now_iso()}",
        f"**Начало работы (первое событие):** {stats['first_event']}",
        f"**Последнее событие:** {stats['last_event']}",
        f"**Общее время:** {hours} часов",
        "",
        "---",
        "",
        "## 📊 Цифры по работе",
        "",
        f"- **Итераций watcher-а:** {stats['watcher']['iterations']}",
        f"- **Событий в журнале:** {stats['events_total']}",
        f"- **Fidelity-отчётов сгенерировано:** {stats['fidelity_reports']}",
        f"- **Конкурент-отчётов:** {len(stats['competitor_reports'])}",
        f"- **Research-отчётов:** {len(stats['research_reports'])}",
        f"- **Opus 4.7 tokens IN всего:** {stats['total_opus_tokens_in']:,}",
        f"- **Opus 4.7 tokens OUT всего:** {stats['total_opus_tokens_out']:,}",
        f"- **Tokens IN+OUT суммарно:** {stats['total_opus_tokens_in'] + stats['total_opus_tokens_out']:,}",
        "",
        "## 🗂 События по типам",
        "",
    ]
    for t, c in sorted(stats["events_by_type"].items(), key=lambda x: -x[1]):
        out.append(f"- `{t}` × **{c}**")
    out.append("")
    out.append("## 🎯 Fidelity отчёты (Opus 4.7 + thinking + Council + Anti-drift)")
    out.append("")
    out.append("| Глава | Tokens in | Tokens out |")
    out.append("|---|---|---|")
    for f in stats["fidelity_tokens"]:
        out.append(f"| `{f['chapter']}` | {f['in']:,} | {f['out']:,} |")
    if not stats["fidelity_tokens"]:
        out.append("| _(пока пусто)_ | | |")
    out.append("")
    out.append("## 🏆 Конкурентный анализ (8 параллельных агентов)")
    out.append("")
    for c in stats["competitor_reports"]:
        out.append(f"- `competitors/{c}`")
    if not stats["competitor_reports"]:
        out.append("- _(пока не завершены)_")
    out.append("")
    out.append("## 🔬 Research")
    out.append("")
    for r in stats["research_reports"]:
        out.append(f"- `research/{r}`")
    if not stats["research_reports"]:
        out.append("- _(пока не завершены)_")
    out.append("")
    out.append("## 📁 Артефакты на диске")
    out.append("")
    out.append("```")
    out.append(f"~/Desktop/Codex2/reports/MORNING-PLAN.md                 ← главный план")
    out.append(f"~/Desktop/Codex2/reports/overnight-style-scan.md         ← корпус с %")
    out.append(f"~/Desktop/Codex2/reports/lessons-from-past.md            ← уроки v1")
    out.append(f"~/Desktop/Codex2/reports/research/*.md                   ← best practices")
    out.append(f"~/Desktop/Codex2/reports/competitors/*.md                ← 8 конкурентов")
    out.append(f"~/Desktop/Codex2/reports/fidelity/*.md                   ← глубокий разбор глав")
    out.append(f"~/Desktop/Codex2/reports/TIMESHEET.md                    ← этот файл")
    out.append("```")
    return "\n".join(out)


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    stats = gather_stats()
    md = render(stats)
    out_path = REPORTS / "TIMESHEET.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"✓ TIMESHEET: {out_path}")
    print(f"  Часов работы: {elapsed_hours(stats['first_event'], stats['last_event'])}")
    print(f"  Tokens in/out: {stats['total_opus_tokens_in']:,} / {stats['total_opus_tokens_out']:,}")
    print(f"  Fidelity: {stats['fidelity_reports']} · Competitors: {len(stats['competitor_reports'])} · Research: {len(stats['research_reports'])}")


if __name__ == "__main__":
    main()
