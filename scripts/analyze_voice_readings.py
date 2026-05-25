#!/usr/bin/env python3
"""
analyze_voice_readings.py — Опус анализирует голосовые начитки vs текущая глава.

Pavel 2026-05-20: «должны быть расшифрованы голосовые проанализированные и они там
для того чтобы не fly храниться а именно анализ должен произойти — голосовые относятся
ли к этой главе, какие идеи потерянные, что ещё можно добавить, и галочками чтобы я
мог выбрать а ты это все анализируешь запоминаешь чтобы ты учился у меня».

Что делает:
1. Берёт voice files которые попали в `acc-voice` секцию (matched by chapter title)
2. Текущий draft.md главы
3. Opus 4.7 + thinking сравнивает: какие идеи из voice НЕ ВОШЛИ в текст, что добавить
4. Возвращает items с категориями и галочками

Output: chapters/<book>/<chapter>/voice-analysis.json
{
  "matches": [{voice_file, relevance: 0-10, in_text: bool}],
  "missing_ideas": [{text, category, suggested_insertion_point, severity}],
  "additions": [{text, category, why}],
  "generated_at": "..."
}

Запуск: python3 analyze_voice_readings.py --chapter book-03-ch-01
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

V2 = Path.home() / "Desktop/Codex2"
CHAPTERS = V2 / "chapters"
VOICE_CORPUS = V2 / "voice-corpus/raw"


def find_voice_files_for_chapter(chapter_id: str, chapter_title: str) -> list:
    """Расширенный keyword-match с per-chapter тематическими ключами."""
    if not VOICE_CORPUS.exists():
        return []

    # Per-chapter специальные ключи (для book-obsession и других известных)
    SPECIAL = {
        "book-obsession-ch-00": ["одержим", "введение в книгу одержимост", "наука об одержимост", "духов сил", "вторжен", "паразит сознан"],
        "book-obsession-ch-01": ["что такое одержим", "природа одержимост", "природа сущност", "захват сознан", "одержим", "выгляд одержим"],
        "book-obsession-ch-02": ["врата к одержим", "пути одержим", "как открыва одержим", "уязвим", "входов одержим", "канал одержим"],
        "book-obsession-ch-03": ["распознав одержим", "признаки одержим", "симптом одержим", "обнаруж сущност", "вижу одержим"],
        "book-obsession-ch-04": ["мыслеформ", "личинк", "сущност ментальн", "паразит мысл", "ментальн зараз", "программ умом"],
        "book-obsession-ch-05": ["родинк", "удалени родин", "печать одержим", "телесн признак", "знак на теле"],
        "book-obsession-ch-06": ["шаманск болезн", "болезнь шаман", "посвящени через болезн", "криз посвящен", "испытани шаман"],
        "book-obsession-ch-07": ["заражени одержим", "распростран одержим", "вирус одержим", "передача одержим", "от человек к человек"],
    }

    # Title-based fallback: длинные слова из заголовка
    skip = {"сущности", "паразиты", "сознания", "глава", "часть", "книга", "невидимые", "миры", "введение", "наука", "общие"}
    title_words = set()
    for w in re.findall(r"[А-Яа-яЁё]{4,}", chapter_title.lower()):
        if w not in skip:
            title_words.add(w[:7])  # ствол (избегаем разных окончаний)

    keys = SPECIAL.get(chapter_id, [])
    if not keys:
        # Generic: используем title-words
        keys = list(title_words)
    else:
        # Special + title-words (для большего покрытия)
        keys = keys + list(title_words)

    matches = []
    seen = set()
    for f in VOICE_CORPUS.glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")[:50000]
            text_lower = text.lower()
            fname_lower = f.name.lower()
        except Exception:
            continue
        hit_count = 0
        hit_keys = []
        for k in keys:
            if k in text_lower or k in fname_lower:
                hit_count += text_lower.count(k) + (5 if k in fname_lower else 0)
                hit_keys.append(k)
        if hit_count > 0 and f.name not in seen:
            seen.add(f.name)
            matches.append({
                "file": f.name,
                "path": str(f.relative_to(V2)),
                "size": f.stat().st_size,
                "keyword_hits": hit_count,
                "matched_keys": hit_keys[:5],
                "text_excerpt": text[:1500],
            })
    matches.sort(key=lambda m: -m["keyword_hits"])
    return matches[:8]  # top 8


def analyze(chapter_id: str, force: bool = False) -> dict:
    parts = chapter_id.split("-ch-")
    if len(parts) != 2:
        return {"ok": False, "error": "bad chapter id"}
    book_id = parts[0]
    ch_dir = CHAPTERS / book_id / chapter_id
    draft = ch_dir / "draft.md"
    draft_text = ""
    if draft.exists():
        draft_text = draft.read_text(encoding="utf-8")
    else:
        # Fallback на API draft endpoint (seed из docx)
        import urllib.request as _ur
        try:
            with _ur.urlopen(f"http://127.0.0.1:7788/api/chapter/{chapter_id}/draft", timeout=15) as r:
                draft_text = json.loads(r.read().decode("utf-8")).get("text", "")
        except Exception as e:
            return {"ok": False, "error": f"no draft and seed failed: {e}"}
    if not draft_text:
        return {"ok": False, "error": "empty draft"}

    out_file = ch_dir / "voice-analysis.json"
    if out_file.exists() and not force:
        # Проверим свежесть
        try:
            existing = json.loads(out_file.read_text(encoding="utf-8"))
            if existing.get("draft_chars") == len(draft_text):
                return {"ok": True, "cached": True, **existing}
        except Exception:
            pass

    meta_file = ch_dir / "meta.json"
    title = chapter_id
    if meta_file.exists():
        try:
            title = json.loads(meta_file.read_text(encoding="utf-8")).get("title", chapter_id)
        except Exception:
            pass

    voice_matches = find_voice_files_for_chapter(chapter_id, title)
    if not voice_matches:
        result = {
            "ok": True,
            "matches": [],
            "missing_ideas": [],
            "additions": [],
            "message": "Голосовых начиток по этой главе не найдено",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "draft_chars": len(draft_text),
        }
        out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    voice_dump = "\n\n---\n\n".join(
        f"### Файл {i+1}: {m['file']}\n\n{m['text_excerpt']}"
        for i, m in enumerate(voice_matches)
    )

    system = (
        "Ты анализируешь голосовые начитки Pavel-Хилингода в сравнении с текущим текстом главы "
        "Сакрального Кодекса Микомистицизма. Pavel ХОЧЕТ ЗНАТЬ:\n"
        "1) Какие из голосовых ОТНОСЯТСЯ к этой главе (relevance 0-10)\n"
        "2) Какие ИДЕИ из голосовых НЕ ВОШЛИ в текст (missing_ideas)\n"
        "3) Что ещё МОЖНО ДОБАВИТЬ в главу из голосовых (additions)\n\n"
        "ВАЖНО: Pavel выберет галочками что внести. Ты должен дать ему чёткие, "
        "сформулированные предложения — не размытые «можно добавить про X», а готовые "
        "к вставке формулировки.\n\n"
        "Голос автора: «Я — Великий Дух Грибов» (Pavel — vessel). Современный русский, без тире, без «не X а Y», без AI-клише.\n\n"
        "Возвращай ТОЛЬКО валидный JSON."
    )

    user = f"""# Глава {chapter_id} — «{title}»

