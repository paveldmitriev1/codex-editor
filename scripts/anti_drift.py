#!/usr/bin/env python3
"""
anti_drift.py — Anti-drift sentinel.

Pavel: «главное не потерять нить идей которые я изначально в потоке наговаривал
когда писал оригиналы и правил эти тексты».

Логика:
1) Для главы X — находим все voice-extracts по теме (slug-match)
2) Через Opus 4.7 извлекаем главные тезисы из них (Pavel-голос ОРИГИНАЛ)
3) Сравниваем с текущим драфтом главы
4) Выдаём: «вот 12 идей Pavel сказал голосом — в драфте есть 7. 5 ПОТЕРЯНО. Список ↓»

Это сторож-проверка: каждая глава проходит через него ПЕРЕД published.

Использование:
    from anti_drift import check_chapter_drift
    result = check_chapter_drift('book-03-ch-01', draft_text='...')
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

HOME = Path.home()
V1_VOICE = HOME / "Desktop/Codex/sources/voice-extracts"
V2 = HOME / "Desktop/Codex2"


def slugify(text: str) -> str:
    t = text.lower()
    table = str.maketrans({
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh",
        "з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o",
        "п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts",
        "ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu",
        "я":"ya",
    })
    t = t.translate(table)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t)).strip("-")


def find_voice_extracts_for_chapter(chapter_title: str) -> List[Path]:
    """Найти voice-extract .md по slug-пересечению с названием главы."""
    if not V1_VOICE.exists():
        return []
    chapter_words = set(slugify(chapter_title).split("-"))
    chapter_words = {w for w in chapter_words if len(w) >= 4}
    matched = []
    for vf in V1_VOICE.glob("*.md"):
        vf_words = set(slugify(vf.stem).split("-"))
        if chapter_words & vf_words:
            matched.append(vf)
    return matched


def extract_pavel_core_ideas(voice_files: List[Path]) -> dict:
    """Через Opus — выделить ОРИГИНАЛЬНЫЕ ключевые идеи Pavel-а из voice-надиктовок."""
    if not voice_files:
        return {"ideas": [], "skipped": True, "reason": "нет voice-extracts по теме"}

    combined = "\n\n--- РАЗДЕЛИТЕЛЬ ---\n\n".join(
        f"### Источник: {vf.name}\n\n{vf.read_text(encoding='utf-8')[:8000]}"
        for vf in voice_files[:5]   # топ-5
    )

    system = (
        "Ты — хранитель оригинального голоса Pavel-а (Хилингода). Эти voice-extracts — "
        "ЕГО ПРЯМАЯ РЕЧЬ в потоке (не пересказ AI). Твоя задача: выделить "
        "ВСЕ КЛЮЧЕВЫЕ ИДЕИ, которые он там сказал. Не пересказ, не суммарий — список тезисов "
        "в его собственных формулировках где возможно. Цель: не потерять НИЧЕГО важного "
        "когда мы будем собирать главу. Отвечай только валидным JSON."
    )

    user = f"""# Voice-надиктовки Pavel-а на эту тему

{combined[:30000]}

---

# Что вернуть

JSON со схемой:

```json
{{
  "core_ideas": [
    {{
      "id": "i01",
      "idea": "одна фраза-тезис в стиле Pavel-а",
      "source_quote": "цитата из voice если есть",
      "importance": "high|medium|low",
      "category": "тема к которой принадлежит"
    }}
  ]
}}
```

Извлеки 8-25 идей. Каждая — одна мысль, не общая категория. Используй РЕЧЬ Pavel-а:
«есть» не «является», активные глаголы, «я скажу вам» а не «я хотел бы сказать».
"""

    resp = ask_opus(user=user, system=system, max_tokens=4000, thinking=3000)
    try:
        cleaned = re.sub(r"^```json\s*|\s*```$", "", resp["text"].strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
    except Exception as e:
        return {"ideas": [], "error": str(e), "raw": resp["text"][:1000]}

    return {
        "ideas": data.get("core_ideas", []),
        "voice_files_count": len(voice_files),
        "usage": resp["usage"],
        "model": resp["model"],
    }


def check_idea_coverage(draft_text: str, ideas: List[dict]) -> dict:
    """Через Opus — для каждой идеи: есть/частично/нет в драфте."""
    if not ideas:
        return {"covered": [], "partial": [], "lost": [], "added": []}

    ideas_block = "\n".join(f"- **{i['id']}**: {i['idea']}" for i in ideas)

    system = (
        "Ты — судья сохранности идей. Сравниваешь оригинальные тезисы Pavel-а из его "
        "voice-потока с текущим драфтом главы. Для каждой идеи определяешь: ПРИСУТСТВУЕТ "
        "(есть в драфте по смыслу), ЧАСТИЧНО (упомянуто, но размыто/слабо), ПОТЕРЯНО "
        "(в драфте отсутствует или искажено). Также флагуешь идеи в драфте которых НЕТ "
        "в оригинале (могут быть AI-добавлениями). Отвечай только JSON."
    )

    user = f"""# Оригинальные идеи Pavel-а (из его voice-потока)

{ideas_block}

# Текущий драфт главы

{draft_text[:25000]}

---

JSON ответ:

