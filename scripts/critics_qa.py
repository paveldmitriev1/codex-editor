#!/usr/bin/env python3
"""
critics_qa.py — Критики-Q&A (UC-91).

Pavel 2026-05-21: после Журналиста (UC-90) и ДО написания главы Opus-ом
каждый из 15 критиков получает контекст темы + Q&A Журналиста и задаёт
свой уточняющий вопрос с собственного угла (voice_purity, ai_tells,
sacred_lexicon, council_tolstoy и т.д.). Pavel отвечает — критик либо
просит ещё уточнение, либо «УДОВЛЕТВОРЁН: <резюме>».

Сессия закрыта (`all_satisfied: true`) когда все критики удовлетворены.

Workflow:
1. start_session(journalist_session_id) — загружает Q&A Журналиста,
   для каждого включённого критика делает Opus call с system promptом
   критика + context (тема + Q&A) → получает первый вопрос. Делает
   sequentially (5-10 min на старт нормально).
2. answer(session_id, critic_id, answer) — добавляет ответ Pavel-а
   в conversation именно этого критика, делает Opus call, получает
   следующий вопрос ИЛИ маркер «УДОВЛЕТВОРЁН: ...» с summary.
3. get_session(session_id) — читать текущее состояние.

Storage: data/critics-qa-sessions/<id>.json

Запуск standalone (для теста):
  python3 critics_qa.py --start <journalist_session_id>
  python3 critics_qa.py --answer <session_id> <critic_id> "ответ"
  python3 critics_qa.py --get <session_id>
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
SESSIONS_DIR = V2 / "data/critics-qa-sessions"
JOURNALIST_SESSIONS_DIR = V2 / "data/journalist-sessions"
CRITICS_CONFIG = V2 / "data/critics-config.json"

SATISFIED_MARKER = "УДОВЛЕТВОРЁН"


# ─── helpers ────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def load_critics_config() -> dict:
    """Грузим из data/critics-config.json. Fallback на DEFAULT_CRITICS из critic_council."""
    if CRITICS_CONFIG.exists():
        try:
            return json.loads(CRITICS_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    # fallback
    try:
        sys.path.insert(0, str(V2 / "scripts"))
        from critic_council import DEFAULT_CRITICS
        return DEFAULT_CRITICS
    except Exception:
        return {}


def load_journalist_session(journalist_session_id: str):
    p = JOURNALIST_SESSIONS_DIR / f"{journalist_session_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_journalist_qa_block(journalist_session: dict) -> str:
    """Превращаем messages журналиста в читабельный Q&A блок.
    Пропускаем первый message с kind='context_dump' (он только для AI).
    """
    msgs = journalist_session.get("messages", [])
    parts = []
    for m in msgs:
        if m.get("kind") == "context_dump":
            continue
        role = m.get("role")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if role == "journalist":
            kind = m.get("kind", "question")
            if kind == "completion":
                parts.append(f"## Резюме Журналиста\n\n{text}")
            else:
                parts.append(f"### Вопрос Журналиста\n\n{text}")
        elif role == "pavel":
            parts.append(f"### Ответ Pavel-а\n\n{text}")
        elif role == "user":
            parts.append(f"### Ответ Pavel-а\n\n{text}")
    return "\n\n".join(parts)


def build_critic_system(critic_id: str, critic_cfg: dict) -> str:
    """Готовим system prompt для критика-в-Q&A режиме.
    Базовый system промпт критика + инструкция вести Q&A до удовлетворения.
    """
    base_system = critic_cfg.get("system", "")
    label = critic_cfg.get("label", critic_id)
    qa_instructions = f"""
# ВАЖНО: ты сейчас НЕ оцениваешь готовую главу. Глава ещё не написана.

Pavel (Хилингод) задумал новую главу. Журналист уже задал ему свои вопросы и Pavel ответил. Теперь твой ход: твоя задача как «{label}» — задать СВОЙ уточняющий вопрос ДО того, как Opus начнёт писать главу, чтобы заранее предотвратить нарушения по твоей зоне ответственности.

# Что делать

