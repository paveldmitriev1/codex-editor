#!/usr/bin/env python3
"""
analyze_corpus.py — Слой A: локальный анализ всего корпуса (без API).

Что делает:
- Сканирует все .docx Pavel-а (исключая AI-батчи post-Friday)
- Извлекает текст (stdlib zipfile+xml)
- Считает стиль-метрики по правилам из chapters/.canon/voice/human-pavel-style.md
- Скорит каждый файл 0-100 «человечность»
- Маппит к каноническим главам (Книга III по canon.json, остальные по chapter-status.md)
- Ищет дубликаты (одинаковый контент в разных файлах)
- Пишет отчёт в Codex2/reports/overnight-style-scan.md

Запуск:
    python3 ~/Desktop/Codex2/scripts/analyze_corpus.py
    python3 ~/Desktop/Codex2/scripts/analyze_corpus.py --quick   # только первые 50 файлов
"""

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# ─── Пути ──────────────────────────────────────────────
HOME = Path.home()

# Корни для сканирования (только Pavel-оригиналы)
SCAN_ROOTS = [
    HOME / "Desktop/Codex/sources/01. КОДЕКСА ПО СОДЕРЖАНИЮ (СБОРКА ПО ТЕМЕ. ВСЕ МАТЕРИАЛЫ)",
    HOME / "Desktop/Codex/sources/originals-archive",
    HOME / "Desktop/Codex/sources/mushroom-bible-full",
    HOME / "Desktop/Codex/sources/я. СБОРКА ПО ТЕМАМ (рабочая)",
    HOME / "Desktop/Codex/sources/project-docs",
    HOME / "Desktop/Codex/sources/voice-extracts",
    HOME / "Desktop/Codex/sources/ustav-comparison",
    # Свежие распаковки из ~/Downloads (Mushroom Bible, Грибная Библия, и т.п.)
    HOME / "Desktop/Codex2/fresh-downloads",
]

# Маркеры что текст про Анти-Христа / Дракона — НЕ для Кодекса
OFF_TOPIC_MARKERS = {
    "антихрист": 5,    # каждое упоминание = 5 баллов off-topic
    "анти-христ": 5,
    "дракон": 2,       # драконы упоминаются и в Кодексе (Книга III), но мало
    "криста": 3,
    "кристон": 3,
    "спиритон": 3,
    "верховный жрец": 2,
}

# Маркеры что текст определённо Mushroom Bible / Codex
CODEX_MARKERS = [
    "великий дух грибов", "великий дух",
    "великие творцы", "творцы",
    "псилоцибин", "псилоциб",
    "микомистицизм", "мистицизм гриб",
    "хилингод",
    "святая грибная церковь",
    "грибная библия", "mushroom bible",
    "грибное послание",
]

# Жёсткий cutoff: pavel 2026-05-19, всё AI после 2026-05-15 — исключаем
CUTOFF_DATE = datetime(2026, 5, 15)

# Имена-маркеры AI-батчей которые ВСЕГДА исключаем
AI_PATTERNS = [
    r"\[overnight",
    r"\[polish",
    r"\[opus-direct",
    r"\[opus-max",
    r"\[weekend-opus",
    r"\[humanized",
    r"\[auto-write",
    r"\[critique-revised",
    r"\[draft 2026-05-1[5-9]",
    r"\[draft 2026-05-2",
    r"MASTER_BOOK_v",
    r"tom-autonomous-outputs",
    r"lessons-learned",
]

