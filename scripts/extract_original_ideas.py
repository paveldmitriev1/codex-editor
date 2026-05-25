#!/usr/bin/env python3
"""
extract_original_ideas.py — для каждой канонической главы выделяет ОРИГИНАЛЬНЫЕ
идеи Pavel-а из всех его надиктовок по теме.

Pavel: «выявить оригинальные мои идеи которые я наговаривал в потоке».

Pipeline:
1) Читает voice-corpus/analysis.json (от analyze_voice_corpus.py)
2) Группирует conversations по канонической chapter
3) Для каждой chapter:
   - Собирает все Pavel-сообщения из подходящих conversations
   - Обрезает до 80K знаков (если больше)
   - Отправляет в Opus 4.7 + extended thinking с задачей
     «извлеки 20-40 уникальных идей которые Pavel впервые произнёс»
4) Сохраняет в voice-corpus/original-ideas/<slug>.md
5) Сводный отчёт voice-corpus/ORIGINAL-IDEAS.md

Запуск:
    python3 extract_original_ideas.py
    python3 extract_original_ideas.py --chapter "Книга III"  # только одна
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
CORPUS = V2 / "voice-corpus/raw"
ANALYSIS = V2 / "voice-corpus/analysis.json"
OUT_DIR = V2 / "voice-corpus/original-ideas"


def slugify(s: str, max_len: int = 50) -> str:
    s = s.lower().strip()
    table = str.maketrans({
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh",
        "з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o",
        "п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts",
        "ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu",
        "я":"ya",
    })
    s = s.translate(table)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:max_len]


def parse_pavel_messages(md_path: Path) -> list:
    text = md_path.read_text(encoding="utf-8")
    parts = re.split(r"^### Message \d+ · ", text, flags=re.MULTILINE)
    messages = []
    for p in parts[1:]:
        lines = p.split("\n")
        if not lines:
            continue
        body = "\n".join(lines[1:])
        body = re.sub(r"---$", "", body, flags=re.MULTILINE).strip()
        if body and len(body) > 100:  # только длинные
            messages.append(body)
    return messages


def gather_chapter_corpus(chapter: str, results: list) -> tuple:
    """Собрать все Pavel-сообщения по conversations этой главы. Лимит 80K знаков."""
    chapter_results = [r for r in results if r.get("top_chapter") == chapter]
    chapter_results.sort(key=lambda r: -r["n_chars"])  # сначала самые большие

    parts = []
    total_chars = 0
    sources = []
    for r in chapter_results:
        path = CORPUS / r["file"]
        if not path.exists():
            continue
        msgs = parse_pavel_messages(path)
        if not msgs:
            continue
        combined = "\n\n[---]\n\n".join(msgs)
        if total_chars + len(combined) > 80000:
            # Берём столько сколько вмещается
            remaining = 80000 - total_chars
            if remaining > 1000:
                parts.append(f"# {r['name']} ({r['date']})\n\n{combined[:remaining]}")
                sources.append(r["name"])
                total_chars += remaining
            break
        parts.append(f"# {r['name']} ({r['date']})\n\n{combined}")
        sources.append(r["name"])
        total_chars += len(combined)

    return "\n\n---\n\n".join(parts), sources, total_chars


def extract_ideas(chapter: str, corpus: str, sources: list) -> dict:
    """Один Opus call: извлечь 20-40 оригинальных идей Pavel-голосом."""
    system = (
        "Ты — хранитель оригинального голоса Pavel-а (Хилингода). Эти тексты — "
        "его ПРЯМАЯ РЕЧЬ из чатов с Claude, надиктованная в потоке. Не пересказ, "
        "не AI-сборка — его собственные слова. Твоя задача: выделить ВСЕ "
        "оригинальные идеи, метафоры, образы, формулировки, мысли которые "
        "Pavel говорил САМ. Цель: не потерять НИЧЕГО уникального когда мы будем "
        "собирать главу. Ты работаешь над книгой-шедевром о Микомистицизме "
        "(мистическая религия Грибов). Голос: «Я — Великий Дух Грибов» или "
        "«Я — Хилингод». Никакой нейрохимии, никаких персонажей (Жрец/Криста/"
        "Кристон — в Кодексе Дракона). Отвечай только JSON."
    )

    user = f"""# Надиктовки Pavel-а на тему «{chapter}»

