#!/usr/bin/env python3
"""
archive_explorer.py — ночной анализатор архивов Кодекса (UC-93).

Pavel 2026-05-21: «там намного больше, раз в 5 больше написано мной.
Ты не все файлы извлёк и не разложил по оглавлению. Каждую ночь анализируешь
архивы Google Drive, ищешь какие главы куда идут».

Что делает:
1. Сканит источники: sources/, fresh-downloads/, Codex/sources/
2. Сравнивает с chapters/ (рабочая структура)
3. Парсит оглавления Pavel-а (3 .docx файла) — пока best-effort plain text
4. Находит:
   - главы которые есть в архиве но не извлечены
   - книги где работа ещё не начата
   - новые файлы в fresh-downloads (не сортированы по книгам)
   - пустые главы (есть заголовок но нет текста)
5. Выдаёт отчёт reports/ARCHIVE-ANALYSIS-<date>.md
   + JSON sidecar reports/ARCHIVE-ANALYSIS-<date>.json для UI

Запуск: python3 archive_explorer.py
Launchd: ai.codex2.archive-explorer каждую ночь в 02:30
"""
import json
import subprocess
import sys
import zipfile
import re
from datetime import datetime
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
OLD_CODEX = Path.home() / "Desktop/Codex"
SOURCES = V2 / "sources"
CHAPTERS = V2 / "chapters"
FRESH = V2 / "fresh-downloads"
REPORTS = V2 / "reports"
TOC_PATH = V2 / "toc.json"

TOC_FILES = [
    OLD_CODEX / "sources/я. СБОРКА ПО ТЕМАМ (рабочая)/СОДЕРЖАНИЕ КОДЕКСА/Кодекс. Оглавления/КОДЕКС МИКОМИСТИЦИЗМА Финальное Оглавление 10-25-2025.docx",
    OLD_CODEX / "sources/я. СБОРКА ПО ТЕМАМ (рабочая)/СОДЕРЖАНИЕ КОДЕКСА/Кодекс. Оглавления/БИБЛИЯ ГРИБОВ Финальное Оглавление 10-25-2025.docx",
    OLD_CODEX / "sources/я. СБОРКА ПО ТЕМАМ (рабочая)/СОДЕРЖАНИЕ КОДЕКСА/Кодекс. Оглавления/ФИНАЛЬНЫЙ КОДЕКС МИКОМИСТИЦИЗМА (Неразделенный).docx",
]


def docx_to_text(path: Path) -> str:
    """Без внешних либ, читаем .docx как ZIP и достаём текст из document.xml."""
    if not path.exists():
        return ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            with z.open("word/document.xml") as f:
                xml = f.read().decode("utf-8", errors="replace")
        # Достаём <w:t>...</w:t>
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.DOTALL)
        # XML escapes
        out = "\n".join(texts)
        out = out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        # &#xNNNN;
        out = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), out)
        return out
    except Exception as e:
        return f"[ERROR: {e}]"


def count_files(root: Path, recursive: bool = True) -> dict:
    """Считаем .docx/.md/.txt файлы в папке."""
    if not root.exists():
        return {"docx": 0, "md": 0, "txt": 0, "total": 0}
    iterator = root.rglob("*") if recursive else root.iterdir()
    counts = {"docx": 0, "md": 0, "txt": 0}
    for f in iterator:
        if not f.is_file():
            continue
        suf = f.suffix.lower()
        if suf == ".docx":
            counts["docx"] += 1
        elif suf == ".md":
            counts["md"] += 1
        elif suf == ".txt":
            counts["txt"] += 1
    counts["total"] = sum(counts.values())
    return counts


def chapter_status(ch_dir: Path) -> dict:
    """Статус одной главы: есть ли draft, finalized, iterations."""
    if not ch_dir.exists():
        return {"exists": False}
    draft = ch_dir / "draft.md"
    finalized = ch_dir / "finalized.md"
    meta = ch_dir / "meta.json"
    iterations_dir = ch_dir / "iterations"
    word_count = 0
    if draft.exists():
        try:
            word_count = len(draft.read_text(encoding="utf-8").split())
        except Exception:
            pass
    return {
        "exists": True,
        "has_draft": draft.exists(),
        "draft_words": word_count,
        "has_finalized": finalized.exists(),
        "has_meta": meta.exists(),
        "iterations_count": len(list(iterations_dir.glob("v*.md"))) if iterations_dir.exists() else 0,
    }