# Каноническое оглавление: Книга → главы (упрощённое для маппинга)
CANON_BOOKS = {
    "ustav": ("Устав и Принципы", ["устав", "право", "член", "проводник", "церемони", "финансов", "храмов", "продвижени", "этик"]),
    "prologue": ("Пролог. Призвание и Посвящение", ["пролог", "призвание", "посвящение", "введение", "предупрежден"]),
    "book-01": ("Книга I. Основы Микомистицизма", ["введение", "философи", "божественн", "псилоцибин", "проводник", "десятин", "возмездие", "основы"]),
    "book-02": ("Книга II. Священные Законы", ["закон", "возмездие", "санкци", "наказан"]),
    "book-03": ("Книга III. Невидимые Миры", ["сущности", "паразит", "одержим", "кровь", "хридайя", "сердце", "мыслеформ", "личинк", "родинк", "шаманск", "рабск", "бардо", "загробн", "невидим"]),
    "book-04": ("Книга IV. Болезни Духа", ["болезнь", "болезни", "исцеление", "истинная природа", "предательств", "энергетическ", "блокировк", "страх", "травм", "холистич", "диета", "питан"]),
    "book-05": ("Книга V. Грибной Экзорцизм", ["экзорцизм", "очищение", "бэд-трип", "приемы", "инструменты", "выгнать"]),
    "book-06": ("Книга VI. Священная Церемония", ["церемони", "ритуал", "сет", "сеттинг", "подготовка", "интеграция", "сан-педро"]),
    "book-07": ("Книга VII. Путь Целителя и Проводника", ["целитель", "проводник", "путь", "наставник", "учитель", "ученичеств"]),
    "book-08": ("Книга VIII. Мистицизм и Духовность", ["мистицизм", "духовность", "медитация", "молитва", "созерцани"]),
    "book-09": ("Книга IX. Практическое Применение", ["применение", "трансформ", "мир", "практик"]),
    "book-10": ("Книга X. Священное Выращивание и Алхимия", ["выращивание", "алхими", "субстрат", "грибниц", "мицели"]),
    "book-11": ("Книга XI. Предупреждения и Защита", ["предупрежден", "защита", "опасност", "осторожн", "риск"]),
    "book-12": ("Книга XII. Организационная Структура", ["организац", "структура", "управлени", "распределен"]),
    "epilogue": ("Эпилог", ["эпилог", "завершение", "новое начало"]),
    "appendices": ("Приложения", ["приложени"]),
}

# ─── Утилиты ──────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_ai_excluded(path: Path) -> bool:
    """Файл — AI-батч который исключаем?"""
    s = str(path)
    for pat in AI_PATTERNS:
        if re.search(pat, s):
            return True
    # Также проверяем mtime (защитная сеть)
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        # Только если файл в Codex/drafts или подобной AI-папке + после cutoff
        if mtime >= CUTOFF_DATE and "/drafts/" in s:
            return True
    except OSError:
        pass
    return False


