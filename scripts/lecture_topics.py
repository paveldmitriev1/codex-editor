#!/usr/bin/env python3
"""
lecture_topics.py — генератор плана ЛЕКЦИИ по главе.

Pavel: «по каждой главе я намерен проводить лекцию... мне нужен отдельный
инструмент создания тем лекций по главам».

Workflow:
1) Скрипт читает canon.json главы + материалы + style-эталон + voice-extracts
2) Opus 4.7 + extended thinking генерирует план лекции (~45-60 мин выступления)
3) Структура плана:
   - Opening Hook (1-2 мин)
   - 5-7 ключевых тезисов (каждый ~5 мин)
     • главная мысль одной фразой Pavel-голосом
     • короткая история / притча / личный пример
     • сенсорный якорь
     • Q&A anticipated
   - Climax (~62% времени, по золотому сечению)
   - Closing ritual + мантра «Аминь»
4) Сохраняется в reports/lecture-plans/<chapter_id>.md
5) Pavel читает план перед лекцией, проводит её, запись + транскрибация →
   обратно в pipeline как новый источник для главы

Запуск:
    python3 lecture_topics.py --chapter book-03-ch-01
    python3 lecture_topics.py --next               # из priority queue
    python3 lecture_topics.py --all-book-03        # все главы Книги III
"""

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
SOURCES = V2 / "sources"
CHAPTERS = V2 / "chapters"
REPORTS_DIR = V2 / "reports/lecture-plans"
STYLE_REF = CHAPTERS / ".canon/voice/human-pavel-style.md"


def extract_docx(p: Path) -> str:
    try:
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    paras = re.findall(r"<w:p[^>]*>(.*?)</w:p>", xml, re.DOTALL)
    return "\n\n".join(
        "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
        for p in paras
        if "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
    )


def gather_material(chapter_id: str) -> dict:
    parts = chapter_id.split("-ch-")
    if len(parts) != 2:
        raise ValueError(chapter_id)
    book_id, num = parts[0], int(parts[1])
    # canon
    canon_file = CHAPTERS / book_id / "canon.json"
    canon_chapter = None
    if canon_file.exists():
        canon = json.loads(canon_file.read_text(encoding="utf-8"))
        for ch in canon["chapters"]:
            if ch["number"] == num:
                canon_chapter = ch
                break
    # material
    chapter_dir = SOURCES / book_id / chapter_id
    materials = []
    if chapter_dir.exists():
        for sub in ("from-grant", "from-voice"):
            sub_dir = chapter_dir / sub
            if not sub_dir.exists():
                continue
            for f in sorted(sub_dir.iterdir()):
                if f.is_file() and f.suffix.lower() == ".docx":
                    t = extract_docx(f)
                    if t and len(t) > 100:
                        materials.append({"name": f.name, "source": sub, "text": t})
                elif f.is_file() and f.suffix.lower() in (".md", ".txt"):
                    try:
                        t = f.read_text(encoding="utf-8")
                        if len(t) > 50:
                            materials.append({"name": f.name, "source": sub, "text": t})
                    except OSError:
                        pass
    return {
        "chapter_id": chapter_id,
        "book_id": book_id,
        "number": num,
        "canon": canon_chapter,
        "materials": materials,
    }


