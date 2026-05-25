#!/usr/bin/env python3
"""
learn_pavel_style.py — Pavel-Learning Agent.

Pavel 2026-05-20: «когда я проработаю 20 процентов текста — ты все это запомнишь
и сможешь сам писать в этом стиле. тебе нужно будет создать агента который будет
изучать как я думаю комментирую и пишу».

Что делает:
1) Читает .codex/pavel-edits.jsonl — все действия Pavel-а в редакторе
   (approve, reject, edit, stream-accept, deep_analyze)
2) Читает voice-corpus/original-ideas/*.md — оригинальные идеи Pavel-голосом
3) Читает существующий human-pavel-style.md (v1)
4) Через Opus 4.7 + extended thinking (max budget 16K) синтезирует обновлённый
   профиль стиля v2 с конкретными паттернами Pavel-вмешательства:
   - что Pavel принимает (паттерны в одобренных)
   - что Pavel правит (delta original → new)
   - какие инструкции Pavel дал stream-у (что он просит)
   - какие фразы Pavel сохраняет дословно
   - какие AI-маркеры Pavel срезает
5) Сохраняет в chapters/.canon/voice/human-pavel-style-v2.md
   (приоритет для последующих Opus-вызовов)

Запуск:
    python3 learn_pavel_style.py
    python3 learn_pavel_style.py --threshold 0.2   # требовать 20% проработки

Триггер из watcher-а:
    if total_progress >= 20%: trigger learn_pavel_style.py
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus


HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
EDITS = V2 / ".codex/pavel-edits.jsonl"
ORIGINAL_IDEAS = V2 / "voice-corpus/original-ideas"
STYLE_V1 = V2 / "chapters/.canon/voice/human-pavel-style.md"
STYLE_V2 = V2 / "chapters/.canon/voice/human-pavel-style-v2.md"
PROGRESS_THRESHOLD = 0.20  # 20%


def load_edits() -> list:
    if not EDITS.exists():
        return []
    out = []
    for line in EDITS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def calculate_progress() -> dict:
    """Считает % проработанных параграфов по всем главам."""
    chapters_dir = V2 / "chapters"
    if not chapters_dir.exists():
        return {"total": 0, "approved": 0, "pct": 0}
    total = 0
    approved = 0
    for draft_file in chapters_dir.glob("*/*/draft.md"):
        text = draft_file.read_text(encoding="utf-8")
        paras = [p for p in text.split("\n\n") if p.strip()]
        total += len(paras)
        # Соответствующий approvals.json
        approvals_file = draft_file.parent / "approvals.json"
        if approvals_file.exists():
            data = json.loads(approvals_file.read_text(encoding="utf-8"))
            approved += len(data.get("approved_indices", []))
    pct = approved / total if total else 0
    return {"total": total, "approved": approved, "pct": pct}


def summarize_edits(edits: list) -> str:
    """Группирует edits по action и составляет краткий обзор."""
    by_action = defaultdict(list)
    for e in edits:
        by_action[e.get("action", "?")].append(e)

    lines = []
    for action, items in sorted(by_action.items(), key=lambda x: -len(x[1])):
        lines.append(f"\n## Action: {action} ({len(items)})")
        for e in items[:30]:  # max 30 per action
            orig = (e.get("original") or "")[:300]
            new = (e.get("new") or "")[:300]
            instr = e.get("instruction") or ""
            score = e.get("masterpiece_score")
            lines.append(f"\n### {e.get('chapter_id', '?')} para {e.get('paragraph_idx', '?')}")
            if instr:
                lines.append(f"**Инструкция Pavel-а:** {instr}")
            if orig:
                lines.append(f"**Оригинал:** {orig}")
            if new:
                lines.append(f"**Новое:** {new}")
            if score is not None:
                lines.append(f"**Masterpiece score:** {score}")
    return "\n".join(lines)


def gather_original_ideas_sample(max_chars: int = 30000) -> str:
    if not ORIGINAL_IDEAS.exists():
        return ""
    parts = []
    total = 0
    for f in sorted(ORIGINAL_IDEAS.glob("*.md")):
        text = f.read_text(encoding="utf-8")[:5000]
        if total + len(text) > max_chars:
            break
        parts.append(f"# {f.stem}\n\n{text}")
        total += len(text)
    return "\n\n---\n\n".join(parts)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=PROGRESS_THRESHOLD)
    ap.add_argument("--force", action="store_true", help="Запустить даже если < threshold")
    args = ap.parse_args()

    progress = calculate_progress()
    print(f"Прогресс: {progress['approved']} / {progress['total']} параграфов = {progress['pct']*100:.1f}%")
    if progress["pct"] < args.threshold and not args.force:
        print(f"Меньше {args.threshold*100:.0f}% — пропускаю (используй --force чтобы запустить вручную)")
        return

    edits = load_edits()
    print(f"Edits в журнале: {len(edits)}")

    style_v1 = STYLE_V1.read_text(encoding="utf-8") if STYLE_V1.exists() else ""
    edits_summary = summarize_edits(edits) if edits else "(пока нет edits)"
    voice_sample = gather_original_ideas_sample()

    system = (
        "Ты — учитель-аналитик. Изучаешь как Pavel (Хилингод) принимает решения "
        "над текстом Сакрального Кодекса Микомистицизма. Твоя задача — извлечь "
        "СВЕЖИЕ ПАТТЕРНЫ его стиля из его последних правок в редакторе "
        "+ его оригинальных voice-надиктовок. Это будет новой версией style-эталона "
        "которым AI калибрует генерацию. "
        "\n"
        "Фокус на:\n"
        "1) Какие конкретные слова Pavel оставляет / удаляет\n"
        "2) Какие синтаксические паттерны он любит\n"
        "3) Какие инструкции он даёт AI («сократи», «усиль сакральность»...)\n"
        "4) Что он принимает (приняты после deep_analyze с masterpiece_score)\n"
        "5) Что он переписывает (delta до → после)\n"
        "6) Его типичные образы и метафоры из voice-корпуса\n"
        "\n"
        "Отвечай по-русски, в формате Markdown — этот документ заменит "
        "human-pavel-style.md как новый канон стиля."
    )

    user = f"""# Базовый профиль стиля v1 (что у нас уже есть)

