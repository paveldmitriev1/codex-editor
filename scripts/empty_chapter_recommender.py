#!/usr/bin/env python3
"""
empty_chapter_recommender.py — утренний выбор пустой главы из активной книги (UC-95).

Pavel 2026-05-21: «каждое утро если будет пустая глава которая идёт в книгу
которую мы уже заканчиваем, ты будешь рекомендовать её как новую главу,
я буду наговаривать, потом опросит совет старейшин и Журналист».

Алгоритм:
1. Считает completion_pct по каждой книге (chapters с draft / всего папок).
2. Активные книги = completion_pct >= 30% и не 100%.
3. Из активных выбирает книгу с самым высоким completion.
4. Из её глав выбирает первую пустую (нет draft.md) по возрастанию number.
5. Пишет рекомендацию в reports/EMPTY-CHAPTER-RECOMMENDATION.md +
   JSON sidecar reports/EMPTY-CHAPTER-RECOMMENDATION.json (для UI).
6. Если ничего активного нет — пишет «все книги завершены или ни одна не активна».

Запуск: python3 empty_chapter_recommender.py
Launchd: ai.codex2.empty-chapter каждое утро 06:30
"""
import json
import sys
from datetime import datetime
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
CHAPTERS = V2 / "chapters"
REPORTS = V2 / "reports"
TOC_PATH = V2 / "toc.json"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_meta(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def analyze_book(book_dir: Path) -> dict:
    """Считаем главы и их статус в одной книге."""
    chapters = []
    for ch_dir in sorted(book_dir.iterdir()):
        if not ch_dir.is_dir() or ch_dir.name.startswith("."):
            continue
        draft = ch_dir / "draft.md"
        meta_path = ch_dir / "meta.json"
        meta = load_meta(meta_path) if meta_path.exists() else {}
        words = 0
        if draft.exists():
            try:
                words = len(draft.read_text(encoding="utf-8").split())
            except Exception:
                pass
        chapters.append({
            "chapter_id": ch_dir.name,
            "number": meta.get("number", 0),
            "title": meta.get("title") or ch_dir.name,
            "has_draft": draft.exists(),
            "draft_words": words,
            "status": meta.get("status", "unknown"),
        })
    total = len(chapters)
    with_draft = sum(1 for c in chapters if c["has_draft"])
    return {
        "book_id": book_dir.name,
        "total": total,
        "with_draft": with_draft,
        "completion_pct": round(100 * with_draft / total, 1) if total else 0.0,
        "chapters": sorted(chapters, key=lambda c: c["number"]),
    }


def pick_recommendation(books: list) -> dict:
    """Активная книга = 30..99% completion. Берём с самым высоким completion."""
    candidates = [b for b in books if 30.0 <= b["completion_pct"] < 100.0]
    candidates.sort(key=lambda b: -b["completion_pct"])
    if not candidates:
        # Fallback: книга со ВЗЯТЫМИ драфтами (> 0), но < 30%
        candidates = [b for b in books if 0 < b["with_draft"] < b["total"]]
        candidates.sort(key=lambda b: -b["completion_pct"])
    if not candidates:
        return {"ok": False, "reason": "Нет активных книг (где есть драфты + есть пустые)."}
    book = candidates[0]
    empty = [c for c in book["chapters"] if not c["has_draft"]]
    if not empty:
        return {"ok": False, "reason": f"Книга {book['book_id']} помечена активной, но пустых глав нет."}
    pick = empty[0]
    return {
        "ok": True,
        "book": {"book_id": book["book_id"], "completion_pct": book["completion_pct"],
                 "total": book["total"], "with_draft": book["with_draft"]},
        "chapter": pick,
        "alternatives": empty[1:5],
    }


def write_report(books: list, rec: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS / "EMPTY-CHAPTER-RECOMMENDATION.md"
    json_path = REPORTS / "EMPTY-CHAPTER-RECOMMENDATION.json"

    lines = []
    date = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"# Рекомендация на сегодня · {date}\n")
    lines.append(f"_UC-95: утренний выбор пустой главы. Сгенерировано {datetime.now().strftime('%H:%M:%S')}_\n")

    if not rec.get("ok"):
        lines.append(f"\n## Нет рекомендации\n\n{rec.get('reason', '')}\n")
    else:
        ch = rec["chapter"]
        bk = rec["book"]
        lines.append(f"\n## Сегодня начни эту главу\n")
        lines.append(f"### {ch['title']}\n")
        lines.append(f"- Книга: `{bk['book_id']}` ({bk['with_draft']}/{bk['total']} глав готово, {bk['completion_pct']}%)")
        lines.append(f"- Chapter ID: `{ch['chapter_id']}`")
        lines.append(f"- Номер главы: {ch['number']}")
        lines.append("")
        lines.append(f"**[Открыть Журналиста с этой темой →](/journalist?topic={ch['title']})**")
        lines.append("")
        lines.append("Шаги на сегодня:")
        lines.append(f"1. Открой /journalist, расскажи Журналисту о теме «{ch['title']}»")
        lines.append("2. Журналист задаст 5-15 вопросов, ответь голосом или текстом")
        lines.append("3. После закрытия темы — пройди через Критиков-Q&A (UC-91, в работе)")
        lines.append(f"4. Когда готово — Opus 4.7 напишет первый драфт в `chapters/{bk['book_id']}/{ch['chapter_id']}/draft.md`")

        if rec.get("alternatives"):
            lines.append("\n## Если эта не идёт — альтернативы из той же книги\n")
            for alt in rec["alternatives"]:
                lines.append(f"- **Глава {alt['number']}.** {alt['title']} (`{alt['chapter_id']}`)")

    lines.append("\n## Все книги (статус)\n")
    lines.append("| Книга | готово | всего | % |")
    lines.append("|---|---|---|---|")
    for b in sorted(books, key=lambda x: -x["completion_pct"]):
        lines.append(f"| `{b['book_id']}` | {b['with_draft']} | {b['total']} | {b['completion_pct']}% |")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path.write_text(json.dumps({
        "generated_at": now_iso(),
        "recommendation": rec,
        "books": books,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    return md_path


def main() -> int:
    if not CHAPTERS.exists():
        print(f"chapters/ не найден: {CHAPTERS}", file=sys.stderr)
        return 1
    books = []
    for book_dir in sorted(CHAPTERS.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        books.append(analyze_book(book_dir))
    rec = pick_recommendation(books)
    md_path = write_report(books, rec)
    print(f"Готово: {md_path}")
    if rec.get("ok"):
        ch = rec["chapter"]
        bk = rec["book"]
        print(f"  Рекомендация: «{ch['title']}» (книга {bk['book_id']}, {bk['completion_pct']}%)")
    else:
        print(f"  {rec.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
