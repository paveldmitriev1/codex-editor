#!/usr/bin/env python3
"""
cross_chapter_similarity.py — % совпадения идей между главами.

Pavel: «нужно делать анализ если есть главы с похожими идеями чтобы можно
было их объединить в одну и список этих глав на выбор и процент на сколько
они совпадают».

Подход:
1) Читает voice-corpus/original-ideas/*.md (после extract_original_ideas.py)
2) Парсит идеи + категории + цитаты
3) Для каждой пары книг считает:
   - Категорийное пересечение (одинаковые категории)
   - Лексическое сходство (Jaccard на словах идей)
   - Семантические пары идей (high similarity threshold)
4) Сохраняет voice-corpus/chapter-similarity.json + Markdown отчёт
   воспринимаемый editor-ом через /api/chapter/<id>/similar

Запуск:
    python3 cross_chapter_similarity.py
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
IDEAS_DIR = V2 / "voice-corpus/original-ideas"
OUT_JSON = V2 / "voice-corpus/chapter-similarity.json"
OUT_MD = V2 / "voice-corpus/CHAPTER-SIMILARITY.md"

# Маппинг slug → канонический chapter_id (для UI)
SLUG_TO_BOOK_ID = {
    "kniga-i-osnovy-mikomistitsizma": "book-01",
    "kniga-ii-svyaschennye-zakony-i-vozmezdie": "book-02",
    "kniga-iii-nevidimye-miry": "book-03",
    "kniga-iv-bolezni-duha-i-istselenie": "book-04",
    "kniga-v-gribnoy-ekzortsizm": "book-05",
    "kniga-vi-svyaschennaya-tseremoniya": "book-06",
    "kniga-vii-put-tselitelya-i-provodnika": "book-07",
    "kniga-viii-mistitsizm-i-duhovnost": "book-08",
    "kniga-ix-prakticheskoe-primenenie": "book-09",
    "kniga-x-svyaschennoe-vyraschivanie-i-alhimiya": "book-10",
    "kniga-xi-preduprezhdeniya-i-zaschita": "book-11",
    "kniga-xii-organizatsionnaya-struktura": "book-12",
    "prolog-prizvanie-i-posvyaschenie": "prologue",
    "epilog-zavershenie-obucheniya": "epilogue",
    "ustav-i-printsipy": "ustav",
    "prilozheniya": "appendices",
}


def parse_ideas_md(md_path: Path) -> list:
    """Парсит .md файл из original-ideas, возвращает список идей."""
    text = md_path.read_text(encoding="utf-8")
    ideas = []
    # Каждая идея: ### iXX · idea text\n\n> «quote»\n_— source_\n\n**Категория:** cat
    pattern = re.compile(
        r"###\s+(\w+)\s+·\s+(.+?)\n(?:.*?>\s*«(.+?)».*?)?(?:.*?\*\*Категория:\*\*\s*(.+?))?(?=\n###|\n##|\Z)",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        idea_id, idea_text, quote, category = m.groups()
        ideas.append({
            "id": idea_id.strip(),
            "idea": idea_text.strip(),
            "quote": (quote or "").strip(),
            "category": (category or "Без категории").strip().split("\n")[0].strip(),
        })
    return ideas


def tokenize_ru(text: str) -> set:
    """Tokenize, keep only meaningful words (>=4 chars, lowercase)."""
    words = re.findall(r"[\wа-яёА-ЯЁ]+", text.lower())
    # Stopwords
    stop = {"который", "которая", "которое", "которые", "этот", "этого", "этой", "эти",
            "также", "тоже", "тогда", "когда", "поэтому", "потому", "чтобы", "только",
            "может", "можно", "очень", "просто", "более", "менее", "после", "перед",
            "через", "между", "вокруг", "около", "ничего", "всего", "всех"}
    return {w for w in words if len(w) >= 4 and w not in stop}


def idea_similarity(a: dict, b: dict) -> float:
    """Jaccard similarity между idea-текстами + bonus за общую категорию."""
    wa = tokenize_ru(a["idea"] + " " + a.get("quote", ""))
    wb = tokenize_ru(b["idea"] + " " + b.get("quote", ""))
    if not wa or not wb:
        return 0.0
    inter = wa & wb
    union = wa | wb
    jaccard = len(inter) / len(union) if union else 0
    # Bonus если одна и та же категория
    if a.get("category") == b.get("category"):
        jaccard += 0.1
    return min(1.0, jaccard)


def chapter_similarity(ideas_a: list, ideas_b: list, threshold: float = 0.12) -> tuple:
    """Возвращает (overlap_pct, shared_pairs)."""
    if not ideas_a or not ideas_b:
        return 0, []
    shared = []
    matched_b = set()
    for ia in ideas_a:
        best_b, best_sim = None, 0.0
        for j, ib in enumerate(ideas_b):
            if j in matched_b:
                continue
            sim = idea_similarity(ia, ib)
            if sim > best_sim:
                best_sim, best_b = sim, (j, ib)
        if best_b and best_sim >= threshold:
            j, ib = best_b
            matched_b.add(j)
            shared.append({
                "this_id": ia["id"],
                "this_text": ia["idea"][:200],
                "other_id": ib["id"],
                "other_text": ib["idea"][:200],
                "similarity": round(best_sim, 2),
                "category": ia.get("category"),
            })
    # Total ideas considered
    total = max(len(ideas_a), len(ideas_b))
    overlap_pct = round(len(shared) / total * 100, 1) if total else 0
    # Сортируем shared по similarity
    shared.sort(key=lambda x: -x["similarity"])
    return overlap_pct, shared


def slug_to_chapter_id(slug: str) -> str:
    return SLUG_TO_BOOK_ID.get(slug, slug)


def main():
    if not IDEAS_DIR.exists():
        print("✗ Сначала запусти extract_original_ideas.py")
        return

    files = sorted(IDEAS_DIR.glob("*.md"))
    print(f"Загружаю идеи из {len(files)} файлов...")
    chapters = {}
    for f in files:
        ideas = parse_ideas_md(f)
        if ideas:
            chapters[f.stem] = ideas
            print(f"  ✓ {f.stem}: {len(ideas)} идей")

    print(f"\nСравниваю все пары ({len(chapters)} × {len(chapters) - 1})...")
    # Build similarity matrix
    result = defaultdict(list)
    for slug_a, ideas_a in chapters.items():
        for slug_b, ideas_b in chapters.items():
            if slug_a == slug_b:
                continue
            overlap_pct, shared = chapter_similarity(ideas_a, ideas_b)
            if overlap_pct > 1 or shared:  # хоть одна общая идея
                result[slug_a].append({
                    "chapter_slug": slug_b,
                    "chapter_id": slug_to_chapter_id(slug_b),
                    "chapter_name": readable_name(slug_b),
                    "overlap_pct": overlap_pct,
                    "shared_count": len(shared),
                    "shared_ideas": shared[:10],  # топ-10
                })

    # Sort each chapter's similar list
    for slug in result:
        result[slug].sort(key=lambda x: -x["overlap_pct"])

    # Save JSON — also produce chapter_id-keyed copy for /api/chapter/<id>/similar
    # У нас есть только book-level similarity, но editor запрашивает chapter-level.
    # Заполним все chapters книги одним и тем же similarity (на уровне Книги).
    by_chapter_id = {}
    for slug, sims in result.items():
        book_id = slug_to_chapter_id(slug)
        # Применяем эти sims ко всем главам этой книги
        for ch_num in range(0, 20):  # max 20 chapters per book
            ch_id = f"{book_id}-ch-{ch_num:02d}"
            by_chapter_id[ch_id] = [
                {
                    "chapter": s["chapter_name"],
                    "chapter_id": s["chapter_id"],
                    "overlap_pct": s["overlap_pct"],
                    "shared_ideas": s["shared_ideas"][:5],
                    "shared_count": s["shared_count"],
                }
                for s in sims[:8]
            ]

    OUT_JSON.write_text(json.dumps(by_chapter_id, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ JSON: {OUT_JSON}")

    # Markdown отчёт
    md = ["# Cross-Chapter Similarity — % совпадения идей между книгами", ""]
    md.append(f"**Сгенерировано:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    md.append(f"**Глав проанализировано:** {len(chapters)}")
    md.append("")
    md.append("## Топ пар по совпадению идей")
    md.append("")
    all_pairs = []
    for slug_a, sims in result.items():
        for s in sims:
            all_pairs.append((s["overlap_pct"], slug_a, s["chapter_slug"], s["shared_count"]))
    all_pairs.sort(reverse=True)
    md.append("| % | Книга A | Книга B | Общих идей |")
    md.append("|---|---|---|---|")
    for pct, a, b, n in all_pairs[:30]:
        md.append(f"| **{pct}%** | {readable_name(a)} | {readable_name(b)} | {n} |")
    md.append("")
    md.append("## По каждой книге — детально")
    md.append("")
    for slug, sims in sorted(result.items()):
        md.append(f"### {readable_name(slug)}")
        md.append("")
        if not sims:
            md.append("_(нет похожих)_")
            md.append("")
            continue
        md.append("| % | Похожая книга | Общих идей |")
        md.append("|---|---|---|")
        for s in sims[:10]:
            md.append(f"| {s['overlap_pct']}% | {readable_name(s['chapter_slug'])} | {s['shared_count']} |")
        md.append("")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"✓ MD:   {OUT_MD}")

    # Event
    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "cross_chapter_similarity",
        "target": "voice-corpus/chapter-similarity.json",
        "payload": {
            "chapters": len(chapters),
            "pairs_above_5pct": sum(len(s) for s in result.values()),
        },
    }
    events_file = V2 / ".codex/events.jsonl"
    with events_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def readable_name(slug: str) -> str:
    # Найти в SLUG_TO_BOOK_ID обратное
    titles = {
        "kniga-i-osnovy-mikomistitsizma": "Книга I. Основы Микомистицизма",
        "kniga-ii-svyaschennye-zakony-i-vozmezdie": "Книга II. Священные Законы",
        "kniga-iii-nevidimye-miry": "Книга III. Невидимые Миры",
        "kniga-iv-bolezni-duha-i-istselenie": "Книга IV. Болезни Духа",
        "kniga-v-gribnoy-ekzortsizm": "Книга V. Грибной Экзорцизм",
        "kniga-vi-svyaschennaya-tseremoniya": "Книга VI. Священная Церемония",
        "kniga-vii-put-tselitelya-i-provodnika": "Книга VII. Путь Целителя",
        "kniga-viii-mistitsizm-i-duhovnost": "Книга VIII. Мистицизм",
        "kniga-ix-prakticheskoe-primenenie": "Книга IX. Практическое Применение",
        "kniga-x-svyaschennoe-vyraschivanie-i-alhimiya": "Книга X. Алхимия",
        "kniga-xi-preduprezhdeniya-i-zaschita": "Книга XI. Предупреждения",
        "kniga-xii-organizatsionnaya-struktura": "Книга XII. Структура",
        "prolog-prizvanie-i-posvyaschenie": "Пролог",
        "epilog-zavershenie-obucheniya": "Эпилог",
        "ustav-i-printsipy": "Устав",
    }
    return titles.get(slug, slug)


if __name__ == "__main__":
    main()