1. Прочитай тему главы и Q&A Журналиста.
2. С точки зрения твоего критерия («{label}»), реши: есть ли в материале что-то, что тревожит тебя? Где Pavel может скатиться в нарушения по твоей зоне? Что нужно уточнить, чтобы глава вышла чистой?
3. Задай ОДИН точный вопрос Pavel-у. Один. Не два. Не «вопрос плюс комментарий».
4. Pavel ответит. Дальше у тебя выбор:
   - Если ответ снял твою тревогу — выдай ровно одну строку: «{SATISFIED_MARKER}: <короткое резюме того, что Pavel прояснил>». Резюме 1-3 предложения, оно пойдёт в Opus.
   - Если осталась неясность — задай ещё один уточняющий вопрос.
5. Норма 1-4 вопроса. Больше 5 — ты застрял.

# Тон

- Без преамбулы. Без «спасибо за ответ». Только вопрос или маркер удовлетворения.
- Можешь сослаться на свою специализацию: «как критик {label}, меня беспокоит...».
- Конкретный, точный, по своей зоне. Не лезь в зоны других критиков.
- Pavel может ответить голосом (с ошибками транскрипции — интерпретируй смысл).

# Чем твой вопрос отличается от вопроса Журналиста

Журналист собирал общее содержание главы. Ты заранее ловишь риски ПО СВОЕЙ ЗОНЕ. Например voice_purity ловит места где Pavel может сорваться в академический регистр; sacred_lexicon ловит запрещённую лексику; rhythm ловит риск монотонии; council_tolstoy ловит риск красивости и позы; и так далее. Ниже — твой полный профиль (читай как свой характер).

---

