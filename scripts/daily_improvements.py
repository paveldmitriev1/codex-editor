#!/usr/bin/env python3
"""
daily_improvements.py — каждое утро генерирует идеи по упрощению жизни Pavel-а.

Pavel 2026-05-20: «каждое утро генерируй идеи по упрощению и улучшению
процессов, запомни что твоя главная задача упростить мне жизнь».

Что делает:
1) Читает события прошедшего дня (events.jsonl)
2) Читает watcher.log на предмет ошибок и медленных мест
3) Читает TIMESHEET.md и MORNING-PLAN.md
4) Через Opus 4.7 + thinking — выдаёт 5-10 конкретных идей по упрощению
5) Сохраняет в reports/DAILY-IMPROVEMENTS.md (overwrite — это RAW свежий взгляд)
6) Архивирует прошлый файл в reports/archive/daily-improvements/<date>.md

Запуск:
    python3 daily_improvements.py
"""

import json
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
REPORTS = V2 / "reports"
EVENTS = V2 / ".codex/events.jsonl"
WATCHER_LOG = V2 / ".codex/watcher.log"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def yesterday_events(hours_back: int = 24) -> list:
    if not EVENTS.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    out = []
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts = e.get("ts", "")
            if ts:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t > cutoff:
                    out.append(e)
        except (json.JSONDecodeError, ValueError):
            pass
    return out


def watcher_problems() -> list:
    """Найти ошибки и медленные места в watcher логе."""
    if not WATCHER_LOG.exists():
        return []
    text = WATCHER_LOG.read_text(encoding="utf-8")
    errors = re.findall(r"\[.*?\]\s+✗.*", text)[-50:]
    return errors


def read_if_exists(p: Path, max_chars: int = None) -> str:
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8")
    return txt[:max_chars] if max_chars else txt


def main():
    events = yesterday_events()
    problems = watcher_problems()
    timesheet = read_if_exists(REPORTS / "TIMESHEET.md")
    morning = read_if_exists(REPORTS / "MORNING-PLAN.md", max_chars=15000)

    system = (
        "Ты — analyst-strategist Pavel-а Дмитриева (Хилингода). Твоя задача — каждое утро "
        "найти конкретные способы УПРОСТИТЬ его рабочий день: что починить, что автоматизировать, "
        "что упразднить (как лишнее), что оставить без изменений (оно работает). "
        "Pavel ценит: один артефакт, не три варианта; авто-фон, не вопросы; "
        "tech end-to-end. На Mac. Русский язык. Книга-шедевр. "
        "Без воды, без хеджей, без «возможно стоит». Прямо: «делаем X, потому что Y»."
    )

    events_summary = "\n".join(
        f"- {e['ts'][:16]} {e['type']} → {e.get('target', '?')}"
        for e in events[-40:]
    ) or "(нет событий)"

    problems_block = "\n".join(problems[-15:]) or "(чисто)"

    user = f"""# События последних 24 часов
{events_summary}

# Ошибки и сбои watcher-а
{problems_block}

# TIMESHEET (что было сделано, сколько токенов)
{timesheet[:5000]}

# Последний MORNING-PLAN (первые 15К)
{morning}

---

# Что мне нужно

Сгенерируй DAILY-IMPROVEMENTS.md в Markdown. Структура:

## 🎯 5-10 ИДЕЙ ПО УПРОЩЕНИЮ (приоритет ↓)

### #1 [короткое название]
**Что делаем:** конкретно — один шаг
**Почему упрощает:** одна фраза
**Как реализовать:** 3-5 строк (псевдо-код или команда)
**Сложность:** S/M/L
**Эффект на Pavel-а:** «-1 клик», «-30 мин в день», «-1 решение которое он должен принимать» и т.п.

### #2 ...

## 🔧 Что починить (если что-то сломалось)

Список конкретных bug-ов из ошибок watcher-а или из событий.

## 🗑 Что упразднить

Что мы делаем но не используем / дублируем / лишнее. Pavel ценит лаконичность системы.

## ✓ Что оставить как есть

Что работает хорошо — НЕ ТРОГАЕМ. Признак: упоминается в TIMESHEET-е как «отработал», нет ошибок в логе.

## 📊 Завтра по умолчанию

ОДНА команда которую Pavel запустит первым делом утром (если он не хочет читать весь план).

---

ОЧЕНЬ КРАТКО. 800-1500 слов. Каждая идея = решение, не вопрос.
"""

    print("→ Opus 4.7 + thinking 6K...")
    resp = ask_opus(user=user, system=system, max_tokens=8000, thinking=6000)

    out_path = REPORTS / "DAILY-IMPROVEMENTS.md"

    # Архивировать предыдущий если есть
    if out_path.exists():
        archive_dir = REPORTS / "archive/daily-improvements"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        shutil.move(str(out_path), str(archive_dir / f"{ts}.md"))

    header = (
        f"# 💡 DAILY IMPROVEMENTS — {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"**Сгенерировано:** {now_iso()}\n"
        f"**Модель:** {resp.get('model')}\n"
        f"**Tokens:** in {resp['usage'].get('input_tokens')}, out {resp['usage'].get('output_tokens')}\n"
        f"**События последних 24ч:** {len(events)}\n\n"
        "_Главная задача Tom-а — упростить жизнь Pavel-а. Каждое утро свежий взгляд на «что починить / автоматизировать / упразднить»._\n\n"
        "---\n\n"
    )
    out_path.write_text(header + resp["text"], encoding="utf-8")
    print(f"✓ {out_path}")

    # Event
    event = {
        "ts": now_iso(),
        "type": "daily_improvements_generated",
        "target": "reports/DAILY-IMPROVEMENTS.md",
        "payload": {
            "model": resp.get("model"),
            "tokens_in": resp["usage"].get("input_tokens"),
            "tokens_out": resp["usage"].get("output_tokens"),
            "events_analyzed": len(events),
        },
    }
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
