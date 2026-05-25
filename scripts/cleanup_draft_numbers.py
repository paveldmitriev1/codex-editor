#!/usr/bin/env python3
"""
cleanup_draft_numbers.py — убирает мусор-префиксы «№N\n №N\n» из draft.md.

Pavel 2026-05-20: «зачем ты пишешь номера параграфов в самом тексте параграфа».
Корень: предыдущие apply-paragraph endpoint или import-docx случайно сохранили
«№3» как часть текста параграфа.

Что делает:
1. Сканирует chapters/*/*/draft.md
2. Удаляет строки которые содержат только «№\d+» (одну на абзац, иногда дважды)
3. Сохраняет бэкап в chapters/<book>/<ch>/history/<ts>-pre-cleanup.md
4. Перезаписывает draft.md без мусора

Безопасно: бэкап сохраняется ВСЕГДА. Если что-то пойдёт не так — откат через
`mv history/<ts>-pre-cleanup.md draft.md`.

Запуск:
  python3 scripts/cleanup_draft_numbers.py --dry-run    # просто показать что почистит
  python3 scripts/cleanup_draft_numbers.py --apply      # реально почистить
"""
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
CHAPTERS = V2 / "chapters"


def cleanup_text(text: str) -> tuple:
    """Returns (cleaned, num_removed)."""
    lines = text.split("\n")
    out = []
    removed = 0
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"№\d+", stripped):
            removed += 1
            continue
        out.append(line)
    # Двойные пустые строки → одна
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, removed


def process_chapter(draft: Path, apply: bool) -> dict:
    text = draft.read_text(encoding="utf-8")
    cleaned, removed = cleanup_text(text)
    result = {"path": str(draft.relative_to(V2)), "removed": removed, "changed": removed > 0}
    if not result["changed"]:
        return result
    if apply:
        history_dir = draft.parent / "history"
        history_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = history_dir / f"{ts}-pre-cleanup.md"
        backup.write_text(text, encoding="utf-8")
        draft.write_text(cleaned, encoding="utf-8")
        result["backup"] = str(backup.relative_to(V2))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Реально применить очистку (иначе dry-run)")
    args = ap.parse_args()

    apply = args.apply
    label = "APPLY" if apply else "DRY-RUN"
    print(f"=== cleanup_draft_numbers.py — {label} ===\n")

    if not CHAPTERS.exists():
        print("Нет chapters/")
        return

    total_changed = 0
    total_removed = 0
    for book in sorted(CHAPTERS.iterdir()):
        if not book.is_dir() or book.name.startswith("."):
            continue
        for ch in sorted(book.iterdir()):
            if not ch.is_dir():
                continue
            draft = ch / "draft.md"
            if not draft.exists():
                continue
            r = process_chapter(draft, apply=apply)
            if r["changed"]:
                total_changed += 1
                total_removed += r["removed"]
                print(f"  {r['path']}: -{r['removed']} лишних №N строк" + (f"  (backup: {r.get('backup')})" if apply else ""))

    print(f"\nИтого: {total_changed} файлов, {total_removed} мусорных строк")
    if not apply:
        print("\n(dry-run — изменения НЕ применены)")
        print("Чтобы применить:  python3 scripts/cleanup_draft_numbers.py --apply")


if __name__ == "__main__":
    main()