{style_v1[:5000]}

---

# Pavel-edits журнал ({len(edits)} событий)

{edits_summary[:30000]}

---

# Sample из voice-corpus original-ideas (oригинальный голос Pavel-а)

{voice_sample[:30000]}

---

# Что мне нужно

Создай **human-pavel-style v2** — обновлённый канон стиля Pavel-а.

Структура (точно по этой схеме):

## 🎯 Главное (что нового я узнал из правок)

3-5 пунктов — новые паттерны которые проявились после изучения правок.

## 📋 Обновлённые приёмы (v2)

Расширенный список приёмов с конкретными примерами ИЗ ЕГО ПРАВОК.
Каждый приём:
- Описание
- Пример из его edits: «Pavel взял X и сделал Y»
- Пример из его voice-корпуса (цитата)

## 🚫 Что Pavel ВСЕГДА удаляет / правит

Конкретные слова/обороты которые он систематически вычищает.

## ✓ Что Pavel ВСЕГДА сохраняет

Конкретные слова/обороты которые он систематически оставляет.

## 🎙 Любимые инструкции к AI

Какие команды Pavel даёт (из stream-accept events) — это даст подсказку что
приоритизировать при auto-generation.

## 🔥 Сильные образы из voice-корпуса

10-15 авторских образов/метафор которые Pavel часто использует.

## 📊 Style fitness — 10 параметров v2

Обновлённые 10 параметров для text_analyzer.py с КОНКРЕТНЫМИ values
(не «больше есть» а «есть-density > 0.05 per sentence»).

## 🎓 Pavel thinks like

Описание мышления Pavel-а — как он подходит к тексту, что ценит, чего избегает.
3-5 фраз. Это будет использоваться как контекст в каждом Opus-вызове.

---

Длина: 2000-4000 слов. Конкретно, с цитатами из его собственных правок.
"""

    print("→ Opus 4.7 + extended thinking 12K — изучает Pavel-а...")
    resp = ask_opus(user=user, system=system, max_tokens=14000, thinking=12000)

    STYLE_V2.parent.mkdir(parents=True, exist_ok=True)
    # Архив старого v2 если есть
    if STYLE_V2.exists():
        archive = STYLE_V2.parent / "archive"
        archive.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        (archive / f"human-pavel-style-v2-{ts}.md").write_text(STYLE_V2.read_text(encoding="utf-8"), encoding="utf-8")

    header = (
        f"<!-- generated: {now_iso()} -->\n"
        f"<!-- model: {resp.get('model')} -->\n"
        f"<!-- tokens: in {resp['usage'].get('input_tokens')}, out {resp['usage'].get('output_tokens')} -->\n"
        f"<!-- progress: {progress['pct']*100:.1f}% ({progress['approved']}/{progress['total']} paragraphs) -->\n"
        f"<!-- edits analyzed: {len(edits)} -->\n\n"
    )
    STYLE_V2.write_text(header + resp["text"], encoding="utf-8")
    print(f"✓ Style v2: {STYLE_V2}")
    print(f"  Tokens in/out: {resp['usage'].get('input_tokens')}/{resp['usage'].get('output_tokens')}")

    # Event
    event = {
        "ts": now_iso(),
        "type": "pavel_style_learned",
        "target": "chapters/.canon/voice/human-pavel-style-v2.md",
        "payload": {
            "edits_analyzed": len(edits),
            "progress_pct": progress["pct"],
            "tokens_in": resp["usage"].get("input_tokens"),
            "tokens_out": resp["usage"].get("output_tokens"),
        },
    }
    events_file = V2 / ".codex/events.jsonl"
    with events_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