def analyze_books() -> list:
    """Сравниваем sources/ и chapters/ — что извлечено, что нет."""
    if not SOURCES.exists():
        return []
    books = []
    for book_dir in sorted(SOURCES.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        book_id = book_dir.name
        src_chapters = []
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith("."):
                continue
            files = count_files(ch_dir, recursive=False)
            src_chapters.append({
                "chapter_id": ch_dir.name,
                "source_files": files,
            })
        # Состояние рабочей папки
        work_book = CHAPTERS / book_id
        work_chapters = {}
        if work_book.exists():
            for ch_dir in work_book.iterdir():
                if not ch_dir.is_dir() or ch_dir.name.startswith("."):
                    continue
                work_chapters[ch_dir.name] = chapter_status(ch_dir)
        # Объединяем
        merged = []
        for sc in src_chapters:
            cid = sc["chapter_id"]
            ws = work_chapters.get(cid)
            merged.append({
                "chapter_id": cid,
                "source_files": sc["source_files"]["total"],
                "in_work": bool(ws and ws.get("exists")),
                "has_draft": bool(ws and ws.get("has_draft")),
                "draft_words": (ws or {}).get("draft_words", 0),
                "is_empty": bool(ws and not ws.get("has_draft")),
            })
        # Главы которые ЕСТЬ в работе но НЕТ в sources (всё-таки бывает)
        for cid, ws in work_chapters.items():
            if not any(m["chapter_id"] == cid for m in merged):
                merged.append({
                    "chapter_id": cid,
                    "source_files": 0,
                    "in_work": True,
                    "has_draft": ws.get("has_draft", False),
                    "draft_words": ws.get("draft_words", 0),
                    "is_empty": not ws.get("has_draft"),
                    "no_source": True,
                })
        total_src = len(src_chapters)
        in_work = sum(1 for m in merged if m["in_work"])
        with_draft = sum(1 for m in merged if m["has_draft"])
        books.append({
            "book_id": book_id,
            "source_chapters": total_src,
            "in_work_chapters": in_work,
            "with_draft_chapters": with_draft,
            "not_extracted_chapters": total_src - in_work,
            "completion_pct": round(100 * with_draft / total_src, 1) if total_src else 0.0,
            "chapters": merged,
        })
    return books


def analyze_fresh_downloads() -> list:
    """Что лежит в fresh-downloads / не разобрано по книгам."""
    if not FRESH.exists():
        return []
    out = []
    for sub in sorted(FRESH.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        counts = count_files(sub)
        out.append({
            "archive": sub.name,
            "files": counts,
        })
    return out


def parse_toc_docx() -> dict:
    """Best-effort парсинг 3 файлов-оглавлений Pavel-а."""
    result = {}
    for toc_path in TOC_FILES:
        if not toc_path.exists():
            result[toc_path.name] = {"error": "not found"}
            continue
        text = docx_to_text(toc_path)
        # Считаем «Глава X» упоминания
        chapters = re.findall(r"Глава\s+\d+", text)
        books = re.findall(r"КНИГА\s+[IVX]+", text)
        result[toc_path.name] = {
            "size": len(text),
            "chapter_mentions": len(chapters),
            "book_mentions": len(books),
            "preview": text[:500],
        }
    return result


def find_active_books(books: list) -> list:
    """«Активная» книга = в работе >= 1 главы с draft + ещё есть не извлечённые."""
    active = []
    for b in books:
        if b["with_draft_chapters"] >= 1 and b["not_extracted_chapters"] >= 1:
            active.append({
                "book_id": b["book_id"],
                "with_draft": b["with_draft_chapters"],
                "total_in_sources": b["source_chapters"],
                "not_extracted": b["not_extracted_chapters"],
                "completion_pct": b["completion_pct"],
            })
    active.sort(key=lambda x: -x["completion_pct"])
    return active


def recommend_next_chapters(books: list, limit: int = 5) -> list:
    """Рекомендуем следующие главы для извлечения / надиктовки.
    Приоритет: активная книга → не извлечённая глава с большим source_files.
    Также: пустые папки (есть meta но нет draft) — высокий приоритет."""
    recs = []
    for b in books:
        if b["with_draft_chapters"] == 0:
            continue  # книга ещё не начата → не активна
        for ch in b["chapters"]:
            if ch["has_draft"]:
                continue
            recs.append({
                "book_id": b["book_id"],
                "chapter_id": ch["chapter_id"],
                "source_files": ch["source_files"],
                "in_work": ch["in_work"],
                "is_empty": ch["is_empty"],
                "priority": (1000 if ch["is_empty"] else 0) + ch["source_files"] * 10 + b["completion_pct"],
            })
    recs.sort(key=lambda r: -r["priority"])
    return recs[:limit]


def write_report(books: list, fresh: list, toc_info: dict, active: list, recs: list) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    md_path = REPORTS / f"ARCHIVE-ANALYSIS-{date}.md"
    json_path = REPORTS / f"ARCHIVE-ANALYSIS-{date}.json"

    lines = []
    lines.append(f"# Анализ архива Кодекса · {date}\n")
    lines.append(f"_Сгенерировано {datetime.now().strftime('%H:%M:%S')} автоматически (UC-93)_\n")
    lines.append("\n## Сводка\n")
    total_src = sum(b["source_chapters"] for b in books)
    total_work = sum(b["in_work_chapters"] for b in books)
    total_draft = sum(b["with_draft_chapters"] for b in books)
    not_extracted = total_src - total_work
    lines.append(f"- Всего глав в `sources/`: **{total_src}**")
    lines.append(f"- В работе (есть папка в `chapters/`): **{total_work}**")
    lines.append(f"- С драфтом (написаны): **{total_draft}**")
    lines.append(f"- **Не извлечено в работу: {not_extracted}**")
    fd_total = sum(f["files"]["total"] for f in fresh)
    lines.append(f"- Файлов в `fresh-downloads/` (не разобрано): **{fd_total}**\n")

    lines.append("\n## Книги: статус извлечения\n")
    lines.append("| Книга | в sources | в работе | с драфтом | не извлечено | прогресс |")
    lines.append("|---|---|---|---|---|---|")
    for b in books:
        lines.append(
            f"| `{b['book_id']}` | {b['source_chapters']} | {b['in_work_chapters']} | "
            f"{b['with_draft_chapters']} | {b['not_extracted_chapters']} | "
            f"{b['completion_pct']}% |"
        )

    lines.append("\n## Активные книги (есть драфты + есть что доделать)\n")
    if active:
        for a in active:
            lines.append(
                f"- **`{a['book_id']}`** — {a['with_draft']}/{a['total_in_sources']} глав готово, "
                f"{a['not_extracted']} не извлечено ({a['completion_pct']}%)"
            )
    else:
        lines.append("_Нет активных книг (ни одна не начата с драфтами)._\n")

    lines.append("\n## Рекомендации на следующие главы\n")
    if recs:
        for i, r in enumerate(recs, 1):
            note = "пустая папка" if r["is_empty"] else f"{r['source_files']} файлов в архиве"
            lines.append(
                f"{i}. **`{r['chapter_id']}`** ({r['book_id']}) — {note}"
            )
    else:
        lines.append("_Все главы активных книг готовы. Можно браться за новую книгу._\n")

    lines.append("\n## Архивы Google Drive (не разобрано)\n")
    if fresh:
        for f in fresh:
            lines.append(f"- `{f['archive']}` — {f['files']['total']} файлов (docx: {f['files']['docx']}, md: {f['files']['md']})")
    else:
        lines.append("_Папка `fresh-downloads/` пуста._\n")

    lines.append("\n## Оглавления Pavel-а\n")
    for name, info in toc_info.items():
        if "error" in info:
            lines.append(f"- `{name}` — **{info['error']}**")
        else:
            lines.append(
                f"- `{name}` — {info['size']} chars, упоминаний «Глава N»: {info['chapter_mentions']}, "
                f"«КНИГА»: {info['book_mentions']}"
            )

    lines.append("\n## Что делать дальше\n")
    if not_extracted > 0:
        lines.append(
            f"1. **Извлечь {not_extracted} глав из `sources/` в `chapters/`** — создать папки + meta.json. "
            f"См. `scripts/populate_empty_chapters.py` (UC-94)."
        )
    if fd_total > 0:
        lines.append(
            f"2. **Разобрать {fd_total} файлов из `fresh-downloads/`** — сравнить с оглавлением, "
            f"переместить в соответствующие книги."
        )
    if recs:
        first = recs[0]
        lines.append(
            f"3. **Сегодня начать**: глава `{first['chapter_id']}` (книга `{first['book_id']}`) "
            f"— открой /journalist и расскажи Журналисту."
        )

    md_path.write_text("\n".join(lines), encoding="utf-8")

    # JSON sidecar
    json_path.write_text(json.dumps({
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_source_chapters": total_src,
            "total_in_work": total_work,
            "total_with_draft": total_draft,
            "not_extracted": not_extracted,
            "fresh_files": fd_total,
        },
        "books": books,
        "fresh_downloads": fresh,
        "toc_files": toc_info,
        "active_books": active,
        "recommendations": recs,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    return md_path


def main():
    print("→ Сканю sources/, chapters/, fresh-downloads/…")
    books = analyze_books()
    fresh = analyze_fresh_downloads()
    print("→ Парсю оглавления Pavel-а…")
    toc_info = parse_toc_docx()
    print("→ Считаю активные книги и рекомендации…")
    active = find_active_books(books)
    recs = recommend_next_chapters(books)
    print("→ Записываю отчёт…")
    md_path = write_report(books, fresh, toc_info, active, recs)
    print(f"✓ Готово: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
