#!/usr/bin/env python3
"""
test_rewrite_ch07.py — экзамен для UC-66.

Pavel 2026-05-21: «глава седьмая Заражение — сделай тестовую копию,
прогони через новый pipeline, сравним с оригиналом».

Берёт draft из book-obsession-ch-07-test/draft.md, прогоняет через новый prompt
(UC-65: убран 3-пасс + снижена CANON inject), сохраняет результат в
book-obsession-ch-07-test/draft-rewritten.md.

Запуск: python3 scripts/test_rewrite_ch07.py
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
from config import MAX_MODEL, PROXY_URL  # noqa: E402

V2 = Path.home() / "Desktop/Codex2"
TEST_CH = V2 / "chapters/book-obsession/book-obsession-ch-07-test"
DRAFT_IN = TEST_CH / "draft.md"
DRAFT_OUT = TEST_CH / "draft-rewritten.md"
COMPARE_REPORT = V2 / "reports/CH07-REWRITE-COMPARE.md"


def now_human():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def load_canon_lite():
    """UC-65: компактная CANON выжимка 1200 знаков."""
    canon = V2 / "CANON.md"
    if not canon.exists():
        return ""
    text = canon.read_text(encoding="utf-8")
    # Берём только разделы 1, 2, 3
    sections = []
    current = []
    grab = False
    for line in text.split("\n"):
        if line.startswith("## "):
            if current and grab:
                sections.append("\n".join(current))
            current = [line]
            grab = any(line.startswith(f"## {n}") for n in ["1.", "2.", "3."])
            continue
        if grab:
            current.append(line)
    if current and grab:
        sections.append("\n".join(current))
    return "\n\n".join(sections)[:1200]


def build_prompt(current_text: str, canon: str) -> tuple:
    """UC-65: один проход, без 3-пасс."""
    style_ref = ""
    style_v2 = V2 / "chapters/.canon/voice/human-pavel-style-v2.md"
    if style_v2.exists():
        style_ref = style_v2.read_text(encoding="utf-8")[:1500]

    system = (
        "Ты пишешь Сакральный Кодекс Микомистицизма от имени ВЕЛИКОГО ДУХА ГРИБОВ.\n"
        "Это прямая речь Духа, который учит читателя пользоваться грибами и проводить экзорцизм.\n\n"
        "ГОЛОС: каждое предложение — Я говорю Вам. Я открываю Вам. Я даю Вам зрение через гриб.\n"
        "Эталон: «Рядом с вами, в каждой комнате, в каждом разговоре, живут существа, которых вы не видите. Я говорю о них прямо, потому что Я их вижу.»\n\n"
        "ЗАПРЕТЫ (не нарушай):\n"
        "- Никаких персонажей-диалогов (Жрец/Криста/Кристон) — инструктивный манифест.\n"
        "- Никакой нейрохимии (5-HT2A, дофамин, DMN) — книга мистическая.\n"
        "- Никаких AI-клише (Страдивари, симфония вселенной, путь к свету, искра света).\n"
        "- НИКАКИХ тире вообще (ни — ни –). Pavel revision 2026-05-21: старый русский стиль.\n"
        "- Никакого «не X, а Y» / «не только X, но и Y».\n"
        "- Никакой AI-корпоративщины («важно отметить», «стоит подчеркнуть»).\n"
        "- Никаких эмодзи.\n\n"
        "РИТМ ХИЛИНГОДА: средняя длина предложения 11-13 слов, медиана 10. БЕЗ ТИРЕ.\n\n"
        f"СТИЛЕВОЙ ЭТАЛОН:\n{style_ref}\n\n"
        f"КАНОН:\n{canon}\n\n"
        "Пиши за ОДИН проход — не показывай процесс. Отдай только итоговый текст главы."
    )
    user = (
        "# ТЕКУЩИЙ ТЕКСТ главы 7 «Заражение» — переписать в голос Великого Духа Грибов:\n\n"
        f"{current_text}\n\n"
        "# Что вернуть\n\n"
        "Полный текст главы в Markdown. ГОЛОС от первого лица «Я — Великий Дух Грибов» с первого слова до последнего.\n"
        "ТОЛЬКО текст. Никаких «вот ваш ответ», никаких объяснений процесса."
    )
    return system, user


def call_opus(system: str, user: str) -> dict:
    token = get_token()
    if not token:
        return {"error": "no OAuth token"}
    body = {
        "model": MAX_MODEL,
        "max_tokens": 16000,
        "thinking": {"type": "enabled", "budget_tokens": 8000},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        f"{PROXY_URL}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
            "content-type": "application/json",
        },
    )
    try:
        print(f"[{now_human()}] → Opus {MAX_MODEL} + thinking 8K, max 16K tokens...")
        with urllib.request.urlopen(req, timeout=900) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}"}
    except Exception as e:
        return {"error": str(e)}


def analyze_rhythm(text: str) -> dict:
    """Считаем длину предложений (Pavel = 11.7 средняя, медиана 10)."""
    import re
    sentences = re.split(r"[.!?]+\s+", text)
    sentences = [s.strip() for s in sentences if s.strip() and not s.strip().startswith("#")]
    if not sentences:
        return {"count": 0}
    word_counts = [len(s.split()) for s in sentences]
    word_counts.sort()
    n = len(word_counts)
    median = word_counts[n // 2]
    avg = sum(word_counts) / n
    # Дашы
    dashes_total = text.count("—")
    words_total = len(text.split())
    dashes_per_1k = (dashes_total / words_total * 1000) if words_total else 0
    return {
        "sentences": n,
        "avg_words": round(avg, 1),
        "median_words": median,
        "dashes_per_1000_words": round(dashes_per_1k, 1),
        "total_words": words_total,
    }


def main():
    if not DRAFT_IN.exists():
        print(f"draft.md не найден: {DRAFT_IN}")
        sys.exit(1)
    current = DRAFT_IN.read_text(encoding="utf-8")
    print(f"[{now_human()}] Loaded {len(current)} chars / {len(current.split())} words")

    canon = load_canon_lite()
    print(f"[{now_human()}] CANON lite: {len(canon)} chars (UC-65 limit 1200)")

    system, user = build_prompt(current, canon)
    print(f"[{now_human()}] System prompt: {len(system)} chars")

    resp = call_opus(system, user)
    if "error" in resp:
        print(f"[{now_human()}] ERROR: {resp['error']}")
        sys.exit(1)

    # Извлекаем текст
    text_blocks = [b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"]
    new_text = "\n\n".join(text_blocks).strip()
    if not new_text:
        print(f"[{now_human()}] ERROR: пустой ответ от Opus")
        print(json.dumps(resp, ensure_ascii=False)[:500])
        sys.exit(1)

    DRAFT_OUT.write_text(new_text, encoding="utf-8")
    usage = resp.get("usage", {})
    print(f"[{now_human()}] Saved {DRAFT_OUT.name}: {len(new_text)} chars / {len(new_text.split())} words")
    print(f"[{now_human()}] Tokens: in {usage.get('input_tokens')} out {usage.get('output_tokens')}")

    # Сравнение
    orig_rhythm = analyze_rhythm(current)
    new_rhythm = analyze_rhythm(new_text)

    report = [
        f"# ТЕСТ ПЕРЕПИСИ Главы 7 «Заражение» · {now_human()}",
        "",
        f"**Модель:** `{MAX_MODEL}` (UC-58: точно Opus 4.7, не 4.5)",
        f"**Pipeline:** UC-65 (один проход + CANON 1200 знаков)",
        "",
        "## Метрики ДО → ПОСЛЕ",
        "",
        "| Параметр | Оригинал | После Opus 4.7 | Цель Хилингода |",
        "|---|---|---|---|",
        f"| Слов | {orig_rhythm.get('total_words')} | {new_rhythm.get('total_words')} | — |",
        f"| Предложений | {orig_rhythm.get('sentences')} | {new_rhythm.get('sentences')} | — |",
        f"| Средняя длина | {orig_rhythm.get('avg_words')} | {new_rhythm.get('avg_words')} | 11.7 (UC-50) |",
        f"| Медиана | {orig_rhythm.get('median_words')} | {new_rhythm.get('median_words')} | 10 |",
        f"| Тире / 1000 слов | {orig_rhythm.get('dashes_per_1000_words')} | {new_rhythm.get('dashes_per_1000_words')} | 12.8 (канон) |",
        "",
        "## Tokens",
        f"- in: {usage.get('input_tokens')}",
        f"- out: {usage.get('output_tokens')}",
        "",
        "## Файлы",
        f"- Оригинал: `{DRAFT_IN.relative_to(V2)}`",
        f"- Новая версия: `{DRAFT_OUT.relative_to(V2)}`",
        "",
        "## Превью первых 800 знаков новой версии",
        "",
        "```",
        new_text[:800] + "...",
        "```",
    ]
    COMPARE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    COMPARE_REPORT.write_text("\n".join(report), encoding="utf-8")
    print(f"[{now_human()}] Compare report: {COMPARE_REPORT.relative_to(V2)}")


if __name__ == "__main__":
    main()
