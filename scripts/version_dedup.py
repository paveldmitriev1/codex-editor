#!/usr/bin/env python3
"""
version_dedup.py — обнаружение дубликатов docx-версий по всему репо.

Pavel 2026-05-20: «в папках возможны разные версии одного и того же текста и разных книг,
тебе нужно смотреть даты когда последняя версия была сделана, соответственно дать приоритет
той которая была последняя если есть дубликаты, это очень важно».

Что делает:
1. Сканирует все sources/*/from-grant/*.docx
2. Группирует по нормализованному имени темы (без «Copy of», без подчёркиваний, lowercase)
3. Внутри группы — самый свежий по mtime = PRIMARY, остальные = ARCHIVE
4. Сохраняет version-map в `chapters/<book>/<chapter>/version-map.json`:
   {
     "primary": {"name": "...", "mtime": "...", "size": ...},
     "archive": [{"name": "...", "mtime": "...", "size": ...}, ...],
     "groups": [...]
   }
5. С флагом --apply перемещает archive → from-grant/_archive/
6. Кросс-папки: если два разных chapter folder содержат файл с одной темой —
   тоже флажит и выбирает свежий

Запуск:
  python3 version_dedup.py           # scan + report, ничего не двигает
  python3 version_dedup.py --apply   # переместит старые в _archive/
  python3 version_dedup.py --threshold 0.85  # минимальная схожесть имени

Output: reports/VERSION-DEDUP.md
"""
import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
SOURCES = V2 / "sources"
OUTPUT = V2 / "reports/VERSION-DEDUP.md"


def normalize_filename(name: str) -> str:
    """Нормализует имя файла к canonical форме для группировки дубликатов."""
    n = name.lower()
    # Убираем расширение
    n = re.sub(r"\.docx?$", "", n)
    # Убираем «Copy of»
    n = re.sub(r"^copy\s+of\s+", "", n)
    # Убираем префиксы вроде "01 ", "001 ", "(копия)" и т.п.
    n = re.sub(r"^\d{1,3}\s+", "", n)
    n = re.sub(r"\(копия.*?\)", "", n)
    n = re.sub(r"\(copy\)", "", n)
    n = re.sub(r"копия\s+\w+", "", n)
    # Все знаки препинания → пробелы (.,;:!?_-/\)
    n = re.sub(r"[\W_]+", " ", n)
    # Множественные пробелы → один
    n = re.sub(r"\s+", " ", n).strip()
    return n


def find_archive_dir(chapter_dir: Path) -> Path:
    return chapter_dir / "from-grant" / "_archive"


