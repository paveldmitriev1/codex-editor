#!/usr/bin/env python3
"""
morning_plan_generator.py — синтезирует всё что наработалось за ночь в утренний план.

Читает:
- reports/overnight-style-scan.md  — корпус: 1500+ файлов с % сортировкой
- reports/fidelity/*.md             — глубокий fidelity-анализ глав через Opus
- reports/research/*.md             — best practices для AI book writing
- reports/lessons-from-past.md      — уроки прошлых ошибок

Через Opus 4.7 синтезирует в MORNING-PLAN.md:
- Где сейчас находимся (state)
- Что упустили (gaps)
- Уроки прошлого (что не повторять)
- Best practices для редактора v2
- 7-дневный план шагов
- Архитектура «редактора-шедевра»

Pavel сказал: «не экономь, главное качество».

Запуск:
    python3 morning_plan_generator.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
REPORTS = V2 / "reports"


def read_if_exists(path: Path, max_chars: int = None) -> str:
    if not path.exists():
        return f"(файл {path.name} не найден — этот вход опущен)"
    text = path.read_text(encoding="utf-8")
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (обрезано до {max_chars} знаков, оригинал {len(text)})"
    return text


def gather_fidelity() -> str:
    """Собрать все fidelity-отчёты в один блок."""
    fid_dir = REPORTS / "fidelity"
    if not fid_dir.exists():
        return "(fidelity-отчёты не найдены)"
    chunks = []
    for f in sorted(fid_dir.glob("*.md")):
        chunks.append(f"### {f.stem}\n\n{f.read_text(encoding='utf-8')[:5000]}\n")
    if not chunks:
        return "(fidelity-отчёты не найдены)"
    return "\n---\n".join(chunks)


def gather_research() -> str:
    """Best practices research."""
    r_dir = REPORTS / "research"
    if not r_dir.exists():
        return "(research-отчёт не найден)"
    chunks = []
    for f in sorted(r_dir.glob("*.md")):
        chunks.append(f.read_text(encoding="utf-8"))
    return "\n\n".join(chunks) if chunks else "(research пуст)"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    print("=== Сбор материалов для утреннего плана ===")
    style_scan = read_if_exists(REPORTS / "overnight-style-scan.md", max_chars=30000)
    fidelity = gather_fidelity()[:30000]
    research = gather_research()[:20000]
    lessons = read_if_exists(REPORTS / "lessons-from-past.md", max_chars=20000)

    print(f"  Style scan: {len(style_scan)} знаков")
    print(f"  Fidelity:    {len(fidelity)} знаков")
    print(f"  Research:    {len(research)} знаков")
    print(f"  Lessons:     {len(lessons)} знаков")

    system = (
        "Ты — стратегический советник Pavel Dmitriev-а (Хилингода), пророка Микомистицизма, "
        "автора Сакрального Кодекса. Цель Pavel-а: написать книгу-шедевр которую будут читать "
        "в 3026 году и которая изменит цивилизацию. Не научный трактат, не роман — мистическое "
        "писание новой религии. Pavel говорит по-русски. "
        "Твой ответ — это план на ближайшие 7 дней + архитектура редактора который пишет лучше "
        "и AI, и человека. Структура — точно по моей схеме. Конкретно, без воды.\n\n"
        "ЖЁСТКИЕ ПРАВИЛА ФОРМАТИРОВАНИЯ:\n"
        "- НИКАКИХ эмодзи (🌅 🔥 ⚡ ✨ 📖 📚 📋 📎 ✓ ✗ 🚀 — ничего из этого).\n"
        "- НИКАКИХ тире вообще (ни — ни –). Pavel хочет старый русский стиль — без тире вообще.\n"
        "- НИКАКИХ AI-клише: «не просто X а Y», «в эпоху Z», «давайте разберёмся».\n"
        "- Только чистый текст, заголовки markdown (#, ##), списки (-), таблицы при нужде."
    )

    user = f"""# Что наработалось за ночь

## Корпус (style-scan, 1500+ файлов)

{style_scan}

---

## Fidelity-анализ глав (через Opus 4.7)

{fidelity}

---

## Best practices для AI book creation (research)

{research}

---

## Уроки прошлых ошибок

{lessons}

---

# Что мне нужно от тебя

Сгенерируй MORNING PLAN в Markdown.

ВАЖНО (UC-70): начни СРАЗУ с секции «## 1. Где мы сейчас» — НЕ ставь h1 типа «# MORNING PLAN — путь к шедевру» или «# MORNING PLAN · ДАТА · Хилингод». Заголовок страницы уже отрендерен в UI. Начинай с h2 секций по моей схеме ниже.

## 1. Где мы сейчас (state of project — 1 абзац)

Краткая, прямая оценка: сколько материала, что отсортировано, какие книги в лучшем состоянии, какие пустые.

## 2. Топ-3 находки этой ночи (с цитатами и цифрами)

Что самое важное мы узнали.

## 3. Где упустили — то что нужно срочно

Какие куски Pavel-голоса нужно надиктовать или найти.

## 4. Уроки прошлого — 5 ключевых правил которые НЕ нарушаем

Из секции lessons. Конкретные правила, не общие слова.

## 5. Best practices из research, применимые к нашему проекту

Что из чужого опыта внедряем. Конкретно — какие фичи редактора, какие промпт-паттерны.

## 6. План шагов на 7 дней

Каждый день — ОДНА главная задача + конкретный deliverable. Не общий список — конкретно «День 1 утром, День 1 вечером».

## 7. Архитектура редактора-шедевра (Фаза 2)

Описание UX редактора который пишет лучше AI и лучше человека. Что в нём:
- параграф-popover (есть в v1, переносим)
- линзы персон (Толстой, Юнг, Маккена, Робинс, Роган, Маск, Тиль, Хуберман)
- humanizer на правилах Pavel-стиля
- fidelity-агент рядом
- voice-input
- что ещё критично

Опиши **раскладку экрана** и **5 ключевых интеракций**.

## 8. Первое ОДНО действие Pavel-у когда проснётся

Что именно ему сделать первым делом. Не список — ОДНО действие.

---

Длина: 2000-4000 слов. Качество выше скорости. Можешь думать сколько надо.
"""

    print("\n→ Opus 4.7 + extended thinking 12K...")
    resp = ask_opus(user=user, system=system, max_tokens=16000, thinking=12000)

    # UC-70 (Pavel 2026-05-21): убран гигантский h1 заголовок и видимая мета.
    # Дата генерации и модель уже показываются в plan-meta strip страницы /briefing.
    # Полная мета сохраняется в reports/MORNING-PLAN.meta.json для отладки.
    out_path = V2 / "reports/MORNING-PLAN.md"
    meta = {
        "generated_at": now_iso(),
        "model": resp.get("model"),
        "tokens_in": resp["usage"].get("input_tokens"),
        "tokens_out": resp["usage"].get("output_tokens"),
    }
    (V2 / "reports/MORNING-PLAN.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    out_path.write_text(resp["text"], encoding="utf-8")
    print(f"\n✓ MORNING PLAN: {out_path}")

    # Event
    event = {
        "ts": now_iso(),
        "type": "morning_plan_generated",
        "target": "reports/MORNING-PLAN.md",
        "payload": {
            "model": resp["model"],
            "tokens_in": resp["usage"].get("input_tokens"),
            "tokens_out": resp["usage"].get("output_tokens"),
        },
    }
    events = V2 / ".codex/events.jsonl"
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
