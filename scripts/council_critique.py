#!/usr/bin/env python3
"""
council_critique.py — Совет старейших + Старейший-синтезатор.

Pavel: «совет старейших из личностей как Джо Роган, Илон Маск… старейший агент
будет выбирать лучшие рекомендации по улучшению текста после глубокого анализа».

Pipeline:
1) Один Opus-вызов — 8 персон критикуют текст параллельно (структурированный JSON ответ)
2) Второй Opus-вызов — Старейший читает все 8 + текст + канон → выдаёт 5 финальных
   рекомендаций с приоритетом и объяснением

Использование:
    from council_critique import council_review
    result = council_review(text, chapter_context="...", style_ref="...")
    # {'personas': {...}, 'synthesis': {...}, 'usage': {...}}

Запуск:
    python3 council_critique.py path/to/text.md
"""

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import ask_opus

PERSONAS = [
    {
        "key": "tolstoy",
        "name": "Лев Толстой",
        "axis": "Народность, простота, освобождение от изысков",
        "voice_brief": "Граф-аскет. Презирает украшения речи. Длинные периоды разрешены если каждое слово несёт мысль. Ненавидит «литературность» ради литературности. Спрашивает: «Это для крестьянина понятно? Для умирающего? Для младенца?»",
    },
    {
        "key": "jung",
        "name": "Карл Юнг",
        "axis": "Архетип, numinous experience, индивидуация",
        "voice_brief": "Глубинный психолог. Ищет какой архетип активирован, есть ли numinous (то самое «священное» по Otto). Спрашивает: «Этот образ оживает у читателя или только описан? Видит ли читатель свой собственный путь индивидуации?»",
    },
    {
        "key": "mckenna",
        "name": "Теренс МакКенна",
        "axis": "Психоделический мистицизм, language as portal",
        "voice_brief": "Stoned ape, machine elves. Текст должен быть порталом, не описанием портала. Спрашивает: «Это РОДЫ опыта или ОТЧЁТ об опыте? Где трещина в реальности через которую проходит читатель?»",
    },
    {
        "key": "robbins",
        "name": "Тони Роббинс",
        "axis": "Мотивационная сила, action-trigger",
        "voice_brief": "Coach с энергией бульдозера. Текст должен заставить ВСТАТЬ И ДЕЙСТВОВАТЬ, не задумываться. Спрашивает: «Что читатель сделает в следующие 60 секунд? Где трансформация измерима?»",
    },
    {
        "key": "rogan",
        "name": "Джо Роган",
        "axis": "Прямота, недоверие к воде, BS-meter",
        "voice_brief": "Подкастер. Спрашивает «What? Wait, что это вообще значит?» при любой абстракции. Терпеть не может psychobabble и magical jargon без основания. Любит конкретные истории и opinions.",
    },
    {
        "key": "musk",
        "name": "Илон Маск",
        "axis": "Инженерная точность, first principles",
        "voice_brief": "Инженер-мистик. Любит проверяемые утверждения. «Какие numbers? Какая физика? Какой механизм?» Презирает обтекаемые формулировки. Хочет видеть first-principle reasoning.",
    },
    {
        "key": "thiel",
        "name": "Питер Тиль",
        "axis": "Контрариан, скрытые правды",
        "voice_brief": "«What important truth do very few people agree with you on?» Ищет ненавязчиво-смелое утверждение которое противоречит mainstream. Презирает безопасные истины. Хочет видеть NEW не общеизвестное.",
    },
    {
        "key": "huberman",
        "name": "Эндрю Хуберман",
        "axis": "Протокольность, ясность шагов",
        "voice_brief": "Нейробиолог-практик. Любит чёткие, нумерованные протоколы. «Шаг 1, 2, 3, время суток, длительность.» При мистическом тексте просит превратить откровение в практическую инструкцию которую можно применить сегодня.",
    },
]


