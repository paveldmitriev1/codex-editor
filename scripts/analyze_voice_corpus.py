#!/usr/bin/env python3
"""
analyze_voice_corpus.py — тематическая карта всех 546 voice-conversations.

Локально (без API):
- Для каждого .md в voice-corpus/raw/: размер, длина Pavel-сообщений, плотность доктринального словаря
- Mapping к каноническим главам по ключевым словам (как в analyze_corpus.py + дополнения для Книги)
- Кластеризация по темам
- Выявление «больших monologue-сессий» (длинные сообщения = надиктовки в потоке)
- Сводный отчёт voice-corpus/THEMATIC-MAP.md

Запуск:
    python3 analyze_voice_corpus.py
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
CORPUS = V2 / "voice-corpus/raw"
OUT = V2 / "voice-corpus"

# Канонические темы → keywords (slug-friendly, lowercase)
CHAPTER_KEYWORDS = {
    "Пролог. Призвание и Посвящение": ["призвание", "посвящение", "пробуждение", "предупреждение", "введение", "первое касание", "встреча с грибами"],
    "Устав и Принципы": ["устав", "право", "член", "проводник", "финансов", "храм", "этик", "регламент", "категори"],
    "Книга I. Основы Микомистицизма": ["введение в микомистицизм", "философия микомистицизма", "псилоцибин", "божественная связь", "творц", "десятин", "возмездие", "проводник", "основы"],
    "Книга II. Священные Законы и Возмездие": ["священный закон", "возмездие", "санкци", "наказан", "закон гриб", "договор", "клятва"],
    "Книга III. Невидимые Миры": ["сущност", "паразит", "одержим", "кровь как проводник", "хридайя", "сердце как центр", "мыслеформ", "личинк", "родинк", "шаманск", "рабск", "невидим", "астральн", "демон"],
    "Книга IV. Болезни Духа и Исцеление": ["болезнь духа", "истинная природа болезни", "предательство", "энергетическ блокиров", "страх", "травм", "холистич", "диета", "питан", "исцелен"],
    "Книга V. Грибной Экзорцизм": ["экзорцизм", "бэд-трип", "очищен", "выгнать", "ритуал изгнан", "техник изгнан"],
    "Книга VI. Священная Церемония": ["церемони", "ритуал церемон", "сет", "сеттинг", "подготовка к церемон", "интеграц", "сан-педро", "пятая стихи"],
    "Книга VII. Путь Целителя и Проводника": ["целитель", "проводник", "наставник", "учитель", "ученичеств", "уровни проводника", "роль провод"],
    "Книга VIII. Мистицизм и Духовность": ["мистицизм", "духовность", "медитац", "молитв", "созерцан", "духовные практ", "святая грибная церковь"],
    "Книга IX. Практическое Применение": ["применение", "трансформация мира", "практик", "повседневн", "мирские дела", "семья", "работа", "отношения"],
    "Книга X. Священное Выращивание и Алхимия": ["выращиван", "алхими", "субстрат", "грибниц", "мицели", "хранен", "сушка", "приготовлен"],
    "Книга XI. Предупреждения и Защита": ["предупрежден", "защита", "опасност", "осторожн", "риск", "ошибки", "ловушк"],
    "Книга XII. Организационная Структура": ["организац", "структура", "управлени", "распределен финансов", "иерархи", "сообщество"],
    "Эпилог. Завершение Обучения": ["эпилог", "завершен обучения", "новое начало", "финал", "прощан", "что дальше"],
    "Приложения": ["приложен", "глоссари", "термин", "индекс", "ссылки"],
}

# Доктринальный словарь (присутствие = pro-Pavel sacred register)
SACRED_VOCAB = [
    "великий дух грибов", "великий дух", "великие творцы", "творц",
    "хилингод", "микомистицизм", "псилоцибин", "псилоциб",
    "святая грибная церковь", "грибная церковь", "грибной",
    "сан педро", "мицели", "проводник", "церемони",
    "великий перелом", "портал творцов",
]


def parse_pavel_messages(md_path: Path) -> list:
    """Распарсить .md файл — вернуть список Pavel-сообщений (только text)."""
    text = md_path.read_text(encoding="utf-8")
    # Разделители: «### Message N · timestamp»
    parts = re.split(r"^### Message \d+ · ", text, flags=re.MULTILINE)
    messages = []
    for p in parts[1:]:  # 0-й — это шапка
        # Убрать timestamp в первой строке + ---
        lines = p.split("\n")
        if not lines:
            continue
        body = "\n".join(lines[1:])  # skip timestamp line
        body = re.sub(r"---$", "", body, flags=re.MULTILINE).strip()
        if body:
            messages.append(body)
    return messages


def map_chapters(text: str, conv_name: str = "") -> list:
    """Вернуть [(chapter, score)] — топ-3."""
    hay = (conv_name + " " + text[:8000]).lower()
    scores = []
    for ch, kws in CHAPTER_KEYWORDS.items():
        s = sum(hay.count(kw) for kw in kws)
        if s > 0:
            scores.append((ch, s))
    scores.sort(key=lambda x: -x[1])
    return scores[:3]


def sacred_density(text: str) -> float:
    n_words = max(1, len(re.findall(r"\b[\wа-яё]+\b", text.lower())))
    hits = sum(text.lower().count(w) for w in SACRED_VOCAB)
    return round(hits / n_words * 1000, 1)


def analyze_file(p: Path) -> dict:
    msgs = parse_pavel_messages(p)
    if not msgs:
        return None
    full = "\n\n".join(msgs)
    n_chars = len(full)
    n_words = len(re.findall(r"\b[\wа-яё]+\b", full))
    n_msgs = len(msgs)
    avg_len = n_chars / n_msgs if n_msgs else 0
    monologue = sum(1 for m in msgs if len(m) > 500)  # «надиктовка в потоке»
    sacred = sacred_density(full)
    # Извлечь дату из имени файла
    date_m = re.match(r"^(\d{4}-\d{2}-\d{2})", p.name)
    date = date_m.group(1) if date_m else "0000-00-00"
    # Имя беседы из шапки
    name_m = re.search(r"^# (.+)$", p.read_text(encoding="utf-8").split("\n", 1)[0], flags=re.MULTILINE)
    name = name_m.group(1) if name_m else p.stem
    # Темы
    chapters = map_chapters(full, name)
    return {
        "file": p.name,
        "name": name,
        "date": date,
        "n_chars": n_chars,
        "n_words": n_words,
        "n_msgs": n_msgs,
        "avg_len": int(avg_len),
        "monologue_msgs": monologue,
        "sacred_per_1000": sacred,
        "top_chapter": chapters[0][0] if chapters else "(off-topic)",
        "top_chapter_score": chapters[0][1] if chapters else 0,
        "chapters_top3": chapters,
    }


def main():
    if not CORPUS.exists():
        print("✗ Нет voice-corpus/raw/")
        return

    files = sorted(CORPUS.glob("*.md"))
    print(f"Анализирую {len(files)} файлов...")
    results = []
    for p in files:
        try:
            r = analyze_file(p)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  ✗ {p.name}: {e}")

    print(f"✓ Проанализировано: {len(results)} файлов")

    # Группировка по chapter
    by_chapter = defaultdict(list)
    for r in results:
        by_chapter[r["top_chapter"]].append(r)

    # Сводный отчёт
    total_chars = sum(r["n_chars"] for r in results)
    total_words = sum(r["n_words"] for r in results)
    total_msgs = sum(r["n_msgs"] for r in results)
    total_monologue = sum(r["monologue_msgs"] for r in results)

    # Top monologue conversations (>1000 chars avg = настоящие потоки)
    monologues = sorted(
        [r for r in results if r["avg_len"] > 1000 and r["monologue_msgs"] >= 3],
        key=lambda r: -r["n_chars"],
    )[:40]

    out = [
        "# Voice Corpus — Тематическая Карта",
        "",
        f"**Сгенерировано:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Файлов проанализировано:** {len(results)} (из всех бесед Claude.ai архива)",
        "",
        "## Сводка корпуса",
        "",
        f"- **Символов всего:** {total_chars:,}",
        f"- **Слов всего:** {total_words:,}",
        f"- **Сообщений Pavel-а:** {total_msgs:,}",
        f"- **Длинных monologue-сообщений (>500 знаков):** {total_monologue:,}",
        f"- **Объём текста:** ~{total_chars / 1_000_000:.1f} МБ чистой речи",
        "",
        "## Распределение по каноническим темам",
        "",
        "| Тема | Бесед | Знаков | Слов | Monologue-сообщений |",
        "|---|---|---|---|---|",
    ]
    sorted_chapters = sorted(by_chapter.items(), key=lambda x: -sum(r["n_chars"] for r in x[1]))
    for ch, items in sorted_chapters:
        ch_chars = sum(r["n_chars"] for r in items)
        ch_words = sum(r["n_words"] for r in items)
        ch_mono = sum(r["monologue_msgs"] for r in items)
        out.append(f"| {ch} | {len(items)} | {ch_chars:,} | {ch_words:,} | {ch_mono} |")

    out.append("")
    out.append("## ТОП-40 monologue-сессий (Pavel в потоке)")
    out.append("")
    out.append("Эти беседы — где Pavel диктовал длинные mono­logue-сообщения. **Главный primary source.**")
    out.append("")
    out.append("| Дата | Беседа | Топ-тема | Знаков | Сообщений | Sacred/1k |")
    out.append("|---|---|---|---|---|---|")
    for r in monologues:
        name = r["name"][:55]
        ch_short = r["top_chapter"][:30]
        out.append(f"| {r['date']} | [{name}](raw/{r['file']}) | {ch_short} | {r['n_chars']:,} | {r['n_msgs']} | {r['sacred_per_1000']} |")

    out.append("")
    out.append("## По темам — детально")
    out.append("")
    for ch, items in sorted_chapters:
        items.sort(key=lambda r: -r["n_chars"])
        out.append(f"### {ch} — {len(items)} бесед · {sum(r['n_chars'] for r in items):,} знаков")
        out.append("")
        out.append("| Дата | Беседа | Знаков | Pavel-сообщ. |")
        out.append("|---|---|---|---|")
        for r in items[:25]:  # топ-25 на тему
            out.append(f"| {r['date']} | [{r['name'][:55]}](raw/{r['file']}) | {r['n_chars']:,} | {r['n_msgs']} |")
        if len(items) > 25:
            out.append(f"| | _… ещё {len(items) - 25} бесед_ | | |")
        out.append("")

    (OUT / "THEMATIC-MAP.md").write_text("\n".join(out), encoding="utf-8")
    print(f"✓ Карта: {OUT / 'THEMATIC-MAP.md'}")

    # JSON для downstream
    (OUT / "analysis.json").write_text(
        json.dumps({"results": results, "by_chapter": {k: len(v) for k, v in by_chapter.items()}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Event
    event = {
        "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "voice_corpus_analyzed",
        "target": "voice-corpus/THEMATIC-MAP.md",
        "payload": {
            "files": len(results),
            "total_chars": total_chars,
            "total_words": total_words,
            "monologue_msgs": total_monologue,
        },
    }
    events = V2 / ".codex/events.jsonl"
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
