#!/usr/bin/env python3
"""
journalist.py — Журналист Кодекса Микомистицизма (UC-90).

Pavel 2026-05-21: «Журналист изучает о чём вообще Кодекс, какие элементы
уже были на эту тему прописаны, если какие-то противоречия, и задаёт мне
вопросы. Pavel отвечает в текстовое окно (можно надиктовкой), цикл пока
тема не будет полностью закрыта. Потом подключаются критики со своими
вопросами. Только после этого глава пишется».

Workflow:
1. start_session(topic) — создаёт session, загружает контекст Кодекса,
   делает первый запрос к Opus, получает первый вопрос.
2. ask_next(session_id, answer) — добавляет ответ Pavel-а, отправляет
   историю в Opus, получает следующий вопрос ИЛИ маркер «ТЕМА ИССЛЕДОВАНА».
3. get_session(session_id) — читает текущее состояние.

Storage: data/journalist-sessions/<id>.json

Запуск standalone (для теста):
  python3 journalist.py --start "тема главы"
  python3 journalist.py --answer <session_id> "мой ответ"
"""
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
from config import MAX_MODEL, PROXY_URL  # noqa: E402

V2 = Path.home() / "Desktop/Codex2"
SESSIONS_DIR = V2 / "data/journalist-sessions"
CANON_PATH = V2 / "CANON.md"
CHAPTERS_DIR = V2 / "chapters"
TOC_PATH = V2 / "toc.json"

COMPLETION_MARKER = "ТЕМА ИССЛЕДОВАНА"