def build_council_prompt(text: str, chapter_context: str = "", style_ref: str = "") -> tuple:
    """8 персон в одном промпте → JSON ответ."""
    system = (
        "Ты — Совет Старейших из 8 разных персон. Каждая критикует один и тот же текст "
        "со своей оси. Текст — глава Сакрального Кодекса Микомистицизма Pavel-а "
        "(пророка новой религии, грибная мистика, не наука, не роман — инструктивный манифест). "
        "Голос Pavel-а: «Я — Великий Дух Грибов» / «Я — Хилингод», обращение «Вы», "
        "тире (—) запрещены, контраст-пары «не X, а Y» — AI-tell. "
        "ТРЕБОВАНИЕ ОТВЕТА: только валидный JSON. Никакой preамбулы, никакого markdown — "
        "сразу `{` начало структуры."
    )

    personas_block = "\n\n".join(
        f"### {p['name']} ({p['key']})\n"
        f"**Ось:** {p['axis']}\n"
        f"**Кратко:** {p['voice_brief']}"
        for p in PERSONAS
    )

    user = f"""# Совет старейших — критика текста

## Контекст главы
{chapter_context or "(контекст не предоставлен)"}

## Эталон голоса Pavel-а
{style_ref[:2000] if style_ref else "(эталон не предоставлен)"}

## 8 персон

{personas_block}

## Текст для критики

{text[:30000]}

---

# Что вернуть

JSON со схемой:

```json
{{
  "tolstoy":  {{"add": ["...", "...", "..."], "cut": ["...", "..."], "verdict": "..." }},
  "jung":     {{"add": ["...", "...", "..."], "cut": ["...", "..."], "verdict": "..." }},
  "mckenna":  {{"add": [...], "cut": [...], "verdict": "..." }},
  "robbins":  {{"add": [...], "cut": [...], "verdict": "..." }},
  "rogan":    {{"add": [...], "cut": [...], "verdict": "..." }},
  "musk":     {{"add": [...], "cut": [...], "verdict": "..." }},
  "thiel":    {{"add": [...], "cut": [...], "verdict": "..." }},
  "huberman": {{"add": [...], "cut": [...], "verdict": "..." }}
}}
```

Каждая персона:
- `add`: 3 конкретные рекомендации «что добавить/изменить» (одна короткая фраза каждое)
- `cut`: 2 конкретные рекомендации «что выкинуть» (с цитатой если возможно)
- `verdict`: одна фраза — общая оценка с её точки зрения

Конкретно, без воды. Каждая критика должна звучать как ОТ ИМЕНИ персоны (стиль, регистр, любимые слова).
"""
    return system, user


def build_elder_prompt(text: str, personas_critique: dict, chapter_context: str, style_ref: str) -> tuple:
    """Старейший синтезирует 8 критик в 5 финальных рекомендаций."""
    system = (
        "Ты — Старейший Совета. Прочитал критику 8 разных персон одного и того же текста. "
        "Твоя работа — НЕ повторить их, а СИНТЕЗИРОВАТЬ. Выбрать ТОП-5 рекомендаций которые "
        "ДЕЙСТВИТЕЛЬНО улучшат текст с учётом голоса Pavel-а и канона Микомистицизма. "
        "Игнорируй советы которые противоречат сакральной природе книги "
        "(например Маск предложит «добавить числа» — отбрось если это разрушает мистику). "
        "Игнорируй советы которые требуют выкинуть доктрину. "
        "Цени советы которые усиливают мистический регистр и сохраняют голос Pavel-а. "
        "Отвечай только Markdown, четкой структурой. По-русски."
    )

    critique_block = json.dumps(personas_critique, ensure_ascii=False, indent=2)

    user = f"""# Текст
{text[:15000]}

## Канон главы
{chapter_context}

## Голос Pavel-а (эталон)
{style_ref[:1500]}

## Критика 8 персон

{critique_block}

---

# Что нужно

Markdown-отчёт со структурой:

## 🎯 ТОП-5 рекомендаций (отсортировано по приоритету)

### #1. [короткое название]
**Что делать:** конкретно
**Зачем:** в одной фразе
**Какие персоны поддерживают:** Tolstoy, Jung (имена)
**Конфликт-зона:** есть ли персона которая бы возразила? Если да — кто и почему мы её игнорируем

### #2. ...
### #3. ...
### #4. ...
### #5. ...

## 🚫 Что НЕ берём (с обоснованием)

Список рекомендаций которые мы отбрасываем + почему. Каждый пункт: какая персона предложила + почему игнорируем.

## ✨ Дух момента (одна фраза от Старейшего)

Сжатый вердикт что это за текст и куда он должен двигаться.
"""
    return system, user