Источники ({len(sources)} бесед, ~{len(corpus):,} знаков):
{chr(10).join(f'- {s}' for s in sources[:25])}

---

{corpus}

---

# Что нужно

Извлеки **20-40 ОРИГИНАЛЬНЫХ ИДЕЙ** Pavel-а на эту тему. Каждая идея — это
одна конкретная мысль которую он произносит САМ в этих текстах.

JSON-схема:

```json
{{
  "chapter": "{chapter}",
  "ideas": [
    {{
      "id": "i01",
      "idea": "Одна фраза-тезис в голосе Pavel-а (не пересказ — формулировка)",
      "quote": "Прямая цитата из надиктовки (15-50 слов)",
      "category": "тематический подраздел (паразиты / экзорцизм / голос Творцов / и т.п.)",
      "novelty": "high|medium|low — насколько идея уникальна",
      "source_hint": "название беседы где впервые появилась"
    }},
    ...
  ]
}}
```

Принципы:
- Если идея повторяется в разных бесебах — оставляй ОДНУ запись (самую сильную формулировку)
- Цитата ОБЯЗАТЕЛЬНА — это якорь обратно к голосу Pavel-а
- Категория группирует идеи внутри главы
- novelty:high = «впервые слышу такое от него»; medium = «он развивает известную мысль новым углом»; low = «классика, базовая доктрина»
- Pavel-голос: «есть» вместо «является», активные глаголы, без тире, без контраст-пар «не X, а Y»
- Сохраняй его собственные образы и метафоры дословно

