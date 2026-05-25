#!/usr/bin/env python3
"""
daily_recommendations.py — каждое утро: «над какими главами поработать сегодня».

Pavel 2026-05-20: «выбирай книги где максимально уже написано глав и работать сначала
с теми которые легко закончить — чтобы я вошёл в кураж и привык к победам».

Plus: «каждое утро мне нужны рекомендации пронумерованные по улучшению функционала».

Что делает:
1) Для каждой книги канона считает «easy-win score»:
   - % параграфов с approve marks
   - наличие fidelity report (готовность к работе)
   - воспоминания из voice-corpus (есть ли голос на тему)
2) Сортирует «легко завершить → сложно». Quick wins наверх.
3) Через Opus 4.7 + thinking генерит:
   - Главы на сегодня (с обоснованием «почему именно эти», зависимости)
   - Numbered functionality improvements (continuation of DAILY-IMPROVEMENTS)
4) Сохраняет в reports/DAILY-RECOMMENDATIONS-{date}.md + symlink DAILY-RECOMMENDATIONS-TODAY.md

Запуск:
    python3 daily_recommendations.py
"""

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
TOC = V2 / "toc.json"
REPORTS = V2 / "reports"
EVENTS = V2 / ".codex/events.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def calculate_book_progress() -> list:
    """Для каждой книги — что есть, что готово, easy-win score."""
    if not TOC.exists():
        return []
    toc = json.loads(TOC.read_text(encoding="utf-8"))

    fidelity_dir = REPORTS / "fidelity"
    fid_files = {f.stem for f in fidelity_dir.glob("*.md")} if fidelity_dir.exists() else set()

    voice_dir = V2 / "voice-corpus/raw"
    voice_count_per_book = defaultdict(int)
    if voice_dir.exists():
        for f in voice_dir.glob("*.md"):
            # match by slug keywords (rough)
            slug = f.stem.lower()
            for book in toc["books"]:
                title_low = book["title_clean"].lower()
                for kw in [w for w in re.split(r"[^\wа-яё]+", title_low) if len(w) >= 5]:
                    if kw in slug:
                        voice_count_per_book[book["id"]] += 1
                        break

    books = []
    for book in toc["books"]:
        if book.get("status") == "reference":
            continue
        chapters = [c for c in book.get("chapters", []) if c.get("number", 0) > 0]
        if not chapters:
            continue

        # Подсчёт draft + approved
        total_chapters = len(chapters)
        chapters_with_material = sum(1 for c in chapters if c["stats"]["grant_count"] + c["stats"]["voice_count"] > 0)
        chapters_with_fidelity = sum(1 for c in chapters if c["id"] in fid_files)

        # Drafts existing
        chapters_with_draft = 0
        chapters_with_approvals = 0
        total_approved_paragraphs = 0
        for c in chapters:
            draft_p = V2 / "chapters" / book["id"] / c["id"] / "draft.md"
            approv_p = V2 / "chapters" / book["id"] / c["id"] / "approvals.json"
            if draft_p.exists():
                chapters_with_draft += 1
            if approv_p.exists():
                data = json.loads(approv_p.read_text(encoding="utf-8"))
                approved = len(data.get("approved_indices", []))
                if approved > 0:
                    chapters_with_approvals += 1
                    total_approved_paragraphs += approved

        # Easy-win score: чем выше — тем легче закончить книгу
        # Факторы: материала много, fidelity готов, voice есть, мало пустых глав
        empty_chapters = total_chapters - chapters_with_material
        material_score = chapters_with_material / max(1, total_chapters) * 100
        fidelity_score = chapters_with_fidelity / max(1, total_chapters) * 100
        voice_score = min(50, voice_count_per_book.get(book["id"], 0) * 5)
        emptiness_penalty = empty_chapters * 8
        ready_to_finish = chapters_with_material >= total_chapters * 0.7  # >= 70% chapters have material

        easy_win = round(material_score * 0.4 + fidelity_score * 0.3 + voice_score * 0.3 - emptiness_penalty, 1)

        books.append({
            "id": book["id"],
            "title": book["title_clean"],
            "total_chapters": total_chapters,
            "chapters_with_material": chapters_with_material,
            "chapters_with_fidelity": chapters_with_fidelity,
            "chapters_with_draft": chapters_with_draft,
            "chapters_with_approvals": chapters_with_approvals,
            "total_approved_paragraphs": total_approved_paragraphs,
            "empty_chapters": empty_chapters,
            "voice_files": voice_count_per_book.get(book["id"], 0),
            "easy_win_score": easy_win,
            "ready_to_finish": ready_to_finish,
            "material_pct": round(material_score, 1),
            "fidelity_pct": round(fidelity_score, 1),
        })
    # Сортируем по easy-win descending
    books.sort(key=lambda b: -b["easy_win_score"])
    return books


