#!/usr/bin/env python3
"""
text_analyzer.py — 10-параметровый coach-режим анализа текста.

Pavel: «прогоняет текст и даёт рекомендации как коуч».

Каждый параметр 0-100 + coach-комментарий. Финальный score = средний.
Никаких API — чистый Python + регексы. Дёшево, быстро, детерминированно.

Использование:
    from text_analyzer import analyze
    result = analyze(text)
    # {'score': 67, 'params': {1: {...}, 2: {...}}, 'coach_summary': '...'}

Запуск из CLI:
    python3 text_analyzer.py path/to/file.md
    python3 text_analyzer.py path/to/file.docx
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, List


# ─── 70 готовых русских AI-маркеров (из humanizer-ru + vc.ru, см. research-отчёт) ─
AI_MARKERS_RU = {
    # AI-corporatespeak (vc.ru топ-10 + humanizer-ru)
    "важно отметить", "стоит подчеркнуть", "необходимо учесть", "следует понимать",
    "важно понимать", "стоит сказать", "необходимо обратить внимание",
    "следует помнить", "важно подчеркнуть", "необходимо отметить",
    "стоит заметить", "следует обратить внимание", "важно знать",

    # Шаблонные заходы абзацев
    "представьте себе", "задумайтесь над", "обратите внимание",
    "давайте рассмотрим", "стоит задуматься", "следует задуматься",

    # Псевдо-связки
    "более того", "тем не менее", "однако стоит", "при этом необходимо",
    "вместе с тем", "вместе с этим", "наряду с этим", "вместе они",
    "что касается", "в этом контексте", "в данном контексте",

    # AI-определения
    "это не просто", "это не только", "является не просто", "представляет собой",
    "является ключевым", "играет важную роль", "имеет огромное значение",

    # Бюрократические глаголы
    "осуществляется", "осуществляет", "осуществлять", "осуществление",
    "реализуется", "реализует", "реализация",

    # AI-абстракции
    "духовный потенциал", "энергетический баланс", "глубинное понимание",
    "истинное предназначение", "сакральное измерение",

    # Метаистория-AI
    "на протяжении веков", "на протяжении тысячелетий", "испокон веков",
    "с незапамятных времён", "с древнейших времён",
}

# Хеджи
HEDGES_RU = {"возможно", "пожалуй", "вероятно", "представляется", "как будто",
             "как бы", "вроде бы", "по-видимому", "возможно даже", "наверное"}

# Доктринальный словарь (присутствие — pro-Pavel)
SACRED_VOCAB = [
    "великий дух грибов", "великий дух", "великие творцы", "творцов", "творцы",
    "священн", "хилингод", "мицели", "грибов", "грибн",
    "проводник", "святая грибная церковь", "портал творцов",
    "великий перелом", "сан педро", "псилоцибин", "псилоциб",
]

# Vata words (резать)
VATA_WORDS = {"личная", "всего сущего", "именно здесь", "по сути", "в принципе",
              "как таковой", "как такового", "в общем-то", "собственно говоря"}

# Modal particles (русская разговорность — pro-human)
MODAL_PARTICLES = {"же", "ведь", "вот", "ну", "так уж", "уж"}

# Императивы для front-loading проверки
IMPERATIVE_STARTS = re.compile(
    r"^(Читай|Помни|Открой|Войди|Прими|Сядь|Дай|Возьми|Слушай|Молчи|Учись|Не отвлекайся|Иди|Стой|Дыши|Знай|Видь)",
)

# Temporal anchors для front-loading
TEMPORAL_ANCHORS = re.compile(
    r"^(Именно сейчас|Здесь|В этот час|В эту эпоху|Сегодня|Когда|Тогда|Сейчас|В наш час|Прямо сейчас)",
)


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def split_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\wа-яёА-ЯЁ]+\b", text))


# ─── 10 параметров ──────────────────────────────────
def param_1_pavel_voice(text: str) -> dict:
    """«есть» vs «является», активный/пассивный, biblical."""
    sents = split_sentences(text)
    n = max(1, len(sents))
    text_low = text.lower()
    есть_cnt = sum(1 for s in sents if re.search(r"\bесть\b", s.lower()))
    является_cnt = sum(1 for s in sents if re.search(r"\bявляется|являются\b", s.lower()))
    passive_cnt = len(re.findall(r"\bбыл[оаи]?\b\s+\w+", text_low))
    ratio_есть = есть_cnt / n
    ratio_являет = являет_cnt = является_cnt / n
    score = 50 + min(30, есть_cnt * 3) - min(30, является_cnt * 5) - min(15, passive_cnt // 3)
    score = max(0, min(100, score))
    coach = []
    if является_cnt > 2:
        coach.append(f"⚠ «является» × {является_cnt} — биб­лей­ское «есть» сильнее")
    if passive_cnt > n * 0.2:
        coach.append(f"⚠ Пассивы «было сделано» × {passive_cnt} — активные глаголы")
    if есть_cnt < 1 and n > 5:
        coach.append("💡 Нет «есть» — добавь сакральный регистр Бога к Моисею")
    return {"score": score, "name": "Голос Pavel-а (есть/активный/biblical)",
            "есть": есть_cnt, "является": является_cnt, "passive": passive_cnt,
            "coach": coach}


def param_2_front_loading(text: str) -> dict:
    """Temporal anchor в начало предложения."""
    sents = split_sentences(text)
    if not sents:
        return {"score": 50, "name": "Front-loading", "coach": ["(текст пуст)"]}
    n = len(sents)
    front = sum(1 for s in sents if TEMPORAL_ANCHORS.match(s))
    # Проверка анти-паттерна: temporal в середине
    buried = len(re.findall(r"[^.!?][^.!?]*?\b(именно сейчас|в эту эпоху|здесь и сейчас)\b",
                            text.lower()))
    score = 50 + min(30, front * 8) - min(25, buried * 5)
    score = max(0, min(100, score))
    coach = []
    if front == 0 and n > 5:
        coach.append("💡 Ни одного temporal anchor в начале — Pavel ставит «Именно сейчас» спереди")
    if buried > 0:
        coach.append(f"⚠ Temporal anchor закопан в {buried} местах — вынеси в начало предложения")
    return {"score": score, "name": "Front-loading", "front": front, "buried": buried,
            "coach": coach}


def param_3_command_first(text: str) -> dict:
    """Команда (императив) перед объяснением."""
    paras = split_paragraphs(text)
    imperative_paras = 0
    explanation_paras = 0
    for p in paras:
        first = p.split(".")[0]
        if IMPERATIVE_STARTS.match(first):
            imperative_paras += 1
        elif first.startswith(("Пусть каждый", "Каждый кто", "Тот кто", "Любой кто", "Всякий кто")):
            explanation_paras += 1
    score = 50 + min(30, imperative_paras * 5) - min(25, explanation_paras * 5)
    score = max(0, min(100, score))
    coach = []
    if explanation_paras > imperative_paras:
        coach.append(f"⚠ «Пусть каждый кто...» × {explanation_paras} — команда «Читай», «Войди» сильнее")
    return {"score": score, "name": "Команда → объяснение",
            "imperative": imperative_paras, "explanation_lead": explanation_paras,
            "coach": coach}


def param_4_vata(text: str) -> dict:
    """Вата-слова: 'личная', 'всего сущего', 'именно здесь' и т.п."""
    text_low = text.lower()
    hits = []
    for w in VATA_WORDS:
        c = text_low.count(w)
        if c > 0:
            hits.append((w, c))
    total = sum(c for _, c in hits)
    score = 100 - min(60, total * 8)
    coach = []
    if hits:
        top = sorted(hits, key=lambda x: -x[1])[:3]
        coach.append(f"⚠ Вата: {', '.join(f'«{w}»×{c}' for w, c in top)} — резать")
    return {"score": score, "name": "Вата (лишние квалификаторы)",
            "vata_hits": dict(hits), "total": total, "coach": coach}


def param_5_ai_tells(text: str) -> dict:
    """Контраст-пары + «не только X, но и Y» (мягко, контекст важен)."""
    text_low = text.lower()
    contrast = len(re.findall(r"не\s+\w+,\s+а\s+\w+", text_low))
    not_only = len(re.findall(r"не только\b.{1,60}\bно и\b", text_low))
    # Жёстче: цепочка «не X и не Y, а Z»
    chain = len(re.findall(r"не\s+\w+\s+и\s+не\s+\w+,\s+а\s+\w+", text_low))
    score = 100 - min(50, contrast * 5) - min(20, not_only * 2) - min(30, chain * 10)
    score = max(0, min(100, score))
    coach = []
    if chain > 0:
        coach.append(f"⚠⚠ Контраст-цепочка «не X и не Y, а Z» × {chain} — жёсткий AI-tell, переписать")
    if contrast > 2:
        coach.append(f"⚠ Контраст-пары «не X, а Y» × {contrast} — Pavel определяет напрямую, не через противопоставление")
    if not_only > 3:
        coach.append(f"💡 «не только X, но и Y» × {not_only} — ОК если эскалирует масштаб, AI-tell если защита")
    return {"score": score, "name": "AI-tells (контраст-пары)",
            "contrast": contrast, "not_only": not_only, "chain": chain,
            "coach": coach}


def param_6_тире(text: str) -> dict:
    """Тире (—) — абсолютный 0 в тексте Кодекса."""
    тире_cnt = text.count("—") + text.count("–")
    score = 100 if тире_cnt == 0 else max(0, 100 - тире_cnt * 5)
    coach = []
    if тире_cnt > 0:
        coach.append(f"🚨 Тире × {тире_cnt} — в Кодексе ЗАПРЕЩЕНЫ. Заменить точкой, запятой или причастием.")
    return {"score": score, "name": "Тире (запрещены)", "тире": тире_cnt, "coach": coach}


def param_7_ai_corp(text: str) -> dict:
    """AI-corporatespeak: 70 готовых маркеров."""
    text_low = text.lower()
    hits = []
    for m in AI_MARKERS_RU:
        c = text_low.count(m)
        if c > 0:
            hits.append((m, c))
    total = sum(c for _, c in hits)
    score = 100 - min(70, total * 6)
    score = max(0, min(100, score))
    coach = []
    if hits:
        top = sorted(hits, key=lambda x: -x[1])[:5]
        coach.append(f"⚠ AI-маркеры: {', '.join(f'«{m}»×{c}' for m, c in top)}")
    return {"score": score, "name": "AI-corp (70 маркеров)",
            "top_hits": dict(top) if hits else {}, "total": total, "coach": coach}


def param_8_doctrinal(text: str) -> dict:
    """Плотность сакрального словаря. Sweet spot для священного текста: 10-80 на 1000."""
    text_low = text.lower()
    n_words = max(1, count_words(text))
    total_hits = sum(text_low.count(w) for w in SACRED_VOCAB)
    per_1000 = total_hits / n_words * 1000
    # Калибровано под жанр священного писания: Pavel-преамбула = 53.7/1000 — это ОК
    if per_1000 < 2:
        score = 20 + per_1000 * 10
    elif per_1000 < 10:
        score = 50 + per_1000 * 4    # 10 → 90
    elif per_1000 <= 80:
        score = 100                   # sweet spot
    else:
        score = max(60, 100 - (per_1000 - 80) * 0.5)  # очень плотно — слегка снижаем
    coach = []
    if per_1000 < 2:
        coach.append(f"⚠ Сакральный словарь редок ({per_1000:.1f}/1000) — где Великий Дух, Творцы, Хилингод?")
    elif per_1000 > 100:
        coach.append(f"💡 Сакральных слов очень плотно ({per_1000:.1f}/1000) — нормально для центральных моментов, но рассмотри разбавление")
    return {"score": score, "name": "Доктринальный словарь",
            "per_1000_words": round(per_1000, 1), "total": total_hits, "coach": coach}


def param_9_rhythm(text: str) -> dict:
    """Burstiness — вариация длины. AI пишет однообразно."""
    sents = split_sentences(text)
    paras = split_paragraphs(text)
    if len(sents) < 5:
        return {"score": 50, "name": "Ритм (burstiness)", "coach": ["(текст короткий)"]}
    slens = [len(s.split()) for s in sents]
    plens = [len(p.split()) for p in paras] if paras else [0]
    avg_s = sum(slens) / len(slens)
    var_s = sum((l - avg_s) ** 2 for l in slens) / len(slens)
    cv_s = (var_s ** 0.5) / avg_s if avg_s > 0 else 0
    avg_p = sum(plens) / max(1, len(plens))
    var_p = sum((l - avg_p) ** 2 for l in plens) / max(1, len(plens))
    cv_p = (var_p ** 0.5) / avg_p if avg_p > 0 else 0
    # Sweet spot CV: 0.4-0.8 (живая речь). <0.3 = AI, >1 = хаос.
    score_s = 100 if 0.4 <= cv_s <= 0.8 else (60 if 0.3 <= cv_s < 0.4 or 0.8 < cv_s <= 1.0 else 30)
    score_p = 100 if 0.4 <= cv_p <= 0.8 else (60 if 0.3 <= cv_p < 0.4 or 0.8 < cv_p <= 1.0 else 30)
    score = (score_s + score_p) / 2
    coach = []
    if cv_s < 0.3:
        coach.append(f"⚠ Длина предложений однообразная (CV {cv_s:.2f}) — варьируй: короткое, длинное, среднее")
    if cv_p < 0.3:
        coach.append(f"⚠ Абзацы одинаковые (CV {cv_p:.2f}) — режь длинные, расширяй важные")
    return {"score": score, "name": "Ритм (burstiness)",
            "cv_sentences": round(cv_s, 2), "cv_paragraphs": round(cv_p, 2),
            "avg_sentence_words": round(avg_s, 1), "coach": coach}


def param_10_modal_particles(text: str) -> dict:
    """Modal particles («же», «ведь», «вот»). Для священного писания нейтрально, для речевых вставок — bonus."""
    text_low = text.lower()
    counts = {p: len(re.findall(r"\b" + p + r"\b", text_low)) for p in MODAL_PARTICLES}
    total = sum(counts.values())
    n_words = max(1, count_words(text))
    per_1000 = total / n_words * 1000
    # Священный текст по умолчанию формальный → отсутствие нейтрально (70), наличие — bonus
    if per_1000 == 0:
        score = 70   # нейтрально для формального жанра
    elif per_1000 < 2:
        score = 80
    elif 2 <= per_1000 <= 12:
        score = 100  # живые вставки
    else:
        score = max(70, 100 - (per_1000 - 12) * 2)  # слишком много — разговорно
    coach = []
    if per_1000 > 12:
        coach.append(f"💡 Modal particles очень плотно ({per_1000:.1f}/1000) — текст уходит в разговорный регистр")
    elif per_1000 == 0 and n_words > 200:
        coach.append("💡 Нет «же/ведь/вот» — для священного текста ОК; для живых вставок добавил бы")
    return {"score": score, "name": "Modal particles (же/ведь/вот)",
            "per_1000_words": round(per_1000, 1), "counts": counts, "coach": coach}


# ─── Главная функция ────────────────────────────────
PARAMS = [
    param_1_pavel_voice,
    param_2_front_loading,
    param_3_command_first,
    param_4_vata,
    param_5_ai_tells,
    param_6_тире,
    param_7_ai_corp,
    param_8_doctrinal,
    param_9_rhythm,
    param_10_modal_particles,
]


def analyze(text: str) -> dict:
    """Возвращает все 10 параметров + overall score + summary coach-комментарий."""
    if len(text.strip()) < 50:
        return {"score": 0, "error": "слишком короткий текст"}

    results = {}
    all_coach = []
    for i, fn in enumerate(PARAMS, 1):
        try:
            r = fn(text)
            results[i] = r
            for c in r.get("coach", []):
                all_coach.append((r["score"], i, r["name"], c))
        except Exception as e:
            results[i] = {"score": 50, "name": fn.__name__, "error": str(e), "coach": []}

    avg = round(sum(r["score"] for r in results.values()) / len(results), 1)

    # Coach summary: топ-3 самых низких + 2 положительных
    all_coach.sort()  # сначала самые низкие
    crit = [c for c in all_coach if "⚠" in c[3] or "🚨" in c[3]][:5]
    encour = []
    for i, r in results.items():
        if r["score"] >= 80:
            encour.append((i, r["name"], r["score"]))

    summary = f"## 🎯 Overall score: **{avg}/100**\n\n"
    if crit:
        summary += "### Что улучшить (приоритет ↓)\n"
        for s, i, name, c in crit:
            summary += f"- **#{i} {name}** (score {s:.0f}): {c}\n"
    if encour:
        summary += "\n### Что уже хорошо\n"
        for i, name, s in encour[:3]:
            summary += f"- **#{i} {name}**: {s:.0f}/100 ✓\n"

    return {
        "score": avg,
        "params": results,
        "summary": summary,
        "words": count_words(text),
        "sentences": len(split_sentences(text)),
        "paragraphs": len(split_paragraphs(text)),
    }


def render_markdown_report(result: dict, source_name: str = "(текст)") -> str:
    out = [
        f"# Text Analyzer — {source_name}",
        "",
        f"**Слов:** {result.get('words')} · **Предложений:** {result.get('sentences')} · **Параграфов:** {result.get('paragraphs')}",
        "",
        result["summary"],
        "",
        "## Подробно по параметрам",
        "",
        "| # | Параметр | Score |",
        "|---|---|---|",
    ]
    for i, r in result["params"].items():
        out.append(f"| {i} | {r['name']} | **{r['score']:.0f}/100** |")
    out.append("")
    out.append("## Coach-комментарии")
    out.append("")
    for i, r in result["params"].items():
        if r.get("coach"):
            out.append(f"### #{i} · {r['name']} ({r['score']:.0f}/100)")
            for c in r["coach"]:
                out.append(f"- {c}")
            out.append("")
    return "\n".join(out)


def _extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    paras = re.findall(r"<w:p[^>]*>(.*?)</w:p>", xml, re.DOTALL)
    out = []
    for p in paras:
        t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
        if t:
            out.append(t)
    return "\n\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Путь к .md, .txt или .docx")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    p = Path(args.path)
    if p.suffix.lower() == ".docx":
        text = _extract_docx(p)
    else:
        text = p.read_text(encoding="utf-8")

    result = analyze(text)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_markdown_report(result, p.name))


if __name__ == "__main__":
    main()