```json
{{
  "covered":  [{{"id": "iXX", "where": "цитата из драфта"}}],
  "partial":  [{{"id": "iXX", "why_weak": "одна фраза"}}],
  "lost":     [{{"id": "iXX", "criticality": "high|medium|low", "where_to_add": "в какое место драфта"}}],
  "added_by_ai": [{{"what": "идея из драфта которой нет в voice", "risk": "high|medium|low"}}]
}}
```
"""

    resp = ask_opus(user=user, system=system, max_tokens=4000, thinking=3000)
    try:
        cleaned = re.sub(r"^```json\s*|\s*```$", "", resp["text"].strip(), flags=re.MULTILINE).strip()
        return {**json.loads(cleaned), "usage": resp["usage"], "model": resp["model"]}
    except Exception as e:
        return {"error": str(e), "raw": resp["text"][:1000]}


def check_chapter_drift(chapter_id: str, chapter_title: str, draft_text: str) -> dict:
    """Полный pipeline: найти voice → извлечь идеи → проверить покрытие → отчёт."""
    voice_files = find_voice_extracts_for_chapter(chapter_title)

    if not voice_files:
        return {
            "chapter_id": chapter_id,
            "no_voice": True,
            "message": "Нет voice-extracts по теме главы. Drift-проверка пропущена.",
        }

    print(f"  → Anti-drift: нашёл {len(voice_files)} voice-extracts для «{chapter_title}»")
    print(f"     Извлекаю core ideas через Opus...")

    ideas_result = extract_pavel_core_ideas(voice_files)
    if not ideas_result.get("ideas"):
        return {"chapter_id": chapter_id, "error": "Не извлеклись идеи", "raw": ideas_result}

    print(f"     {len(ideas_result['ideas'])} ключевых идей извлечено")
    print(f"     Проверяю покрытие в драфте...")

    coverage = check_idea_coverage(draft_text, ideas_result["ideas"])

    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "voice_files": [vf.name for vf in voice_files],
        "ideas": ideas_result["ideas"],
        "coverage": coverage,
        "total_in":  (ideas_result.get("usage", {}).get("input_tokens", 0) +
                      coverage.get("usage", {}).get("input_tokens", 0)),
        "total_out": (ideas_result.get("usage", {}).get("output_tokens", 0) +
                      coverage.get("usage", {}).get("output_tokens", 0)),
    }


def render_drift_report(result: dict) -> str:
    if result.get("no_voice"):
        return f"## 🔒 Anti-drift\n\n_{result['message']}_\n"
    if "error" in result:
        return f"## 🔒 Anti-drift\n\n⚠ Ошибка: {result['error']}\n"

    ideas = result.get("ideas", [])
    cov = result.get("coverage", {})

    covered = cov.get("covered", [])
    partial = cov.get("partial", [])
    lost = cov.get("lost", [])
    added = cov.get("added_by_ai", [])

    score = round(len(covered) / max(1, len(ideas)) * 100, 1)

    out = [
        "## 🔒 Anti-drift — нить оригинальных идей Pavel-а",
        "",
        f"**Voice-extracts использовано:** {len(result.get('voice_files', []))}",
        f"**Идей извлечено:** {len(ideas)}",
        f"**Покрытие в драфте:** {len(covered)} есть / {len(partial)} частично / {len(lost)} **ПОТЕРЯНО**",
        f"**Drift-score:** **{score}/100**",
        "",
    ]
    if lost:
        out.append("### 🚨 ПОТЕРЯННЫЕ идеи (нужно вернуть в драфт)")
        out.append("")
        # Сопоставить с original ideas
        ideas_by_id = {i["id"]: i for i in ideas}
        for l in lost:
            idea = ideas_by_id.get(l.get("id"), {})
            crit = l.get("criticality", "?")
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(crit, "⚪")
            out.append(f"- {emoji} **[{crit}]** {idea.get('idea', '?')} (id: {l.get('id')})")
            if l.get("where_to_add"):
                out.append(f"  → куда вернуть: {l['where_to_add']}")
        out.append("")
    if partial:
        out.append("### 🟡 ЧАСТИЧНО — усилить")
        out.append("")
        ideas_by_id = {i["id"]: i for i in ideas}
        for p in partial:
            idea = ideas_by_id.get(p.get("id"), {})
            out.append(f"- {idea.get('idea', '?')} — _{p.get('why_weak', '')}_")
        out.append("")
    if added:
        out.append("### ⚠ ДОБАВЛЕНО AI (не из voice — может быть дрейф)")
        out.append("")
        for a in added:
            risk = a.get("risk", "?")
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(risk, "⚪")
            out.append(f"- {emoji} **[{risk}]** {a.get('what', '?')}")
        out.append("")
    if covered:
        out.append("### ✓ Сохранено")
        out.append("")
        ideas_by_id = {i["id"]: i for i in ideas}
        for c in covered[:10]:
            idea = ideas_by_id.get(c.get("id"), {})
            out.append(f"- {idea.get('idea', '?')}")
        if len(covered) > 10:
            out.append(f"- … ещё {len(covered) - 10}")
        out.append("")

    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter_id")
    ap.add_argument("title")
    ap.add_argument("draft_path")
    args = ap.parse_args()
    draft = Path(args.draft_path).read_text(encoding="utf-8")
    r = check_chapter_drift(args.chapter_id, args.title, draft)
    print(render_drift_report(r))