def read_if_exists(p: Path, max_chars: int = 8000) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")[:max_chars]


def main():
    books_progress = calculate_book_progress()

    morning_plan = read_if_exists(REPORTS / "MORNING-PLAN.md", 10000)
    daily_imp = read_if_exists(REPORTS / "DAILY-IMPROVEMENTS.md", 5000)
    pavel_actions = ""
    edits_file = V2 / ".codex/pavel-edits.jsonl"
    if edits_file.exists():
        lines = edits_file.read_text(encoding="utf-8").splitlines()[-50:]
        pavel_actions = "\n".join(lines)

    top5_books = books_progress[:5]
    books_table = "\n".join(
        f"| {b['title']} | {b['easy_win_score']:.0f} | {b['chapters_with_material']}/{b['total_chapters']} | {b['chapters_with_fidelity']} | {b['voice_files']} | {b['total_approved_paragraphs']} |"
        for b in books_progress[:10]
    )

    system = (
        "Ты — стратегический советник Pavel-а Дмитриева (Хилингода). Каждое утро "
        "выдаёшь короткий план: какие 2-4 главы взять сегодня, чтобы войти в кураж. "
        "Pavel ценит «легко закончить → быстрая победа». Приоритет — главы где материала много, "
        "fidelity-отчёт готов, есть voice-extracts. Избегай пустых глав в начале дня. "
        "Объясняй ЛОГИКУ: почему именно эти главы, что они дают, какие зависимости с другими. "
        "Pavel читает русский. Отвечай только Markdown."
    )

    user = f"""# Состояние книг (easy-win sort, top-10)

| Книга | Easy-Win | Материал | Fidelity | Voice | Approved |
|---|---|---|---|---|---|
{books_table}

# Контекст: вчерашний morning plan

{morning_plan}

# Вчерашние улучшения процессов

{daily_imp}

# Последние действия Pavel-а (50 событий)

{pavel_actions}

---

# Что вернуть

Markdown по схеме:

## 🎯 СЕГОДНЯ — ГЛАВЫ ДЛЯ РАБОТЫ ({today_str()})

### Quick win #1 (легче всего, начать с этой)
- **Книга / Глава:** [конкретно]
- **Почему именно она:** одна-две фразы — что в ней уже есть, почему быстро завершится
- **Связано с:** какие другие главы потом легче пойдут после этой
- **Что сегодня делать:** одна конкретная задача (30-60 мин)

### Quick win #2
[аналогично]

### Quick win #3
[аналогично]

### (опц) Челлендж #4 — на случай если уже в кураже
[если Pavel разогрелся]

## 💡 РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ ФУНКЦИОНАЛА (numbered)

Конкретные предложения как ОБЛЕГЧИТЬ работу Pavel-а сегодня. По одной строке каждое.

1. **[короткое название]** — что внедрить + почему упростит
2. ...
3. ...
4. ...
5. ...

## 🔗 Логика дня

Одна-две фразы — общая идея почему такой порядок глав сегодня важен.

## ❓ Открытые вопросы

Что Pavel должен решить (если есть). Иначе раздел опустить.
"""

    print(f"→ Opus 4.7 + thinking 6K для DAILY-RECOMMENDATIONS на {today_str()}…")
    resp = ask_opus(user=user, system=system, max_tokens=6000, thinking=6000)

    today = today_str()
    path = REPORTS / f"DAILY-RECOMMENDATIONS-{today}.md"
    today_link = REPORTS / "DAILY-RECOMMENDATIONS-TODAY.md"

    header = (
        f"<!-- generated: {now_iso()} model: {resp.get('model')} tokens: in {resp['usage'].get('input_tokens')} out {resp['usage'].get('output_tokens')} -->\n\n"
    )
    path.write_text(header + resp["text"], encoding="utf-8")

    if today_link.exists() or today_link.is_symlink():
        today_link.unlink()
    today_link.symlink_to(path.name)
    print(f"✓ {path}")

    event = {
        "ts": now_iso(),
        "type": "daily_recommendations_generated",
        "target": str(path.relative_to(V2)),
        "payload": {
            "model": resp.get("model"),
            "tokens_in": resp["usage"].get("input_tokens"),
            "tokens_out": resp["usage"].get("output_tokens"),
            "top_easy_win_book": top5_books[0]["title"] if top5_books else None,
        },
    }
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
