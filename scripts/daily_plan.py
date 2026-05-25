#!/usr/bin/env python3
"""
daily_plan.py — ежедневный календарь действий Pavel-а на 2-4 часа.

Pavel 2026-05-20: «мне нужен календарь действий на каждый день от 2-4 часов
в день моего времени на каждое утро с планом и вопросами если есть».

Что делает:
1) Читает MORNING-PLAN.md (стратегия) + DAILY-IMPROVEMENTS.md (тактика) +
   TIMESHEET.md (что было сделано) + fidelity queue + lecture queue + events
2) Через Opus 4.7 генерирует ПЛАН ДНЯ:
   - Блок «Утро» (1.5-2 ч глубокой работы) — конкретные действия
   - Блок «Mid-day» (30-60 мин review)
   - Блок «Вечер» (30-60 мин решения)
   - Список ВОПРОСОВ к Pavel-у (если есть блокеры)
   - ОДНО действие на 30 минут (если день занят)
3) Каждое действие: время • что делать • ссылка на файл/страницу • estimated minutes
4) Сохраняет в reports/DAILY-PLAN-YYYY-MM-DD.md (overwrite если уже есть)
5) Симлинк reports/DAILY-PLAN-TODAY.md всегда указывает на сегодня

Запуск:
    python3 daily_plan.py
"""

import json
import sys
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
REPORTS = V2 / "reports"
EVENTS = V2 / ".codex/events.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def read_if_exists(p: Path, max_chars: int = None) -> str:
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8")
    return txt[:max_chars] if max_chars else txt


def fidelity_queue_state() -> dict:
    q_file = V2 / ".codex/fidelity-queue.json"
    if not q_file.exists():
        return {"pending": [], "done": []}
    return json.loads(q_file.read_text(encoding="utf-8"))


def list_files(directory: Path, pattern: str = "*.md") -> list:
    if not directory.exists():
        return []
    return sorted([f.name for f in directory.glob(pattern)])


def yesterday_events(hours: int = 24) -> list:
    if not EVENTS.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts = e.get("ts", "")
            if ts and datetime.fromisoformat(ts.replace("Z", "+00:00")) > cutoff:
                out.append(e)
        except (json.JSONDecodeError, ValueError):
            pass
    return out


