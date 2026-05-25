#!/usr/bin/env python3
"""
logic_audit.py — ночной анализ логики Pavel-а + предложения инструментов для bug detection.

Pavel 2026-05-20: «ночью сделаешь анализ моей логики и советов которые тебе давал
и придумаешь также инструменты которые помогут нам выявлять баги и все недостатки
в логике и утром мне предоставишь на подтверждение все эти варианты».

Отличие от night_followups_review.py:
- followups = что Pavel просил vs что я сделал/пропустил
- logic_audit = МЕТА-уровень: какие принципы/правила/паттерны видны в советах Pavel-а,
  какие баги система склонна повторять, какие инструменты bug-detection помогут.

Что делает:
1. Читает USER messages за последние 30 дней
2. Opus анализирует и возвращает:
   a) Pavel's principles — повторяющиеся требования (стиль, UI, процессы)
   b) Recurring bugs — баги которые я делаю снова (тёмный popover, дубликаты UI-кодов, undefined в TOC)
   c) Proposed tools — инструменты для авто-обнаружения этих багов (linter правил, regex check, vision QA расширения)
   d) Implementation priorities — что внедрить первым
3. Pavel утром одобряет → создаём реальные инструменты

Output: reports/LOGIC-AUDIT.md
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from claude_helper import ask_opus
except ImportError:
    ask_opus = None

V2 = Path.home() / "Desktop/Codex2"
SESSIONS_DIR = Path.home() / ".claude/projects/-Users-kingofhealers-Desktop-Claude-Folder"
OUTPUT = V2 / "reports/LOGIC-AUDIT.md"


def load_recent_user_messages(days: int = 30) -> list:
    if not SESSIONS_DIR.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    messages = []
    for jsonl in sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:30]:
        try:
            for line in jsonl.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "user":
                    continue
                ts = obj.get("timestamp", "")
                if ts and ts < cutoff_iso:
                    continue
                msg = obj.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
                if not isinstance(content, str) or len(content) < 50:
                    continue
                if content.startswith("<command-") or content.startswith("<system-"):
                    continue
                messages.append({"ts": ts, "text": content[:3500]})
        except Exception:
            continue
    return messages


def system_inventory() -> str:
    """Краткий обзор текущих инструментов."""
    items = []
    for p in ["scripts/extract_metaphors.py", "scripts/analyze_voice_readings.py",
              "scripts/daily_system_report.py", "scripts/night_followups_review.py",
              "scripts/technical_qa_agent.py", "scripts/visual_qa_agent.py",
              "scripts/auto_fix_agent.py", "scripts/structure_audit.py",
              "scripts/version_dedup.py", "scripts/learn_pavel_style.py",
              "scripts/logic_audit.py"]:
        f = V2 / p
        items.append(f"  - {p} {'✓' if f.exists() else '✗'}")
    return "\n".join(items)


def analyze_logic(messages: list) -> dict:
    if not messages:
        return {"error": "no messages"}
    if ask_opus is None:
        return {"error": "claude_helper unavailable"}

    messages.sort(key=lambda m: m.get("ts", ""), reverse=True)
    msgs_dump = "\n\n".join(
        f"### {m['ts'][:19]}\n{m['text']}"
        for m in messages[:30]
    )

    system = (
        "Ты — Tom, ассистент Pavel-а на Codex Микомистицизма. Pavel дал указание: "
        "ночью анализировать его сообщения и НА МЕТА-УРОВНЕ выявлять "
        "(1) принципы которые он постоянно повторяет, "
        "(2) баги которые ты делаешь снова и снова, "
        "(3) ИНСТРУМЕНТЫ которые помогли бы автоматически их ловить. "
        "Будь конкретным и самокритичным. Pavel хочет утром получить "
        "actionable список «вот эти инструменты можно сделать прямо сейчас». "
        "Отвечай ТОЛЬКО валидным JSON."
    )

    user = f"""# История сообщений Pavel-а (последние 30 дней, свежее сверху)

{msgs_dump}

# Текущий arsenal инструментов

{system_inventory()}

# Что вернуть

```json
{{
  "principles": [
    {{"rule": "повторяющееся требование Pavel-а", "evidence": "цитаты или примеры", "category": "стиль|UI|процесс|архитектура|голос"}}
  ],
  "recurring_bugs": [
    {{"bug": "что я делал/делаю плохо", "examples": ["пример 1", "пример 2"], "category": "design|content|process|technical", "severity": 1-10}}
  ],
  "proposed_tools": [
    {{
      "name": "имя инструмента",
      "what_it_does": "что делает",
      "detects": "какой класс багов ловит",
      "implementation": "как реализовать (1-2 предложения)",
      "effort_hours": 0.5-8,
      "priority": "high|medium|low",
      "auto_runnable": true/false
    }}
  ],
  "implementation_order": ["имя инструмента 1", "имя инструмента 2"],
  "patterns_in_pavel_language": [
    {{"pattern": "как Pavel пишет / что он любит / стоп-слова", "implication": "что я должен учесть"}}
  ]
}}
```