Извлеки как можно больше high-novelty идей. low-novelty оставляй только если они структурно нужны для главы.
"""

    print(f"  → Opus 4.7 + thinking 8K для главы «{chapter}» ({len(corpus):,} знаков)...")
    resp = ask_opus(user=user, system=system, max_tokens=10000, thinking=8000)
    try:
        cleaned = re.sub(r"^```json\s*|\s*```$", "", resp["text"].strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
    except Exception as e:
        return {"error": str(e), "raw": resp["text"][:2000], "usage": resp["usage"]}

    return {
        "data": data,
        "usage": resp["usage"],
        "model": resp["model"],
    }


def render_chapter_md(chapter: str, data: dict, sources: list, char_count: int) -> str:
    ideas = data.get("ideas", [])
    by_cat = defaultdict(list)
    for i in ideas:
        by_cat[i.get("category", "Без категории")].append(i)

    high = [i for i in ideas if i.get("novelty") == "high"]
    medium = [i for i in ideas if i.get("novelty") == "medium"]

    out = [
        f"# Оригинальные идеи Pavel-а — {chapter}",
        "",
        f"**Сгенерировано:** {datetime.now().isoformat()}",
        f"**Источников:** {len(sources)} бесед",
        f"**Объём проанализированного голоса:** {char_count:,} знаков",
        f"**Извлечено идей:** {len(ideas)} (high-novelty: {len(high)}, medium: {len(medium)})",
        "",
        "---",
        "",
        "## 🌟 HIGH-NOVELTY — уникальные мысли Pavel-а",
        "",
    ]
    for i in high:
        out.append(f"### {i.get('id', '?')} · {i.get('idea', '?')}")
        out.append("")
        if i.get("quote"):
            out.append(f"> «{i['quote']}»")
        if i.get("source_hint"):
            out.append(f"_— {i['source_hint']}_")
        out.append(f"\n**Категория:** {i.get('category', '?')}")
        out.append("")

    out.append("## 🔧 MEDIUM-NOVELTY — углы и развитие")
    out.append("")
    for i in medium:
        out.append(f"### {i.get('id', '?')} · {i.get('idea', '?')}")
        if i.get("quote"):
            out.append(f"> «{i['quote']}»")
        out.append(f"_{i.get('category', '?')}_")
        out.append("")

    # По категориям
    out.append("## 📋 Все идеи сгруппированы по категориям")
    out.append("")
    for cat, items in sorted(by_cat.items()):
        out.append(f"### {cat} — {len(items)} идей")
        out.append("")
        for i in items:
            out.append(f"- **{i.get('id', '?')}** {i.get('idea', '?')}")
        out.append("")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="Конкретная глава (по точному названию)")
    ap.add_argument("--skip-empty", action="store_true", help="Пропускать главы с <5K знаков")
    args = ap.parse_args()

    if not ANALYSIS.exists():
        print("✗ Сначала запусти analyze_voice_corpus.py")
        sys.exit(2)

    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    results = analysis["results"]

    # Группировка по главам
    by_chapter = defaultdict(list)
    for r in results:
        by_chapter[r.get("top_chapter", "(off-topic)")].append(r)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    chapters_to_process = [args.chapter] if args.chapter else list(by_chapter.keys())
    chapters_to_process = [c for c in chapters_to_process if c != "(off-topic)"]

    # Сортируем по объёму — самые богатые первыми (быстрее ROI)
    chapters_to_process.sort(key=lambda c: -sum(r["n_chars"] for r in by_chapter[c]))

    # Skip уже сделанные
    chapters_to_process = [
        c for c in chapters_to_process
        if not (OUT_DIR / f"{slugify(c)}.md").exists()
    ]
    print(f"К обработке: {len(chapters_to_process)} глав (уже сделано — пропущено)")

    summary = []
    total_in = total_out = 0

    for chapter in chapters_to_process:
        items = by_chapter[chapter]
        total_chars = sum(r["n_chars"] for r in items)
        if args.skip_empty and total_chars < 5000:
            print(f"⏭  {chapter}: пропуск ({total_chars} знаков, < 5K)")
            continue

        slug = slugify(chapter)
        print(f"\n=== {chapter} ({len(items)} бесед, {total_chars:,} знаков) ===")

        corpus, sources, used_chars = gather_chapter_corpus(chapter, results)
        if not corpus:
            print("  (нет corpus)")
            continue

        result = extract_ideas(chapter, corpus, sources)
        if "error" in result:
            print(f"  ✗ {result['error']}")
            continue

        usage = result["usage"]
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)

        md = render_chapter_md(chapter, result["data"], sources, used_chars)
        out_path = OUT_DIR / f"{slug}.md"
        out_path.write_text(md, encoding="utf-8")
        ideas_count = len(result["data"].get("ideas", []))
        print(f"  ✓ {ideas_count} идей → {out_path.name}")

        summary.append({
            "chapter": chapter,
            "slug": slug,
            "conversations": len(items),
            "chars_total": total_chars,
            "chars_analyzed": used_chars,
            "ideas": ideas_count,
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0),
        })

    # Сводный отчёт
    out = [
        f"# 🌟 Оригинальные Идеи Pavel-а — Сводный Отчёт",
        "",
        f"**Сгенерировано:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Глав проанализировано:** {len(summary)}",
        f"**Tokens IN (всего):** {total_in:,}",
        f"**Tokens OUT (всего):** {total_out:,}",
        "",
        "## По главам",
        "",
        "| Глава | Бесед | Знаков | Идей | Файл |",
        "|---|---|---|---|---|",
    ]
    for s in summary:
        out.append(f"| {s['chapter']} | {s['conversations']} | {s['chars_total']:,} | {s['ideas']} | [{s['slug']}.md](original-ideas/{s['slug']}.md) |")

    (V2 / "voice-corpus/ORIGINAL-IDEAS.md").write_text("\n".join(out), encoding="utf-8")
    print(f"\n✓ Сводный отчёт: voice-corpus/ORIGINAL-IDEAS.md")

    # Event
    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "original_ideas_extracted",
        "target": "voice-corpus/original-ideas",
        "payload": {
            "chapters": len(summary),
            "total_ideas": sum(s["ideas"] for s in summary),
            "tokens_in": total_in,
            "tokens_out": total_out,
        },
    }
    events = V2 / ".codex/events.jsonl"
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
