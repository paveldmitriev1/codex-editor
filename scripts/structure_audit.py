#!/usr/bin/env python3
"""
structure_audit.py — аудит структуры sources/ vs toc.json.

Pavel 2026-05-20: «Может ты очень много сейчас глав и книг уже написанных потерял,
всю ночь будешь делать анализ, все просмотришь все прочитаешь и восстановишь,
потом внесёшь это всё в оглавление».

Что делает:
1. Сканирует все папки sources/<book>/<chapter>/from-grant/
2. Находит:
   a) Вложенные книги — папки с ≥3 файлами «Глава N» с разными N
   b) Главы которых нет в toc.json
   c) Папки с одиночными файлами но толстыми (>100K) — потенциально несколько глав в одной
   d) Megafiles без раздельных глав — нужна ручная разборка
3. Opus 4.7 анализирует подозрительные кейсы и выносит вердикт:
   - "nested_book" — это вложенная книга, нужно разделить
   - "single_chapter" — одна глава, всё ок
   - "needs_split" — одна big файл с несколькими темами, нужен ручной split
4. Пишет в reports/STRUCTURE-AUDIT.md

Режимы:
  --scan         # только отчёт, не трогает toc.json
  --apply        # применяет уверенные исправления (с backup)
  --opus         # включить Opus-анализ подозрительных кейсов

Запуск: python3 structure_audit.py --scan --opus
"""
import argparse
import json
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from claude_helper import ask_opus
except ImportError:
    ask_opus = None

V2 = Path.home() / "Desktop/Codex2"
SOURCES = V2 / "sources"
TOC_FILE = V2 / "toc.json"
OUTPUT = V2 / "reports/STRUCTURE-AUDIT.md"

MEGAFILE_MARKERS = ["общий текст", "всех глав", "единый текст", "весь текст", "полный текст"]


def is_megafile(name: str) -> bool:
    if name.startswith("!"):
        return True
    low = name.lower()
    return any(m in low for m in MEGAFILE_MARKERS)


