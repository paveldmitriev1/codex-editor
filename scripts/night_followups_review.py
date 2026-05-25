#!/usr/bin/env python3
"""
night_followups_review.py — ночной аудит «что Pavel просил, что я пропустил».

Pavel 2026-05-20: «в течение ночи ты проверяешь все задания которые я тебе давал
которые ты в тексте может проигнорировал на тот момент и смотри какие моменты
ты пропустил или не доделал в процессе то есть в этих чатах изучай что я тебе давал,
было сделано, что было пропущено и если это имеет смысл — внедряется».

Что делает:
1. Читает `~/.claude/projects/-Users-kingofhealers-Desktop-Claude-Folder/*.jsonl` (сессии)
2. Извлекает USER messages за последние 7 дней
3. Opus анализирует: что Pavel просил, что я сделал, что пропустил
4. Возвращает structured report:
   - Done — что сделано
   - Pending — что в работе
   - Missed — что я пропустил (с обоснованием)
   - Worth doing — что имеет смысл реализовать сейчас
5. Пишет в `reports/NIGHT-FOLLOWUPS.md`
6. Pavel читает утром → отмечает что взять в работу

Запуск (overnight_watcher): раз в день в 03:30.
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
OUTPUT = V2 / "reports/NIGHT-FOLLOWUPS.md"


def load_recent_user_messages(days: int = 7) -> list:
    """Извлекает USER messages из jsonl сессий за последние N дней."""
    if not SESSIONS_DIR.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    messages = []
    for jsonl in sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:20]:
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
                    # multipart
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                    content = " ".join(text_parts)
                if not isinstance(content, str):
                    continue
                content = content.strip()
                if len(content) < 30:
                    continue
                if content.startswith("<command-") or content.startswith("<system-"):
                    continue
                messages.append({"ts": ts, "text": content[:4000], "session": jsonl.name})
        except Exception as e:
            print(f"  ! {jsonl.name}: {e}", file=sys.stderr)
            continue
    return messages


def analyze_followups(messages: list) -> dict:
    if not messages:
        return {"done": [], "pending": [], "missed": [], "worth_doing": [], "message": "нет user messages"}

    if ask_opus is None:
        return {"done": [], "pending": [], "missed": [], "worth_doing": [], "message": "claude_helper не доступен"}

    # Свежее → старое
    messages.sort(key=lambda m: m.get("ts", ""), reverse=True)
    msgs_dump = "\n\n".join(
        f"### Сообщение {i+1} — {m['ts'][:19]}\n{m['text']}"
        for i, m in enumerate(messages[:25])  # топ-25 свежих
    )

    # Сводка по системе — что сейчас существует
    inventory = []
    for p in ["scripts/extract_metaphors.py", "scripts/analyze_voice_readings.py",
              "scripts/daily_system_report.py", "scripts/night_followups_review.py",
              "scripts/technical_qa_agent.py", "scripts/auto_fix_agent.py",
              "PROTOCOLS.md", ".codex/metaphors-library.json",
              "chapters/.canon/voice/human-pavel-style.md",
              "chapters/.canon/voice/human-pavel-style-v2.md"]:
        f = V2 / p
        if f.exists():
            inventory.append(f"  ✓ {p}")
        else:
            inventory.append(f"  ✗ {p}")
    inventory_text = "\n".join(inventory)

    system = (
        "Ты — Tom, ассистент Pavel-а на проекте Сакрального Кодекса Микомистицизма. "
        "Твоя задача — провести аудит: что Pavel просил за последние дни, "
        "что я сделал, что пропустил. Это ОЧЕНЬ ВАЖНО — Pavel специально дал указание "
        "ночью просматривать свои сообщения и находить пропущенное.\n\n"
        "Будь честным и самокритичным. Не выгораживай себя. "
        "Если Pavel что-то просил а я НЕ ЗАМЕТИЛ или ОТЛОЖИЛ без причины — флажь.\n\n"
        "Отвечай ТОЛЬКО валидным JSON."
    )

    user = f"""# Последние user-сообщения Pavel-а в Codex v2 (свежее сверху)

{msgs_dump}

# Что СЕЙЧАС существует в системе

{inventory_text}

# Что вернуть