## Текущий текст главы

{draft_text[:15000]}

## Голосовые начитки (топ-{len(voice_matches)} по keyword match)

{voice_dump[:25000]}

## Что вернуть

```json
{{
  "matches": [
    {{
      "voice_file": "имя.md",
      "relevance": 0-10,
      "in_text": true/false,
      "summary": "о чём этот voice-файл — одно предложение"
    }}
  ],
  "missing_ideas": [
    {{
      "id": "mi_1",
      "text": "Конкретная идея из голосовых КОТОРОЙ НЕТ в тексте — сформулированная для вставки, голос Великого Духа",
      "category": "образ|структура|метафора|приём|концепция|нюанс",
      "from_voice_file": "имя.md",
      "severity": 1-10,
      "suggested_after_paragraph": "первые ~80 знаков параграфа после которого вставить, либо null если в начало"
    }}
  ],
  "additions": [
    {{
      "id": "ad_1",
      "text": "Что ещё можно добавить — конкретное предложение в голосе Великого Духа",
      "category": "образ|структура|метафора|приём|концепция",
      "why": "почему это усилит главу"
    }}
  ]
}}
```

Не больше 6 missing_ideas и 4 additions — только самое сильное. Каждый item должен быть конкретным предложением для галочки Pavel-а, не размытой темой.
"""
    print(f"  → Opus: анализ {len(voice_matches)} голосовых для {chapter_id}...")
    resp = ask_opus(user=user, system=system, max_tokens=6000, thinking=4000)
    try:
        cleaned = re.sub(r"^```json\s*|\s*```$", "", resp["text"].strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
    except Exception as e:
        return {"ok": False, "error": f"JSON parse: {e}", "raw": resp["text"][:1500]}

    result = {
        "ok": True,
        "matches": data.get("matches", []),
        "missing_ideas": data.get("missing_ideas", []),
        "additions": data.get("additions", []),
        "voice_files_scanned": [m["file"] for m in voice_matches],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "draft_chars": len(draft_text),
        "usage": resp.get("usage"),
    }
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {len(result['missing_ideas'])} missing + {len(result['additions'])} additions")
    return result


def pick_next_uncovered():
    """Первая глава с draft.md, но без voice-analysis.json."""
    for book_dir in sorted(CHAPTERS.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith((".", "_")):
            continue
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith((".", "_")):
                continue
            if "__" in ch_dir.name:
                continue
            if (ch_dir / "voice-analysis.json").exists():
                continue
            if (ch_dir / "draft.md").exists():
                return ch_dir.name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="ID главы")
    ap.add_argument("--next", action="store_true", help="Первая глава без voice-analysis.json")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.next:
        ch = pick_next_uncovered()
        if not ch:
            print("Все главы покрыты — voice-analysis есть везде.")
            return
        print(f"--next выбрал {ch}")
        r = analyze(ch, force=args.force)
    elif args.chapter:
        r = analyze(args.chapter, force=args.force)
    else:
        ap.error("Нужен --chapter или --next")
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