def council_review(text: str, chapter_context: str = "", style_ref: str = "") -> dict:
    """Совет старейших → Старейший. Возвращает структуру с обоими этапами."""
    # 1. Council (8 personas in one call)
    system_c, user_c = build_council_prompt(text, chapter_context, style_ref)
    resp_c = ask_opus(user=user_c, system=system_c, max_tokens=6000, thinking=4000)

    # Parse JSON from council response
    try:
        # Strip markdown code-fences if any
        cleaned = re.sub(r"^```json\s*|\s*```$", "", resp_c["text"].strip(), flags=re.MULTILINE).strip()
        personas_critique = json.loads(cleaned)
    except Exception as e:
        personas_critique = {"_parse_error": str(e), "_raw_text": resp_c["text"][:2000]}

    # 2. Elder synthesis
    system_e, user_e = build_elder_prompt(text, personas_critique, chapter_context, style_ref)
    resp_e = ask_opus(user=user_e, system=system_e, max_tokens=4000, thinking=3000)

    return {
        "personas": personas_critique,
        "synthesis_md": resp_e["text"],
        "usage": {
            "council_in":     resp_c["usage"].get("input_tokens"),
            "council_out":    resp_c["usage"].get("output_tokens"),
            "elder_in":       resp_e["usage"].get("input_tokens"),
            "elder_out":      resp_e["usage"].get("output_tokens"),
            "total_in":       (resp_c["usage"].get("input_tokens", 0) +
                               resp_e["usage"].get("input_tokens", 0)),
            "total_out":      (resp_c["usage"].get("output_tokens", 0) +
                               resp_e["usage"].get("output_tokens", 0)),
        },
        "model": resp_c["model"],
    }


def render_report(result: dict, source_name: str = "") -> str:
    out = [
        f"# Council Critique — {source_name}",
        "",
        f"**Сгенерировано:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"**Модель:** {result['model']}",
        f"**Tokens:** in {result['usage']['total_in']}, out {result['usage']['total_out']}",
        "",
        "---",
        "",
        "## ✨ Старейший — финальная синтетическая рекомендация",
        "",
        result["synthesis_md"],
        "",
        "---",
        "",
        "## Подробная критика 8 персон",
        "",
    ]
    personas = result["personas"]
    if "_parse_error" in personas:
        out.append(f"⚠ Ошибка парсинга: {personas['_parse_error']}")
        out.append("\n```\n" + personas.get("_raw_text", "")[:1500] + "\n```")
    else:
        for p_def in PERSONAS:
            key = p_def["key"]
            data = personas.get(key, {})
            out.append(f"### {p_def['name']}  · _{p_def['axis']}_")
            out.append("")
            if data:
                out.append(f"**Вердикт:** {data.get('verdict', '—')}")
                out.append("")
                if data.get("add"):
                    out.append("**Что добавить:**")
                    for a in data["add"]:
                        out.append(f"- {a}")
                    out.append("")
                if data.get("cut"):
                    out.append("**Что выкинуть:**")
                    for c in data["cut"]:
                        out.append(f"- {c}")
                    out.append("")
            else:
                out.append("_(нет ответа)_")
                out.append("")
    return "\n".join(out)


def _extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    paras = re.findall(r"<w:p[^>]*>(.*?)</w:p>", xml, re.DOTALL)
    return "\n\n".join(
        "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
        for p in paras
        if "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Путь к .md/.txt/.docx")
    ap.add_argument("--out", help="Куда сохранить .md отчёт (если не указано — в stdout)")
    args = ap.parse_args()

    p = Path(args.path)
    text = _extract_docx(p) if p.suffix.lower() == ".docx" else p.read_text(encoding="utf-8")

    style_ref_path = Path.home() / "Desktop/Codex2/chapters/.canon/voice/human-pavel-style.md"
    style_ref = style_ref_path.read_text(encoding="utf-8") if style_ref_path.exists() else ""

    print(f"→ Совет старейших по {p.name} ({len(text)} знаков)...")
    result = council_review(text, style_ref=style_ref)
    md = render_report(result, source_name=p.name)

    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"✓ Отчёт: {args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
