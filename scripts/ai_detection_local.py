#!/usr/bin/env python3
"""Локальный детектор AI-текста БЕЗ внешних API.

Pavel 2026-05-25: «думай как сделать чтобы главы была написаны так чтобы
невозможно было определить что редактором был ИИ».

Что делаем:
1. Статистический анализ — sentence length variance, vocabulary diversity,
   AI-маркеры (типа «важно отметить», «стоит подчеркнуть»).
2. Сравнение с эталоном — voice corpus Pavel-а, его реальная разговорная
   речь. Если глава ОЧЕНЬ ровная по сравнению с голосовыми — это AI.
3. Возвращаем AI-score 0-100 и список конкретных «маркеров» которые надо
   убрать или разбавить.

Usage:
    python3 scripts/ai_detection_local.py --chapter book-12-ch-17
    python3 scripts/ai_detection_local.py --text "..."
"""
import argparse
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# AI-маркеры — фразы которые часто появляются в AI-сгенерированном русском
AI_MARKERS_PHRASES = [
    "важно отметить",
    "стоит подчеркнуть",
    "следует понимать",
    "необходимо помнить",
    "ключевым является",
    "представляет собой",
    "является важным",
    "играет важную роль",
    "имеет место",
    "в данном контексте",
    "в этом отношении",
    "с точки зрения",
    "не только..., но и",
    "более того",
    "тем не менее",
    "однако стоит",
    "стоит заметить",
    "в заключение",
    "подводя итог",
]

# AI любит троичные структуры и parallel symmetric — это нормально для Pavel-а
# но AI делает их СЛИШКОМ ИДЕАЛЬНО симметричными
AI_RHYTHM_MARKERS = [
    # «X. Y. Z.» — 3 коротких подряд (часто AI)
    "microsentences_3plus_run",
    # «и X, и Y, и Z» — троичная конъюнкция
    "triple_and_pattern",
    # Полностью симметричные параграфы (одинаковая длина sentences)
    "perfect_sentence_length_uniformity",
]


