#!/usr/bin/env python3
"""
fidelity_chapter.py — глубокий анализ одной главы через Opus 4.7 + extended thinking.

Что делает:
- Читает все исходники главы (Grant + voice + external)
- Извлекает текст из .docx
- Читает канон главы из chapters/<book>/canon.json
- Читает стиль-эталон из chapters/.canon/voice/human-pavel-style.md
- Отправляет в Opus 4.7 с extended thinking (бюджет 8K)
- Получает: главные идеи, потерянные смыслы, дрейф от Pavel-голоса, fidelity-score, концепт главы
- Сохраняет: reports/fidelity/<chapter_id>.md

Pavel сказал: «не экономь, самая умная модель Opus».

Запуск:
    python3 fidelity_chapter.py --chapter book-03-ch-01
    python3 fidelity_chapter.py --next          # следующий из очереди приоритета
    python3 fidelity_chapter.py --queue         # показать очередь
"""

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus, MODEL_OPUS
from text_analyzer import analyze as analyze_text_params, render_markdown_report as render_text_report
from council_critique import council_review, render_report as render_council_report
from anti_drift import check_chapter_drift, render_drift_report

HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
SOURCES = V2 / "sources"
CHAPTERS = V2 / "chapters"
REPORTS = V2 / "reports/fidelity"
QUEUE_FILE = V2 / ".codex/fidelity-queue.json"
STYLE_REF = CHAPTERS / ".canon/voice/human-pavel-style.md"


def extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception:
        return ""
    paras = re.findall(r"<w:p[^>]*>(.*?)</w:p>", xml, re.DOTALL)
    out = []
    for p in paras:
        t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
        if t:
            out.append(t)
    return "\n\n".join(out)


