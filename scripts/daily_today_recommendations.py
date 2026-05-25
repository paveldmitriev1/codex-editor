#!/usr/bin/env python3
"""
daily_today_recommendations.py — единый daily digest по утверждённому Pavel-ом formatу.

Pavel 2026-05-20 утвердил формат IMPROVEMENT-FRAMEWORK.md. Этот скрипт:
1. Читает сигналы изо всех отчётов (visual_qa, tech_qa, followups, logic_audit, structure, version_dedup)
2. Opus 4.7 синтезирует ТОП-5-7 рекомендаций в формате карточки А
3. Пишет в reports/TODAY-RECOMMENDATIONS.md
4. Логирует в pavel-actions.jsonl как `recommendation_proposed` (для метрик G)

Утром Pavel читает → отмечает approved / rejected / deferred → я внедряю.

Запуск (watcher 07:30 ежедневно): python3 daily_today_recommendations.py
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from claude_helper import ask_opus
except ImportError:
    ask_opus = None

V2 = Path.home() / "Desktop/Codex2"
REPORTS = V2 / "reports"
OUTPUT = REPORTS / "TODAY-RECOMMENDATIONS.md"

SIGNAL_FILES = [
    ("VISUAL-QA-PENDING.md", "UI-bugs from vision QA"),
    ("TECH-QA-PENDING.md", "endpoint / JSON / data integrity bugs"),
    ("NIGHT-FOLLOWUPS.md", "что я пропустил по Pavel-у"),
    ("LOGIC-AUDIT.md", "мета-аудит логики"),
    ("STRUCTURE-AUDIT.md", "потерянные книги / структура"),
    ("VERSION-DEDUP.md", "дубликаты версий"),
    ("SYSTEM-UNDER-HOOD.md", "состояние системы"),
]


def collect_signals() -> str:
    """Собирает свежие сигналы из всех отчётов."""
    chunks = []
    for fname, desc in SIGNAL_FILES:
        p = REPORTS / fname
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8", errors="ignore")
        # Берём только tail если очень длинный (последние N символов)
        if len(content) > 8000:
            content = content[:1500] + "\n\n[...] (truncated)\n\n" + content[-5000:]
        chunks.append(f"## {fname} — {desc}\n\n{content}")
    return "\n\n---\n\n".join(chunks)


def generate(signals_text: str) -> dict:
    if ask_opus is None:
        return {"error": "claude_helper unavailable"}

    framework = (V2 / "reports/IMPROVEMENT-FRAMEWORK.md").read_text(encoding="utf-8") if (V2 / "reports/IMPROVEMENT-FRAMEWORK.md").exists() else ""

    system = (
        "Ты — Tom, ассистент Pavel-а. Pavel утвердил IMPROVEMENT-FRAMEWORK (формат А). "
        "Твоя задача: прочитать сигналы из ВСЕХ отчётов и синтезировать ТОП-5-7 "
        "конкретных, actionable рекомендаций ровно в формате карточки А. "
        "Никаких размытых формулировок типа «улучшить UI». Каждая карточка — "
        "одна точечная проблема + точечное решение.\n\n"
        "Приоритеты:\n"
        "1. Блокеры для book-obsession (приоритет №1) — top\n"
        "2. Pavel сказал прямо в сообщениях недавно — high\n"
        "3. Найдено агентами с severity ≥ 7 — medium\n"
        "4. Slow-burn idea-tools — low\n\n"
        "Отвечай ТОЛЬКО валидным JSON по схеме."
    )

    user = f"""# FRAMEWORK (как формулировать)

{framework[:4000]}

# СИГНАЛЫ ИЗ ОТЧЁТОВ

{signals_text[:30000]}

# Что вернуть

```json
{{
  "today_date": "YYYY-MM-DD",
  "recommendations": [
    {{
      "id": "A1 | B2 | C3 ...",
      "category": "UI | Voice | Process | Data | AI-Pipeline | Architecture",
      "trigger": "цитата Pavel ИЛИ найдено агентом X ИЛИ метрика",
      "problem": "1 предложение",
      "now": "как работает сейчас",
      "should_be": "как должно",
      "effect": "что Pavel получит",
      "effort": "30 мин | 2ч | день",
      "auto_check": "yes/no + как именно",
      "risk": "что может сломаться",
      "priority": "top | high | medium | low",
      "blocks_book_obsession": true/false
    }}
  ]
}}
```

