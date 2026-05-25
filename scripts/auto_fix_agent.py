#!/usr/bin/env python3
"""
auto_fix_agent.py — ночной агент авто-починки тривиальных проблем.

Берёт самые БЕЗОПАСНЫЕ и явные проблемы из TECH-QA-PENDING.md / VISUAL-QA-PENDING.md
и пытается их починить автоматически.

Безопасные правки:
- Удалить stale PID files
- Очистить corrupted строки events.jsonl
- Пересоздать пустые/corrupted JSON файлы (council.json, metaphors.json) с дефолтами

НЕ безопасные (только в --aggressive режиме):
- Опус-фикс UI-багов в editor.html (по описанию из VISUAL-QA-PENDING.md)
- Опус-фикс python ошибок

Каждое применение → запись в AUTO-FIXES-APPLIED.md
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
TECH_QA = V2 / "reports/TECH-QA-PENDING.md"
VISUAL_QA = V2 / "reports/VISUAL-QA-PENDING.md"
APPLIED = V2 / "reports/AUTO-FIXES-APPLIED.md"


def remove_stale_pids():
    fixes = []
    for f in (V2 / ".codex").glob("*.pid"):
        try:
            pid = int(f.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, OSError):
            try:
                f.unlink()
                fixes.append(f"удалён stale pid: {f.relative_to(V2)}")
            except Exception as e:
                pass
    return fixes


def clean_events_jsonl():
    f = V2 / ".codex/events.jsonl"
    if not f.exists():
        return []
    fixes = []
    good = []
    bad = 0
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if "ts" in obj and "type" in obj:
                good.append(line)
            else:
                bad += 1
        except json.JSONDecodeError:
            bad += 1
    if bad > 0:
        # Backup
        backup = V2 / f".codex/events.jsonl.bak.{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        f.rename(backup)
        f.write_text("\n".join(good) + "\n", encoding="utf-8")
        fixes.append(f"очищено {bad} битых строк events.jsonl (backup: {backup.name})")
    return fixes


def reset_corrupted_json():
    """Пересоздать пустые/битые JSON файлы с дефолтами."""
    defaults = {
        "approvals.json": {"approved_indices": []},
        "notes.json": {"notes": {}},
        "metaphors.json": {"metaphors": []},
    }
    fixes = []
    for ch_dir in (V2 / "chapters").glob("*/*"):
        if not ch_dir.is_dir():
            continue
        for fname, default in defaults.items():
            f = ch_dir / fname
            if f.exists():
                try:
                    json.loads(f.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    backup = ch_dir / f"{fname}.bak.{datetime.now().strftime('%Y%m%dT%H%M%S')}"
                    f.rename(backup)
                    f.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
                    fixes.append(f"reset corrupted {f.relative_to(V2)} (backup: {backup.name})")
    return fixes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-safe", action="store_true", help="Применить безопасные правки (default)")
    ap.add_argument("--aggressive", action="store_true", help="Опус-фикс UI/Python багов (рискованно)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not (args.apply_safe or args.aggressive):
        args.apply_safe = True  # default

    all_fixes = []
    if args.apply_safe and not args.dry_run:
        all_fixes.extend(remove_stale_pids())
        all_fixes.extend(clean_events_jsonl())
        all_fixes.extend(reset_corrupted_json())

    if args.aggressive:
        # TODO: pull bug из VISUAL-QA-PENDING.md, отправить в Opus с инструкцией пофиксить
        # Пока что — placeholder
        pass

    if all_fixes:
        APPLIED.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with APPLIED.open("a", encoding="utf-8") as f:
            f.write(f"\n## {ts}\n\n")
            for fix in all_fixes:
                f.write(f"- {fix}\n")
        print(f"✓ auto-fix applied {len(all_fixes)} fixes")
        # Event
        with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts, "type": "auto_fix_applied", "target": "system",
                "payload": {"count": len(all_fixes)}
            }, ensure_ascii=False) + "\n")
    else:
        print("auto-fix: nothing to fix")


if __name__ == "__main__":
    main()