ОЖИДАНИЯ Pavel-а (он сказал прямо за последние дни):
- Modern Russian voice, no тире
- Voice of Великий Дух Грибов
- Design Lock (никаких хардкодов цветов, Statly шаблон)
- Multi-pass самопроверка перед отдачей
- Pre-write / post-write rule checks
- Никаких alert/confirm/prompt native
- UI коды видны только на hover
- Recent 10 главы + session resume
- Кликабельные scores с галочными правками
- Auto-voice-extract при открытии главы
- Markdown rendering вместо ###

Найди ЕЩЁ паттерны помимо этих — что Pavel повторял но я мог упустить.

5-7 предложенных инструментов, не больше. Каждый — actionable, конкретный.
"""

    print(f"  → Opus: анализ {len(messages)} сообщений…")
    try:
        resp = ask_opus(user=user, system=system, max_tokens=10000, thinking=6000)
        text = resp["text"].strip()
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return {**json.loads(cleaned), "usage": resp.get("usage")}
    except Exception as e:
        return {"error": f"Opus/JSON: {e}"}


def write_report(analysis: dict, total_msgs: int):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# 🧠 Logic audit — {now}")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «ночью анализируй мою логику и советы, придумывай инструменты для выявления багов, утром на подтверждение»")
    lines.append("")
    lines.append(f"Проанализировано user-сообщений: **{total_msgs}**")
    lines.append("")

    if analysis.get("error"):
        lines.append(f"⚠️ Ошибка: {analysis['error']}")
        lines.append("")
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
        return

    principles = analysis.get("principles", [])
    if principles:
        lines.append(f"## 📜 Принципы Pavel-а — {len(principles)}")
        lines.append("")
        by_cat = {}
        for p in principles:
            by_cat.setdefault(p.get("category", "?"), []).append(p)
        for cat, items in by_cat.items():
            lines.append(f"### {cat}")
            for p in items:
                lines.append(f"- **{p.get('rule', '?')}**")
                if p.get("evidence"):
                    lines.append(f"  _evidence:_ {p['evidence']}")
            lines.append("")

    bugs = analysis.get("recurring_bugs", [])
    if bugs:
        lines.append(f"## 🐛 Повторяющиеся баги — {len(bugs)}")
        lines.append("")
        bugs_sorted = sorted(bugs, key=lambda b: -b.get("severity", 0))
        for b in bugs_sorted:
            sev = b.get("severity", "?")
            lines.append(f"- **[severity {sev}/10] [{b.get('category', '?')}]** {b.get('bug', '?')}")
            for ex in b.get("examples", [])[:3]:
                lines.append(f"  - _example:_ {ex}")
        lines.append("")

    tools = analysis.get("proposed_tools", [])
    if tools:
        lines.append(f"## 🛠 Предлагаемые инструменты — {len(tools)} (на подтверждение Pavel-а)")
        lines.append("")
        tools_sorted = sorted(tools, key=lambda t: {"high": 0, "medium": 1, "low": 2}.get(t.get("priority", "low"), 3))
        for t in tools_sorted:
            lines.append(f"### `{t.get('name', '?')}` — приоритет **{t.get('priority', '?')}** ({t.get('effort_hours', '?')}ч)")
            lines.append(f"- **Что делает:** {t.get('what_it_does', '?')}")
            lines.append(f"- **Ловит:** {t.get('detects', '?')}")
            lines.append(f"- **Реализация:** {t.get('implementation', '?')}")
            lines.append(f"- **Автозапуск:** {'да' if t.get('auto_runnable') else 'нет'}")
            lines.append("")

    order = analysis.get("implementation_order", [])
    if order:
        lines.append(f"## 📋 Порядок внедрения (рекомендация)")
        lines.append("")
        for i, name in enumerate(order, 1):
            lines.append(f"{i}. `{name}`")
        lines.append("")

    patterns = analysis.get("patterns_in_pavel_language", [])
    if patterns:
        lines.append(f"## 🗣 Паттерны языка Pavel-а — {len(patterns)}")
        lines.append("")
        for p in patterns:
            lines.append(f"- **«{p.get('pattern', '?')}»** → {p.get('implication', '?')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Что делать Pavel-у:**")
    lines.append("")
    lines.append("- Прочитай **🛠 Предлагаемые инструменты** — выбери что внедрить")
    lines.append("- Скажи «внедри tool X» — я сделаю в следующей сессии")
    lines.append("- Если паттерн в **🐛 баги** реален — флажни, я добавлю в правила")
    lines.append("")
    if "usage" in analysis:
        u = analysis["usage"] or {}
        lines.append(f"_Opus tokens: {u.get('input_tokens', '?')} → {u.get('output_tokens', '?')}_")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ {OUTPUT}")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "logic_audit",
            "target": "history",
            "payload": {
                "messages": total_msgs,
                "principles": len(principles),
                "bugs": len(bugs),
                "tools_proposed": len(tools),
            },
        }, ensure_ascii=False) + "\n")


def main():
    messages = load_recent_user_messages(days=30)
    print(f"Загружено user messages: {len(messages)}")
    analysis = analyze_logic(messages)
    write_report(analysis, len(messages))


if __name__ == "__main__":
    main()