5-7 рекомендаций, не больше. Сначала те что блокируют book-obsession. Никаких дубликатов с уже работающими процессами.
"""
    print(f"  → Opus: синтез {len(signals_text)} знаков сигналов...")
    try:
        resp = ask_opus(user=user, system=system, max_tokens=10000, thinking=6000)
        text = resp["text"].strip()
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return {**json.loads(cleaned), "usage": resp.get("usage")}
    except Exception as e:
        return {"error": f"Opus/JSON: {e}"}


def render(data: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    today = data.get("today_date", datetime.now().strftime("%Y-%m-%d"))
    lines = []
    lines.append(f"# 🎯 TODAY — {today}")
    lines.append("")
    lines.append(f"_Сгенерировано: {now}_")
    lines.append("")
    lines.append("> Формат — `IMPROVEMENT-FRAMEWORK.md` (утверждён 2026-05-20). Pavel читает карточки → ставит approve/reject → внедряю.")
    lines.append("")

    if data.get("error"):
        lines.append(f"⚠️ Ошибка Opus: {data['error']}")
        return "\n".join(lines)

    recs = data.get("recommendations", [])
    if not recs:
        lines.append("_Сегодня сигналов нет — всё чисто._")
        return "\n".join(lines)

    # Сортируем: blocking book-obsession сначала, потом по priority
    order = {"top": 0, "high": 1, "medium": 2, "low": 3}
    recs_sorted = sorted(recs, key=lambda r: (not r.get("blocks_book_obsession", False), order.get(r.get("priority"), 4)))

    for r in recs_sorted:
        marker = " 🔴 БЛОКИРУЕТ КНИГУ" if r.get("blocks_book_obsession") else ""
        lines.append(f"## `{r.get('id', '?')}` — **{r.get('priority', '?')}**{marker}")
        lines.append("")
        lines.append(f"- **Категория:** {r.get('category', '?')}")
        lines.append(f"- **Триггер:** {r.get('trigger', '?')}")
        lines.append(f"- **Проблема:** {r.get('problem', '?')}")
        lines.append(f"- **Сейчас:** {r.get('now', '?')}")
        lines.append(f"- **Должно быть:** {r.get('should_be', '?')}")
        lines.append(f"- **Эффект:** {r.get('effect', '?')}")
        lines.append(f"- **Усилие:** {r.get('effort', '?')}")
        lines.append(f"- **Авто-чек:** {r.get('auto_check', '?')}")
        lines.append(f"- **Risk:** {r.get('risk', '?')}")
        lines.append("")
        lines.append("**Действие:** `[ ] approve` · `[ ] reject` · `[ ] defer` · _твой комментарий:_")
        lines.append("")
        lines.append("---")
        lines.append("")

    if "usage" in data:
        u = data["usage"] or {}
        lines.append(f"_Opus tokens: {u.get('input_tokens', '?')} → {u.get('output_tokens', '?')}_")

    return "\n".join(lines)


def log_proposed(recs: list):
    """Логирует каждую рекомендацию в pavel-actions.jsonl для метрик G."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    f = V2 / ".codex/pavel-actions.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps({
                "ts": ts,
                "action": "recommendation_proposed",
                "rec_id": r.get("id"),
                "priority": r.get("priority"),
                "category": r.get("category"),
                "blocks_book_obsession": r.get("blocks_book_obsession", False),
            }, ensure_ascii=False) + "\n")


def main():
    print("Собираю сигналы из reports/...")
    signals = collect_signals()
    print(f"  signals: {len(signals)} chars")
    print("Генерирую через Opus...")
    data = generate(signals)
    text = render(data)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"✓ {OUTPUT}")
    if "recommendations" in data:
        log_proposed(data["recommendations"])
        print(f"   logged {len(data['recommendations'])} recommendations")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "today_recommendations_generated",
            "target": "daily",
            "payload": {
                "count": len(data.get("recommendations", [])),
                "blocking_count": sum(1 for r in data.get("recommendations", []) if r.get("blocks_book_obsession")),
            },
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
