#!/usr/bin/env python3
"""
morning_briefing.py — единый утренний брифинг (Pavel 2026-05-20 UC-24).

Pavel: «объединение утренний план и рекомендации в одной секции. Каждое утро —
рекомендации по упрощению процессов: меньше работы, мощнее результат».

Что делает:
1. Запускает morning_plan_generator.py + daily_recommendations.py + auto_bug_tester.py
2. Сшивает их в единый `reports/MORNING-BRIEFING.md` с разделами:
   - 🌅 ПЛАН НА ДЕНЬ (приоритет book-obsession)
   - 🔧 УПРОЩЕНИЯ ПРОЦЕССОВ — что автоматизировать чтобы работы меньше
   - 🐛 БАГ-АУДИТ — что найдено за ночь
   - 📊 ПРОГРЕСС
3. Удаляет старые разрозненные отчёты (если все вошли в брифинг)

Запуск: `python3 morning_briefing.py` (вызывается из overnight_watcher.sh в 06:00)
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
REPORTS = V2 / "reports"
OUTPUT = REPORTS / "MORNING-BRIEFING.md"
SCRIPTS = V2 / "scripts"


def run_script(name: str) -> bool:
    """Запустить один из скриптов, return True if ok."""
    path = SCRIPTS / name
    if not path.exists():
        return False
    try:
        result = subprocess.run(
            ["python3", str(path)],
            timeout=300,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def read_section(filepath: Path, max_lines: int = 80) -> str:
    """Прочитать отчёт, обрезать."""
    if not filepath.exists():
        return f"_(нет файла: {filepath.name})_\n"
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n\n_... ещё {len(lines) - max_lines} строк в {filepath.name}_\n"
    return text


def clean_imported_text(text: str) -> str:
    """UC-73 (Pavel 2026-05-21): подчищает текст вставляемый в брифинг —
    убирает эмодзи, мусорные h1 (« # MORNING PLAN ... »), tech-meta строки,
    дублирующие разделители ---.
    Содержимое /briefing рендерится через markdown — мусор виден как огромные h1."""
    import re as _re
    # 1. Убираем эмодзи
    text = _re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", text)
    # 2. Убираем строки типа «# MORNING PLAN ...» (h1 внутри importable contents)
    new_lines = []
    skip_meta = False
    for line in text.split("\n"):
        stripped = line.strip()
        # h1 (одна #) внутри импорта = мусорный заголовок, превращаем в h2
        if stripped.startswith("# ") and not stripped.startswith("## "):
            line = "## " + stripped[2:]
        # Tech-meta строки «**Сгенерировано:** ...», «**Модель:** ...», «**Tokens:** ...»
        if _re.match(r"\*\*(Сгенерировано|Модель|Tokens|Generated|Model|Tokens?):\*\*", stripped):
            continue
        # Литеральные разделители --- между meta-блоком и контентом
        if stripped == "---" and not new_lines:
            continue  # в начале
        new_lines.append(line)
    # 3. Свернуть множественные пустые строки
    cleaned = "\n".join(new_lines)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def anti_friction_recommendations() -> str:
    """Раздел «Упрощения процессов» — что автоматизировать.

    Сканирует pavel-actions.jsonl за последние 7 дней:
    - Какие действия Pavel делает повторно?
    - Какие steps можно автоматизировать?
    """
    pa_file = V2 / ".codex/pavel-actions.jsonl"
    if not pa_file.exists():
        return "_(pavel-actions.jsonl пуст)_\n"

    # Парсим последние 7 дней
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    action_counts = {}
    with pa_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                ts = e.get("ts") or e.get("timestamp")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except ValueError:
                    continue
                action = e.get("action", "unknown")
                action_counts[action] = action_counts.get(action, 0) + 1
            except json.JSONDecodeError:
                pass

    if not action_counts:
        return "_(нет данных за 7 дней)_\n"

    # Сортируем
    sorted_actions = sorted(action_counts.items(), key=lambda x: -x[1])

    lines = []
    lines.append("**Топ-10 действий Pavel-а за 7 дней:**")
    lines.append("")
    for action, count in sorted_actions[:10]:
        lines.append(f"- `{action}` × **{count}**")
    lines.append("")

    # Anti-friction предложения по самым частым
    lines.append("**🔧 Что автоматизировать сегодня:**")
    lines.append("")
    auto_recs = []
    for action, count in sorted_actions[:5]:
        if count < 3:
            continue
        if "stream_suggestion_rejected" == action and count >= 5:
            auto_recs.append(f"- **{count}× отверг suggestion** → возможно фильтр перед показом? Pavel-style learning: после 100+ pairs запустить `learn_pavel_style.py`")
        if "paragraph_clicked" == action and count >= 10:
            auto_recs.append(f"- **{count}× кликов на параграфы** → клавиатурные шорткаты (j/k для следующего/предыдущего)?")
        if "quick_check" in action and count >= 5:
            auto_recs.append(f"- **{count}× quick-check** → пакетный режим: ⚡ для всей главы одной кнопкой")
        if "council" in action and count >= 3:
            auto_recs.append(f"- **{count}× council** → кэширование per-chapter, не запускать заново на тех же текстах")
    if not auto_recs:
        auto_recs.append("- _(пока паттерны слабые — нужно больше данных)_")
    lines.extend(auto_recs)
    return "\n".join(lines)


def progress_section() -> str:
    """Раздел прогресса — сколько глав готово."""
    chapters_root = V2 / "chapters"
    if not chapters_root.exists():
        return "_(нет chapters/)_\n"

    books = {}
    for book_dir in chapters_root.iterdir():
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        total = 0
        finalized = 0
        draft_exists = 0
        for ch_dir in book_dir.iterdir():
            if not ch_dir.is_dir():
                continue
            total += 1
            if (ch_dir / "draft.md").exists():
                draft_exists += 1
            status_file = ch_dir / "status.json"
            if status_file.exists():
                try:
                    if json.loads(status_file.read_text())["status"] == "finalized":
                        finalized += 1
                except Exception:
                    pass
        books[book_dir.name] = {"total": total, "draft": draft_exists, "final": finalized}

    if not books:
        return "_(книг не найдено)_\n"

    lines = []
    lines.append("| Книга | Глав | С draft | Финализ. |")
    lines.append("|---|---|---|---|")
    # Приоритет — book-obsession первой
    book_order = sorted(books.keys(), key=lambda k: (0 if "obsession" in k else 1, k))
    for book in book_order:
        b = books[book]
        is_priority = " 🎯" if "obsession" in book else ""
        lines.append(f"| {book}{is_priority} | {b['total']} | {b['draft']} | {b['final']} |")
    return "\n".join(lines)


def main():
    print("🌅 Утренний брифинг…")
    # 1. Запускаем upstream-скрипты (best effort)
    run_script("morning_plan_generator.py")
    run_script("daily_recommendations.py")
    run_script("auto_bug_tester.py")
    # 2. Собираем
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # UC-73 (Pavel 2026-05-21): эмодзи в section-заголовках убраны.
    # h1 «Утренний брифинг» убран — он уже отрисован UI шапкой страницы /briefing.
    # Из вставляемых файлов вырезаются мусорные h1 (см. clean_imported_text).
    sections = []

    # === ПЛАН НА ДЕНЬ ===
    sections.append("## ПЛАН НА ДЕНЬ")
    sections.append("")
    plan_files = [
        REPORTS / "MORNING-PLAN.md",
        REPORTS / f"DAILY-PLAN-{today}.md",
        REPORTS / "DAILY-PLAN-TODAY.md",
    ]
    plan_text = ""
    for f in plan_files:
        if f.exists():
            plan_text = clean_imported_text(read_section(f, 50))
            break
    sections.append(plan_text or "_(нет MORNING-PLAN.md — запусти morning_plan_generator.py)_")
    sections.append("")

    # === УПРОЩЕНИЯ ПРОЦЕССОВ ===
    sections.append("## УПРОЩЕНИЯ ПРОЦЕССОВ — меньше работы, мощнее результат")
    sections.append("")
    sections.append(anti_friction_recommendations())
    sections.append("")

    # === РЕКОМЕНДАЦИИ НА СЕГОДНЯ ===
    sections.append("## РЕКОМЕНДАЦИИ")
    sections.append("")
    recs_files = [
        REPORTS / f"DAILY-RECOMMENDATIONS-{today}.md",
        REPORTS / "DAILY-RECOMMENDATIONS-TODAY.md",
        REPORTS / "TODAY-RECOMMENDATIONS.md",
    ]
    recs_text = ""
    for f in recs_files:
        if f.exists():
            recs_text = clean_imported_text(read_section(f, 40))
            break
    sections.append(recs_text or "_(нет рекомендаций — запусти daily_recommendations.py)_")
    sections.append("")

    # === БАГ-АУДИТ ===
    sections.append("## БАГ-АУДИТ (за ночь)")
    sections.append("")
    audit_files = [
        REPORTS / "AUTO-BUG-AUDIT.md",
        REPORTS / "VISUAL-TECH-AUDIT.md",
    ]
    for f in audit_files:
        if f.exists():
            sections.append(f"### {f.name}")
            sections.append("")
            sections.append(clean_imported_text(read_section(f, 30)))
            sections.append("")

    # === ПРОГРЕСС ===
    sections.append("## ПРОГРЕСС ПО КНИГАМ")
    sections.append("")
    sections.append(progress_section())
    sections.append("")

    # === SYSTEM IMPROVEMENTS (ночной анализ) ===
    si_dir = REPORTS / "SYSTEM-IMPROVEMENTS"
    if si_dir.exists():
        recent = sorted(si_dir.glob(f"{today}-*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if recent:
            sections.append("## СЕГОДНЯШНИЙ NIGHTLY-IMPROVEMENT")
            sections.append("")
            sections.append(f"См. `reports/SYSTEM-IMPROVEMENTS/{recent[0].name}`")
            sections.append("")
            sections.append(clean_imported_text(read_section(recent[0], 30)))
            sections.append("")

    sections.append("---")
    sections.append("")
    sections.append("**Источник:** этот файл собран `scripts/morning_briefing.py` из MORNING-PLAN, DAILY-RECOMMENDATIONS, AUTO-BUG-AUDIT, VISUAL-TECH-AUDIT, SYSTEM-IMPROVEMENTS. Pavel UC-24 — единая точка входа утром.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(sections), encoding="utf-8")
    print(f"   → {OUTPUT}")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "morning_briefing",
            "target": "reports",
            "payload": {"size": len("\n".join(sections))},
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
