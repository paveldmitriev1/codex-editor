#!/usr/bin/env python3
"""
chapter_coherence_in_book.py — UC-21 (Pavel 2026-05-20).

Pavel: «когда анализируешь главу, проанализируй другие главы этой книги.
Вполне возможно там будут уже похожие тексты. Тогда нужно принять решение
в какой главе эту идею оставлять. Если убираем здесь — пометка что в другой
главе оставляем».

Что делает:
1. Берёт draft.md одной главы (chapter_id)
2. Сканирует все ДРУГИЕ главы той же книги
3. Считает Jaccard similarity между параграфами (по lemmatized словам)
4. Находит пары: paragraph_idx (этой главы) ↔ другой_chapter:другой_paragraph_idx
5. Если similarity ≥ 0.45 — это «повтор идеи между главами»
6. Дает recommendation: «keep_here» / «keep_other» / «merge» — на основе:
   - В какой главе тема логически уместнее (по title главы)
   - Где параграф ярче / содержательнее (по длине + плотности уникальных слов)
   - Score обеих глав по ideology-fit (если есть кэш)

Результат: `chapters/<book>/<chapter>/coherence-in-book.json` + UI секция.

Запуск:
    python3 chapter_coherence_in_book.py --chapter book-obsession-ch-02
    python3 chapter_coherence_in_book.py --book book-obsession --all
"""
import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
CHAPTERS_ROOT = V2 / "chapters"

# Слова которые игнорируем (служебные, частые без смысла)
STOPWORDS = set("""
и а но или что как это так где когда же ведь вот ли да не он она оно они мы вы я ты
но в во к ко с со на по для у от из под над без через между перед после об обо
сей этот тот те эта это эти все весь вся всю всё всех своего своей своих
ещё уже теперь сейчас потом тогда сюда туда здесь там
быть был была были есть будет будем будут стать стал стала стали стало
свой свои свою своим своими своей нашим нашими нашей наш наша
мне меня мной мою моих моя моё мой моим
вам вас вами ваш ваша ваше ваши вашими
им их ими его её ему ей нём нём
""".split())

# Минимальные параметры
MIN_PAR_LEN = 100        # короткие параграфы (заголовки, переходы) не сравниваем
SIMILARITY_THRESHOLD = 0.40
MIN_OVERLAP_TOKENS = 8   # должно быть минимум N общих слов


