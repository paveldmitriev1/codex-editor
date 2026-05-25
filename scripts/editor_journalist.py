#!/usr/bin/env python3
"""UC-119: editor-журналист — Q&A после галочек, до рерайта.

Pavel: «после того как все рекомендации даны журналист относительно этих
рекомендаций ещё задаёт мне вопросы пока не доведём до шедевра. Я хочу
чтобы я ещё в этом участвовал».

Workflow:
  1. Pavel поставил галочки на рекомендациях в editor
  2. Apply-targeted: ПЕРЕД Opus-рерайтом вызывается этот журналист
  3. Журналист видит: текущую главу + выбранные fixes + voice missing_ideas + analysis
     → формирует 3-5 ТОЧЕЧНЫХ вопросов Pavel-у
  4. Pavel отвечает (через UI panel)
  5. Ответы добавляются в Opus prompt как дополнительный контекст «Pavel сказал…»
  6. Opus делает рерайт с учётом всего

Сессия:
  data/editor-journalist-sessions/<chapter_id>-<ts>.json
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
try:
    from config import MAX_MODEL, PROXY_URL
except Exception:
    MAX_MODEL = "claude-opus-4-7"
    PROXY_URL = "http://127.0.0.1:8787"

V2 = Path.home() / "Desktop/Codex2"
SESSIONS_DIR = V2 / "data/editor-journalist-sessions"

SYSTEM = (
    "Ты — Журналист-редактор. Pavel Хилингод доверил тебе финальный шлифовочный диалог "
    "перед тем как Opus 4.7 перепишет главу Сакрального Кодекса Микомистицизма с учётом "
    "выбранных правок.\n\n"
    "Pavel сказал: «Я хочу чтобы я ещё в этом участвовал. Будут моменты где недостаточно "
    "информации для создания идеальной главы».\n\n"
    "🚨🚨🚨 АБСОЛЮТНЫЙ ЗАПРЕТ — НИКАКИХ ВЫМЫШЛЕННЫХ ГЕРОЕВ И ИСТОРИЙ 🚨🚨🚨\n"
    "Pavel явно сказал: «никаких вымышленных героев мы не будем писать никогда».\n"
    "ЗАПРЕЩЕНО упоминать в вопросах или рекомендациях:\n"
    "  • Иоанна из Анжера 1612, монаха на Афоне 1347, Хильдегарду Бингенскую\n"
    "  • Любые «реконструированные» исторические сцены (Безье 1209, Вавилон, Псков)\n"
    "  • Любые вымышленные литературные персонажи или 'примеры из истории'\n"
    "ЕДИНСТВЕННЫЙ ИСТОЧНИК конкретики: реальный опыт Pavel-а. Если в его голосовых "
    "надиктовках нет конкретного человека/случая — НЕ ПРИДУМЫВАЙ. Лучше спроси у Pavel-а "
    "напрямую: «Ты сам видел такое? Кто это был, где?»\n\n"
    "Твоя работа: посмотри текущий текст главы + список правок которые Pavel отметил + "
    "потерянные с голосовых идеи. Найди ОДИН-ТРИ места где недостаёт конкретики/опыта/"
    "примера/года/имени/телесной детали для того чтобы переписанная глава стала шедевром.\n\n"
    "Задай ОДИН вопрос за раз. Вопросы:\n"
    "  • Конкретные (не «расскажи в общем», а «ты был в …? что именно видел?»)\n"
    "  • Связанные с конкретным параграфом или правкой\n"
    "  • Открытые (Pavel рассказывает своим голосом, не да/нет)\n"
    "  • Без преамбулы — сразу вопрос\n"
    "  • НИКОГДА не предлагай в вопросе вымышленных имён или дат как пример\n\n"
    "Канон Pavel-а: первое лицо Я-свидетель, телесные якоря из реальной жизни Pavel-а, "
    "без AI-клише, без хеджа. Без тире (UC-76). Без контраст-пар «не X, а Y».\n\n"
    "🛡️ ЗАЩИТА АВТОРСКОГО ГОЛОСА (UC-135 regression audit):\n"
    "НИКОГДА не задавай вопросов которые провоцируют «нормализовать» стиль Pavel-а:\n"
    "  • НЕ спрашивай «можно сократить?» / «не слишком ли много повторов?» — анафоры это канон.\n"
    "  • НЕ предлагай «заменить торжественный глагол на бытовой» через вопрос.\n"
    "  • НЕ просись разбивать длинные предложения «для читабельности».\n"
    "Твоя цель — собрать новый КОНКРЕТНЫЙ материал у Pavel-а, а не помочь Opus-у «причесать» текст.\n\n"
    "Финал: когда задал 3-5 вопросов или чувствуешь что больше не нужно — верни JSON\n"
    '{"complete": true, "summary": "что Pavel рассказал и как это поможет рерайту"}.\n'
    'До этого — обычный текст вопроса.'
)


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def call_opus(messages, system):
    token = get_token()
    if not token:
        return None, "no oauth token"
    body = {
        "model": MAX_MODEL,
        "max_tokens": 1500,
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
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:
        return None, str(e)
    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(blocks).strip(), None


def load_chapter_draft(chapter_id):
    m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
    if not m:
        return None
    book_id = m.group(1)
    p = V2 / "chapters" / book_id / chapter_id / "draft.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def build_initial_user(chapter_id, selected_fixes, chapter_text):
    """Первое сообщение Журналисту: контекст главы + выбранные правки."""
    parts = [f"# ГЛАВА: {chapter_id}\n"]
    parts.append("# ТЕКУЩИЙ ТЕКСТ ГЛАВЫ\n")
    parts.append(chapter_text[:12000])
    parts.append("\n\n# ВЫБРАННЫЕ PAVEL-ом ПРАВКИ\n")
    if not selected_fixes:
        parts.append("(пусто — Pavel не отметил конкретных правок, но хочет общего шлифа)")
    else:
        for i, f in enumerate(selected_fixes, 1):
            critic = f.get("critic") or f.get("source") or "?"
            text = f.get("text") or f.get("comment") or ""
            meta = f.get("meta") or f.get("category") or ""
            parts.append(f"{i}. [{critic}] {text[:300]} {('· ' + meta) if meta else ''}")
    parts.append("\n\n# ЗАДАНИЕ\nНайди ОДНО самое важное место где не хватает конкретики и задай ОДИН точечный вопрос Pavel-у. Не объясняй что собираешься делать — сразу вопрос.")
    return "\n".join(parts)


def start_session(chapter_id, selected_fixes):
    chapter_text = load_chapter_draft(chapter_id)
    if not chapter_text:
        return {"ok": False, "error": f"no draft for {chapter_id}"}
    session_id = uuid.uuid4().hex[:12]
    user_msg = build_initial_user(chapter_id, selected_fixes, chapter_text)
    messages = [{"role": "user", "content": user_msg}]
    question, err = call_opus(messages, SYSTEM)
    if err:
        return {"ok": False, "error": err}
    messages.append({"role": "assistant", "content": question})
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": session_id,
        "chapter_id": chapter_id,
        "selected_fixes_count": len(selected_fixes or []),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "messages": messages,
        "qa": [{"q": question, "a": None}],
        "complete": False,
    }
    out = SESSIONS_DIR / f"{session_id}.json"
    out.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "session_id": session_id, "question": question, "complete": False, "qa_count": 1}


def load_session(session_id):
    p = SESSIONS_DIR / f"{session_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_session(s):
    p = SESSIONS_DIR / f"{s['session_id']}.json"
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def answer(session_id, answer_text, skip=False):
    """skip=True — Pavel сказал пропустить этот вопрос. Журналист задаст ДРУГОЙ вопрос."""
    s = load_session(session_id)
    if not s:
        return {"ok": False, "error": "session not found"}
    if s.get("complete"):
        return {"ok": False, "error": "session already complete"}
    # обновляем последний qa
    if s["qa"] and s["qa"][-1]["a"] is None:
        if skip:
            s["qa"][-1]["a"] = "[ПРОПУЩЕНО Pavel-ом — вопрос неподходящий]"
            s["qa"][-1]["skipped"] = True
            # отдельное сообщение для Opus
            s["messages"].append({"role": "user", "content": "Пропускаю этот вопрос — он не подходит (вымышленный пример, неуместный, неудачная формулировка). Задай ДРУГОЙ вопрос о другой стороне главы. Помни: НИКАКИХ вымышленных имен или историй."})
        else:
            s["qa"][-1]["a"] = answer_text
            s["messages"].append({"role": "user", "content": answer_text})
    else:
        s["messages"].append({"role": "user", "content": answer_text})
    # Ограничение: 5 вопросов максимум
    if len([qa for qa in s["qa"] if qa.get("a")]) >= 5:
        s["complete"] = True
        s["summary"] = "Достигнут лимит в 5 вопросов. Pavel дал достаточно информации."
        save_session(s)
        return {"ok": True, "complete": True, "summary": s["summary"], "qa_count": len(s["qa"])}
    # Иначе — следующий вопрос
    nxt, err = call_opus(s["messages"], SYSTEM)
    if err:
        return {"ok": False, "error": err}
    # Проверим — может AI вернул JSON с complete:true
    is_complete = False
    summary = ""
    try:
        # Может быть просто текст вопроса или JSON
        if nxt.startswith("{") or "complete" in nxt.lower()[:200]:
            clean = nxt
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean
                if clean.endswith("```"):
                    clean = clean.rsplit("```", 1)[0]
                if clean.startswith("json"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean
            parsed = json.loads(clean.strip())
            if isinstance(parsed, dict) and parsed.get("complete"):
                is_complete = True
                summary = parsed.get("summary", "")
    except Exception:
        pass
    s["messages"].append({"role": "assistant", "content": nxt})
    if is_complete:
        s["complete"] = True
        s["summary"] = summary or "Журналист завершил сессию."
        save_session(s)
        return {"ok": True, "complete": True, "summary": s["summary"], "qa_count": len(s["qa"])}
    s["qa"].append({"q": nxt, "a": None})
    save_session(s)
    return {"ok": True, "complete": False, "question": nxt, "qa_count": len(s["qa"])}


def get_pavel_context(session_id):
    """Сформировать блок текста для инжектирования в Opus prompt после Q&A."""
    s = load_session(session_id)
    if not s:
        return ""
    if not s.get("qa"):
        return ""
    lines = ["## Pavel ответил Журналисту перед рерайтом:"]
    for i, qa in enumerate(s["qa"], 1):
        if qa.get("a"):
            lines.append(f"\nВопрос {i}: {qa['q']}")
            lines.append(f"Ответ Pavel-а: {qa['a']}")
    if s.get("summary"):
        lines.append(f"\nИтог: {s['summary']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--chapter-id", required=True)
    s.add_argument("--fixes-json", default="[]", help='JSON array of selected fixes')
    a = sub.add_parser("answer")
    a.add_argument("--session-id", required=True)
    a.add_argument("--answer", required=True)
    args = ap.parse_args()
    if args.cmd == "start":
        fixes = json.loads(args.fixes_json)
        print(json.dumps(start_session(args.chapter_id, fixes), ensure_ascii=False, indent=2))
    elif args.cmd == "answer":
        print(json.dumps(answer(args.session_id, args.answer), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main() or 0)