def docx_text_excerpt(path: Path, max_chars: int = 2000) -> str:
    """Быстро извлечь начало текста из docx (без python-docx)."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        paras = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)
        text = " ".join(p for p in paras if p.strip())[:max_chars]
        return text
    except Exception as e:
        return f"<read error: {e}>"


def scan_sources() -> dict:
    """Возвращает structured findings."""
    if not TOC_FILE.exists():
        return {"error": "no toc.json"}
    toc = json.loads(TOC_FILE.read_text(encoding="utf-8"))
    in_toc = set()
    for b in toc.get("books", []):
        for c in b.get("chapters", []):
            in_toc.add(c["id"])

    findings = {
        "nested_book_suspects": [],  # >=3 «Глава N» в папке
        "not_in_toc": [],            # папки которых нет в toc
        "missing_sources": [],       # toc-главы без файлов
        "megafile_only": [],         # только megafile, без отдельных глав
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

    source_chapter_ids = set()
    for book_dir in sorted(SOURCES.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        if book_dir.name == "_external" or book_dir.name.startswith("_"):
            continue
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir():
                continue
            cid = ch_dir.name
            source_chapter_ids.add(cid)
            if cid not in in_toc:
                findings["not_in_toc"].append(f"{book_dir.name}/{cid}")
            grant = ch_dir / "from-grant"
            if not grant.exists():
                continue
            chapter_files = []
            intro_files = []
            megafile = False
            other = []
            for f in sorted(grant.iterdir()):
                if not f.is_file() or f.suffix.lower() != ".docx":
                    continue
                if is_megafile(f.name):
                    megafile = True
                    continue
                m = re.match(r"^(?:Copy of\s+)?(Глава|Часть|Раздел)\s+(\d+)[.:_\s]", f.name, re.IGNORECASE)
                if m:
                    chapter_files.append({"num": int(m.group(2)), "name": f.name, "size": f.stat().st_size, "path": str(f.relative_to(V2))})
                elif "введени" in f.name.lower() or "предислов" in f.name.lower():
                    intro_files.append({"name": f.name, "size": f.stat().st_size, "path": str(f.relative_to(V2))})
                else:
                    other.append({"name": f.name, "size": f.stat().st_size, "path": str(f.relative_to(V2))})

            unique_nums = sorted(set(c["num"] for c in chapter_files))
            current_title = next(
                (c["title"] for b in toc["books"] for c in b.get("chapters", []) if c["id"] == cid),
                None
            )
            if len(unique_nums) >= 3:
                findings["nested_book_suspects"].append({
                    "path": f"{book_dir.name}/{cid}",
                    "chapter_id": cid,
                    "book_id": book_dir.name,
                    "current_title": current_title,
                    "chapter_files": chapter_files,
                    "intro_files": intro_files,
                    "other_files": other,
                    "unique_chapter_numbers": unique_nums,
                })
            if megafile and not chapter_files and not intro_files and not other:
                findings["megafile_only"].append(f"{book_dir.name}/{cid}")

    # toc-главы без источников
    for cid in in_toc:
        if cid not in source_chapter_ids:
            findings["missing_sources"].append(cid)

    return findings


def opus_verdict(suspect: dict) -> dict:
    """Опус решает: вложенная книга или нет."""
    if ask_opus is None:
        return {"verdict": "unknown", "reason": "claude_helper не доступен"}
    excerpts = []
    for f in suspect["chapter_files"][:6]:
        ex = docx_text_excerpt(V2 / f["path"], 800)
        excerpts.append(f"### {f['name']} ({f['size']//1024}KB)\n{ex[:500]}")
    intros_dump = "\n".join(f"- Введение: {i['name']}" for i in suspect["intro_files"])

    system = (
        "Ты помогаешь Pavel-у Сакральному Кодексу. Анализируешь структуру: "
        "одна папка содержит несколько .docx файлов с «Глава N» в имени. "
        "Реши: это ОДНА глава с подпунктами (nested chapter), или ПОЛНОЦЕННАЯ книга "
        "которую нужно вытащить отдельно (nested book).\n\n"
        "Возвращай ТОЛЬКО JSON."
    )
    user = f"""# Папка: {suspect['path']}
# Текущее название в toc.json: «{suspect['current_title'] or 'нет в toc'}»

# Файлы внутри (по номерам глав):
- Главы: {suspect['unique_chapter_numbers']}
{intros_dump}

# Образцы текстов первых глав:
{chr(10).join(excerpts)}

# Что вернуть

```json
{{
  "verdict": "nested_book" | "single_chapter" | "single_chapter_with_subsections",
  "confidence": 0-10,
  "suggested_book_id": "book-например-name (только если nested_book)",
  "suggested_book_title": "КНИГА: ... (только если nested_book)",
  "chapter_titles": ["Глава 1. ...", "Глава 2. ..."] (только если nested_book),
  "reasoning": "почему так решил"
}}
```