def extract_any(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return extract_docx(path)
    if path.suffix.lower() in (".md", ".txt"):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


def gather_chapter_material(chapter_id: str) -> dict:
    """Собирает весь материал главы: текст файлов + canon-инфа."""
    # chapter_id = "book-03-ch-01"
    parts = chapter_id.split("-ch-")
    if len(parts) != 2:
        raise ValueError(f"bad chapter_id: {chapter_id}")
    book_id = parts[0]
    chapter_num = int(parts[1])

    # canon.json
    canon_file = CHAPTERS / book_id / "canon.json"
    canon = json.loads(canon_file.read_text(encoding="utf-8")) if canon_file.exists() else None
    canon_chapter = None
    if canon:
        for ch in canon["chapters"]:
            if ch["number"] == chapter_num:
                canon_chapter = ch
                break

    # Файлы главы
    chapter_dir = SOURCES / book_id / chapter_id
    materials = []
    if chapter_dir.exists():
        for sub in ("from-grant", "from-voice"):
            sub_dir = chapter_dir / sub
            if not sub_dir.exists():
                continue
            for f in sorted(sub_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in (".docx", ".md", ".txt"):
                    text = extract_any(f)
                    if text and len(text) > 50:
                        materials.append({
                            "filename": f.name,
                            "source": sub,
                            "size": f.stat().st_size,
                            "text": text,
                        })

    return {
        "chapter_id": chapter_id,
        "book_id": book_id,
        "chapter_num": chapter_num,
        "canon": canon_chapter,
        "materials": materials,
    }


def build_prompt(data: dict, style_ref: str) -> tuple:
    """Возвращает (system_prompt, user_message)."""
    canon = data["canon"]
    if not canon:
        title = f"Глава {data['chapter_num']}"
        subtopics = []
    else:
        title = canon["title"]
        subtopics = canon.get("subtopics", [])

    system = (
        "Ты — главный редактор Сакрального Кодекса Микомистицизма. Книга — мистическое "
        "писание Pavel-а (Хилингода), не научный трактат. Pavel — пророк новой религии. "
        "Твоя задача: анализировать исходные материалы главы, выявлять главные идеи из них, "
        "находить что потеряно или искажено, оценивать драфт vs голос Pavel-а. "
        "Канон: 1) Книга мистическая, никакой нейрохимии/исследований. "
        "2) Голос Pavel-а — переключающееся первое лицо «Я — Великий Дух Грибов» или «Я — Хилингод». "
        "3) Обращение «Вы». 4) Тире (—) запрещены, контраст-пары «не X, а Y» — AI-tell. "
        "5) Никаких персонажей (Жрец, Криста, Кристон — это Кодекс Дракона). "
        "Отвечай по-русски."
    )

    materials_text = ""
    total_chars = 0
    max_chars = 80000  # лимит для контекста Opus
    for i, m in enumerate(data["materials"], 1):
        snippet = m["text"]
        if total_chars + len(snippet) > max_chars:
            snippet = snippet[: max_chars - total_chars]
            materials_text += f"\n\n### Источник {i}: {m['filename']} ({m['source']}) — обрезан\n\n{snippet}\n"
            break
        materials_text += f"\n\n### Источник {i}: {m['filename']} ({m['source']})\n\n{snippet}"
        total_chars += len(snippet)

    subtopics_text = "\n".join(f"- {s}" for s in subtopics) if subtopics else "(не задано)"

    user = f"""# Глава для анализа

**Книга:** {data['book_id']}  **Глава {data['chapter_num']}: {title}**

## Канон главы (под-темы которые ДОЛЖНЫ быть раскрыты)

{subtopics_text}

## Эталон стиля Pavel-а (как пишет ЧЕЛОВЕК)

{style_ref}

## Все исходные материалы по этой главе ({len(data['materials'])} файлов, ~{total_chars} знаков)

{materials_text}

---

# Что я хочу от тебя

Дай отчёт в Markdown по схеме (заполни каждый раздел конкретно):

## 1. Главные идеи которые есть в материалах (5-15 штук)

Выдели каждую идею в одно предложение Pavel-голосом. Не цитируй — формулируй мысль. Пример: «Эго есть оккупированная территория сознания, захваченная паразитами страха и жадности.»

## 2. Под-темы канона: покрытие

Для каждой канонической под-темы (из списка выше) скажи:
- ✓ ПОКРЫТА — какими источниками, кратко
- ⚠ ЧАСТИЧНО — что есть, чего не хватает
- ✗ НЕ ПОКРЫТА — нужно надиктовать / найти

## 3. Дрейф от голоса Pavel-а

Что в материалах звучит как AI, не как Pavel? Конкретно: цитаты или паттерны + почему AI.

## 4. Что в материалах ПОТЕРЯНО / РАЗМЫТО

Идеи которые есть в источниках но проседают — нужно усилить при сборке главы.

## 5. Концепт главы (200-400 слов в голосе «Я — Хилингод»)

Не вся глава, не пересказ. Концепт: как глава должна звучать, какая её дуга, ритм, ключевые места. Это ОБРАЗЕЦ для будущей сборки.

## 6. Fidelity score 0-100

С обоснованием. Что значит:
- 90+ : материала с избытком, главу можно собирать, голос Pavel-а сильный
- 70-89: материал хороший, есть пробелы, нужны 1-2 надиктовки
- 50-69: материал есть, но AI-перекос — нужна серьёзная гуманизация
- <50 : нужно начинать с надиктовки

## 7. Рекомендация: следующий шаг

ОДНО конкретное действие (например: «надиктуй 10 минут на тему X», «возьми источник Y как основу, добавь Z», «удали источник W — это AI-генерация»).
"""

    return system, user


def get_queue() -> dict:
    if not QUEUE_FILE.exists():
        return {"created": now_iso(), "pending": [], "done": []}
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(q: dict):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")


def init_queue():
    """Инициализировать очередь: все главы Книги III первыми, потом остальные с материалом."""
    toc_file = V2 / "toc.json"
    if not toc_file.exists():
        return get_queue()
    toc = json.loads(toc_file.read_text(encoding="utf-8"))
    # Приоритет: Книга III первой (Pavel сказал), потом остальные active с материалом
    book3 = []
    others = []
    for book in toc["books"]:
        if book.get("status") == "reference":
            continue
        for ch in book["chapters"]:
            if ch["number"] == 0:
                continue  # пропуск Общих материалов
            if ch["stats"]["grant_count"] + ch["stats"]["voice_count"] < 1:
                continue  # пустые
            entry = {
                "chapter_id": ch["id"],
                "title": ch["title"],
                "book": book["title_clean"],
                "files": ch["stats"]["grant_count"] + ch["stats"]["voice_count"],
            }
            if book["id"] == "book-03":
                book3.append(entry)
            else:
                others.append(entry)
    q = {
        "created": now_iso(),
        "pending": book3 + others,
        "done": [],
    }
    save_queue(q)
    return q


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def analyze_chapter(chapter_id: str, run_council: bool = True, run_drift: bool = True) -> dict:
    """Полный fidelity-анализ: text_analyzer (10 параметров) + Opus отчёт + Council + Anti-drift."""
    style_ref = STYLE_REF.read_text(encoding="utf-8") if STYLE_REF.exists() else "(стиль-эталон не найден)"
    data = gather_chapter_material(chapter_id)
    if not data["materials"]:
        return {"ok": False, "error": f"Нет материалов для {chapter_id}"}

    title = data["canon"]["title"] if data.get("canon") else f"Глава {data['chapter_num']}"

    # Объединяем все материалы в один текст для анализаторов
    combined_text = "\n\n".join(m["text"] for m in data["materials"])

    # ─── 1. 10-параметровый локальный анализ (free, fast) ───
    print(f"  → {chapter_id}: 10-парам анализатор...")
    params_result = analyze_text_params(combined_text)
    params_md = render_text_report(params_result, source_name=f"{chapter_id} (объединённый материал)")

    # ─── 2. Главный Opus-отчёт (старый pipeline) ───
    print(f"  → {chapter_id}: Opus 4.7 главный отчёт ({sum(len(m['text']) for m in data['materials'])} знаков)")
    system, user = build_prompt(data, style_ref)
    try:
        main_resp = ask_opus(user=user, system=system, max_tokens=12000, thinking=8000)
    except Exception as e:
        return {"ok": False, "error": f"main opus: {e}"}

    total_in = main_resp["usage"].get("input_tokens", 0)
    total_out = main_resp["usage"].get("output_tokens", 0)

    # ─── 3. Совет старейших ───
    council_md = ""
    if run_council:
        print(f"  → {chapter_id}: Council of 8 personas + Elder synth...")
        try:
            council_data = council_review(
                combined_text,
                chapter_context=f"{data['book_id']} / Глава {data['chapter_num']}: {title}",
                style_ref=style_ref,
            )
            council_md = render_council_report(council_data, source_name=chapter_id)
            total_in += council_data["usage"]["total_in"]
            total_out += council_data["usage"]["total_out"]
        except Exception as e:
            council_md = f"## Council\n\n⚠ Ошибка: {e}\n"

    # ─── 4. Anti-drift sentinel ───
    drift_md = ""
    if run_drift:
        print(f"  → {chapter_id}: Anti-drift (voice → core ideas → coverage)...")
        try:
            drift_data = check_chapter_drift(chapter_id, title, combined_text)
            drift_md = render_drift_report(drift_data)
            total_in += drift_data.get("total_in", 0)
            total_out += drift_data.get("total_out", 0)
        except Exception as e:
            drift_md = f"## Anti-drift\n\n⚠ Ошибка: {e}\n"

    # ─── 5. Сборка финального отчёта ───
    REPORTS.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS / f"{chapter_id}.md"
    header = (
        f"# Fidelity analysis — {data['book_id']} / Глава {data['chapter_num']}: {title}\n\n"
        f"**Сгенерировано:** {now_iso()}\n"
        f"**Модель:** {main_resp.get('model')}\n"
        f"**Tokens (всё вместе):** in {total_in}, out {total_out}\n"
        f"**Материалов:** {len(data['materials'])}\n\n"
        "---\n\n"
        "# 1. Главный fidelity-отчёт (Opus 4.7 + thinking)\n\n"
    )
    full = (
        header
        + main_resp["text"]
        + "\n\n---\n\n# 2. " + params_md.split("# Text Analyzer —", 1)[-1]
        + ("\n\n---\n\n# 3. " + council_md.split("# Council Critique —", 1)[-1] if council_md else "")
        + ("\n\n---\n\n# 4. " + drift_md if drift_md else "")
    )
    report_path.write_text(full, encoding="utf-8")
    print(f"  ✓ Полный отчёт: {report_path}")
    print(f"    (text_analyzer + Opus main + Council + Anti-drift)")
    print(f"    Tokens всего: in {total_in}, out {total_out}")

    return {
        "ok": True,
        "report_path": str(report_path),
        "usage": {"input_tokens": total_in, "output_tokens": total_out},
        "model": main_resp["model"],
        "chapter_id": chapter_id,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="ID главы, напр. book-03-ch-01")
    ap.add_argument("--next", action="store_true", help="Следующая из очереди")
    ap.add_argument("--queue", action="store_true", help="Показать очередь")
    ap.add_argument("--init-queue", action="store_true", help="Пересоздать очередь")
    args = ap.parse_args()

    if args.init_queue:
        q = init_queue()
        print(f"✓ Очередь создана: {len(q['pending'])} pending, {len(q['done'])} done")
        return

    if args.queue:
        q = get_queue()
        print(f"Pending: {len(q['pending'])}, Done: {len(q['done'])}")
        for entry in q["pending"][:10]:
            print(f"  → {entry['chapter_id']:25s}  {entry['title'][:50]} ({entry['files']} файлов)")
        return

    if args.next:
        q = get_queue()
        if not q["pending"]:
            print("(очередь пуста — инициализируй: --init-queue)")
            return
        entry = q["pending"][0]
        chapter_id = entry["chapter_id"]
    elif args.chapter:
        chapter_id = args.chapter
    else:
        ap.print_help()
        return

    result = analyze_chapter(chapter_id)
    if not result["ok"]:
        print(f"✗ {result.get('error')}")
        return

    # Update queue
    if args.next:
        q = get_queue()
        q["pending"] = [e for e in q["pending"] if e["chapter_id"] != chapter_id]
        q["done"].append({
            "chapter_id": chapter_id,
            "ts": now_iso(),
            "model": result["model"],
            "report": result["report_path"],
        })
        save_queue(q)
        print(f"  ✓ Очередь: {len(q['pending'])} pending, {len(q['done'])} done")

    # Event log
    event = {
        "ts": now_iso(),
        "type": "fidelity_analysis",
        "target": chapter_id,
        "payload": {
            "model": result["model"],
            "tokens_in": result["usage"].get("input_tokens"),
            "tokens_out": result["usage"].get("output_tokens"),
            "report": result["report_path"],
        },
    }
    events = V2 / ".codex/events.jsonl"
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