def extract_docx_text(path: Path) -> str:
    """Вытащить текст из .docx stdlib (zipfile + regex). Грубо но работает."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    paras = re.findall(r"<w:p[^>]*>(.*?)</w:p>", xml, re.DOTALL)
    out = []
    for p in paras:
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
        text = text.strip()
        if text:
            out.append(text)
    return "\n\n".join(out)


def extract_text(path: Path) -> str:
    """Универсальный экстрактор по расширению."""
    if path.suffix.lower() == ".docx":
        return extract_docx_text(path)
    if path.suffix.lower() in (".md", ".txt"):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


# ─── Скоринг человеческого стиля ──────────────────────
SACRED_VOCAB = [
    "великий дух грибов", "великий дух", "великие творцы", "творцов", "творцы",
    "священн", "хилингод", "мицели", "грибов", "грибн",
    "проводник", "святая грибная церковь", "портал творцов",
    "великий перелом",
]

AI_CORP = [
    "важно отметить", "стоит подчеркнуть", "необходимо учесть", "следует понимать",
    "стоит сказать", "необходимо обратить внимание", "важно понимать",
    "следует помнить",
]

HEDGES = ["возможно", "пожалуй", "вероятно", "представляется", "как будто", "как бы"]


def score_human_style(text: str) -> dict:
    """Score 0-100 + метрики. См. правила в chapters/.canon/voice/human-pavel-style.md"""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    words = re.findall(r"\b[\wа-яА-ЯёЁ]+\b", text.lower())
    n_sent = len(sentences)
    n_words = len(words)

    if n_words < 20:
        return {"score": 0, "words": n_words, "sentences": n_sent, "empty": True}

    score = 50.0  # baseline
    flags = []

    # ─── Анти-AI ────────────────────────────────────
    # «является» — бюрократический регистр
    is_count = sum(1 for s in sentences if re.search(r"\bявляется|являются\b", s.lower()))
    if n_sent > 0:
        density = is_count / n_sent
        if density > 0.1:
            penalty = min(20, int(density * 100))
            score -= penalty
            flags.append(f"является×{is_count} ({int(density*100)}%)")

    # Пассивы «было сделано», «было явлено» и т.п.
    passive = len(re.findall(r"\bбыл[оаи]?\b\s+\w+", text.lower()))
    if passive > n_sent * 0.15:
        score -= min(15, passive // 3)
        flags.append(f"пассив×{passive}")

    # AI-corporatespeak
    corp_total = sum(text.lower().count(p) for p in AI_CORP)
    if corp_total > 0:
        score -= min(20, corp_total * 5)
        flags.append(f"ai-corp×{corp_total}")

    # Хеджи
    hedge_total = sum(re.findall(r"\b" + h + r"\b", text.lower()).__len__() for h in HEDGES)
    if hedge_total > 2:
        score -= min(10, hedge_total * 2)
        flags.append(f"хеджи×{hedge_total}")

    # Тире (в любом тексте Кодекса — должно быть 0)
    тире = text.count("—") + text.count("–")
    if тире > 0:
        score -= min(20, тире)
        flags.append(f"тире×{тире}")

    # «Не только X, но и Y» — контекст-зависимо, мягкий штраф
    not_only = len(re.findall(r"не только\b.{1,60}\bно и\b", text.lower()))
    if not_only > 2:
        score -= 5
        flags.append(f"не-только×{not_only}")

    # Контраст-пары «не X, а Y» (определение через противопоставление)
    contrast = len(re.findall(r"не\s+\w+,\s+а\s+\w+", text.lower()))
    if contrast > 1:
        score -= min(10, contrast * 3)
        flags.append(f"контраст×{contrast}")

    # Длина параграфов — однообразие = AI
    paras = [p for p in text.split("\n\n") if p.strip()]
    if len(paras) > 5:
        plens = [len(p.split()) for p in paras]
        avg_plen = sum(plens) / len(plens)
        var = sum((l - avg_plen) ** 2 for l in plens) / len(plens)
        cv = (var ** 0.5) / avg_plen if avg_plen > 0 else 0
        if cv < 0.3:
            score -= 12
            flags.append("параграфы однообразные")
        elif cv > 0.6:
            score += 5

    # ─── Pro-Pavel-human ──────────────────────────────
    # «есть» вместо «является» — биб­лей­ский регистр
    есть_count = sum(1 for s in sentences if re.search(r"\bесть\b", s.lower()))
    if есть_count > 0:
        score += min(10, есть_count)

    # Sacred vocabulary density
    sacred_total = sum(text.lower().count(w) for w in SACRED_VOCAB)
    density_per_1000 = sacred_total / max(1, n_words) * 1000
    if density_per_1000 > 5:
        score += min(15, int(density_per_1000 // 2))

    # Variance of sentence lengths (Pavel варьирует)
    if n_sent > 5:
        slens = [len(s.split()) for s in sentences]
        avg_slen = sum(slens) / len(slens)
        var = sum((l - avg_slen) ** 2 for l in slens) / len(slens)
        cv = (var ** 0.5) / avg_slen if avg_slen > 0 else 0
        if 0.4 <= cv <= 0.8:
            score += 8

    # Императивы в начале (команда → объяснение) — рудиментарно
    imperative_start = sum(1 for s in sentences if re.match(r"^(Читай|Помни|Открой|Войди|Прими|Сядь|Дай|Возьми)", s))
    if imperative_start > 0:
        score += min(5, imperative_start)

    score = max(0, min(100, score))

    return {
        "score": round(score, 1),
        "words": n_words,
        "sentences": n_sent,
        "paragraphs": len(paras),
        "avg_sent_len": round(n_words / n_sent, 1) if n_sent else 0,
        "is_count": is_count,
        "passive": passive,
        "тире": тире,
        "ai_corp": corp_total,
        "hedges": hedge_total,
        "есть": есть_count,
        "sacred_per_1000": round(density_per_1000, 1),
        "flags": flags,
    }


# ─── Тематический маппинг (% confidence) ────────────
def chapter_confidence(text: str, keywords: List[str]) -> float:
    """Возвращает 0-100% — насколько текст по теме главы."""
    text_lower = text.lower()
    n_words = max(1, len(re.findall(r"\b[\wа-яё]+\b", text_lower)))
    # Сколько раз каждое ключевое слово встретилось
    hit_counts = [text_lower.count(kw) for kw in keywords]
    total_hits = sum(hit_counts)
    unique_hits = sum(1 for h in hit_counts if h > 0)
    # Density per 1000 words (часто = сильнее)
    density = total_hits / n_words * 1000
    # Coverage: какая доля ключей сматчилась
    coverage = unique_hits / max(1, len(keywords))
    # Score 0-100
    density_part = min(50, density * 4)      # 12.5 density → 50 баллов
    coverage_part = coverage * 50            # 100% покрытие → 50 баллов
    return round(min(100, density_part + coverage_part), 1)


def is_codex_text(text: str, filename: str) -> Tuple[bool, int, int]:
    """(belongs_to_codex, codex_marker_count, offtopic_marker_count)"""
    text_lower = (filename + " " + text[:5000]).lower()
    codex_hits = sum(text_lower.count(m) for m in CODEX_MARKERS)
    offtopic_hits = sum(text_lower.count(m) * w for m, w in OFF_TOPIC_MARKERS.items())
    # Решающее: если off-topic-сигнал в 2+ раза сильнее codex-сигнала → не наше
    if offtopic_hits > codex_hits * 2 and offtopic_hits > 10:
        return False, codex_hits, offtopic_hits
    return True, codex_hits, offtopic_hits


def suggest_chapter(filename: str, text: str) -> List[Tuple[str, float]]:
    """Топ-3 каноничных главы с % confidence."""
    haystack = filename + " " + text[:5000]
    scores = []
    for book_id, (title, keywords) in CANON_BOOKS.items():
        conf = chapter_confidence(haystack, keywords)
        if conf > 0:
            scores.append((book_id, conf))
    scores.sort(key=lambda x: -x[1])
    return scores[:3]


def content_hash(text: str) -> str:
    """Hash первых 1500 нормализованных знаков для поиска дублей."""
    norm = re.sub(r"\s+", " ", text.lower())
    norm = re.sub(r"[^\wа-яё]", "", norm)
    return hashlib.md5(norm[:1500].encode("utf-8")).hexdigest()


# ─── Главный обход ────────────────────────────────────
def gather_files() -> List[Path]:
    files = []
    seen = set()
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".docx", ".md", ".txt"):
                continue
            if p.stat().st_size == 0:
                continue
            if p.name.startswith("."):
                continue
            if is_ai_excluded(p):
                continue
            # Уникализация: одинаковый name+size — дубль файловой системы
            key = (p.name, p.stat().st_size)
            if key in seen:
                continue
            seen.add(key)
            files.append(p)
    return files


def analyze_file(path: Path) -> Optional[dict]:
    text = extract_text(path)
    if not text or len(text) < 100:
        return None
    metrics = score_human_style(text)
    if metrics.get("empty"):
        return None
    chapters = suggest_chapter(path.name, text)
    is_codex, codex_hits, offtopic_hits = is_codex_text(text, path.name)
    # Категоризация
    top_conf = chapters[0][1] if chapters else 0
    if not is_codex:
        category = "off_topic"
    elif top_conf >= 60:
        category = "strong"            # уверенно ложится в главу
    elif top_conf >= 30:
        category = "recommended"       # подходит как доп. материал
    elif top_conf > 0:
        category = "weak"              # слабый намёк
    else:
        category = "unmapped"
    return {
        "path": str(path),
        "name": path.name,
        "rel": str(path.relative_to(HOME / "Desktop")),
        "size": path.stat().st_size,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "metrics": metrics,
        "chapters": chapters,
        "category": category,
        "codex_markers": codex_hits,
        "offtopic_markers": offtopic_hits,
        "hash": content_hash(text),
    }


# ─── Отчёт ────────────────────────────────────────────
def render_report(results: List[dict], started: str, finished: str) -> str:
    n = len(results)
    if not n:
        return "# Отчёт пуст — файлов не нашлось"

    scores = [r["metrics"]["score"] for r in results]
    avg_score = sum(scores) / n if scores else 0
    high = [r for r in results if r["metrics"]["score"] >= 80]
    mid = [r for r in results if 50 <= r["metrics"]["score"] < 80]
    low = [r for r in results if r["metrics"]["score"] < 50]

    # Дубликаты
    hash_groups = defaultdict(list)
    for r in results:
        hash_groups[r["hash"]].append(r)
    dups = {h: g for h, g in hash_groups.items() if len(g) > 1}

    # Группировка по главам (только Codex-релевантные)
    by_book = defaultdict(list)
    off_topic = []
    unmapped = []
    for r in results:
        if r["category"] == "off_topic":
            off_topic.append(r)
        elif r["chapters"]:
            top_book = r["chapters"][0][0]
            by_book[top_book].append(r)
        else:
            unmapped.append(r)
    # Сортировка внутри книги по убыванию confidence
    for items in by_book.values():
        items.sort(key=lambda r: -r["chapters"][0][1])

    out = []
    out.append(f"# Overnight Style Scan — {finished}")
    out.append("")
    out.append("**Источники:** только pre-Friday оригиналы Pavel-а (исключены 4649 AI-батчей post-2026-05-15)")
    out.append(f"**Старт:** {started} · **Финиш:** {finished}")
    out.append("")
    out.append("## Сводка")
    out.append("")
    out.append(f"- Файлов проанализировано: **{n}**")
    out.append(f"- Средний human-score: **{avg_score:.1f}/100**")
    out.append(f"- 🟢 Высокий (≥80, ближе к человеческому): **{len(high)}**")
    out.append(f"- 🟡 Средний (50-79, нужна правка): **{len(mid)}**")
    out.append(f"- 🔴 Низкий (<50, AI-перекос): **{len(low)}**")
    out.append(f"- 🗂 Групп дубликатов: **{len(dups)}** ({sum(len(g) for g in dups.values())} файлов)")
    out.append("")

    # ─── ТОП AI-перекос (главное для правки) ──────
    out.append("## 🔴 Топ-20 файлов с AI-перекосом (приоритет на правку)")
    out.append("")
    out.append("| Score | Файл | AI-маркеры |")
    out.append("|---|---|---|")
    low_sorted = sorted(low, key=lambda r: r["metrics"]["score"])[:20]
    for r in low_sorted:
        flags = ", ".join(r["metrics"].get("flags", []))[:80] or "—"
        name = r["name"][:60]
        out.append(f"| {r['metrics']['score']:.0f} | `{name}` | {flags} |")
    out.append("")

    # ─── ТОП человечных ───────────────────────────
    out.append("## 🟢 Топ-20 наиболее человечных (эталоны для humanizer)")
    out.append("")
    out.append("| Score | Файл |")
    out.append("|---|---|")
    high_sorted = sorted(high, key=lambda r: -r["metrics"]["score"])[:20]
    for r in high_sorted:
        out.append(f"| {r['metrics']['score']:.0f} | `{r['name'][:80]}` |")
    out.append("")

    # ─── По книгам ────────────────────────────────
    # Categories overview
    n_strong = sum(1 for r in results if r["category"] == "strong")
    n_recomm = sum(1 for r in results if r["category"] == "recommended")
    n_weak   = sum(1 for r in results if r["category"] == "weak")
    n_off    = len(off_topic)
    n_unmap  = len(unmapped)
    out.append("## Тематические корзины")
    out.append("")
    out.append(f"- 🎯 **Strong match (≥60%)** — уверенно идёт в главу: **{n_strong}**")
    out.append(f"- 💡 **Recommended (30-59%)** — подходит как доп. материал: **{n_recomm}**")
    out.append(f"- 🤏 **Weak match (1-29%)** — слабый намёк: **{n_weak}**")
    out.append(f"- 🚫 **Off-topic** (Дракон/Антихрист): **{n_off}**")
    out.append(f"- ❓ **Не сматчено к канону**: **{n_unmap}**")
    out.append("")

    out.append("## По книгам канона (с % совпадения)")
    out.append("")
    for book_id, (title, _) in CANON_BOOKS.items():
        items = by_book.get(book_id, [])
        if not items:
            continue
        strong = [r for r in items if r["category"] == "strong"]
        recomm = [r for r in items if r["category"] == "recommended"]
        weak = [r for r in items if r["category"] == "weak"]
        out.append(f"### {title}")
        out.append(f"_Всего {len(items)} файлов · 🎯 {len(strong)} strong · 💡 {len(recomm)} recommended · 🤏 {len(weak)} weak_")
        out.append("")
        if strong:
            out.append("**🎯 STRONG MATCH (готовы к работе):**")
            out.append("")
            out.append("| % | Human | Файл |")
            out.append("|---|---|---|")
            for r in strong[:20]:
                out.append(f"| **{r['chapters'][0][1]:.0f}%** | {r['metrics']['score']:.0f} | `{r['name'][:70]}` |")
            if len(strong) > 20:
                out.append(f"| | | … ещё {len(strong) - 20} файлов |")
            out.append("")
        if recomm:
            out.append("**💡 RECOMMENDED (доп. материал):**")
            out.append("")
            out.append("| % | Human | Файл |")
            out.append("|---|---|---|")
            for r in recomm[:15]:
                out.append(f"| {r['chapters'][0][1]:.0f}% | {r['metrics']['score']:.0f} | `{r['name'][:70]}` |")
            if len(recomm) > 15:
                out.append(f"| | | … ещё {len(recomm) - 15} |")
            out.append("")
        if weak and len(strong) + len(recomm) < 5:
            out.append("**🤏 Weak (на всякий случай):**")
            out.append("")
            for r in weak[:5]:
                out.append(f"- {r['chapters'][0][1]:.0f}% · `{r['name'][:70]}`")
            out.append("")

    # ─── Off-topic ─────────────────────────────────
    if off_topic:
        out.append(f"## 🚫 Off-topic — НЕ для Кодекса ({len(off_topic)} файлов)")
        out.append("")
        out.append("_Маркеры Анти-Христа / Дракона / Кристы / Кристона. Сохранить отдельно как материал для других книг Pavel-а._")
        out.append("")
        for r in sorted(off_topic, key=lambda r: -r["offtopic_markers"])[:30]:
            out.append(f"- ({r['offtopic_markers']} off-topic-маркеров) `{r['name']}`")
        if len(off_topic) > 30:
            out.append(f"- … ещё {len(off_topic) - 30}")
        out.append("")

    # ─── Не сматчено ──────────────────────────────
    if unmapped:
        out.append(f"## ❓ Не сматчены ни к одной книге ({len(unmapped)} файлов)")
        out.append("")
        for r in unmapped[:30]:
            out.append(f"- `{r['name']}` (score {r['metrics']['score']:.0f}, {r['metrics']['words']} слов)")
        if len(unmapped) > 30:
            out.append(f"- … ещё {len(unmapped) - 30}")
        out.append("")

    # ─── Дубликаты ─────────────────────────────────
    if dups:
        out.append("## 🗂 Группы дубликатов (один и тот же контент в разных файлах)")
        out.append("")
        for i, (h, group) in enumerate(sorted(dups.items(), key=lambda x: -len(x[1]))[:15], 1):
            out.append(f"### Группа {i} — {len(group)} копий")
            for r in group:
                out.append(f"- `{r['rel']}` · score {r['metrics']['score']:.0f} · {r['metrics']['words']} слов")
            out.append("")

    return "\n".join(out)


# ─── Main ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="Только первые 50 файлов (для теста)")
    args = ap.parse_args()

    started = now_iso()
    print(f"⌚ Старт: {started}")

    files = gather_files()
    if args.quick:
        files = files[:50]
    print(f"📁 К анализу: {len(files)} файлов")

    results = []
    for i, p in enumerate(files):
        if i % 25 == 0:
            print(f"  [{i}/{len(files)}] {p.name[:60]}")
        try:
            r = analyze_file(p)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  ✗ {p.name}: {e}")

    finished = now_iso()
    print(f"✓ Обработано: {len(results)} файлов")

    # Сохранить JSON
    out_dir = HOME / "Desktop/Codex2/reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "overnight-style-scan.json").write_text(
        json.dumps({
            "started": started,
            "finished": finished,
            "results": results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Сохранить Markdown отчёт
    md = render_report(results, started, finished)
    (out_dir / "overnight-style-scan.md").write_text(md, encoding="utf-8")
    print(f"✓ Отчёт: {out_dir / 'overnight-style-scan.md'}")
    print(f"✓ JSON:  {out_dir / 'overnight-style-scan.json'}")

    # Событие
    events = HOME / "Desktop/Codex2/.codex/events.jsonl"
    events.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": finished,
        "type": "corpus_analysis",
        "target": "all-pre-friday-sources",
        "payload": {
            "files_analyzed": len(results),
            "avg_score": round(sum(r["metrics"]["score"] for r in results) / max(1, len(results)), 1),
            "high": sum(1 for r in results if r["metrics"]["score"] >= 80),
            "low": sum(1 for r in results if r["metrics"]["score"] < 50),
            "report": "reports/overnight-style-scan.md",
        },
    }
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
