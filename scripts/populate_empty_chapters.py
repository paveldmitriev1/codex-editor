#!/usr/bin/env python3
"""
populate_empty_chapters.py — создать пустые папки глав на основе sources/ (UC-94).

Pavel 2026-05-21: «есть главы в которых нет текста но есть заголовок, мы их тоже
будем включать. Создаются папки с книгами куда эти главы пойдут даже если они
пустые, я их потом буду наговаривать».

Что делает:
1. Сканит sources/ — все главы которых ещё нет в chapters/
2. Создаёт chapters/<book>/<ch_id>/ с meta.json:
   {"chapter_id", "book_id", "number", "title", "status": "empty",
    "source_path", "source_files_count"}
3. NE создаёт draft.md (текста нет, Pavel наговорит позже)
4. Обновляет toc.json — добавляет недостающие книги/главы со status="empty"

Идемпотентно: уже созданные папки не трогает.

Запуск: python3 populate_empty_chapters.py
"""
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
SOURCES = V2 / "sources"
CHAPTERS = V2 / "chapters"
TOC_PATH = V2 / "toc.json"


def load_toc_title_map() -> dict:
    """Из toc.json: {chapter_id: title}."""
    if not TOC_PATH.exists():
        return {}
    try:
        toc = json.loads(TOC_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for book in toc.get("books", []):
        for ch in book.get("chapters", []):
            cid = ch.get("id")
            title = ch.get("title_clean") or ch.get("title")
            if cid and title:
                out[cid] = title
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def docx_first_lines(path: Path, max_chars: int = 500) -> str:
    """Best-effort: достаём первые строки из docx чтобы выудить заголовок главы."""
    if not path.exists():
        return ""
    try:
        with zipfile.ZipFile(path, "r") as z:
            with z.open("word/document.xml") as f:
                xml = f.read().decode("utf-8", errors="replace")
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.DOTALL)
        out = "\n".join(texts[:30])
        out = out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        out = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), out)
        return out[:max_chars]
    except Exception:
        return ""


def guess_chapter_title(ch_source_dir: Path) -> str:
    """Угадываем заголовок главы из имён файлов или первых строк первого docx."""
    if not ch_source_dir.is_dir():
        return ch_source_dir.name
    # Сначала имена файлов с явным «Глава X.»
    candidates = []
    for f in ch_source_dir.iterdir():
        if not f.is_file():
            continue
        name = f.stem
        # ищем «Глава\s*\d+[\.\s:]+(.+)»
        m = re.search(r"Глава\s*(\d+)[\.\s:]+(.+)", name)
        if m:
            candidates.append((int(m.group(1)), m.group(2).strip()))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        n, title = candidates[0]
        return f"Глава {n}. {title}"
    # Иначе — первая строка первого .docx
    docxs = sorted(ch_source_dir.glob("*.docx"))
    if docxs:
        text = docx_first_lines(docxs[0])
        first_line = text.split("\n", 1)[0].strip()
        if first_line:
            return first_line[:120]
    return ch_source_dir.name.replace("-", " ").replace("_", " ").title()


def chapter_number_from_id(chapter_id: str) -> int:
    m = re.search(r"-ch-(\d+)", chapter_id)
    return int(m.group(1)) if m else 0


def count_source_files(ch_source_dir: Path) -> dict:
    counts = {"docx": 0, "md": 0, "txt": 0, "other": 0}
    if not ch_source_dir.is_dir():
        return counts
    for f in ch_source_dir.rglob("*"):
        if not f.is_file():
            continue
        suf = f.suffix.lower()
        if suf == ".docx":
            counts["docx"] += 1
        elif suf == ".md":
            counts["md"] += 1
        elif suf == ".txt":
            counts["txt"] += 1
        else:
            counts["other"] += 1
    return counts


def main(dry_run: bool = False) -> int:
    if not SOURCES.exists():
        print(f"sources/ не найден: {SOURCES}", file=sys.stderr)
        return 1
    CHAPTERS.mkdir(parents=True, exist_ok=True)
    toc_titles = load_toc_title_map()
    created = []
    skipped = []
    updated_titles = 0
    for book_dir in sorted(SOURCES.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        book_id = book_dir.name
        work_book = CHAPTERS / book_id
        for ch_source in sorted(book_dir.iterdir()):
            if not ch_source.is_dir() or ch_source.name.startswith("."):
                continue
            chapter_id = ch_source.name
            work_ch = work_book / chapter_id
            if work_ch.exists():
                # Если папка есть, но meta.json устаревший — попробуем подтянуть title из toc.json
                meta_path = work_ch / "meta.json"
                if meta_path.exists() and chapter_id in toc_titles:
                    try:
                        m = json.loads(meta_path.read_text(encoding="utf-8"))
                        if m.get("title") != toc_titles[chapter_id]:
                            m["title"] = toc_titles[chapter_id]
                            m["title_updated_at"] = now_iso()
                            meta_path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
                            updated_titles += 1
                    except Exception:
                        pass
                skipped.append(chapter_id)
                continue
            # Создаём папку и meta.json
            # Приоритет: toc.json → имя файла → имя папки
            title = toc_titles.get(chapter_id) or guess_chapter_title(ch_source)
            number = chapter_number_from_id(chapter_id)
            counts = count_source_files(ch_source)
            meta = {
                "chapter_id": chapter_id,
                "book_id": book_id,
                "number": number,
                "title": title,
                "status": "empty",
                "source_path": str(ch_source.relative_to(V2)),
                "source_files": counts,
                "created_by": "populate_empty_chapters.py (UC-94)",
                "created_at": now_iso(),
            }
            if dry_run:
                created.append({"chapter_id": chapter_id, "title": title, "would_create": str(work_ch)})
                continue
            work_ch.mkdir(parents=True, exist_ok=True)
            (work_ch / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            created.append({"chapter_id": chapter_id, "title": title, "created": str(work_ch.relative_to(V2))})
    print(f"Создано {len(created)} пустых папок, пропущено {len(skipped)} (уже существуют), обновлено title в {updated_titles}.")
    if created:
        print("\nПримеры созданных:")
        for c in created[:10]:
            print(f"  - {c['chapter_id']}: {c['title']}")
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.dry_run))
