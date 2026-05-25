#!/usr/bin/env python3
"""UC-125: Анализ последовательности параграфов.

Pavel: «последним инструментом должен быть анализ последовательности параграфов.
В конце должна быть выстроена правильная логическая последовательность».

Анализирует draft главы → Opus читает все параграфы → выдаёт:
  - reorder: какие параграфы переставить
  - merge: какие склеить (часто два коротких рядом → один)
  - split: какие разбить (если один параграф несёт две идеи)
  - delete: какие убрать совсем (повторы или слабые)
  - keep: правильно расположенные
  - narrative_arc: как выглядит сюжетная дуга сейчас vs идеальная

Результат — структурированный JSON для UI.
Cache: data/sequence/<chapter_id>.json
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
try:
    from config import MAX_MODEL, PROXY_URL
except Exception:
    MAX_MODEL = "claude-opus-4-7"
    PROXY_URL = "http://127.0.0.1:8787"

V2 = Path.home() / "Desktop/Codex2"
CACHE_DIR = V2 / "data/sequence"


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def load_chapter_paragraphs(chapter_id):
    m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
    if not m:
        raise ValueError(f"bad chapter_id: {chapter_id}")
    book_id = m.group(1)
    draft = V2 / "chapters" / book_id / chapter_id / "draft.md"
    if not draft.exists():
        raise FileNotFoundError(f"no draft.md for {chapter_id}")
    text = draft.read_text(encoding="utf-8")
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    return paras


def call_opus(messages, system, max_tokens=6000):
    token = get_token()
    if not token:
        return None, "no oauth token"
    body = {
        "model": MAX_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:
        return None, str(e)
    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(blocks).strip(), data.get("usage", {})


SYSTEM = """Ты — последний редактор Сакрального Кодекса Микомистицизма. Pavel сказал:
«последним инструментом должен быть анализ последовательности параграфов. В конце
должна быть выстроена правильная логическая последовательность».

Прочитай ВСЕ параграфы главы пронумерованные от 1. Найди:

1. **REORDER** — параграфы которые стоят не в том месте.
   Пример: «вывод» в середине, «постановка» в конце. Указать from → to.

2. **MERGE** — два соседних параграфа которые мысленно одно целое.
   Часто короткий параграф 5-15 слов рядом с длинным про ту же тему.

3. **SPLIT** — параграф который несёт ДВЕ разные идеи в одном.
   Указать где разрез.

4. **DELETE** — параграфы которые повторяют сказанное или слабые.
   Только если они реально не несут добавочной ценности.

5. **KEEP** — правильно стоящие (можно опустить если их большинство — указать только сильные).

6. **NARRATIVE_ARC** — текущая дуга vs идеальная для главы Кодекса:
   - открытие (крючок: образ/вопрос/обращение Я-Духа)
   - развитие (постановка, телесность, исторические якоря)
   - вершина (доктринальное откровение, парадокс)
   - закрытие (cliffhanger, обращение «Вы», эхо открытия)

Возврат — JSON:
{
  "current_arc": {"opening": "что сейчас", "development": "...", "peak": "...", "closing": "..."},
  "ideal_arc": {"opening": "что должно быть", ...},
  "reorder": [{"from": N, "to": M, "rationale": "..."}],
  "merge": [{"paragraphs": [N, M], "rationale": "..."}],
  "split": [{"paragraph": N, "where": "после фразы X", "rationale": "..."}],
  "delete": [{"paragraph": N, "rationale": "..."}],
  "ideal_sequence": [N, M, K, ...],   // финальный порядок индексов (1-based)
  "summary": "общая оценка последовательности",
  "score": 0-100   // насколько последовательность сейчас близка к идеалу
}

Без преамбулы. Сразу JSON. Не больше 8 пунктов в каждой категории — фокус на главных.
"""


def analyze(chapter_id, force=False):
    if not force:
        cache = CACHE_DIR / f"{chapter_id}.json"
        if cache.exists():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                from datetime import datetime as _dt
                ts = cached.get("ts", "")
                if ts:
                    age = (datetime.now(timezone.utc) - _dt.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
                    if age < 86400:
                        return cached
            except Exception:
                pass

    paras = load_chapter_paragraphs(chapter_id)
    if not paras:
        return {"ok": False, "error": "no paragraphs"}

    parts = [f"# ГЛАВА: {chapter_id}\n# Всего параграфов: {len(paras)}\n\n# ТЕКСТ ПО ПАРАГРАФАМ\n"]
    for i, p in enumerate(paras, 1):
        parts.append(f"\n## Параграф {i}\n{p[:1000]}")
    user_msg = "\n".join(parts) + "\n\nПроанализируй последовательность и верни JSON."

    raw, usage = call_opus([{"role": "user", "content": user_msg}], SYSTEM, max_tokens=6000)
    if not raw:
        return {"ok": False, "error": str(usage)}
    clean = raw
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        if clean.startswith("json"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean
    try:
        parsed = json.loads(clean.strip())
    except Exception as e:
        return {"ok": False, "error": f"JSON parse: {e}", "raw": raw[:2000]}

    out = {
        "ok": True,
        "chapter_id": chapter_id,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paragraph_count": len(paras),
        **parsed,
        "usage": usage if isinstance(usage, dict) else {},
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{chapter_id}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter-id", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    res = analyze(args.chapter_id, force=args.force)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:3000])
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