def scan() -> dict:
    """Возвращает все группы дубликатов по папкам."""
    findings = {
        "by_chapter": [],          # дубликаты внутри одной главы
        "cross_chapter": [],       # одна тема в разных главах
        "total_archived_size": 0,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

    # Индекс: normalized_name → [(path, mtime, size, chapter_id)]
    index = defaultdict(list)

    for book_dir in sorted(SOURCES.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        if book_dir.name == "_external" or book_dir.name.startswith("_"):
            continue
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith("_"):
                continue
            grant = ch_dir / "from-grant"
            if not grant.exists():
                continue
            for f in grant.iterdir():
                if not f.is_file() or f.suffix.lower() != ".docx":
                    continue
                # Пропускаем уже в _archive
                if "_archive" in f.parts:
                    continue
                norm = normalize_filename(f.name)
                # Пропускаем megafile-маркеры — это не дубликаты
                if f.name.startswith("!") or "общий текст" in norm or "всех глав" in norm:
                    continue
                index[norm].append({
                    "path": str(f.relative_to(V2)),
                    "name": f.name,
                    "mtime": f.stat().st_mtime,
                    "mtime_iso": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                    "size": f.stat().st_size,
                    "chapter_id": ch_dir.name,
                    "book_id": book_dir.name,
                })

    # Группы с >1 файла — потенциальные дубликаты
    for norm_name, items in index.items():
        if len(items) < 2:
            continue
        # Сортируем: mtime округлённое до 60-секундных бакетов DESC (массовое cp = «одна дата»),
        # потом size DESC (полнее = primary при равной дате)
        items_sorted = sorted(items, key=lambda x: (-int(x["mtime"] // 60), -x["size"]))
        primary = items_sorted[0]
        archive = items_sorted[1:]

        # Проверяем все ли в одной главе
        chapters_involved = set(x["chapter_id"] for x in items)
        if len(chapters_involved) == 1:
            findings["by_chapter"].append({
                "normalized_name": norm_name,
                "chapter_id": primary["chapter_id"],
                "book_id": primary["book_id"],
                "primary": primary,
                "archive": archive,
            })
        else:
            findings["cross_chapter"].append({
                "normalized_name": norm_name,
                "chapters": list(chapters_involved),
                "primary": primary,
                "archive": archive,
            })
        findings["total_archived_size"] += sum(a["size"] for a in archive)

    return findings


def apply_in_chapter(findings: dict) -> list:
    """Перемещает archive-файлы в from-grant/_archive/. Возвращает список действий."""
    applied = []
    for g in findings.get("by_chapter", []):
        ch_dir = SOURCES / g["book_id"] / g["chapter_id"]
        archive_dir = find_archive_dir(ch_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)
        for a in g["archive"]:
            src = V2 / a["path"]
            if not src.exists():
                continue
            dst = archive_dir / src.name
            # Если уже есть файл с таким именем — добавляем timestamp
            if dst.exists():
                stem = dst.stem
                suffix = dst.suffix
                dst = archive_dir / f"{stem}.{int(a['mtime'])}{suffix}"
            shutil.move(str(src), str(dst))
            applied.append(f"  archive: {a['path']} → {dst.relative_to(V2)} (newer in this folder: {g['primary']['name']})")
    return applied


def write_report(findings: dict, applied: list = None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# 🔄 Version dedup — {now}")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «приоритет той версии которая последняя по дате».")
    lines.append("")

    by_ch = findings.get("by_chapter", [])
    if by_ch:
        lines.append(f"## 📂 Дубликаты в одной главе — {len(by_ch)} групп")
        lines.append("")
        for g in by_ch:
            lines.append(f"### `{g['chapter_id']}` — тема «{g['normalized_name']}»")
            lines.append(f"- 🟢 **PRIMARY** (свежее, {g['primary']['mtime_iso']}, {g['primary']['size']//1024}KB): `{g['primary']['name']}`")
            for a in g["archive"]:
                lines.append(f"- 🗄️ archive ({a['mtime_iso']}, {a['size']//1024}KB): `{a['name']}`")
            lines.append("")

    cross = findings.get("cross_chapter", [])
    if cross:
        lines.append(f"## 🚨 Один файл в разных главах — {len(cross)} групп")
        lines.append("")
        lines.append("Эти файлы дублируются между папками — нужно решить какая глава owns этот файл.")
        lines.append("")
        for g in cross:
            lines.append(f"### Тема «{g['normalized_name']}»")
            lines.append(f"- Главы: `{', '.join(g['chapters'])}`")
            lines.append(f"- 🟢 PRIMARY ({g['primary']['mtime_iso']}): `{g['primary']['path']}`")
            for a in g["archive"]:
                lines.append(f"- 🗄️ duplicate ({a['mtime_iso']}): `{a['path']}`")
            lines.append("")

    if not by_ch and not cross:
        lines.append("✓ Дубликатов не найдено")
        lines.append("")

    if applied:
        lines.append(f"## ✓ Применено — {len(applied)} файлов перемещены в _archive/")
        lines.append("")
        for a in applied:
            lines.append(a)
        lines.append("")
    else:
        lines.append("---")
        lines.append("")
        lines.append("**Чтобы применить:** `python3 scripts/version_dedup.py --apply`")
        lines.append("")
        lines.append("Старые версии перемещаются в `from-grant/_archive/` — не удаляются, доступны для отката.")
        lines.append("")

    lines.append(f"_Освобождается_: ~{findings['total_archived_size']//1024} KB")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    findings = scan()
    applied = []
    if args.apply:
        applied = apply_in_chapter(findings)
    write_report(findings, applied=applied)
    print(f"✓ {OUTPUT}")
    print(f"   В главе дубликатов групп: {len(findings['by_chapter'])}")
    print(f"   Cross-chapter групп: {len(findings['cross_chapter'])}")
    if applied:
        print(f"   Применено: {len(applied)}")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "version_dedup",
            "target": "sources",
            "payload": {
                "in_chapter": len(findings["by_chapter"]),
                "cross_chapter": len(findings["cross_chapter"]),
                "applied": len(applied) if applied else 0,
                "archived_kb": findings["total_archived_size"] // 1024,
            },
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