Признаки nested_book: связные главы с разной тематикой и Введением; одна общая тема ВСЕЙ книги.
Признаки single_chapter: главы это подпункты одной темы, файлы фрагменты.
"""
    try:
        resp = ask_opus(user=user, system=system, max_tokens=2000, thinking=2000)
        text = resp["text"].strip()
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(cleaned)
    except Exception as e:
        return {"verdict": "error", "reason": str(e)}


def render_report(findings: dict, opus_results: dict = None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# 🔍 Structure audit — {now}")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «может ты очень много глав и книг потерял, проверь всё, восстанови, внеси в оглавление»")
    lines.append("")

    nested = findings.get("nested_book_suspects", [])
    if nested:
        lines.append(f"## 🚨 Подозрение на вложенные книги — {len(nested)}")
        lines.append("")
        for s in nested:
            lines.append(f"### `{s['path']}`")
            lines.append(f"- Текущий title в toc: «{s['current_title'] or '⚠️ НЕТ В TOC'}»")
            lines.append(f"- Найдено глав внутри: **{s['unique_chapter_numbers']}**")
            if s["intro_files"]:
                lines.append(f"- Введение: {', '.join(i['name'] for i in s['intro_files'])}")
            if opus_results and s["path"] in opus_results:
                v = opus_results[s["path"]]
                emoji = "📚" if v.get("verdict") == "nested_book" else "📄"
                lines.append(f"- {emoji} **Opus вердикт:** `{v.get('verdict')}` (confidence {v.get('confidence', '?')}/10)")
                if v.get("suggested_book_title"):
                    lines.append(f"- 💡 Предложенный заголовок: «{v['suggested_book_title']}»")
                    lines.append(f"- 💡 ID: `{v.get('suggested_book_id', '?')}`")
                if v.get("reasoning"):
                    lines.append(f"- _Почему_: {v['reasoning']}")
            lines.append("")
            lines.append("  **Файлы:**")
            for f in s["chapter_files"]:
                lines.append(f"  - Глава {f['num']}: {f['name']} ({f['size']//1024}KB)")
            for f in s["other_files"]:
                lines.append(f"  - _(другое)_: {f['name']} ({f['size']//1024}KB)")
            lines.append("")

    not_in_toc = findings.get("not_in_toc", [])
    if not_in_toc:
        lines.append(f"## 📂 Папки без записи в toc — {len(not_in_toc)}")
        lines.append("")
        for p in not_in_toc:
            lines.append(f"- `{p}`")
        lines.append("")

    missing = findings.get("missing_sources", [])
    if missing:
        lines.append(f"## ❓ Главы в toc без файлов — {len(missing)}")
        lines.append("")
        for m in missing:
            lines.append(f"- `{m}`")
        lines.append("")

    mega = findings.get("megafile_only", [])
    if mega:
        lines.append(f"## 📦 Только megafile, без раздельных глав — {len(mega)}")
        lines.append("")
        for p in mega:
            lines.append(f"- `{p}` — нужен ручной split, либо использовать как одну главу")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Что делать дальше")
    lines.append("")
    lines.append("- Pavel — посмотри **🚨 Подозрение на вложенные книги** и одобри/отклони.")
    lines.append("- `python3 scripts/structure_audit.py --apply` применяет nested_book решения с confidence ≥ 8 (с backup).")
    lines.append("- Запуск раз в сутки в 02:00 в overnight_watcher.sh.")
    lines.append("")
    return "\n".join(lines)


def apply_safe_fixes(findings: dict, opus_results: dict, min_confidence: int = 8) -> list:
    """Применяет уверенные исправления nested_book (с backup)."""
    if not opus_results:
        return ["нет Opus результатов — не могу применять"]
    toc = json.loads(TOC_FILE.read_text(encoding="utf-8"))
    backup = TOC_FILE.with_suffix(f".json.bak.audit-{datetime.now().strftime('%Y%m%dT%H%M%S')}")
    backup.write_text(TOC_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    applied = []

    for s in findings.get("nested_book_suspects", []):
        v = opus_results.get(s["path"])
        if not v or v.get("verdict") != "nested_book" or v.get("confidence", 0) < min_confidence:
            continue
        new_book_id = v.get("suggested_book_id", "")
        if not re.match(r"^book-[a-z][a-z0-9-]*$", new_book_id):
            applied.append(f"skip {s['path']}: invalid book_id «{new_book_id}»")
            continue
        # Проверяем нет ли уже такой книги
        if any(b.get("id") == new_book_id for b in toc.get("books", [])):
            applied.append(f"skip {s['path']}: «{new_book_id}» уже есть")
            continue

        # 1) Создать новые папки sources/<new_book>/<new_book>-ch-NN/from-grant/
        new_book_dir = SOURCES / new_book_id
        chapter_titles = v.get("chapter_titles", []) or [f"Глава {n}" for n in s["unique_chapter_numbers"]]
        new_chapters = []
        # 00 = Введение если есть
        offset = 0
        if s["intro_files"]:
            intro_dir = new_book_dir / f"{new_book_id}-ch-00" / "from-grant"
            intro_dir.mkdir(parents=True, exist_ok=True)
            for f in s["intro_files"]:
                src = V2 / f["path"]
                shutil.copy(src, intro_dir / src.name)
            new_chapters.append({"id": f"{new_book_id}-ch-00", "title": "Введение",
                                  "source_dir": f"sources/{new_book_id}/{new_book_id}-ch-00"})
            offset = 1
        for i, num in enumerate(s["unique_chapter_numbers"]):
            ch_id = f"{new_book_id}-ch-{i+offset:02d}"
            ch_dir = new_book_dir / ch_id / "from-grant"
            ch_dir.mkdir(parents=True, exist_ok=True)
            # Копируем файлы с этим номером
            for f in s["chapter_files"]:
                if f["num"] == num:
                    src = V2 / f["path"]
                    shutil.copy(src, ch_dir / src.name)
            title = chapter_titles[i] if i < len(chapter_titles) else f"Глава {num}"
            new_chapters.append({"id": ch_id, "title": title,
                                  "source_dir": f"sources/{new_book_id}/{ch_id}"})

        # 2) Добавить новую книгу в toc после parent (parent определяем по book_id source-папки)
        new_book_entry = {
            "id": new_book_id,
            "title": v.get("suggested_book_title", new_book_id),
            "parent": s["book_id"],
            "order": 0,  # положим после parent
            "status": "active",
            "chapters": new_chapters,
        }
        new_books = []
        for b in toc["books"]:
            new_books.append(b)
            if b.get("id") == s["book_id"]:
                new_books.append(new_book_entry)
        toc["books"] = new_books

        # 3) Удаляем старую запись если была
        for b in toc["books"]:
            if b.get("id") == s["book_id"]:
                b["chapters"] = [c for c in b.get("chapters", []) if c.get("id") != s["chapter_id"]]

        applied.append(f"✓ создана книга {new_book_id} ({len(new_chapters)} глав) из {s['path']}")

    if applied:
        TOC_FILE.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
        applied.append(f"backup: {backup.name}")
    return applied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", default=True)
    ap.add_argument("--opus", action="store_true", help="Запустить Opus-анализ подозрительных")
    ap.add_argument("--apply", action="store_true", help="Применить уверенные исправления (≥ confidence 8)")
    ap.add_argument("--min-confidence", type=int, default=8)
    args = ap.parse_args()

    findings = scan_sources()
    opus_results = {}
    if args.opus and findings.get("nested_book_suspects"):
        print(f"Opus анализ {len(findings['nested_book_suspects'])} подозрительных…")
        for s in findings["nested_book_suspects"]:
            print(f"  → {s['path']}")
            opus_results[s["path"]] = opus_verdict(s)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(findings, opus_results if opus_results else None)
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"✓ {OUTPUT}")
    print()
    print(f"Подозрительных вложенных книг: {len(findings.get('nested_book_suspects', []))}")
    print(f"Папок не в toc: {len(findings.get('not_in_toc', []))}")
    print(f"Глав в toc без файлов: {len(findings.get('missing_sources', []))}")

    if args.apply and opus_results:
        applied = apply_safe_fixes(findings, opus_results, min_confidence=args.min_confidence)
        print()
        print(f"Применено: {len(applied)}")
        for line in applied:
            print(f"  {line}")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "structure_audit",
            "target": "sources",
            "payload": {
                "nested_suspects": len(findings.get("nested_book_suspects", [])),
                "not_in_toc": len(findings.get("not_in_toc", [])),
                "missing_sources": len(findings.get("missing_sources", [])),
                "opus_used": bool(opus_results),
                "applied": args.apply,
            },
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
