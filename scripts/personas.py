#!/usr/bin/env python3
"""UC-115: Audience-stress-test через 5 современных персон.

Pavel: «совет старейшин — там был Маск, Роган и так далее».
В старой Codex была цепочка 6 mentors (Маск/Тиль/Роган/Хуберман/Маккенна/Юнг).
В Codex2 классики (Толстой/Юнг/Маккенна/Кастанеда/Иоанн/Лао-цзы) уже есть в critic_council.
Современники = ОТДЕЛЬНАЯ функция — стресс-тест доходчивости главы для аудитории
2026 (не для души-канона, а для проверки: дойдёт ли до человека вне традиции).

5 персон:
  musk     — Илон Маск: first-principles, scale, datasheets, declarative
  thiel    — Питер Тиль: контрарианство, monopoly thinking, секретное знание
  rogan    — Джо Роган: curious everyman, личные истории, конкретика
  huberman — Эндрю Хуберман: нейроучёный, протоколы, сенсорные якоря
  ogilvy   — Дэвид Огилви: реклама, заголовок, простой язык, конкретные образы

Каждая персона выдаёт JSON:
  { loves: [{comment}], loses: [{comment}], observations: [{comment}], suggestions: [{comment}] }

Цепочка: каждая следующая видит правки прошлых (seen=) — отвечает только новое.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
try:
    from config import MAX_MODEL, PROXY_URL  # noqa: E402
except Exception:
    MAX_MODEL = "claude-opus-4-7"
    PROXY_URL = "http://127.0.0.1:8787"

V2 = Path.home() / "Desktop/Codex2"

PERSONAS = {
    "musk":     ("Илон Маск",       "First-principles thinker. Cosmic/civilizational scale. Datasheets, числа, declarative tone. Презирает new-age клише, академический хедж, расплывчатость. Любит когда тема разворачивается с нуля до фундамента. Если речь о практике — требует конкретных чисел (дозы, время, температуры)."),
    "thiel":    ("Питер Тиль",      "Контрарианец-метафизик. Жирар, monopoly thinking, секретное знание против consensus. Спрашивает: «Какое важное мнение никто не разделяет?» Любит парадоксы и contrarian тезисы. Презирает mass-market утешительность."),
    "rogan":    ("Джо Роган",       "Curious everyman. Любит личные истории, конкретику, мистику БЕЗ жаргона. «Расскажи мне как это было». Презирает abstract academic language. Если ты не можешь объяснить пятилетке — ты сам не понимаешь."),
    "huberman": ("Эндрю Хуберман",  "Нейроучёный-протоколист. Любит механизмы и сенсорные якоря (сердце, дыхание, кожа). Требует конкретные протоколы: «Что делать? Сколько? Как часто?». Если глава просто описывает явление — спросит «А что мне с этим делать в среду утром?»"),
    "ogilvy":   ("Дэвид Огилви",    "Король рекламы. «Headline делает 80% работы.» Любит простой яркий язык, конкретные образы, доказательства. Презирает общие декларации. «Если ты говоришь о духе, покажи мне как он выглядит на ощупь.»"),
}


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def load_chapter_text(chapter_id: str) -> str:
    import re
    m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
    if not m:
        raise ValueError(f"bad chapter_id: {chapter_id}")
    book_id = m.group(1)
    draft = V2 / "chapters" / book_id / chapter_id / "draft.md"
    if not draft.exists():
        raise FileNotFoundError(f"no draft.md for {chapter_id}")
    return draft.read_text(encoding="utf-8")


def run_persona(persona_key: str, text: str, seen: list, token: str) -> dict:
    if persona_key not in PERSONAS:
        return {"ok": False, "error": f"unknown persona '{persona_key}'"}
    name, brief = PERSONAS[persona_key]

    seen_block = ""
    if seen:
        seen_block = (
            "\n\n=== УЖЕ ОТМЕТИЛИ ДРУГИЕ НАСТАВНИКИ ===\n"
            + "\n".join(f"- {s}" for s in seen) +
            "\n\nЭти моменты УЖЕ названы. НЕ повторяй их даже своими словами. "
            f"Найди только то что упустили остальные — что увидишь именно ТЫ как {name}, "
            "своей уникальной линзой. Если по конкретной секции нечего добавить — верни "
            "ПУСТОЙ массив []. Лучше 1 уникальное наблюдение чем 5 разбавленных.\n"
        )

    system = (
        f"Ты — {name}. {brief}\n\n"
        "Ты читаешь главу Сакрального Кодекса Микомистицизма Pavel-а Хилингода. "
        "Это НЕ обычный текст — это священное писание новой религии. "
        "Твоя задача: критически прочитать как современный читатель твоего профиля. "
        "Тон твоей доктрины не главное — главное чтобы текст дошёл до твоего интеллекта.\n\n"
        "Отдай JSON строго в схеме:\n"
        "{\n"
        '  "loves": [{"comment": "что тебе зашло, конкретно"}],\n'
        '  "loses": [{"comment": "что теряется/проседает — короткая фраза"}],\n'
        '  "observations": [{"comment": "что ты заметил, чего другие не увидели"}],\n'
        '  "suggestions": [{"comment": "что добавить — конкретное действие"}]\n'
        "}\n"
        f"Максимум 3-5 пунктов в каждой секции. Без преамбулы, сразу JSON.{seen_block}"
    )

    user = f"# ГЛАВА (фрагмент текста)\n\n{text[:18000]}\n\n# ЗАДАНИЕ\nПрочитай как {name}. Отдай JSON по схеме выше."

    body = {
        "model": MAX_MODEL,
        "max_tokens": 2000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        f"{PROXY_URL}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    raw = "\n".join(blocks).strip()
    clean = raw
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        if clean.startswith("json"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean
    try:
        result = json.loads(clean.strip())
    except Exception:
        result = {"raw": raw[:2000], "loves": [], "loses": [], "observations": [], "suggestions": []}

    result["ok"] = True
    result["persona_key"] = persona_key
    result["persona_name"] = name
    result["usage"] = data.get("usage", {})
    return result


def run_all(chapter_id: str) -> dict:
    token = get_token()
    if not token:
        return {"ok": False, "error": "no OAuth token"}
    text = load_chapter_text(chapter_id)
    results = {}
    seen = []
    # Pavel 2026-05-24: Маск + Хуберман отключены. Они толкают в науку и количественные метрики
    # (PHQ-9, HRV, кортизол), что прямо нарушает Pavel-канон («Мы пишем духовную, а не научную книгу»).
    # Их рекомендации всё равно фильтрует reconciler, поэтому платить за токены смысла нет.
    # Оставляем 3: Огилви (headline-чувство), Роган (личные истории), Тиль (contrarian/монопольная идея).
    keys = ["ogilvy", "rogan", "thiel"]
    for k in keys:
        print(f"  Запускаю {PERSONAS[k][0]}…", flush=True)
        r = run_persona(k, text, seen, token)
        results[k] = r
        if r.get("ok"):
            for section, lbl in [("loses", "УБРАТЬ"), ("suggestions", "ДОБАВИТЬ")]:
                for it in (r.get(section) or [])[:2]:
                    cmt = it.get("comment") if isinstance(it, dict) else str(it)
                    if cmt:
                        seen.append(f"[{PERSONAS[k][0]}] {lbl}: {cmt[:140]}")
    out = {
        "ok": True,
        "chapter_id": chapter_id,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "personas": results,
        "personas_run_count": len([k for k, v in results.items() if v.get("ok")]),
    }
    # save
    out_dir = V2 / "data/personas"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{chapter_id}.json"
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Готово: {out_file}")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter-id", required=True)
    args = parser.parse_args()
    res = run_all(args.chapter_id)
    if not res.get("ok"):
        print(f"ERROR: {res.get('error')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