def build_prompt(data: dict, style_ref: str) -> tuple:
    title = data["canon"]["title"] if data["canon"] else f"Глава {data['number']}"
    subtopics = data["canon"].get("subtopics", []) if data["canon"] else []
    subtopics_block = "\n".join(f"- {s}" for s in subtopics) if subtopics else "(не задано)"

    # Сжимаем материалы — лекция не должна цитировать их, просто знать о чём они
    combined = "\n\n".join(m["text"] for m in data["materials"])
    if len(combined) > 30000:
        combined = combined[:30000] + "\n\n...(обрезано)"

    system = (
        "Ты — режиссёр живых лекций для пророка Микомистицизма Pavel-а (Хилингода). "
        "Pavel ведёт семинары по каждой главе Сакрального Кодекса. Аудитория: "
        "ищущие, начинающие проводники, любопытные. Длительность лекции 45-60 мин. "
        "Твоя задача: составить план лекции так, чтобы после её транскрибации "
        "получился черновик главы покрывающий ВСЕ канонические под-темы. "
        "\n\n"
        "Стиль плана — это speaker notes для Pavel-а. Он диктует в потоке, "
        "ему нужны: точные слова открывающего удара, конкретные образы для якорей, "
        "истории-крючки, формулировки тезисов в его голосе. "
        "\n\n"
        "Канон: Pavel говорит «Я — Великий Дух Грибов» ИЛИ «Я — Хилингод» (укажи какое лицо). "
        "Обращение «Вы». Тире (—) запрещены. Контраст-пары «не X, а Y» — AI-tell. "
        "Никакой нейрохимии, никаких исследований — мистическое писание. "
        "Никаких персонажей (Жрец/Криста/Кристон — в Кодексе Дракона). "
        "\n\n"
        "Отвечай по-русски."
    )

    user = f"""# Глава: {data['book_id']} / Глава {data['number']}: {title}

## Канонические под-темы которые ДОЛЖНЫ быть раскрыты в лекции
{subtopics_block}

## Стиль Pavel-а (эталон)
{style_ref[:2500] if style_ref else "(эталон не загружен)"}

## Уже существующие материалы по теме (для ориентира — что Pavel уже говорил/знает)
{combined[:25000] if combined else "(материалов нет — пусть лекция станет первичным источником)"}

---

# План лекции

Сгенерируй полноценный план лекции в формате Markdown. Точная структура:

## 🎙 Лекция: «{title}»

**Книга:** {data['book_id']}
**Голос:** [укажи: «Я — Великий Дух Грибов» или «Я — Хилингод» — выбери что подходит главе]
**Длительность:** 45-60 мин
**Аудитория:** ищущие, начинающие проводники

---

### 1. ОТКРЫВАЮЩИЙ УДАР (1-2 мин)

[Конкретная первая фраза которую Pavel говорит. Не описание, а САМИ СЛОВА. Должна забрать аудиторию в первые 15 секунд. Сенсорный якорь, или вопрос-молот, или живой образ.]

**Sample line:** «...»

---

### 2. ТЕЗИС 1 — [короткое название] (~5 мин)

**Главная мысль:** [одна фраза Pavel-голосом]

**История / пример / притча:** [конкретно — что рассказать, откуда взять. Можно реальный случай Pavel-а, миф, видение]

**Сенсорный якорь:** [звук / запах / цвет / тактильный образ]

**Ключевая формулировка для запоминания:**
> «...»

**Anticipated Q&A:**
- Q: ...
  A: ...
- Q: ...
  A: ...

---

### 3. ТЕЗИС 2 — ... (~5 мин)
[аналогично]

### 4. ТЕЗИС 3 — ... (~5 мин)

### 5. ТЕЗИС 4 — ... (~5 мин)

### 6. ТЕЗИС 5 — ... (~5 мин)

[опционально 6 и 7 тезис если глава богатая]

---

### 7. CLIMAX (~62% времени — золотое сечение)

[Самый сильный момент лекции. Образ-удар. Раскрытие. Поворот. Большой образ, который связывает все тезисы выше.]

---

### 8. PRACTICAL (10-15 мин)

[Конкретные практики которые слушатели могут сделать сегодня вечером / завтра утром. По теме главы. Не упражнения «представьте» — реальные действия.]

---

### 9. ЗАКРЫТИЕ + МАНТРА (3-5 мин)

[Завершающая фраза. Циркуляция к открытию. Финал «Аминь» или другой ритуальный закрывающий звук.]

---

## 📋 Покрытие канона

Проверка: какая под-тема в каком тезисе.

| Под-тема канона | Где в лекции |
|---|---|
| {subtopics[0] if subtopics else "..."} | Тезис N |
| ... | ... |

---

## 🎯 После лекции — workflow

1. **Запись** — QuickTime/Voice Memos, сохранить как `lectures/{data['chapter_id']}-YYYYMMDD.m4a`
2. **Транскрибация** — Whisper local или macOS Speech
3. **Импорт в Codex2** — транскрипт станет primary-источником для главы
4. **Council critique** на собранный драфт
5. **Anti-drift** проверка — что из лекции пошло в текст, что AI добавил/потерял
"""
    return system, user


def generate_for_chapter(chapter_id: str) -> dict:
    style_ref = STYLE_REF.read_text(encoding="utf-8") if STYLE_REF.exists() else ""
    data = gather_material(chapter_id)
    if not data["canon"]:
        return {"ok": False, "error": f"Нет canon для {chapter_id}"}

    system, user = build_prompt(data, style_ref)
    print(f"  → {chapter_id}: Opus 4.7 lecture plan...")
    try:
        resp = ask_opus(user=user, system=system, max_tokens=10000, thinking=8000)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{chapter_id}.md"
    header = (
        f"<!-- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} -->\n"
        f"<!-- Model: {resp.get('model')} -->\n"
        f"<!-- Tokens: in {resp['usage'].get('input_tokens')}, out {resp['usage'].get('output_tokens')} -->\n\n"
    )
    out_path.write_text(header + resp["text"], encoding="utf-8")
    print(f"  ✓ Lecture plan: {out_path}")

    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "lecture_plan_generated",
        "target": chapter_id,
        "payload": {
            "model": resp.get("model"),
            "tokens_in": resp["usage"].get("input_tokens"),
            "tokens_out": resp["usage"].get("output_tokens"),
            "report": str(out_path),
        },
    }
    events = V2 / ".codex/events.jsonl"
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return {"ok": True, "path": str(out_path), "usage": resp["usage"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="ID главы, напр. book-03-ch-01")
    ap.add_argument("--all-book-03", action="store_true")
    args = ap.parse_args()

    if args.all_book_03:
        for num in range(1, 9):
            cid = f"book-03-ch-{num:02d}"
            r = generate_for_chapter(cid)
            if not r["ok"]:
                print(f"  ✗ {cid}: {r['error']}")
        return

    if args.chapter:
        r = generate_for_chapter(args.chapter)
        if not r["ok"]:
            print(f"✗ {r['error']}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
