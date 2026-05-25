#!/usr/bin/env python3
"""
extract_metaphors.py — извлекает метафоры из главы + строит склад уникальных.

Pavel 2026-05-20: «нужен агент который сверяет метафоры между главами и не даёт
им повторяться. Склад уникальных метафор из которых выбираем лучшие».

Что делает:
1) Для каждой главы (draft.md или first source docx):
   - Через Opus извлекает все метафоры (образы, сравнения, аналогии)
   - Категоризирует: грибная/телесная/природная/архитектурная/космическая
   - Считает «силу» метафоры 1-10
2) Складывает в `Codex2/.codex/metaphors-library.json`:
   {
     "metaphors": [
       {
         "id": "m_001",
         "text": "Я срываю штору с ваших глаз",
         "category": "телесная",
         "strength": 9,
         "first_used_in": "book-03-ch-01",
         "also_used_in": [],
         "is_duplicate_of": null,
         "is_ai_cliche": false
       }
     ]
   }
3) Помечает дубликаты — одна метафора используется в нескольких главах
4) Помечает AI-клише: Страдивари, компьютер-молоток, хоккеист-бассейн, и т.п.

Запуск:
    python3 extract_metaphors.py --chapter book-03-ch-01
    python3 extract_metaphors.py --all   # все главы с готовыми draft-ами
    python3 extract_metaphors.py --rebuild-library  # только пересборка склада
"""

import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
SOURCES = V2 / "sources"
CHAPTERS_DIR = V2 / "chapters"
LIBRARY = V2 / ".codex/metaphors-library.json"

# Известные AI-клише — Opus должен их флажить
AI_CLICHE_PATTERNS = [
    "страдивари", "скрипка", "хоккеист в бассейне", "компьютер-молоток",
    "симфония вселенной", "рябь на воде", "вершина айсберга",
    "две стороны медали", "ключ к двери", "корни и крона", "маяк во тьме",
    "нить ариадны", "огонь души", "капля в океане", "семя сознания",
    "зеркало души",
]


def extract_chapter_text(chapter_id: str) -> tuple:
    """Возвращает (book_id, chapter_dir, text_to_analyze)."""
    parts = chapter_id.split("-ch-")
    if len(parts) != 2:
        return None, None, None
    book_id = parts[0]
    chapter_dir = CHAPTERS_DIR / book_id / chapter_id
    # Prefer draft.md, fallback к first source
    draft = chapter_dir / "draft.md"
    if draft.exists():
        return book_id, chapter_dir, draft.read_text(encoding="utf-8")
    # Fallback: source
    src_dir = SOURCES / book_id / chapter_id / "from-grant"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.suffix.lower() != ".docx":
                continue
            if f.name.startswith("!") or "общий текст" in f.name.lower() or "всех глав" in f.name.lower():
                continue
            # Quick docx extract
            try:
                with zipfile.ZipFile(f) as z:
                    xml = z.read("word/document.xml").decode("utf-8", "replace")
                paras = re.findall(r"<w:p[^>]*>(.*?)</w:p>", xml, re.DOTALL)
                text = "\n\n".join(
                    "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
                    for p in paras if "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
                )
                return book_id, chapter_dir, text
            except Exception:
                continue
    return book_id, chapter_dir, None


