#!/usr/bin/env python3
"""
find_lost_chapters.py — найти потерянные главы в Google Drive выгрузках (UC-100).

Pavel 2026-05-22: «ночью найти потерянные главы в скаченных с Google Drive».

Сканит fresh-downloads/ — 3415 файлов в 7 пакетах. Для каждого .docx:
1. Извлекает заголовок (первые строки)
2. Пытается сопоставить с книгой/главой по совпадению ключевых слов
3. Помечает как «потерянное» если нет соответствующей папки в sources/

Выдаёт reports/LOST-CHAPTERS-<date>.md с группировкой по предполагаемой книге.

Запуск: python3 scripts/find_lost_chapters.py
Launchd: ai.codex2.archive-explorer уже стоит на 02:30, добавим этот скрипт после.
"""
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
FRESH = V2 / "fresh-downloads"
SOURCES = V2 / "sources"
TOC = V2 / "toc.json"
REPORTS = V2 / "reports"

BOOK_KEYWORDS = {
    "book-01": ["основы", "что такое микомистицизм", "великий дух", "посвящение"],
    "book-02": ["законы", "возмездие", "карма", "грехи", "заповеди"],
    "book-03": ["невидимые", "духи", "одержимость", "паразиты", "сущности", "родинки", "хридайя", "кровь", "шаманская болезнь"],
    "book-04": ["болезни духа", "исцеление", "недуги", "болеть"],
    "book-05": ["экзорцизм", "изгнание", "очищение", "грибной экзорцизм"],
    "book-06": ["церемония", "ритуал", "приём грибов", "сан педро"],
    "book-07": ["целитель", "проводник", "путь", "ученичество"],
    "book-08": ["мистицизм", "духовность", "мистика", "трансцендентное"],
    "book-09": ["практическое", "применение", "трансформация", "общество"],
    "book-10": ["выращивание", "алхимия", "псилоцибин", "мицелий", "субстрат"],
    "book-11": ["предупреждения", "защита", "опасности", "табу"],
    "book-12": ["организационная", "структура", "управление", "иерархия", "хилингод"],
    "prologue": ["пролог", "призвание"],
    "epilogue": ["эпилог", "завершение", "новое начало"],
    "ustav": ["устав", "принципы микомистицизма"],
}


def docx_to_text(path: Path, limit: int = 5000) -> str:
    try:
        with zipfile.ZipFile(path, "r") as z:
            with z.open("word/document.xml") as f:
                xml = f.read().decode("utf-8", errors="replace")
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.DOTALL)
        out = "\n".join(texts)
        out = out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        out = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), out)
        return out[:limit]
    except Exception:
        return ""


def guess_book(text: str, filename: str) -> str:
    combined = (text[:2000] + " " + filename).lower()
    scores = {}
    for book_id, keywords in BOOK_KEYWORDS.items():
        score = sum(combined.count(kw.lower()) for kw in keywords)
        if score > 0:
            scores[book_id] = score
    if not scores:
        return "unsorted"
    return max(scores, key=scores.get)


def find_chapter_in_sources(book_id: str, filename: str) -> bool:
    """Проверка: совпадает ли название файла с какой-то главой в sources/<book_id>/?"""
    book_dir = SOURCES / book_id
    if not book_dir.exists():
        return False
    name_lower = filename.lower()
    # Простая проверка: если имя файла встречается среди файлов в sources/<book>/*/
    for ch_dir in book_dir.iterdir():
        if not ch_dir.is_dir():
            continue
        for f in ch_dir.iterdir():
            if f.is_file() and f.stem.lower() in name_lower:
                return True
            if f.is_file() and name_lower in f.stem.lower():
                return True
    return False


def main() -> int:
    if not FRESH.exists():
        print(f"fresh-downloads/ не найден: {FRESH}")
        return 1
    REPORTS.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")

    by_book = defaultdict(list)
    archive_stats = {}
    total_docx = 0
    matched = 0
    lost = 0

    for archive_dir in sorted(FRESH.iterdir()):
        if not archive_dir.is_dir() or archive_dir.name.startswith("."):
            continue
        archive_stats[archive_dir.name] = {"docx": 0, "matched": 0, "lost": 0}
        for docx in archive_dir.rglob("*.docx"):
            total_docx += 1
            archive_stats[archive_dir.name]["docx"] += 1
            text = docx_to_text(docx, limit=3000)
            book_guess = guess_book(text, docx.name)
            already_in_sources = find_chapter_in_sources(book_guess, docx.name)
            entry = {
                "file": str(docx.relative_to(V2)),
                "filename": docx.name,
                "book_guess": book_guess,
                "in_sources": already_in_sources,
                "preview": text[:200].replace("\n", " ").strip(),
            }
            by_book[book_guess].append(entry)
            if already_in_sources:
                matched += 1
                archive_stats[archive_dir.name]["matched"] += 1
            else:
                lost += 1
                archive_stats[archive_dir.name]["lost"] += 1

    # Отчёт MD
    md_path = REPORTS / f"LOST-CHAPTERS-{date}.md"
    json_path = REPORTS / f"LOST-CHAPTERS-{date}.json"

    lines = [
        f"# Потерянные главы из Google Drive · {date}\n",
        f"_UC-100. Сгенерировано {datetime.now().strftime('%H:%M:%S')}_\n",
        "\n## Сводка\n",
        f"- Всего .docx файлов в fresh-downloads/: **{total_docx}**",
        f"- Уже есть в sources/: **{matched}** ({round(100*matched/max(total_docx, 1), 1)}%)",
        f"- **Потерянные (не извлечены): {lost}** ({round(100*lost/max(total_docx, 1), 1)}%)",
        "\n## По архивам\n",
        "| Архив | всего | matched | lost |",
        "|---|---|---|---|",
    ]
    for arch, st in archive_stats.items():
        lines.append(f"| `{arch}` | {st['docx']} | {st['matched']} | {st['lost']} |")
    lines.append("\n## По предполагаемой книге\n")
    for book_id in sorted(by_book.keys()):
        files = by_book[book_id]
        lost_only = [f for f in files if not f["in_sources"]]
        if not lost_only:
            continue
        lines.append(f"\n### {book_id}: {len(lost_only)} потерянных файлов\n")
        for f in lost_only[:20]:
            lines.append(f"- `{f['filename']}` — {f['preview'][:80]}")
        if len(lost_only) > 20:
            lines.append(f"- … ещё {len(lost_only) - 20}")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(
        json.dumps({"date": date, "total": total_docx, "matched": matched, "lost": lost,
                    "by_book": dict(by_book), "archive_stats": archive_stats},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Готово: {md_path}")
    print(f"  Всего: {total_docx}, matched: {matched}, lost: {lost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