{base_system}
"""
    return qa_instructions.strip()


def call_opus(messages: list, system: str, thinking_budget: int = 3000) -> dict:
    """Вызов Opus через прокси. Возвращает {ok, text, usage}."""
    token = get_token()
    if not token:
        return {"ok": False, "error": "no OAuth token"}
    body = {
        "model": MAX_MODEL,
        "max_tokens": 4000,
        "thinking": {"type": "enabled", "budget_tokens": thinking_budget},
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


# ─── storage ───────────────────────────────────────────────────────────

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


# ─── core ──────────────────────────────────────────────────────────────

def _parse_satisfaction(text: str):
    """Если в тексте есть маркер удовлетворения — вернуть (True, summary).
    Иначе (False, None).
    """
    if SATISFIED_MARKER not in text:
        return False, None
    # Берём всё что после первого вхождения маркера
    idx = text.find(SATISFIED_MARKER)
    after = text[idx + len(SATISFIED_MARKER):].lstrip(":：— -\n\t")
    summary = after.strip()
    # Если после маркера — пусто, попробуем взять до маркера
    if not summary:
        summary = text[:idx].strip()
    return True, summary or text.strip()


def _critic_initial_user_message(topic: str, journalist_qa: str) -> str:
    parts = []
    parts.append(f"# Тема новой главы\n\n{topic}\n")
    if journalist_qa:
        parts.append(f"# Q&A Журналиста с Pavel-ом\n\n{journalist_qa}\n")
    parts.append(
        "Задай Pavel-у ОДИН точный уточняющий вопрос с точки зрения твоей специализации. "
        "Один вопрос. Без преамбулы."
    )
    return "\n\n".join(parts)


def _messages_for_opus(critic_state: dict) -> list:
    """Реконструируем chat history конкретного критика для Opus.
    role=critic → assistant, role=pavel → user. Первое user-сообщение
    (initial context) восстанавливаем из session-уровня — но мы сохраняем
    его как первый message в critic_state.messages с role='user_initial'.
    """
    out = []
    for m in critic_state.get("messages", []):
        role = m.get("role")
        text = m.get("text", "")
        if role in ("user_initial", "pavel"):
            out.append({"role": "user", "content": text})
        elif role == "critic":
            out.append({"role": "assistant", "content": text})
    return out


def start_session(journalist_session_id: str) -> dict:
    """Создать сессию критиков-Q&A: каждый включённый критик делает Opus call,
    получает первый вопрос. Делает sequentially (5-10 min суммарно).
    """
    jsess = load_journalist_session(journalist_session_id)
    if not jsess:
        return {"ok": False, "error": f"journalist session {journalist_session_id} not found"}
    topic = jsess.get("topic", "")
    journalist_qa = build_journalist_qa_block(jsess)
    initial_user = _critic_initial_user_message(topic, journalist_qa)

    cfg = load_critics_config()
    if not cfg:
        return {"ok": False, "error": "no critics config (data/critics-config.json missing and fallback failed)"}

    session_id = uuid.uuid4().hex[:12]
    session = {
        "session_id": session_id,
        "journalist_session_id": journalist_session_id,
        "topic": topic,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "critics": {},
        "all_satisfied": False,
        "usage_total": {"input_tokens": 0, "output_tokens": 0},
    }

    # synthesis-критик не задаёт вопросов на этапе предварительного Q&A
    # (он работает с готовой главой и результатами других критиков).
    # Поэтому пропускаем его.
    SKIP_CRITICS = {"synthesis"}

    enabled_ids = [
        cid for cid, c in cfg.items()
        if c.get("enabled") and cid not in SKIP_CRITICS
    ]

    for cid in enabled_ids:
        c = cfg[cid]
        system = build_critic_system(cid, c)
        thinking_budget = min(c.get("thinking_budget", 3000), 4000)
        # Первый вопрос
        first_messages = [{"role": "user", "content": initial_user}]
        result = call_opus(first_messages, system=system, thinking_budget=thinking_budget)
        if not result.get("ok"):
            # Запишем критика как недоступного, но не валим всю сессию.
            session["critics"][cid] = {
                "label": c.get("label", cid),
                "group": c.get("group", "technical"),
                "messages": [
                    {"role": "user_initial", "text": initial_user, "ts": now_iso()},
                ],
                "satisfied": False,
                "summary": None,
                "error": result.get("error", "unknown"),
            }
            continue
        question = result["text"]
        satisfied, summary = _parse_satisfaction(question)
        session["critics"][cid] = {
            "label": c.get("label", cid),
            "group": c.get("group", "technical"),
            "messages": [
                {"role": "user_initial", "text": initial_user, "ts": now_iso()},
                {
                    "role": "critic",
                    "text": question,
                    "ts": now_iso(),
                    "kind": "completion" if satisfied else "question",
                },
            ],
            "satisfied": satisfied,
            "summary": summary if satisfied else None,
        }
        u = result.get("usage", {})
        session["usage_total"]["input_tokens"] += u.get("input_tokens") or 0
        session["usage_total"]["output_tokens"] += u.get("output_tokens") or 0

    # Все удовлетворены?
    session["all_satisfied"] = _is_all_satisfied(session)
    save_session(session)
    return {"ok": True, "session": _session_for_ui(session)}


def answer(session_id: str, critic_id: str, pavel_answer: str) -> dict:
    """Pavel ответил конкретному критику. Получаем следующий вопрос или маркер."""
    session = load_session(session_id)
    if not session:
        return {"ok": False, "error": f"session {session_id} not found"}
    critic_state = session.get("critics", {}).get(critic_id)
    if not critic_state:
        return {"ok": False, "error": f"critic {critic_id} not in this session"}
    if critic_state.get("satisfied"):
        return {"ok": False, "error": f"critic {critic_id} already satisfied"}
    pavel_answer = (pavel_answer or "").strip()
    if not pavel_answer:
        return {"ok": False, "error": "empty answer"}

    # Добавим ответ Pavel-а в историю
    critic_state["messages"].append({
        "role": "pavel",
        "text": pavel_answer,
        "ts": now_iso(),
    })

    # Загрузим конфиг этого критика
    cfg = load_critics_config()
    c = cfg.get(critic_id)
    if not c:
        save_session(session)
        return {"ok": False, "error": f"critic {critic_id} config not found"}
    system = build_critic_system(critic_id, c)
    thinking_budget = min(c.get("thinking_budget", 3000), 4000)

    chat = _messages_for_opus(critic_state)
    result = call_opus(chat, system=system, thinking_budget=thinking_budget)
    if not result.get("ok"):
        save_session(session)  # сохраним ответ Pavel-а
        return {"ok": False, "error": result.get("error", "unknown")}

    text = result["text"]
    satisfied, summary = _parse_satisfaction(text)
    critic_state["messages"].append({
        "role": "critic",
        "text": text,
        "ts": now_iso(),
        "kind": "completion" if satisfied else "question",
    })
    if satisfied:
        critic_state["satisfied"] = True
        critic_state["summary"] = summary

    u = result.get("usage", {})
    prev = session.get("usage_total", {"input_tokens": 0, "output_tokens": 0})
    session["usage_total"] = {
        "input_tokens": prev.get("input_tokens", 0) + (u.get("input_tokens") or 0),
        "output_tokens": prev.get("output_tokens", 0) + (u.get("output_tokens") or 0),
    }

    session["all_satisfied"] = _is_all_satisfied(session)
    save_session(session)
    return {"ok": True, "session": _session_for_ui(session)}


def _is_all_satisfied(session: dict) -> bool:
    critics = session.get("critics", {})
    if not critics:
        return False
    # Игнорируем критиков с error (они не блокируют all_satisfied,
    # но сохраняются как «недоступные»).
    actionable = [s for s in critics.values() if not s.get("error")]
    if not actionable:
        return False
    return all(s.get("satisfied") for s in actionable)


def _critic_for_ui(critic_state: dict) -> dict:
    """Облегчённая форма критика для UI: убираем огромный user_initial текст
    (показываем только в первый раз? нет, вообще убираем — UI не нуждается).
    """
    msgs = []
    for m in critic_state.get("messages", []):
        if m.get("role") == "user_initial":
            continue
        msgs.append({
            "role": m.get("role"),
            "text": m.get("text"),
            "ts": m.get("ts"),
            "kind": m.get("kind"),
        })
    out = {
        "label": critic_state.get("label"),
        "group": critic_state.get("group"),
        "satisfied": critic_state.get("satisfied", False),
        "summary": critic_state.get("summary"),
        "messages": msgs,
        "question_count": sum(1 for m in msgs if m.get("role") == "critic" and m.get("kind") != "completion"),
        "answer_count": sum(1 for m in msgs if m.get("role") == "pavel"),
    }
    if critic_state.get("error"):
        out["error"] = critic_state["error"]
    return out


def _session_for_ui(session: dict) -> dict:
    critics_ui = {cid: _critic_for_ui(s) for cid, s in session.get("critics", {}).items()}
    return {
        "session_id": session["session_id"],
        "journalist_session_id": session.get("journalist_session_id"),
        "topic": session.get("topic"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "all_satisfied": session.get("all_satisfied", False),
        "critics": critics_ui,
        "critics_total": len(critics_ui),
        "critics_satisfied": sum(1 for c in critics_ui.values() if c.get("satisfied")),
        "critics_errored": sum(1 for c in critics_ui.values() if c.get("error")),
        "usage_total": session.get("usage_total", {}),
    }


def list_sessions() -> list:
    if not SESSIONS_DIR.exists():
        return []
    out = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            critics = s.get("critics", {})
            out.append({
                "session_id": s["session_id"],
                "journalist_session_id": s.get("journalist_session_id"),
                "topic": s.get("topic"),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
                "all_satisfied": s.get("all_satisfied", False),
                "critics_total": len(critics),
                "critics_satisfied": sum(1 for c in critics.values() if c.get("satisfied")),
                "critics_errored": sum(1 for c in critics.values() if c.get("error")),
            })
        except Exception:
            continue
    return out


# ─── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="journalist_session_id (создаёт сессию критиков-Q&A)")
    parser.add_argument("--answer", nargs=3, metavar=("SESSION_ID", "CRITIC_ID", "ANSWER"),
                        help="ответить конкретному критику в сессии")
    parser.add_argument("--list", action="store_true", help="список сессий")
    parser.add_argument("--get", help="получить сессию по id")
    args = parser.parse_args()
    if args.start:
        r = start_session(args.start)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif args.answer:
        r = answer(args.answer[0], args.answer[1], args.answer[2])
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