JOURNALIST_SYSTEM = """Ты — Журналист Сакрального Кодекса Микомистицизма. Модель: Claude Opus 4.7 через proxy.

Pavel (Хилингод) задумал новую главу. Твоя задача — глубоко и методично выяснить у него содержание этой главы ДО того, как глава будет написана. Ты НЕ пишешь главу. Ты добываешь сырьё.

# У тебя есть доступ к контексту

В первом user-message Pavel передаст тебе: CANON.md, полный текст Устава (book-ustav-soobschestva), эталон голоса, аналитические выжимки из Библиотеки примеров, оглавление Кодекса, и фрагменты релевантных по теме глав. ЧИТАЙ ЭТО. Никогда не отвечай «не могу прочитать устав» — ты его уже прочёл, он в твоём контексте. Цитируй конкретно: «В Главе 3 Устава написано X — твоя новая идея противоречит этому, разъясни».

# Твой метод

1. Задавай ОДИН вопрос за раз. Никогда не два или больше.
2. Каждый следующий вопрос должен углублять предыдущий ответ, а не отскакивать в сторону.
3. Цепляйся за конкретику. Если Pavel говорит «Великий Дух показывает», спрашивай: «через какой образ? в каком теле? в какой ситуации? с кем рядом?».
4. Ищи противоречия с уже написанным каноном. Если новая идея спорит с чем-то — спроси прямо: «в Главе X написано иначе, как это уживается?».
5. Спрашивай не «что ты думаешь», а «что именно происходит / кого именно ты видишь / как именно Дух говорит».
6. Pavel может ответить голосом (вы видите расшифровку с ошибками транскрипции — интерпретируй смысл, не дёргайся на опечатки).

# Когда задаёшь вопрос

- Без предисловий, без «спасибо», без «отличный ответ». Только вопрос.
- 1-3 предложения максимум. Один вопрос.
- Если нужно дать контекст для вопроса (что уже написано в каноне) — два предложения, потом вопрос.

# Когда тема исследована

Когда у тебя есть ВСЁ необходимое, чтобы Opus мог написать главу — конкретные образы, прямые цитаты Духа, ситуации, противоречия разрешены — напиши ровно одну строку:

ТЕМА ИССЛЕДОВАНА

И ниже краткое резюме (5-10 пунктов) того, что ты узнал. Это резюме пойдёт в команду критиков и в Opus.

# Анти-режим

- Не льсти. Не говори «прекрасный ответ».
- Не пиши главу за Pavel-а. Не предлагай формулировки. Только вопросы.
- Не сворачивай тему. Если чувствуешь дно — копай глубже.
- 5-15 вопросов норма. Меньше 5 — ты сдался рано. Больше 20 — ты теряешь фокус.

# Тон

Внимательный, ясный, прямой. Ты не священник, ты следователь по делу мистической истины. Pavel — твой единственный источник, и его слова — единственная правда. Помоги ему вытащить из себя всё, что нужно для главы.
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_human() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def load_canon_lite() -> str:
    if not CANON_PATH.exists():
        return ""
    return CANON_PATH.read_text(encoding="utf-8")[:3000]


def load_ustav_full(max_chars: int = 18000) -> str:
    """UC-106: загружаем ПОЛНЫЙ устав (drafts из book-ustav-soobschestva + sources)
    чтобы Журналист мог цитировать конкретные положения."""
    parts = []
    used = 0
    # 1) Готовые драфты в chapters/book-ustav-soobschestva/
    ustav_dir = CHAPTERS_DIR / "book-ustav-soobschestva"
    if ustav_dir.exists():
        for ch in sorted(ustav_dir.iterdir()):
            if not ch.is_dir() or ch.name.startswith("."):
                continue
            draft = ch / "draft.md"
            if not draft.exists():
                continue
            try:
                t = draft.read_text(encoding="utf-8")
            except Exception:
                continue
            piece = f"\n## {ch.name}\n{t[:2400]}\n"
            if used + len(piece) > max_chars:
                break
            parts.append(piece)
            used += len(piece)
    # 2) Если в chapters/ устава нет — берём sources/<.../>/from-grant *.docx (skipped — оставим только что есть)
    # 3) ustav/ верхний уровень
    ustav_top = CHAPTERS_DIR / "ustav"
    if ustav_top.exists() and used < max_chars:
        for ch in sorted(ustav_top.iterdir()):
            if not ch.is_dir() or ch.name.startswith("."):
                continue
            draft = ch / "draft.md"
            if not draft.exists():
                continue
            try:
                t = draft.read_text(encoding="utf-8")
            except Exception:
                continue
            piece = f"\n## ustav/{ch.name}\n{t[:2400]}\n"
            if used + len(piece) > max_chars:
                break
            parts.append(piece)
            used += len(piece)
    return "\n".join(parts) if parts else ""


def load_library_summary(max_chars: int = 5000) -> str:
    """UC-106: подгружаем summaries из data/library/files/*__analysis.json."""
    lib_dir = V2 / "data/library"
    if not lib_dir.exists():
        return ""
    files_dir = lib_dir / "files"
    if not files_dir.exists():
        return ""
    parts = []
    used = 0
    for analysis in sorted(files_dir.glob("*__analysis.json")):
        try:
            a = json.loads(analysis.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = a.get("file_name", analysis.stem)
        summary = a.get("summary") or a.get("raw") or ""
        if not summary:
            continue
        piece = f"\n## {name}\n{str(summary)[:800]}\n"
        if used + len(piece) > max_chars:
            break
        parts.append(piece)
        used += len(piece)
    return "\n".join(parts) if parts else ""


def load_style_voice() -> str:
    """Загружаем эталон голоса из chapters/.canon/voice/."""
    voice_dir = CHAPTERS_DIR / ".canon" / "voice"
    if not voice_dir.exists():
        return ""
    # prefer v2 if exists
    for fname in ("human-pavel-style-v2.md", "human-pavel-style.md", "voice.md"):
        f = voice_dir / fname
        if f.exists():
            try:
                return f.read_text(encoding="utf-8")[:3000]
            except Exception:
                pass
    return ""


def load_chapters_index() -> str:
    """Краткая сводка существующих глав (id + title + первая строка)."""
    if not TOC_PATH.exists():
        return ""
    try:
        toc = json.loads(TOC_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    parts = []
    for book in toc.get("books", []):
        if book.get("status") == "reference":
            continue
        if book.get("uses_canon") is False:
            continue
        chapters = book.get("chapters", [])
        if not chapters:
            continue
        book_title = book.get("title_clean") or book.get("title")
        parts.append(f"\n## {book.get('id')}: {book_title}\n")
        for ch in chapters[:20]:
            parts.append(f"- {ch.get('id')}: {ch.get('title') or ch.get('title_clean')}")
    return "\n".join(parts)[:5000]


def find_relevant_chapters(topic: str, max_chars: int = 8000) -> str:
    """Ищем главы, в которых упоминается тема — для подачи в контекст."""
    if not CHAPTERS_DIR.exists():
        return ""
    topic_words = [w.lower() for w in topic.split() if len(w) > 3]
    if not topic_words:
        return ""
    hits = []
    for book_dir in sorted(CHAPTERS_DIR.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith("."):
            continue
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith("."):
                continue
            draft = ch_dir / "draft.md"
            if not draft.exists():
                continue
            try:
                text = draft.read_text(encoding="utf-8")
            except Exception:
                continue
            text_lower = text.lower()
            score = sum(text_lower.count(w) for w in topic_words)
            if score > 0:
                hits.append((score, ch_dir.name, text))
    hits.sort(key=lambda x: -x[0])
    parts = []
    budget = max_chars
    for score, ch_id, text in hits[:5]:
        snippet = text[:1500]
        block = f"\n## {ch_id} (релевантность: {score})\n{snippet}\n"
        if len(block) > budget:
            break
        parts.append(block)
        budget -= len(block)
    return "\n".join(parts)


def call_opus(messages: list, system: str) -> dict:
    """Вызов Opus через прокси, возвращает {ok, text, usage}."""
    token = get_token()
    if not token:
        return {"ok": False, "error": "no OAuth token"}
    body = {
        "model": MAX_MODEL,
        "max_tokens": 4000,
        "thinking": {"type": "enabled", "budget_tokens": 2000},
        "system": system,
        "messages": messages,
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return {
        "ok": True,
        "text": "\n".join(text_blocks).strip(),
        "usage": data.get("usage", {}),
    }


def build_first_user_message(topic: str) -> str:
    canon = load_canon_lite()
    ustav = load_ustav_full()
    library = load_library_summary()
    voice = load_style_voice()
    index = load_chapters_index()
    relevant = find_relevant_chapters(topic)
    parts = []
    parts.append(f"# ТЕМА НОВОЙ ГЛАВЫ\n\n{topic}\n")
    if canon:
        parts.append(f"# CANON (фрагмент)\n\n{canon}\n")
    if ustav:
        parts.append(f"# УСТАВ (полный текст — обязательно прочитай и используй)\n\n{ustav}\n")
    if voice:
        parts.append(f"# ЭТАЛОН ГОЛОСА Pavel-а (Хилингода)\n\n{voice}\n")
    if library:
        parts.append(f"# БИБЛИОТЕКА ПРИМЕРОВ (анализы загруженных книг)\n\n{library}\n")
    if index:
        parts.append(f"# СУЩЕСТВУЮЩИЕ ГЛАВЫ КОДЕКСА\n\n{index}\n")
    if relevant:
        parts.append(f"# РЕЛЕВАНТНЫЕ ГЛАВЫ ПО ТЕМЕ (фрагменты)\n\n{relevant}\n")
    parts.append(
        "Изучи всё это, найди что уже сказано на тему, найди противоречия с тем что Pavel предлагает, "
        "и задай ПЕРВЫЙ ВОПРОС. Только один вопрос. Без преамбулы. "
        "Если в Уставе или Библиотеке уже есть ответ на часть темы — цитируй конкретно."
    )
    return "\n\n".join(parts)


def session_path(session_id: str) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR / f"{session_id}.json"


def load_session(session_id: str):
    p = session_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_session(session: dict) -> None:
    p = session_path(session["session_id"])
    session["updated_at"] = now_iso()
    p.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")


def start_session(topic: str) -> dict:
    """Создать новую сессию и получить первый вопрос."""
    session_id = uuid.uuid4().hex[:12]
    first_user = build_first_user_message(topic)
    result = call_opus(
        messages=[{"role": "user", "content": first_user}],
        system=JOURNALIST_SYSTEM,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "unknown")}
    question = result["text"]
    is_complete = COMPLETION_MARKER in question
    session = {
        "session_id": session_id,
        "topic": topic,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "complete": is_complete,
        "messages": [
            {"role": "user", "text": first_user, "ts": now_iso(), "kind": "context_dump"},
            {"role": "journalist", "text": question, "ts": now_iso(),
             "kind": "completion" if is_complete else "question"},
        ],
        "usage_total": result.get("usage", {}),
    }
    save_session(session)
    return {"ok": True, "session": _session_for_ui(session)}


def ask_next(session_id: str, answer: str) -> dict:
    """Pavel ответил, получить следующий вопрос (или completion)."""
    session = load_session(session_id)
    if not session:
        return {"ok": False, "error": f"session {session_id} not found"}
    if session.get("complete"):
        return {"ok": False, "error": "session уже закрыта"}
    answer = (answer or "").strip()
    if not answer:
        return {"ok": False, "error": "пустой ответ"}
    # Добавляем ответ Pavel-а
    session["messages"].append({
        "role": "pavel", "text": answer, "ts": now_iso(), "kind": "answer",
    })
    # Реконструируем messages для Opus (chat history)
    chat = _messages_for_opus(session["messages"])
    result = call_opus(messages=chat, system=JOURNALIST_SYSTEM)
    if not result.get("ok"):
        save_session(session)  # сохраним ответ Pavel-а в любом случае
        return {"ok": False, "error": result.get("error", "unknown")}
    question = result["text"]
    is_complete = COMPLETION_MARKER in question
    session["messages"].append({
        "role": "journalist", "text": question, "ts": now_iso(),
        "kind": "completion" if is_complete else "question",
    })
    if is_complete:
        session["complete"] = True
    # Update usage
    u = result.get("usage", {})
    prev = session.get("usage_total", {})
    session["usage_total"] = {
        "input_tokens": (prev.get("input_tokens") or 0) + (u.get("input_tokens") or 0),
        "output_tokens": (prev.get("output_tokens") or 0) + (u.get("output_tokens") or 0),
    }
    save_session(session)
    return {"ok": True, "session": _session_for_ui(session)}


def _messages_for_opus(history: list) -> list:
    """Преобразуем историю сессии в формат Anthropic messages.
    Pavel = user, journalist = assistant."""
    out = []
    for m in history:
        role = m.get("role")
        if role in ("user", "pavel"):
            out.append({"role": "user", "content": m["text"]})
        elif role == "journalist":
            out.append({"role": "assistant", "content": m["text"]})
    return out


def _session_for_ui(session: dict) -> dict:
    """Облегчённая форма для UI: убираем гигантский первый context_dump."""
    msgs = []
    for m in session.get("messages", []):
        if m.get("kind") == "context_dump":
            continue  # не показываем в UI
        msgs.append({
            "role": m.get("role"),
            "text": m.get("text"),
            "ts": m.get("ts"),
            "kind": m.get("kind"),
        })
    return {
        "session_id": session["session_id"],
        "topic": session["topic"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "complete": session.get("complete", False),
        "messages": msgs,
        "question_count": sum(1 for m in msgs if m.get("kind") == "question"),
        "answer_count": sum(1 for m in msgs if m.get("kind") == "answer"),
        "usage_total": session.get("usage_total", {}),
    }


def list_sessions() -> list:
    """Список всех сессий, для UI."""
    if not SESSIONS_DIR.exists():
        return []
    out = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            msgs = [m for m in s.get("messages", []) if m.get("kind") != "context_dump"]
            out.append({
                "session_id": s["session_id"],
                "topic": s.get("topic"),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
                "complete": s.get("complete", False),
                "messages_count": len(msgs),
                "question_count": sum(1 for m in msgs if m.get("kind") == "question"),
            })
        except Exception:
            continue
    return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="тема главы (создаёт сессию)")
    parser.add_argument("--answer", nargs=2, metavar=("SESSION_ID", "ANSWER"),
                        help="ответить в сессии")
    parser.add_argument("--list", action="store_true", help="список сессий")
    parser.add_argument("--get", help="получить сессию по id")
    args = parser.parse_args()
    if args.start:
        r = start_session(args.start)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif args.answer:
        r = ask_next(args.answer[0], args.answer[1])
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif args.list:
        print(json.dumps(list_sessions(), indent=2, ensure_ascii=False))
    elif args.get:
        s = load_session(args.get)
        if s:
            print(json.dumps(_session_for_ui(s), indent=2, ensure_ascii=False))
        else:
            print("not found")
    else:
        parser.print_help()