def extract_metaphors_from_text(chapter_id: str, text: str) -> dict:
    """Один Opus call — извлекает метафоры с категоризацией."""
    if not text or len(text) < 200:
        return {"metaphors": []}

    system = (
        "Ты — каталогизатор метафор Сакрального Кодекса Микомистицизма. "
        "Pavel хочет иметь СКЛАД уникальных метафор и образов, чтобы они не повторялись "
        "в разных главах. Извлеки ВСЕ метафоры, сравнения, аналогии, образы из текста. "
        "Каждую — в отдельный объект с категорией, силой, и флагом AI-клише. JSON only."
    )
    user = f"""# Текст главы {chapter_id}

{text[:25000]}

# Что вернуть

```json
{{
  "metaphors": [
    {{
      "text": "Я срываю штору с ваших глаз",
      "context": "одна фраза вокруг — для понимания где использована",
      "category": "телесная|природная|архитектурная|космическая|грибная|социальная|техническая|световая",
      "strength": 8,
      "is_ai_cliche": false,
      "cliche_reason": "если is_ai_cliche=true — почему (страдивари, компьютер-молоток и т.п.)"
    }},
    ...
  ]
}}
```

Извлекай:
- Прямые метафоры («ваше тело есть храм»)
- Скрытые сравнения («Я открываю в вас то, что вы закрыли»)
- Аналогии («как мицелий пронизывает почву»)
- Сильные образы (даже без явного «как» — «эго есть оккупированная территория»)

ФЛАЖЬ AI-клише:
- Скрипка Страдивари
- Компьютер/молоток
- Хоккеист в бассейне
- Симфония вселенной
- Рябь на воде
- Вершина айсберга
- Маяк во тьме
- Нить Ариадны
- Любые шаблонные образы

strength 1-10: 10 = уникально, мощно, врезается; 1 = слабо, тривиально.
category — одна из перечисленных, без новых.
"""
    print(f"  → Opus: извлечение метафор для {chapter_id}...")
    resp = ask_opus(user=user, system=system, max_tokens=6000, thinking=4000)
    try:
        cleaned = re.sub(r"^```json\s*|\s*```$", "", resp["text"].strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
    except Exception as e:
        return {"metaphors": [], "error": str(e), "raw": resp["text"][:1000]}

    return {**data, "usage": resp["usage"], "model": resp.get("model")}


def normalize_metaphor(text: str) -> str:
    """Для дедупликации — нормализуем."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def detect_ai_cliche(text: str) -> bool:
    """Простой regex-чек на известные AI-клише."""
    low = text.lower()
    return any(pattern in low for pattern in AI_CLICHE_PATTERNS)


def add_to_library(chapter_id: str, metaphors: list) -> dict:
    """Добавляет в склад с дедупликацией."""
    LIBRARY.parent.mkdir(parents=True, exist_ok=True)
    lib = {"metaphors": [], "by_category": {}, "ai_cliches": []}
    if LIBRARY.exists():
        lib = json.loads(LIBRARY.read_text(encoding="utf-8"))
    existing_by_norm = {normalize_metaphor(m["text"]): m for m in lib["metaphors"]}
    by_id = {m["id"]: m for m in lib["metaphors"]}

    added = 0
    duplicates_found = 0
    for m in metaphors:
        if not m.get("text"):
            continue
        norm = normalize_metaphor(m["text"])
        is_ai = m.get("is_ai_cliche") or detect_ai_cliche(m["text"])
        if norm in existing_by_norm:
            # Дубликат
            ex = existing_by_norm[norm]
            if chapter_id not in ex.get("also_used_in", []) and ex.get("first_used_in") != chapter_id:
                ex.setdefault("also_used_in", []).append(chapter_id)
                duplicates_found += 1
        else:
            new_id = f"m_{len(lib['metaphors']) + 1:04d}"
            entry = {
                "id": new_id,
                "text": m["text"],
                "context": m.get("context", ""),
                "category": m.get("category", "uncategorized"),
                "strength": m.get("strength", 5),
                "is_ai_cliche": is_ai,
                "cliche_reason": m.get("cliche_reason", "") if is_ai else "",
                "first_used_in": chapter_id,
                "also_used_in": [],
            }
            lib["metaphors"].append(entry)
            existing_by_norm[norm] = entry
            by_id[new_id] = entry
            added += 1
            if is_ai:
                lib.setdefault("ai_cliches", []).append(new_id)

    # Пересборка by_category index
    by_cat = defaultdict(list)
    for m in lib["metaphors"]:
        by_cat[m.get("category", "uncategorized")].append(m["id"])
    lib["by_category"] = dict(by_cat)
    lib["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    LIBRARY.write_text(json.dumps(lib, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added": added, "duplicates": duplicates_found, "total_in_library": len(lib["metaphors"])}


def process_chapter(chapter_id: str) -> dict:
    book_id, chapter_dir, text = extract_chapter_text(chapter_id)
    if not text:
        return {"ok": False, "error": "no text"}
    print(f"\n=== {chapter_id} ({len(text):,} chars) ===")
    result = extract_metaphors_from_text(chapter_id, text)
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    metaphors = result.get("metaphors", [])

    # Сохраняем chapter-level metaphors.json
    chapter_dir.mkdir(parents=True, exist_ok=True)
    (chapter_dir / "metaphors.json").write_text(
        json.dumps({"metaphors": metaphors, "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Добавляем в склад
    lib_result = add_to_library(chapter_id, metaphors)
    print(f"  ✓ {len(metaphors)} метафор извлечено")
    print(f"  ✓ В склад добавлено: {lib_result['added']}, дубликатов найдено: {lib_result['duplicates']}")
    print(f"  ✓ Всего в библиотеке: {lib_result['total_in_library']}")

    # Event
    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "metaphors_extracted",
        "target": chapter_id,
        "payload": {
            "count": len(metaphors),
            "added_to_library": lib_result["added"],
            "duplicates": lib_result["duplicates"],
            "tokens_in": result.get("usage", {}).get("input_tokens"),
            "tokens_out": result.get("usage", {}).get("output_tokens"),
        },
    }
    events = V2 / ".codex/events.jsonl"
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return {"ok": True, "count": len(metaphors), **lib_result}


def pick_next_uncovered():
    """Первая глава с draft.md или from-grant, но без metaphors.json."""
    for book_dir in sorted(CHAPTERS_DIR.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith((".", "_")):
            continue
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith((".", "_")):
                continue
            if "__" in ch_dir.name:
                continue
            if (ch_dir / "metaphors.json").exists():
                continue
            if (ch_dir / "draft.md").exists():
                return ch_dir.name
    for book_dir in sorted(SOURCES.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith((".", "_")):
            continue
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith((".", "_")):
                continue
            if "__" in ch_dir.name:
                continue
            chapters_path = CHAPTERS_DIR / book_dir.name / ch_dir.name
            if (chapters_path / "metaphors.json").exists():
                continue
            if (ch_dir / "from-grant").exists():
                return ch_dir.name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="ID главы")
    ap.add_argument("--all", action="store_true", help="Все главы с draft.md или source")
    ap.add_argument("--next", action="store_true", help="Первая глава без metaphors.json")
    ap.add_argument("--rebuild-library", action="store_true", help="Только пересборка склада из per-chapter")
    args = ap.parse_args()

    if args.rebuild_library:
        # TODO: пересобрать из всех chapter-level metaphors.json
        print("rebuild-library: TBD")
        return

    if args.next:
        ch = pick_next_uncovered()
        if not ch:
            print("Все главы покрыты — метафоры извлечены везде.")
            return
        print(f"--next выбрал {ch}")
        process_chapter(ch)
        return

    if args.chapter:
        process_chapter(args.chapter)
        return

    if args.all:
        # Все главы где есть draft.md ИЛИ source docx
        targets = []
        for book_dir in CHAPTERS_DIR.iterdir():
            if not book_dir.is_dir() or book_dir.name.startswith("."):
                continue
            for ch_dir in book_dir.iterdir():
                if (ch_dir / "draft.md").exists():
                    targets.append(ch_dir.name)
        # Также главы с source но без draft
        for book_dir in SOURCES.iterdir():
            if not book_dir.is_dir() or book_dir.name.startswith("."):
                continue
            for ch_dir in book_dir.iterdir():
                if ch_dir.name in targets:
                    continue
                if (ch_dir / "from-grant").exists():
                    targets.append(ch_dir.name)
        targets.sort()
        print(f"Обрабатываю {len(targets)} глав...")
        for ch_id in targets:
            try:
                process_chapter(ch_id)
            except Exception as e:
                print(f"  ✗ {ch_id}: {e}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
