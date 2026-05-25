#!/usr/bin/env python3
"""
pack_chapters.py — упаковщик глав Кодекса v2.

Берёт исходные материалы из Google Drive выгрузки (Grant-организация) и из
voice-extracts, копирует по структуре Codex2/sources/<book>/<chapter>/, пишет
toc.json и событие в events.jsonl.

НЕ использует:
- ~/Desktop/Codex/drafts/  (AI-батчи последних 4 дней — overnight/polish/opus-*)
- MASTER_BOOK_v1.md        (скомпилировано из этих батчей)

Использует:
- ~/Desktop/Codex/sources/01. КОДЕКСА ПО СОДЕРЖАНИЮ.../  (Grant Google Drive)
- ~/Desktop/Codex/sources/voice-extracts/                (надиктовки Pavel)

Запуск:
    python3 ~/Desktop/Codex2/scripts/pack_chapters.py
    python3 ~/Desktop/Codex2/scripts/pack_chapters.py --dry-run
    python3 ~/Desktop/Codex2/scripts/pack_chapters.py --clean   # очистить v2/sources перед паком
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# ─── Пути ─────────────────────────────────────────────
HOME = Path.home()
V1_SOURCES = HOME / "Desktop/Codex/sources"
GRANT_ROOT = V1_SOURCES / "01. КОДЕКСА ПО СОДЕРЖАНИЮ (СБОРКА ПО ТЕМЕ. ВСЕ МАТЕРИАЛЫ)"
VOICE_DIR  = V1_SOURCES / "voice-extracts"

V2_ROOT     = HOME / "Desktop/Codex2"
V2_SOURCES  = V2_ROOT / "sources"
V2_CHAPTERS = V2_ROOT / "chapters"            # canon.json лежит здесь: chapters/<book>/canon.json
V2_TOC      = V2_ROOT / "toc.json"
V2_EVENTS   = V2_ROOT / ".codex" / "events.jsonl"

# ─── Канонический порядок 16 разделов ─────────────────
# status:
#   "active"    — рабочие главы (редактируем/пишем)
#   "reference" — справочный материал (готово, не редактируется; используется как стилевой эталон)
SECTION_ORDER = [
    # (slug,        sort_key, title_grant_prefix,           kind,    status)
    ("ustav",       "a0",  "00 УСТАВ И ПРИНЦИПЫ",           "front", "reference"),  # Pavel 2026-05-19: уже написан, стилевой эталон, в работу не берём
    ("prologue",    "a1",  "0. ПРОЛОГ",                     "front", "active"),
    ("book-01",     "b01", "1. КНИГА I.",                   "book",  "active"),
    ("book-02",     "b02", "2. КНИГА II.",                  "book",  "active"),
    ("book-03",     "b03", "3. КНИГА III.",                 "book",  "active"),
    ("book-04",     "b04", "4. КНИГА IV.",                  "book",  "active"),
    ("book-05",     "b05", "5. КНИГА V.",                   "book",  "active"),
    ("book-06",     "b06", "6. КНИГА VI.",                  "book",  "active"),
    ("book-07",     "b07", "7. КНИГА VII.",                 "book",  "active"),
    ("book-08",     "b08", "8. КНИГА VIII.",                "book",  "active"),
    ("book-09",     "b09", "9. КНИГА IX.",                  "book",  "active"),
    ("book-10",     "b10", "10. КНИГА X.",                  "book",  "active"),
    ("book-11",     "b11", "11. КНИГА XI.",                 "book",  "active"),
    ("book-12",     "b12", "12. КНИГА XII.",                "book",  "active"),
    ("epilogue",    "z1",  "13. ЭПИЛОГ",                    "back",  "active"),
    ("appendices",  "z2",  "14. ПРИЛОЖЕНИЯ",                "back",  "active"),
]


# ─── Утилиты ──────────────────────────────────────────
def slugify(text: str, max_len: int = 60) -> str:
    """Простой латино-кириллический slug. Безопасный для файловой системы."""
    t = text.lower().strip()
    # Транслит самые частые кириллические буквы
    table = str.maketrans({
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh",
        "з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o",
        "п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts",
        "ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu",
        "я":"ya",
    })
    t = t.translate(table)
    t = re.sub(r"[^a-z0-9]+", "-", t)
    t = re.sub(r"-+", "-", t).strip("-")
    return t[:max_len] or "unnamed"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_grant_dir(prefix: str) -> Optional[Path]:
    """Найти Grant-папку по префиксу названия книги."""
    if not GRANT_ROOT.exists():
        return None
    for p in GRANT_ROOT.iterdir():
        if p.is_dir() and p.name.startswith(prefix):
            return p
    return None


def is_source_file(p: Path) -> bool:
    """Файл — материал для копирования (не системный, не пустой)."""
    if not p.is_file():
        return False
    if p.name.startswith(".") or p.name in ("Icon\r",):
        return False
    if p.suffix.lower() not in (".docx", ".doc", ".md", ".txt", ".rtf", ".pdf"):
        return False
    if p.stat().st_size == 0:
        return False
    return True


def extract_chapter_number(folder_name: str) -> Tuple[int, str]:
    """Из 'Глава 1_ Введение в Микомистицизм' → (1, 'Введение в Микомистицизм')."""
    m = re.match(r"Глава\s+(\d+)[_\.\s]+(.+)", folder_name)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return 999, folder_name


# ─── Сборка главы ─────────────────────────────────────
def build_chapter(book_slug: str, chapter_num: int, chapter_title: str,
                  source_files: List[Path], voice_files: List[Path],
                  dry_run: bool) -> dict:
    chapter_id  = f"{book_slug}-ch-{chapter_num:02d}"
    chapter_dir = V2_SOURCES / book_slug / chapter_id

    if not dry_run:
        (chapter_dir / "from-grant").mkdir(parents=True, exist_ok=True)
        if voice_files:
            (chapter_dir / "from-voice").mkdir(exist_ok=True)

    grant_copied = []
    for src in source_files:
        dst = chapter_dir / "from-grant" / src.name
        if not dry_run and not dst.exists():
            shutil.copy2(src, dst)
        grant_copied.append({
            "name": src.name,
            "size": src.stat().st_size,
            "ext":  src.suffix.lower(),
        })

    voice_copied = []
    for src in voice_files:
        dst = chapter_dir / "from-voice" / src.name
        if not dry_run and not dst.exists():
            shutil.copy2(src, dst)
        voice_copied.append({
            "name": src.name,
            "size": src.stat().st_size,
        })

    meta = {
        "id": chapter_id,
        "book": book_slug,
        "number": chapter_num,
        "title": chapter_title,
        "sources": {
            "grant": grant_copied,
            "voice": voice_copied,
        },
        "stats": {
            "grant_count": len(grant_copied),
            "voice_count": len(voice_copied),
            "total_bytes": sum(f["size"] for f in grant_copied + voice_copied),
        },
        "packed_at": now_iso(),
    }

    if not dry_run:
        (chapter_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return meta


# ─── Матчинг voice-extracts к главе ──────────────────
def match_voice_files(chapter_title: str, all_voice: List[Path]) -> List[Path]:
    """Простой match: ищем voice-файлы, у которых slug пересекается с slug главы."""
    chapter_words = set(slugify(chapter_title).split("-"))
    chapter_words = {w for w in chapter_words if len(w) >= 4}  # отсечь короткие слова
    matched = []
    for vf in all_voice:
        vf_slug_words = set(slugify(vf.stem).split("-"))
        if chapter_words & vf_slug_words:
            matched.append(vf)
    return matched


# ─── Canon (override Drive structure for a specific book) ─────
def load_canon(slug: str) -> Optional[dict]:
    """Если у книги есть canon.json — структуру берём из него (override Drive)."""
    p = V2_CHAPTERS / slug / "canon.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ canon.json для {slug} битый: {e}")
        return None


def assign_grant_chapters_to_canon(canon_chapters: List[dict], grant_chapters: dict, threshold: float = 0.25) -> dict:
    """Greedy 1-к-1 матчинг: каждая Grant-папка идёт к одной канонической главе
    (с наибольшим Jaccard-сходством), если score > threshold."""
    # Подготовка слов
    canon_words = {ch["number"]: {w for w in slugify(ch["title"]).split("-") if len(w) >= 4}
                   for ch in canon_chapters}
    grant_words = {title: {w for w in slugify(title).split("-") if len(w) >= 4}
                   for title in grant_chapters}

    # Матрица score (Jaccard, чуть смещённая в пользу пересечения)
    scores = []
    for ch_num, c_words in canon_words.items():
        for g_title, g_words in grant_words.items():
            inter = c_words & g_words
            if not inter:
                continue
            union = c_words | g_words
            score = len(inter) / len(union) if union else 0
            scores.append((score, ch_num, g_title))

    scores.sort(reverse=True)  # сначала наилучшие пары

    assignments = {ch["number"]: [] for ch in canon_chapters}  # ch_num → list of grant files
    used_canon_for_grant = {}  # grant_title → ch_num куда уже ушёл

    for score, ch_num, g_title in scores:
        if score < threshold:
            break
        if g_title in used_canon_for_grant:
            continue
        # Назначаем
        assignments[ch_num].extend(grant_chapters[g_title])
        used_canon_for_grant[g_title] = ch_num

    return assignments, used_canon_for_grant


def find_external_source(doc_name: str, search_dir: Path) -> Optional[Path]:
    """Ищем внешний источник по имени (нестрого) в папке _external."""
    if not search_dir.exists():
        return None
    needle_words = {w for w in slugify(doc_name).split("-") if len(w) >= 4}
    for p in search_dir.iterdir():
        if not is_source_file(p):
            continue
        haystack_words = {w for w in slugify(p.stem).split("-") if len(w) >= 4}
        if needle_words & haystack_words:
            return p
    return None


# ─── Обход одного раздела ────────────────────────────
def pack_section(slug: str, sort_key: str, grant_prefix: str, kind: str,
                 status: str, voice_files: List[Path], dry_run: bool) -> dict:
    grant_dir = find_grant_dir(grant_prefix)
    canon = load_canon(slug)
    book = {
        "id": slug,
        "sort": sort_key,
        "kind": kind,                       # front / book / back
        "status": status,                   # active / reference
        "title": grant_dir.name if grant_dir else f"({grant_prefix} — не найдено)",
        "title_clean": (canon["title"] if canon else clean_book_title(grant_dir.name if grant_dir else grant_prefix)),
        "uses_canon": bool(canon),
        "chapters": [],
        "stats": {"grant_count": 0, "voice_count": 0, "total_bytes": 0},
    }

    # ─── Canon-режим: structure из canon.json, файлы матчим к каноническим главам ───
    if canon:
        ext_dir = V2_SOURCES / slug / "_external"
        # Собираем Grant-главы (название → файлы) для нечёткого матчинга
        grant_chapters = {}
        if grant_dir and grant_dir.exists():
            for cf in grant_dir.iterdir():
                if cf.is_dir() and cf.name.startswith("Глава"):
                    _, gtitle = extract_chapter_number(cf.name)
                    grant_chapters[gtitle] = [p for p in cf.rglob("*") if is_source_file(p)]
            # Book-level + не-Глава под-папки → общая корзина «без главы»
            common_files = []
            for p in grant_dir.iterdir():
                if p.is_file() and is_source_file(p):
                    common_files.append(p)
                elif p.is_dir() and not p.name.startswith("Глава"):
                    common_files.extend([x for x in p.rglob("*") if is_source_file(x)])
        else:
            common_files = []

        # Greedy 1-к-1: каждая Grant-папка идёт к одной канонической главе
        assignments, used_grant = assign_grant_chapters_to_canon(canon["chapters"], grant_chapters)

        for ch_def in canon["chapters"]:
            num = ch_def["number"]
            title = ch_def["title"]
            subtopics = ch_def.get("subtopics", [])
            ext_refs = ch_def.get("external_sources", [])

            grant_files = assignments.get(num, [])

            # Внешние источники — по списку из canon
            external_files = []
            external_meta = []
            for ref in ext_refs:
                doc = ref["doc"]
                f = find_external_source(doc, ext_dir)
                external_meta.append({
                    "doc": doc,
                    "section": ref.get("section"),
                    "note": ref.get("note"),
                    "found": bool(f),
                    "path": str(f.relative_to(V2_ROOT)) if f else None,
                })
                if f and f not in external_files:
                    external_files.append(f)

            # Voice-надиктовки
            v = match_voice_files(title, voice_files)

            # Сборка главы (Grant + external копируются)
            meta = build_chapter(slug, num, title, grant_files + external_files, v, dry_run)
            meta["subtopics"] = subtopics
            meta["external_refs"] = external_meta
            if "extra_section_from_pavel" in ch_def:
                meta["extra_section"] = ch_def["extra_section_from_pavel"]
            book["chapters"].append(meta)

        # Общая корзина — Grant-папки не сматченные ни к одной канонической + book-level
        unmatched = []
        for g_title, files in grant_chapters.items():
            if g_title not in used_grant:
                unmatched.extend(files)
        unmatched.extend(common_files)
        if unmatched:
            v = match_voice_files(book["title_clean"], voice_files)
            meta = build_chapter(slug, 0, "Несортированные материалы книги", unmatched, v, dry_run)
            book["chapters"].insert(0, meta)

        for ch in book["chapters"]:
            book["stats"]["grant_count"] += ch["stats"]["grant_count"]
            book["stats"]["voice_count"] += ch["stats"]["voice_count"]
            book["stats"]["total_bytes"] += ch["stats"]["total_bytes"]
        return book

    # ─── Drive-режим (книги без canon.json) ─────────────────────────────
    if not grant_dir or not grant_dir.exists():
        return book

    # 1) Под-папки «Глава N_ ...» — это явные главы
    chapter_folders = sorted(
        [p for p in grant_dir.iterdir() if p.is_dir() and p.name.startswith("Глава")],
        key=lambda p: extract_chapter_number(p.name)[0],
    )

    if chapter_folders:
        # Стандартный режим (Книги I—XII в основном)
        for cf in chapter_folders:
            num, title = extract_chapter_number(cf.name)
            files = [p for p in cf.rglob("*") if is_source_file(p)]
            v = match_voice_files(title, voice_files)
            meta = build_chapter(slug, num, title, files, v, dry_run)
            book["chapters"].append(meta)
        # Общие материалы книги: всё на верхнем уровне + ВСЕ файлы из не-«Глава» под-папок
        book_level_files = []
        for p in grant_dir.iterdir():
            if p.is_file() and is_source_file(p):
                book_level_files.append(p)
            elif p.is_dir() and not p.name.startswith("Глава"):
                book_level_files.extend([x for x in p.rglob("*") if is_source_file(x)])
        overview_title = "Общие материалы книги"
    else:
        # Нет «Глава N_» (Устав, Эпилог, Приложения, иногда Пролог) —
        # берём ВСЕ файлы раздела рекурсивно как одну «главу»
        book_level_files = [p for p in grant_dir.rglob("*") if is_source_file(p)]
        overview_title = "Все материалы раздела"

    if book_level_files:
        v = match_voice_files(book["title_clean"], voice_files)
        meta = build_chapter(slug, 0, overview_title, book_level_files, v, dry_run)
        book["chapters"].insert(0, meta)

    # Считаем итого по книге
    for ch in book["chapters"]:
        book["stats"]["grant_count"] += ch["stats"]["grant_count"]
        book["stats"]["voice_count"] += ch["stats"]["voice_count"]
        book["stats"]["total_bytes"] += ch["stats"]["total_bytes"]

    return book


ROMAN_NUMERALS = {
    "I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII","XIII","XIV","XV",
}


SHORT_LOWERCASE_RU = {
    "и","в","на","с","со","по","за","под","над","у","к","до","от","без","для",
    "о","об","про","или","но","а","же","ли",
}


def smart_case(text: str) -> str:
    """Mixed case с сохранением римских цифр и короткими союзами/предлогами в нижнем регистре."""
    result = []
    for word in text.split():
        bare = word.rstrip(".,:;)")
        suffix = word[len(bare):]
        if bare.upper() in ROMAN_NUMERALS:
            result.append(bare.upper() + suffix)
        elif word.isupper() and len(word) > 1:
            cap = word[0].upper() + word[1:].lower()
            result.append(cap)
        else:
            result.append(word)
    # Союзы/предлоги в нижний (кроме первого слова)
    for i in range(1, len(result)):
        bare = result[i].rstrip(".,:;)").lower()
        if bare in SHORT_LOWERCASE_RU:
            suffix = result[i][len(bare):]
            result[i] = bare + suffix
    return " ".join(result)


def clean_book_title(name: str) -> str:
    """'1. КНИГА I. ОСНОВЫ МИКОМИСТИЦИЗМА (СБОРКА ПО ТЕМЕ. ВСЕ МАТЕРИАЛЫ)' → 'Книга I. Основы Микомистицизма'"""
    t = re.sub(r"\s*\(СБОРКА ПО ТЕМЕ.*?\)\s*", "", name)
    t = re.sub(r"^\d+\.\s*", "", t)
    return smart_case(t.strip())


# ─── Main ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Codex v2 — упаковщик глав")
    ap.add_argument("--dry-run", action="store_true", help="Не копировать, только посчитать")
    ap.add_argument("--clean",   action="store_true", help="Перед паком очистить Codex2/sources/")
    args = ap.parse_args()

    if not GRANT_ROOT.exists():
        print(f"✗ Не найдена Grant-папка: {GRANT_ROOT}", file=sys.stderr)
        sys.exit(2)

    if args.clean and not args.dry_run:
        print(f"⚠ --clean: удаляю {V2_SOURCES}")
        if V2_SOURCES.exists():
            shutil.rmtree(V2_SOURCES)

    V2_SOURCES.mkdir(parents=True, exist_ok=True)
    V2_EVENTS.parent.mkdir(parents=True, exist_ok=True)

    voice_files = sorted([p for p in VOICE_DIR.glob("*.md") if is_source_file(p)]) if VOICE_DIR.exists() else []
    print(f"  voice-extracts найдено: {len(voice_files)}")
    print(f"  Grant-папка:            {GRANT_ROOT.name}")
    print(f"  Назначение:             {V2_SOURCES}")
    print(f"  Dry-run:                {args.dry_run}")
    print()

    toc = {
        "version": 1,
        "generated_at": now_iso(),
        "source_root": str(GRANT_ROOT),
        "voice_root": str(VOICE_DIR),
        "books": [],
        "stats": {"books": 0, "chapters": 0, "grant_files": 0, "voice_files": 0, "total_bytes": 0},
    }

    toc["stats"]["active_books"] = 0
    toc["stats"]["active_chapters"] = 0
    toc["stats"]["reference_books"] = 0

    for slug, sort_key, prefix, kind, status in SECTION_ORDER:
        book = pack_section(slug, sort_key, prefix, kind, status, voice_files, args.dry_run)
        toc["books"].append(book)
        if book["chapters"]:
            toc["stats"]["books"] += 1
            toc["stats"]["chapters"]    += len(book["chapters"])
            toc["stats"]["grant_files"] += book["stats"]["grant_count"]
            toc["stats"]["voice_files"] += book["stats"]["voice_count"]
            toc["stats"]["total_bytes"] += book["stats"]["total_bytes"]
            if status == "active":
                toc["stats"]["active_books"] += 1
                toc["stats"]["active_chapters"] += len(book["chapters"])
            else:
                toc["stats"]["reference_books"] += 1
        marker = "📚" if status == "reference" else "  "
        print(f"  {marker}[{slug:14s}] {book['title_clean'][:48]:48s} "
              f"глав:{len(book['chapters']):2d} "
              f"файлов:{book['stats']['grant_count']:3d} "
              f"voice:{book['stats']['voice_count']:2d}")

    print()
    print(f"  Итого: {toc['stats']['books']} книг · "
          f"{toc['stats']['chapters']} глав · "
          f"{toc['stats']['grant_files']} файлов Grant · "
          f"{toc['stats']['voice_files']} voice-файлов · "
          f"{toc['stats']['total_bytes']/1024/1024:.1f} МБ")

    if args.dry_run:
        print("\n(dry-run — toc.json и events.jsonl не записаны)")
        return

    # Записать toc.json
    V2_TOC.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ toc.json:    {V2_TOC}")

    # Записать событие
    event = {
        "ts": now_iso(),
        "type": "pack_chapters",
        "target": "codex-v2/sources",
        "payload": {
            "books": toc["stats"]["books"],
            "chapters": toc["stats"]["chapters"],
            "grant_files": toc["stats"]["grant_files"],
            "voice_files": toc["stats"]["voice_files"],
            "total_bytes": toc["stats"]["total_bytes"],
        },
    }
    with V2_EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(f"✓ events.jsonl: {V2_EVENTS}")


if __name__ == "__main__":
    main()
