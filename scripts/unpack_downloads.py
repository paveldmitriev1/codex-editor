#!/usr/bin/env python3
"""
unpack_downloads.py — распаковка всех новых zip из ~/Downloads.

Особенности:
- Правильная кодировка кириллицы (Google Drive zips часто в cp437)
- Идемпотентность: если уже распакован — пропускает
- Целевая папка: ~/Desktop/Codex2/fresh-downloads/<zip_basename>/

Запуск:
    python3 ~/Desktop/Codex2/scripts/unpack_downloads.py
    python3 ~/Desktop/Codex2/scripts/unpack_downloads.py --force   # перераспаковать всё
"""

import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path


HOME = Path.home()
DOWNLOADS = HOME / "Downloads"
TARGET = HOME / "Desktop/Codex2/fresh-downloads"

# Что НЕ считаем материалом Pavel-а
SKIP_NAMES = ("files.zip", "gstack-main.zip")


def is_pavel_archive(p: Path) -> bool:
    if p.suffix.lower() != ".zip":
        return False
    if p.name in SKIP_NAMES:
        return False
    # Pavel-овские zip-ы из Drive обычно содержат «КНИГА», «Mushroom Bible», «Библия», «КОДЕКСА» в имени
    name = p.name
    markers = ["КНИГА", "Mushroom Bible", "Библия", "КОДЕКСА", "ПРОЛОГ", "ЭПИЛОГ", "УСТАВ", "ПРИЛОЖЕНИЯ", "Codex", "Кодекс"]
    return any(m in name for m in markers)


def fix_name(raw: str) -> str:
    """Google Drive часто пишет имена как latin1/cp437 — превратить обратно в UTF-8."""
    try:
        return raw.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def unpack(zip_path: Path, force: bool = False) -> dict:
    target_root = TARGET / zip_path.stem
    if target_root.exists() and not force:
        return {"status": "skipped (already unpacked)", "files": 0, "target": str(target_root)}

    target_root.mkdir(parents=True, exist_ok=True)
    files_extracted = 0
    errors = []

    try:
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                name = fix_name(info.filename)
                target = target_root / name
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, target.open("wb") as out:
                        out.write(src.read())
                    files_extracted += 1
                except (OSError, ValueError) as e:
                    errors.append(f"{name}: {e}")
    except zipfile.BadZipFile as e:
        return {"status": f"BAD_ZIP: {e}", "files": 0, "target": str(target_root)}

    return {
        "status": "ok",
        "files": files_extracted,
        "errors": len(errors),
        "target": str(target_root),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Перераспаковать даже если папка уже есть")
    args = ap.parse_args()

    TARGET.mkdir(parents=True, exist_ok=True)

    zips = sorted([p for p in DOWNLOADS.glob("*.zip") if is_pavel_archive(p)])
    if not zips:
        print("(Нет архивов Pavel-а в ~/Downloads)")
        return

    print(f"=== Найдено {len(zips)} архивов Pavel-а ===")
    total_extracted = 0
    for z in zips:
        size_mb = z.stat().st_size / 1024 / 1024
        print(f"\n→ {z.name} ({size_mb:.1f} МБ)")
        result = unpack(z, force=args.force)
        print(f"  {result['status']}")
        if result.get("files"):
            print(f"  файлов: {result['files']}, ошибок: {result.get('errors', 0)}")
            print(f"  → {result['target']}")
            total_extracted += result["files"]

    print(f"\n✓ Итого распаковано: {total_extracted} файлов")
    print(f"✓ Расположение: {TARGET}")


if __name__ == "__main__":
    main()
