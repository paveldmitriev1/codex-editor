#!/usr/bin/env python3
"""
daily_system_report.py — утренний отчёт «под капотом» для Pavel-а.

Pavel 2026-05-20: «каждое утро ты мне накручивай логику и внутреннюю логику системы,
что происходит под капотом, чтобы я мог понимать как оно работает,
все отчёты, и как я могу это всё улучшить».

Что генерит:
1. Состояние системы (сервер/proxy/watcher)
2. Активность за сутки (по events.jsonl + pavel-actions.jsonl)
3. Под капотом — логика активных процессов
4. Тренды (метафоры/% покрытия/Pavel-Brain)
5. Варианты улучшений с цифрами и предложением запустить

Запуск: python3 daily_system_report.py
Output: reports/SYSTEM-UNDER-HOOD.md
"""
import json
import os
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
EVENTS = V2 / ".codex/events.jsonl"
ACTIONS = V2 / ".codex/pavel-actions.jsonl"
OUTPUT = V2 / "reports/SYSTEM-UNDER-HOOD.md"
LIBRARY = V2 / ".codex/metaphors-library.json"


def check_process(name_substr):
    """Возвращает True если процесс с substring в командной строке жив."""
    try:
        out = subprocess.check_output(["pgrep", "-fl", name_substr], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def check_port(port):
    try:
        subprocess.check_output(["lsof", "-t", f"-iTCP:{port}"], text=True, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def load_jsonl(path, since_ts=None):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if since_ts and r.get("ts", "") < since_ts:
                continue
            out.append(r)
        except json.JSONDecodeError:
            pass
    return out


def count_chapters():
    """Сколько глав с draft.md / metaphors.json / finalized.md."""
    have_draft = 0
    have_meta = 0
    have_final = 0
    total = 0
    chapters_dir = V2 / "chapters"
    for book in chapters_dir.iterdir():
        if not book.is_dir() or book.name.startswith("."):
            continue
        for ch in book.iterdir():
            if not ch.is_dir():
                continue
            total += 1
            if (ch / "draft.md").exists():
                have_draft += 1
            if (ch / "metaphors.json").exists():
                have_meta += 1
            if (ch / "finalized.md").exists():
                have_final += 1
    # Add chapters without dirs but with sources
    src_dir = V2 / "sources"
    if src_dir.exists():
        for book in src_dir.iterdir():
            if not book.is_dir() or book.name.startswith("."):
                continue
            for ch in book.iterdir():
                if not ch.is_dir():
                    continue
                if (ch / "from-grant").exists():
                    ch_dir = chapters_dir / book.name / ch.name
                    if not ch_dir.exists():
                        total += 1
    return {"total": total, "draft": have_draft, "metaphors": have_meta, "finalized": have_final}


def metaphors_stats():
    if not LIBRARY.exists():
        return {"total": 0, "ai_cliches": 0, "duplicates": 0, "by_chapter": 0}
    try:
        lib = json.loads(LIBRARY.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"total": 0, "ai_cliches": 0, "duplicates": 0, "by_chapter": 0}
    metas = lib.get("metaphors", [])
    return {
        "total": len(metas),
        "ai_cliches": sum(1 for m in metas if m.get("is_ai_cliche")),
        "duplicates": sum(1 for m in metas if m.get("also_used_in")),
        "by_chapter": len(set(m.get("first_used_in") for m in metas if m.get("first_used_in"))),
    }


def pavel_brain_stage():
    """Какая стадия обучения Pavel-Brain (0-4)."""
    if not ACTIONS.exists():
        return 0, "ещё не начат"
    actions = load_jsonl(ACTIONS)
    edit_actions = [a for a in actions if a.get("action") in (
        "manual_edit", "replace_whole_paragraph", "refined", "stream-accept"
    )]
    count = len(edit_actions)
    if count < 10:
        return 0, f"{count} правок — нужно 10+ для стадии 1"
    if count < 30:
        return 1, f"{count} правок — Pavel-Brain stage 1 (предпочтения по длине/частоте)"
    if count < 100:
        return 2, f"{count} правок — stage 2 (микро-паттерны)"
    if count < 300:
        return 3, f"{count} правок — stage 3 (автономная дописывание глав)"
    return 4, f"{count} правок — stage 4 (self-revising agent)"


def main():
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_local = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Состояние системы
    server_running = check_port(7788)
    proxy_running = check_port(8787)
    watcher_pid_file = V2 / ".codex/watcher.pid"
    watcher_running = False
    if watcher_pid_file.exists():
        try:
            pid = int(watcher_pid_file.read_text().strip())
            os.kill(pid, 0)
            watcher_running = True
        except (ValueError, ProcessLookupError, OSError):
            pass

    # 2. Активность за сутки
    events = load_jsonl(EVENTS, since_ts=yesterday)
    actions = load_jsonl(ACTIONS, since_ts=yesterday)
    event_types = Counter(e.get("type") for e in events)
    action_types = Counter(a.get("action") for a in actions)

    # 3. Тренды
    chap = count_chapters()
    meta = metaphors_stats()
    brain_stage, brain_msg = pavel_brain_stage()

    # 4. События по часам (для графика)
    by_hour = defaultdict(int)
    for e in events:
        ts = e.get("ts", "")
        if len(ts) >= 13:
            hour = ts[11:13]
            by_hour[hour] += 1

    # 5. Open issues (visual + tech QA)
    visual_qa = V2 / "reports/VISUAL-QA-PENDING.md"
    tech_qa = V2 / "reports/TECH-QA-PENDING.md"
    visual_count = 0
    if visual_qa.exists():
        visual_count = sum(1 for line in visual_qa.read_text(encoding="utf-8").splitlines() if line.startswith("- [ ]"))
    tech_count = 0
    if tech_qa.exists():
        tech_count = sum(1 for line in tech_qa.read_text(encoding="utf-8").splitlines() if line.startswith("- [ ]"))

    # Сформировать markdown
    lines = []
    lines.append(f"# 🔧 Под капотом — {today_local}")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «накручивай мне логику и внутреннюю логику системы что происходит под капотом»")
    lines.append("")

    # Состояние
    lines.append("## 1. Состояние системы")
    lines.append("")
    lines.append(f"- **Сервер** (port 7788): {'✓ работает' if server_running else '✗ НЕ работает — поднять `cd ~/Desktop/Codex2/app && python3 server.py &`'}")
    lines.append(f"- **OAuth proxy** (port 8787): {'✓ работает' if proxy_running else '✗ НЕ работает — `launchctl kickstart -k gui/501/com.user.oauth-proxy`'}")
    lines.append(f"- **Ночной watcher**: {'✓ работает' if watcher_running else '✗ НЕ работает — `bash ~/Desktop/Codex2/scripts/overnight_watcher.sh &`'}")
    lines.append("")

    # Активность
    lines.append("## 2. Что произошло за последние 24 часа")
    lines.append("")
    lines.append(f"**Системных событий:** {len(events)}")
    lines.append("")
    if event_types:
        lines.append("| Событие | Раз |")
        lines.append("|---|--:|")
        for t, n in event_types.most_common(15):
            lines.append(f"| {t} | {n} |")
        lines.append("")
    lines.append(f"**Действий Pavel-а:** {len(actions)}")
    lines.append("")
    if action_types:
        lines.append("| Действие | Раз |")
        lines.append("|---|--:|")
        for t, n in action_types.most_common(15):
            lines.append(f"| {t} | {n} |")
        lines.append("")

    # Тренды
    lines.append("## 3. Тренды и покрытие")
    lines.append("")
    lines.append(f"- **Главы:** {chap['total']} всего · {chap['draft']} с draft.md · {chap['finalized']} финализированы")
    lines.append(f"- **Покрытие метафорами:** {chap['metaphors']} из {chap['total']} глав ({100*chap['metaphors']//max(chap['total'],1)}%)")
    lines.append(f"- **Склад метафор:** {meta['total']} записей · {meta['ai_cliches']} AI-клише · {meta['duplicates']} cross-chapter дубликатов")
    lines.append(f"- **Pavel-Brain stage:** {brain_stage}/4 — {brain_msg}")
    lines.append(f"- **Открытые UI-баги:** {visual_count} в VISUAL-QA-PENDING.md")
    lines.append(f"- **Открытые tech-баги:** {tech_count} в TECH-QA-PENDING.md")
    lines.append("")

    # Под капотом каждого процесса
    lines.append("## 4. Под капотом — логика активных процессов")
    lines.append("")
    lines.append("Каждый процесс описан в `PROTOCOLS.md`. Краткая суть:")
    lines.append("")
    lines.append("### Опус-пайплайны")
    lines.append("- **Точечная переписка:** выделение → `/api/edit/stream` (SSE) → Opus 4.7 + multi-pass самопроверка → вставка")
    lines.append("- **Совет старейшин:** `/api/chapter/council` → 8 персон + Шедевр-Судья → ТОП-5 правок → apply")
    lines.append("- **Полная перезапись:** `/api/chapter/<id>/rewrite-all` → backup → Opus 4.7 + 16K tokens + 8K thinking → новый draft")
    lines.append("- **Метафоры:** `extract_metaphors.py` → склад с AI-cliché detection + cross-chapter дубликаты")
    lines.append("")
    lines.append("### Локальные оценки (без API)")
    lines.append("- Шедевр/Голос/Уникальность/Сакральн./Ритм — эвристики в JS на каждом параграфе")
    lines.append("- Heading detection — context-aware (предыдущий параграф `:`, инфинитивы, длина)")
    lines.append("")
    lines.append("### Background")
    lines.append("- `overnight_watcher.sh` — каждые 30 мин: unpack, analyze, fidelity ×2, metaphors, visual+tech QA, learn_pavel_style")
    lines.append("- 06:00–07:00 — генерация всех ежедневных отчётов")
    lines.append("")

    # Улучшения
    lines.append("## 5. Варианты улучшений (с цифрами)")
    lines.append("")

    suggestions = []
    if chap['metaphors'] < chap['total']:
        missing = chap['total'] - chap['metaphors']
        cost = missing * 25  # ~$0.25 per chapter
        time_min = missing * 2
        suggestions.append(
            f"### A. Покрыть метафорами все главы\n"
            f"Сейчас {chap['metaphors']}/{chap['total']}. Запуск `extract_metaphors.py --all` обработает оставшиеся {missing} глав, "
            f"займёт ~{time_min} мин, стоит ~${cost/100:.2f} в Opus-токенах. "
            f"Watcher делает по 1 главе/30мин — за ночь покроет ~16 глав. Хочешь форсировать?"
        )
    if meta['ai_cliches'] > 0:
        suggestions.append(
            f"### B. Заменить {meta['ai_cliches']} AI-клише\n"
            f"В складе помечено {meta['ai_cliches']} клише («путь к свету», «энергетические вампиры», и т.п.). "
            f"Запуск Opus с инструкцией «замени все клише на свежие образы Великого Духа» — ~5 мин, ~$0.50."
        )
    if brain_stage < 2:
        suggestions.append(
            f"### C. Прокачать Pavel-Brain до stage 2\n"
            f"Сейчас {brain_msg}. Стадия 2 (микро-паттерны) активирует автономное дописывание. "
            f"Нужно ≥30 твоих правок параграфов. Самый быстрый путь — пройти 2-3 главы целиком."
        )
    if chap['draft'] < 5:
        suggestions.append(
            f"### D. Распаковать ещё глав из источников\n"
            f"С draft.md только {chap['draft']} глав. `pack_chapters.py` распакует все остальные из `sources/<book>/<ch>/from-grant/`."
        )
    if visual_count > 0 or tech_count > 0:
        suggestions.append(
            f"### E. Починить {visual_count + tech_count} открытых багов\n"
            f"`auto_fix_agent.py --apply-safe` починит самые явные автоматически. Остальные — в отчётах для ручной проверки."
        )

    if not suggestions:
        suggestions.append("Всё покрыто. Можно фокусироваться на редактуре глав.")

    for s in suggestions:
        lines.append(s)
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("## Журналы")
    lines.append("")
    lines.append("- `.codex/events.jsonl` — системные события (append-only)")
    lines.append("- `.codex/pavel-actions.jsonl` — действия Pavel-а в UI")
    lines.append("- `chapters/<b>/<c>/.history/` — снимки draft.md")
    lines.append("- `reports/*.md` — все отчёты")
    lines.append("")
    lines.append(f"Сгенерировано: {now.isoformat()}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ {OUTPUT}")

    # Event
    event = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "system_report_generated",
        "target": "daily",
        "payload": {
            "events_24h": len(events),
            "actions_24h": len(actions),
            "suggestions": len(suggestions),
        },
    }
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