def main():
    morning_plan = read_if_exists(REPORTS / "MORNING-PLAN.md", max_chars=20000)
    daily_imp = read_if_exists(REPORTS / "DAILY-IMPROVEMENTS.md", max_chars=8000)
    timesheet = read_if_exists(REPORTS / "TIMESHEET.md", max_chars=5000)

    queue = fidelity_queue_state()
    fid_pending = len(queue.get("pending", []))
    fid_done_count = len(queue.get("done", []))
    fid_done_recent = ", ".join(
        d["chapter_id"] for d in queue.get("done", [])[-10:]
    ) or "(пока пусто)"

    fidelity_reports = list_files(REPORTS / "fidelity")
    lecture_plans = list_files(REPORTS / "lecture-plans")
    competitor_reports = list_files(REPORTS / "competitors")
    research_reports = list_files(REPORTS / "research")

    events = yesterday_events()
    by_type = {}
    for e in events:
        by_type[e.get("type", "?")] = by_type.get(e.get("type", "?"), 0) + 1
    events_summary = ", ".join(f"{t}×{c}" for t, c in sorted(by_type.items(), key=lambda x: -x[1])[:8])

    today = today_str()
    weekday_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][datetime.now().weekday()]

    system = (
        "Ты — личный планировщик Pavel-а Дмитриева (Хилингода). Pavel пишет Сакральный "
        "Кодекс Микомистицизма. Его день: 2-4 часа РЕАЛЬНОЙ работы (не больше). "
        "Pavel легко перегружается и теряет фокус — твоя задача дать ему конкретные "
        "блоки времени с одной задачей в каждом. Не семь опций — одна задача на блок. "
        "\n"
        "Pavel работает: утро (deep focus, надиктовки, написание), "
        "mid-day (review результатов AI, принятие решений), "
        "вечер (короткий sign-off, что закрыли, что завтра). "
        "Не загружай больше 4 часов в день, целься на 2.5-3.5. "
        "\n"
        "Каждое действие: время начала, что делать, файл/команда/ссылка, оценка минут. "
        "Каждое решение которое Pavel должен принять — отдельный вопрос. "
        "По-русски. Без воды."
    )

    user = f"""# Контекст для плана

**Дата:** {today} ({weekday_ru})
**Состояние pipeline:**
- Fidelity-отчётов сделано: {fid_done_count} (последние: {fid_done_recent})
- В очереди fidelity: {fid_pending}
- Lecture-планов готовых: {len(lecture_plans)} ({", ".join(lecture_plans[:5]) if lecture_plans else "—"})
- Конкурент-отчётов: {len(competitor_reports)}/8
- Research-отчётов: {len(research_reports)}
- События последних 24ч: {len(events)} ({events_summary})

---

# Стратегия (MORNING-PLAN — первые 20К)

{morning_plan or "(не сгенерирован)"}

---

# Улучшения процессов (DAILY-IMPROVEMENTS)

{daily_imp or "(не сгенерирован)"}

---

# Timesheet (что было)

{timesheet or "(не сгенерирован)"}

---

# Что мне нужно — план дня

Создай ПЛАН НА СЕГОДНЯ в Markdown по схеме:

## 📅 ПЛАН НА {today} ({weekday_ru})

**Всего работы:** 2.5-3.5 часа (выбери конкретное число)
**Фокус дня:** одна фраза — главная цель сегодня

---

### 🌅 УТРО (примерно 09:00-11:00) — N минут

**ОДНА ГЛАВНАЯ ЗАДАЧА:** название одной фразой

#### Шаг 1 (10 мин) — [короткое название]
- Что делать: конкретно
- Файл/команда: `путь` или `bash команда`
- На выходе: что должно получиться

#### Шаг 2 (25 мин) — [короткое название]
...

---

### 🌞 MID-DAY (примерно 13:00-14:00) — N минут

[Review-задача — посмотреть результаты ночной работы, принять решения]

#### Шаг 1 (15 мин) — [название]
...

---

### 🌆 ВЕЧЕР (примерно 18:00-19:00) — N минут

[Sign-off, отметить что закрыли, что завтра]

---

## ❓ Вопросы которые жду от тебя

Если нет блокеров — раздел опускаешь. Если есть — конкретные вопросы где ОБЯЗАТЕЛЬНО твоё решение чтобы я продолжил:

1. **[Конкретный вопрос]**
   - Варианты: A / B / C
   - Что я сделаю исходя из выбора: ...
   - Если не ответишь: я пойду по умолчанию X

2. ...

---

## 🎯 Если у тебя только 30 минут сегодня

ОДНО действие. Самое важное. Конкретно:
- Открой `файл`
- Сделай: X

---

## 📂 Полезные ссылки на сегодня

- `путь/к/файлу1.md` — что в нём
- `http://127.0.0.1:7788/...` — что там
- `bash команда` — что делает

---

ВАЖНО:
- Не больше 3-5 шагов на блок
- Каждое время — реальное, не «когда сможешь»
- Вопросы только реальные блокеры. Если можешь сам — делай сам.
- ОДНА цель дня в начале. Не три.
"""

    print(f"→ Opus 4.7 + thinking 6K для плана на {today}...")
    resp = ask_opus(user=user, system=system, max_tokens=8000, thinking=6000)

    plan_path = REPORTS / f"DAILY-PLAN-{today}.md"
    today_link = REPORTS / "DAILY-PLAN-TODAY.md"

    header = (
        f"<!-- generated: {now_iso()} -->\n"
        f"<!-- model: {resp.get('model')} -->\n"
        f"<!-- tokens: in {resp['usage'].get('input_tokens')}, out {resp['usage'].get('output_tokens')} -->\n\n"
    )
    plan_path.write_text(header + resp["text"], encoding="utf-8")

    # Симлинк TODAY → today's file
    if today_link.exists() or today_link.is_symlink():
        today_link.unlink()
    today_link.symlink_to(plan_path.name)

    print(f"✓ {plan_path}")
    print(f"✓ {today_link} → {plan_path.name}")

    # Event
    event = {
        "ts": now_iso(),
        "type": "daily_plan_generated",
        "target": f"reports/DAILY-PLAN-{today}.md",
        "payload": {
            "model": resp.get("model"),
            "tokens_in": resp["usage"].get("input_tokens"),
            "tokens_out": resp["usage"].get("output_tokens"),
            "weekday": weekday_ru,
            "fidelity_pending": fid_pending,
        },
    }
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