def tokenize(text: str) -> set:
    """Простая токенизация: слова длиной 4+, lowercase, без stopwords."""
    words = re.findall(r"[а-яёa-z]{4,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def load_chapter_paragraphs(chapter_dir: Path) -> list:
    draft = chapter_dir / "draft.md"
    if not draft.exists():
        return []
    text = draft.read_text(encoding="utf-8")
    paragraphs = []
    for i, p in enumerate(text.split("\n\n")):
        p = p.strip()
        if len(p) < MIN_PAR_LEN:
            continue
        if p.startswith("#"):
            continue
        paragraphs.append({"idx": i, "text": p, "tokens": tokenize(p)})
    return paragraphs


def load_chapter_meta(chapter_dir: Path) -> dict:
    src = V2 / "sources" / chapter_dir.parent.name / chapter_dir.name / "meta.json"
    if src.exists():
        try:
            return json.loads(src.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"title": chapter_dir.name, "number": 0}


def recommendation(this_para: dict, other_para: dict, this_meta: dict, other_meta: dict) -> str:
    """Решает где оставлять идею.

    Эвристика:
    - Если this_meta.number > other_meta.number и в other уже была — keep_other (логика построения)
    - Длина+плотность параграфа — где он богаче там и место
    - Если this введение / other основная — keep_other
    """
    this_num = this_meta.get("number", 0) or 0
    other_num = other_meta.get("number", 0) or 0
    this_title = (this_meta.get("title") or "").lower()
    other_title = (other_meta.get("title") or "").lower()

    # 1) Введение → отдает в основную
    if "введ" in this_title and "введ" not in other_title:
        return "keep_other"
    if "введ" in other_title and "введ" not in this_title:
        return "keep_here"
    # 2) Заключение → отдаёт в основную
    if any(k in this_title for k in ["заключ", "итог"]) and not any(k in other_title for k in ["заключ", "итог"]):
        return "keep_other"
    # 3) Хронология: первая глава должна вводить, последующие — расширять. Если идея в более ранней главе уже была — здесь her убираем
    if other_num > 0 and this_num > 0:
        if this_num > other_num:
            # Эта позже — другая ввела первой → keep_other
            return "keep_other"
        if this_num < other_num:
            return "keep_here"
    # 4) Длина — где параграф богаче (больше уникальных слов)
    this_uniq = len(this_para["tokens"])
    other_uniq = len(other_para["tokens"])
    if other_uniq > this_uniq * 1.3:
        return "keep_other"
    if this_uniq > other_uniq * 1.3:
        return "keep_here"
    return "merge"  # одинаковые — нужно слияние


def analyze_chapter(chapter_id: str, verbose: bool = False) -> dict:
    # Парсим chapter_id → (book, chapter_dir)
    m = re.match(r"^(book-[\w-]+?)-ch-(\d+)$", chapter_id)
    if not m:
        return {"error": f"bad chapter_id: {chapter_id}"}
    book_id = m.group(1)
    chapter_dir = CHAPTERS_ROOT / book_id / chapter_id
    if not chapter_dir.exists():
        return {"error": f"no chapter: {chapter_dir}"}

    this_paras = load_chapter_paragraphs(chapter_dir)
    this_meta = load_chapter_meta(chapter_dir)
    if not this_paras:
        return {"error": "no paragraphs (no draft.md or too short)"}

    book_dir = CHAPTERS_ROOT / book_id
    findings = []
    for other_ch_dir in sorted(book_dir.iterdir()):
        if not other_ch_dir.is_dir() or other_ch_dir.name == chapter_id:
            continue
        if other_ch_dir.name.startswith("."):
            continue
        other_paras = load_chapter_paragraphs(other_ch_dir)
        other_meta = load_chapter_meta(other_ch_dir)
        if not other_paras:
            continue
        for tp in this_paras:
            best = None
            for op in other_paras:
                overlap = tp["tokens"] & op["tokens"]
                if len(overlap) < MIN_OVERLAP_TOKENS:
                    continue
                sim = jaccard(tp["tokens"], op["tokens"])
                if sim < SIMILARITY_THRESHOLD:
                    continue
                if not best or sim > best["similarity"]:
                    best = {
                        "this_idx": tp["idx"],
                        "this_preview": tp["text"][:140],
                        "other_chapter": other_ch_dir.name,
                        "other_idx": op["idx"],
                        "other_preview": op["text"][:140],
                        "similarity": round(sim, 2),
                        "overlap_words": sorted(overlap)[:10],
                    }
            if best:
                rec = recommendation(tp, {"tokens": this_paras[0]["tokens"]} if False else next((op for op in other_paras if op["idx"] == best["other_idx"]), {}), this_meta, other_meta)
                best["recommendation"] = rec
                best["recommendation_text"] = {
                    "keep_here": f"💡 Оставить здесь (эта глава раньше / лучше развита); убрать из {other_ch_dir.name}",
                    "keep_other": f"💡 Оставить в {other_ch_dir.name} (там полнее / уместнее); убрать отсюда",
                    "merge": f"💡 Близкие версии — слить лучшее из обеих",
                }.get(rec, rec)
                findings.append(best)
                if verbose:
                    print(f"  P{tp['idx']} ↔ {other_ch_dir.name}:P{best['other_idx']} ({best['similarity']:.2f}) → {rec}")

    return {
        "chapter_id": chapter_id,
        "book_id": book_id,
        "this_meta": this_meta,
        "this_para_count": len(this_paras),
        "duplicates": findings,
        "total_duplicates": len(findings),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def save_result(result: dict, chapter_id: str):
    book_id = result.get("book_id")
    if not book_id:
        return
    out = CHAPTERS_ROOT / book_id / chapter_id / "coherence-in-book.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="конкретная глава (e.g. book-obsession-ch-02)")
    ap.add_argument("--book", help="все главы одной книги")
    ap.add_argument("--all", action="store_true", help="вместе с --book")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.chapter:
        targets = [args.chapter]
    elif args.book and args.all:
        book_dir = CHAPTERS_ROOT / args.book
        targets = [d.name for d in sorted(book_dir.iterdir())
                   if d.is_dir() and not d.name.startswith(".")]
    elif args.book:
        # Только главы без coherence-in-book.json
        book_dir = CHAPTERS_ROOT / args.book
        targets = [d.name for d in sorted(book_dir.iterdir())
                   if d.is_dir() and not d.name.startswith(".")
                   and not (d / "coherence-in-book.json").exists()]
        if not targets:
            print("Все главы уже покрыты coherence-in-book.json")
            return
        targets = targets[:1]  # одна за вызов
    else:
        # По умолчанию — book-obsession первая непокрытая
        book_dir = CHAPTERS_ROOT / "book-obsession"
        if not book_dir.exists():
            print("Передай --chapter или --book")
            return
        targets = [d.name for d in sorted(book_dir.iterdir())
                   if d.is_dir() and not (d / "coherence-in-book.json").exists()]
        if not targets:
            print("Все главы book-obsession покрыты coherence-in-book.json")
            return
        targets = targets[:1]

    for chapter_id in targets:
        print(f"Analyzing {chapter_id}…")
        result = analyze_chapter(chapter_id, verbose=args.verbose)
        if result.get("error"):
            print(f"  ✗ {result['error']}")
            continue
        print(f"  {result['this_para_count']} параграфов, {result['total_duplicates']} дубликатов с другими главами")
        save_result(result, chapter_id)

        # Event
        with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "type": "chapter_coherence_in_book",
                "target": chapter_id,
                "payload": {"duplicates": result["total_duplicates"]},
            }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