```json
{{
  "done": [
    {{"request": "что Pavel просил (1 предложение)", "evidence": "что я сделал — конкретный артефакт или endpoint"}}
  ],
  "pending": [
    {{"request": "что в работе, частично", "what_remains": "что осталось доделать"}}
  ],
  "missed": [
    {{"request": "что Pavel просил но я пропустил/проигнорировал", "why_likely": "почему я мог пропустить", "severity": 1-10}}
  ],
  "worth_doing": [
    {{"task": "конкретное действие", "rationale": "почему это имеет смысл сейчас", "effort_hours": 0.5-8}}
  ]
}}
```

Будь честным с пропусками — Pavel ХОЧЕТ их видеть. Если я молодец — done, если облажался — missed. Не больше 6 пунктов в каждой категории.
"""
    print(f"  → Opus: анализ {len(messages)} user messages...")
    try:
        resp = ask_opus(user=user, system=system, max_tokens=8000, thinking=5000)
        text = resp["text"].strip()
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        return {**data, "usage": resp.get("usage")}
    except Exception as e:
        return {"done": [], "pending": [], "missed": [], "worth_doing": [],
                "error": f"Opus/JSON error: {e}"}


def write_report(analysis: dict, total_msgs: int):
    now = datetime.now(timezone.utc)
    lines = []
    lines.append(f"# 🔍 Ночной аудит follow-ups — {now.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «в течение ночи ты проверяешь все задания которые я тебе давал... ")
    lines.append("> смотри какие моменты ты пропустил или не доделал».")
    lines.append("")
    lines.append(f"Проанализировано user-сообщений: **{total_msgs}**")
    lines.append("")

    if analysis.get("error"):
        lines.append(f"⚠️ Opus ошибка: {analysis['error']}")
        lines.append("")

    done = analysis.get("done", [])
    if done:
        lines.append(f"## ✓ Сделано ({len(done)})")
        lines.append("")
        for d in done:
            lines.append(f"- **{d.get('request', '?')}**")
            lines.append(f"  - {d.get('evidence', '?')}")
        lines.append("")

    pending = analysis.get("pending", [])
    if pending:
        lines.append(f"## ⏳ В работе ({len(pending)})")
        lines.append("")
        for p in pending:
            lines.append(f"- **{p.get('request', '?')}**")
            lines.append(f"  - Осталось: {p.get('what_remains', '?')}")
        lines.append("")

    missed = analysis.get("missed", [])
    if missed:
        missed_sorted = sorted(missed, key=lambda m: -m.get("severity", 0))
        lines.append(f"## ⚠️ Пропущено / Проигнорировано ({len(missed_sorted)})")
        lines.append("")
        lines.append("**Это что я заметил что облажался. Pavel — посмотри, выбери что взять в работу.**")
        lines.append("")
        for m in missed_sorted:
            sev = m.get("severity", "?")
            lines.append(f"- **[severity {sev}/10]** {m.get('request', '?')}")
            lines.append(f"  - {m.get('why_likely', '?')}")
        lines.append("")

    worth = analysis.get("worth_doing", [])
    if worth:
        lines.append(f"## 💡 Имеет смысл сделать сейчас ({len(worth)})")
        lines.append("")
        for w in worth:
            lines.append(f"- **{w.get('task', '?')}** _(~{w.get('effort_hours', '?')}ч)_")
            lines.append(f"  - {w.get('rationale', '?')}")
        lines.append("")

    if not (done or pending or missed or worth):
        lines.append("_Ничего не найдено в последних сессиях. Либо всё чисто, либо нет user-сообщений._")
        lines.append("")

    # Footer — журнал
    lines.append("---")
    lines.append("")
    if "usage" in analysis:
        u = analysis["usage"] or {}
        lines.append(f"_Opus tokens: {u.get('input_tokens', '?')} → {u.get('output_tokens', '?')}_")
    lines.append("")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ {OUTPUT}")

    # Event
    event = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "night_followups_review",
        "target": "history",
        "payload": {
            "messages_analyzed": total_msgs,
            "done": len(done),
            "pending": len(pending),
            "missed": len(missed),
            "worth_doing": len(worth),
        },
    }
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def main():
    messages = load_recent_user_messages(days=7)
    print(f"Найдено user messages: {len(messages)}")
    analysis = analyze_followups(messages)
    write_report(analysis, len(messages))


if __name__ == "__main__":
    main()