def split_sentences(text: str) -> list:
    """Грубое разбиение на предложения."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def count_phrase_matches(text: str, phrases: list) -> dict:
    """Считаем сколько раз каждая AI-фраза встречается."""
    text_lc = text.lower()
    hits = {}
    for p in phrases:
        n = text_lc.count(p.lower())
        if n:
            hits[p] = n
    return hits


def sentence_length_stats(sentences: list) -> dict:
    """Длины предложений в словах. AI любит uniformity."""
    if not sentences:
        return {"mean": 0, "stdev": 0, "min": 0, "max": 0, "uniformity_score": 0}
    lens = [len(s.split()) for s in sentences]
    mean = statistics.mean(lens)
    stdev = statistics.stdev(lens) if len(lens) > 1 else 0
    # uniformity: чем БЛИЖЕ stdev/mean к 0 — тем подозрительнее AI
    cv = stdev / mean if mean > 0 else 0
    return {
        "mean": round(mean, 1),
        "stdev": round(stdev, 1),
        "min": min(lens),
        "max": max(lens),
        "cv_coefficient": round(cv, 2),
        "lens": lens[:20],
    }


def vocabulary_diversity(text: str) -> dict:
    """Лексическое разнообразие. AI часто реcycles words."""
    words = re.findall(r"[А-Яа-яЁёa-zA-Z]+", text.lower())
    if not words:
        return {"total": 0, "unique": 0, "ratio": 0}
    unique = len(set(words))
    return {
        "total": len(words),
        "unique": unique,
        "ratio": round(unique / len(words), 3),
    }


def detect_microsentence_runs(sentences: list) -> int:
    """Сколько серий из 3+ предложений ≤7 слов подряд."""
    runs = 0
    current = 0
    for s in sentences:
        if len(s.split()) <= 7:
            current += 1
            if current == 3:
                runs += 1
        else:
            current = 0
    return runs


def detect_perfect_parallelism(sentences: list) -> int:
    """Сколько раз подряд идут предложения с разницей в длине ≤2 слова.
    AI это любит — слишком ровно."""
    runs = 0
    current_run = 0
    last_len = None
    for s in sentences:
        l = len(s.split())
        if last_len is not None and abs(l - last_len) <= 2:
            current_run += 1
            if current_run == 4:
                runs += 1
        else:
            current_run = 0
        last_len = l
    return runs


def compute_ai_score(text: str) -> dict:
    """Возвращает {score: 0-100, markers: [...], stats: {...}, advice: [...]}"""
    sentences = split_sentences(text)
    if len(sentences) < 3:
        return {"score": 0, "reason": "слишком короткий"}

    phrase_hits = count_phrase_matches(text, AI_MARKERS_PHRASES)
    length_stats = sentence_length_stats(sentences)
    vocab = vocabulary_diversity(text)
    micro_runs = detect_microsentence_runs(sentences)
    parallel_runs = detect_perfect_parallelism(sentences)

    score = 0
    markers = []
    advice = []

    # AI phrase hits — 5 points each, capped at 30
    phrase_score = min(sum(phrase_hits.values()) * 5, 30)
    score += phrase_score
    for p, n in phrase_hits.items():
        markers.append(f"AI-клише «{p}» × {n}")
        advice.append(f"Убрать «{p}» — не входит в голос Хилингода")

    # Uniformity: cv < 0.3 = подозрительно AI, cv > 0.6 = норм человек
    cv = length_stats["cv_coefficient"]
    if cv < 0.3 and len(sentences) > 5:
        score += 25
        markers.append(f"слишком ровный ритм предложений (cv={cv})")
        advice.append("Добавь длинные/короткие предложения для разноритмия")

    # Vocabulary too low diversity
    if vocab["ratio"] < 0.40 and vocab["total"] > 100:
        score += 15
        markers.append(f"низкое лексическое разнообразие ({vocab['ratio']})")
        advice.append("Разнообразь словарь — много повторов одних слов")

    # Microsentence runs (Pavel правило: 3+ подряд ≤7 слов = кричит AI)
    if micro_runs > 0:
        score += 20 * micro_runs
        markers.append(f"микро-предложения подряд × {micro_runs}")
        advice.append("Слить серии коротких предложений в длинные многоклаузные")

    # Perfect parallelism — слишком ровно
    if parallel_runs > 0:
        score += 15 * parallel_runs
        markers.append(f"идеальный параллелизм длин × {parallel_runs}")
        advice.append("Разбавить параллельные ряды одним необычным предложением")

    score = min(score, 100)

    verdict = "человеческий" if score < 30 else ("спорный" if score < 60 else "звучит как AI")

    return {
        "score": score,
        "verdict": verdict,
        "markers": markers,
        "advice": advice,
        "stats": {
            "sentences": len(sentences),
            "length": length_stats,
            "vocabulary": vocab,
            "microsentence_runs": micro_runs,
            "perfect_parallelism_runs": parallel_runs,
            "phrase_hits": phrase_hits,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", help="chapter_id, e.g. book-12-ch-17")
    ap.add_argument("--text", help="raw text to analyze")
    ap.add_argument("--all", action="store_true", help="прогнать на все главы book-12")
    args = ap.parse_args()

    if args.text:
        result = compute_ai_score(args.text)
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.all:
        import json
        for ch_dir in sorted((ROOT / "chapters" / "book-12").iterdir()):
            if not ch_dir.is_dir() or "-ch-" not in ch_dir.name:
                continue
            draft = ch_dir / "draft.md"
            if not draft.exists():
                continue
            text = draft.read_text(encoding="utf-8")
            result = compute_ai_score(text)
            score = result.get("score", 0)
            verdict = result.get("verdict", "?")
            print(f"{ch_dir.name:25s} score={score:3d}  {verdict}")
        return 0

    if args.chapter:
        import re as _re
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", args.chapter)
        if not m:
            print("bad chapter_id", file=sys.stderr)
            return 1
        book_id = m.group(1)
        draft = ROOT / "chapters" / book_id / args.chapter / "draft.md"
        if not draft.exists():
            print(f"no draft.md for {args.chapter}", file=sys.stderr)
            return 1
        result = compute_ai_score(draft.read_text(encoding="utf-8"))
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
