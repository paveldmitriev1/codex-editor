#!/usr/bin/env python3
"""UC-124: Reconciler рекомендаций.

Pavel: «рекомендации должны быть логически проверены и не конфликтовать одна
с другой. Приоритет голосовые + Журналист — все остальные после них. Перед
выдачей рекомендаций AI должен сверить, убрать конфликты, выдать результат».

Workflow:
  1. Собрать ВСЕ рекомендации из critics/synthesis/elder/voice/personas/density/logic/...
  2. Каждой назначить priority_tier (1=voice, 2=journalist, 3=synthesis, 4=elders, 5=technical)
  3. Запустить Opus reconciliation:
     - Найти семантические дубли (две правки про один и тот же параграф)
     - Найти противоречия (mystical_depth «развернуть» vs Толстой «резать»)
     - Решить кто прав по контексту главы
     - Удалить дубли (оставить высший priority_tier)
     - Вернуть чистый ranked список + conflicts_log

Cache: data/reconciled/<chapter_id>.json
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
CACHE_DIR = V2 / "data/reconciled"

PRIORITY_TIER = {
    # 1: голосовые надиктовки — сакральный источник, всегда выигрывают
    "voice_missing": 1,
    "voice_addition": 1,
    # 2: ответы Журналиста — живой контекст от Pavel-а
    "journalist": 2,
    # 3: synthesis priority — главный дирижёр 15 критиков
    "synthesis": 3,
    "synthesis_top5": 3,
    "synthesis_pressure": 3,
    # 4: главный старейшина — топ-4 от классиков
    "chief_elder": 4,
    "council_tolstoy": 4,
    "council_jung": 4,
    "council_mckenna": 4,
    "council_castaneda": 4,
    "council_john": 4,
    "council_laotzu": 4,
    # 5: технические оси
    "voice_purity": 5,
    "ai_tells": 5,
    "mystical_depth": 5,
    "rhythm": 5,
    "sacred_lexicon": 5,
    "paragraph_architecture": 5,
    "opening_closing": 5,
    "resonance": 5,
    # 6: дополнительные параметры
    "density": 6,
    "logic": 6,
    "hook": 6,
    "cliffhanger": 6,
    "style_coherence": 6,
    "style_opus_fix": 6,
    "coherence_in_book": 6,
    # 7: современная аудитория — лёгкий слой
    "persona_musk_loves": 7,
    "persona_musk_loses": 7,
    "persona_musk_observations": 7,
    "persona_musk_suggestions": 7,
}


def tier_for_critic(critic_id):
    if not critic_id:
        return 8
    # точное совпадение
    if critic_id in PRIORITY_TIER:
        return PRIORITY_TIER[critic_id]
    # префикс
    for prefix, tier in PRIORITY_TIER.items():
        if critic_id.startswith(prefix):
            return tier
    return 8


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def call_opus(messages, system, max_tokens=4000):
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
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:
        return None, str(e)
    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(blocks).strip(), data.get("usage", {})


def collect_all_recommendations(full_analysis: dict) -> list:
    """Из full-analysis dict собрать все правки в единый формат:
       { source, text, para_idx, priority_tier, original_critic }
    """
    recs = []

    def add(critic, text, para_idx=None, kind=""):
        if not text or len(str(text).strip()) < 5:
            return
        recs.append({
            "source": critic,
            "text": str(text).strip()[:500],
            "para_idx": para_idx,
            "priority_tier": tier_for_critic(critic),
            "kind": kind,
        })

    # 1) Voice missing — приоритет 1
    for m in (full_analysis.get("voice_missing_ideas") or []):
        text = m if isinstance(m, str) else (m.get("idea") or m.get("text") or "")
        add("voice_missing", text, None, "return_voice")
    for m in (full_analysis.get("voice_additions") or []):
        text = m if isinstance(m, str) else (m.get("text") or m.get("comment") or "")
        add("voice_addition", "ОТКАТИТЬ AI-добавление: " + text, None, "rollback")

    # 2) Synthesis pressure_points + top_5
    critics_data = (full_analysis.get("critics") or {}).get("results") or {}
    synth = (critics_data.get("synthesis") or {}).get("result") or {}
    for pp in (synth.get("pressure_points") or []):
        add("synthesis_pressure", pp.get("fix") or pp.get("issue"), pp.get("para_idx"), "fix")
    for t in (synth.get("top_5_priority_edits") or []):
        add("synthesis_top5", t, None, "priority")

    # 3) Chief elder top-4
    for it in (full_analysis.get("chief_elder_top4") or []):
        add("chief_elder_" + (it.get("critic") or ""), it.get("text"), None, it.get("kind") or "elder")

    # 4) Council elders (individual cuts/strengthens beyond top-4)
    for cid, c in critics_data.items():
        if not cid.startswith("council_") or not c.get("ok"):
            continue
        r = c.get("result") or {}
        for cut in (r.get("top_3_cuts") or []):
            text = cut if isinstance(cut, str) else (cut.get("text") or cut.get("comment") or "")
            add(cid, "✂️ РЕЗАТЬ: " + text, None, "cut")
        for s in (r.get("top_3_strengthen") or []):
            text = s if isinstance(s, str) else (s.get("text") or s.get("comment") or "")
            add(cid, "💪 УСИЛИТЬ: " + text, None, "strengthen")

    # 5) Technical critics
    for cid in ["voice_purity", "ai_tells", "mystical_depth", "rhythm", "sacred_lexicon", "paragraph_architecture", "opening_closing", "resonance"]:
        c = critics_data.get(cid) or {}
        if not c.get("ok"):
            continue
        r = c.get("result") or {}
        viol = r.get("violations") or r.get("weak_passages") or r.get("hits") or []
        for v in viol[:8]:
            text = v.get("fix") or v.get("why") or v.get("issue") or v.get("how_to_deepen") or v.get("pattern") or (v if isinstance(v, str) else "")
            add(cid, text, v.get("para_idx") if isinstance(v, dict) else None, "violation")

    # 6) Param analyzers
    logic = full_analysis.get("logic") or {}
    for it in (logic.get("issues") or []):
        text = (it.get("issue") or "") + (" → " + it.get("fix") if it.get("fix") else "")
        add("logic", text, it.get("para_idx"), "logic_issue")

    resonance = full_analysis.get("resonance") or {}
    for w in (resonance.get("weak_passages") or []):
        add("resonance", (w.get("why") or "") + (" → " + (w.get("fix") or "")), w.get("para_idx"), "weak")

    hc = full_analysis.get("hook_cliff") or {}
    for s in (hc.get("hook_suggestions") or []):
        text = s if isinstance(s, str) else (s.get("text") or "")
        add("hook", "🎣 ОТКРЫТИЕ: " + text, 0, "hook")
    for s in (hc.get("cliffhanger_suggestions") or []):
        text = s if isinstance(s, str) else (s.get("text") or "")
        add("cliffhanger", "🪝 ЗАКРЫТИЕ: " + text, -1, "cliff")

    sc = full_analysis.get("style_coherence") or {}
    for f in (sc.get("opus_fixes") or [])[:10]:
        text = f.get("fix") or f.get("issue") or ""
        add("style_opus_fix", text, f.get("para_idx"), "style")

    # 7) Personas
    personas = (full_analysis.get("personas") or {}).get("personas") or {}
    for pk, p in personas.items():
        if not p or not p.get("ok"):
            continue
        for sec in ["loses", "suggestions"]:
            for it in (p.get(sec) or [])[:3]:
                text = it.get("comment") if isinstance(it, dict) else str(it)
                add("persona_" + pk + "_" + sec, "[" + (p.get("persona_name") or pk) + "] " + text, None, sec)

    return recs


def reconcile(chapter_id: str, full_analysis: dict, force: bool = False) -> dict:
    """Главная функция: запустить Opus reconcile, вернуть очищенный список."""
    if not force:
        cache = CACHE_DIR / f"{chapter_id}.json"
        if cache.exists():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                # Если кэш свежее 24ч — отдаём
                from datetime import datetime as _dt
                ts = cached.get("ts", "")
                if ts:
                    age = (datetime.now(timezone.utc) - _dt.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
                    if age < 86400:
                        return cached
            except Exception:
                pass

    all_recs = collect_all_recommendations(full_analysis)
    if not all_recs:
        return {"ok": False, "error": "нет рекомендаций для reconcile"}

    # Sort by tier for context. para_idx может быть None/int/str — нормализуем в int.
    def _para_key(r):
        pi = r.get("para_idx")
        if pi is None:
            return 999
        try:
            return int(pi)
        except Exception:
            return 999
    all_recs.sort(key=lambda r: (r["priority_tier"], _para_key(r)))

    # Build user prompt
    parts = ["# ВСЕ РЕКОМЕНДАЦИИ ПО ГЛАВЕ\n"]
    for i, r in enumerate(all_recs, 1):
        pi = r.get("para_idx")
        try:
            pi_int = int(pi) if pi is not None else None
        except Exception:
            pi_int = None
        para = f"П{pi_int + 1}" if (pi_int is not None and pi_int >= 0) else "—"
        parts.append(f"{i}. [tier {r['priority_tier']}] [{r['source']}] [{para}] {r['text']}")

    system = (
        "Ты — RECONCILER рекомендаций для редактора Сакрального Кодекса.\n\n"
        "Pavel сказал: «рекомендации должны быть логически проверены и не конфликтовать "
        "одна с другой. Приоритет голосовые + Журналист — все остальные после. Перед "
        "выдачей рекомендаций AI должен сверить, убрать конфликты, выдать результат».\n\n"
        "🚨🚨🚨 АБСОЛЮТНЫЙ ЗАПРЕТ — НИКАКИХ ВЫМЫШЛЕННЫХ ГЕРОЕВ И ИСТОРИЙ 🚨🚨🚨\n"
        "Pavel явно сказал: «никаких вымышленных героев мы не будем писать никогда».\n"
        "ОТФИЛЬТРУЙ все рекомендации которые предлагают:\n"
        "  • «добавить Иоанна из Анжера 1612, монаха на Афоне, Хильдегарду» и т.п.\n"
        "  • «вставить сцену из истории» (Безье, Вавилон, Псков) если это не из Pavel-овских голосовых\n"
        "  • любые литературные/исторические персонажи которых нет в реальном опыте Pavel-а\n"
        "  • придуманных Анну, Михаила, Сергея, Марию — всех безымянных «героев историй».\n"
        "Такие рекомендации помечай как RemovedDuplicates с reason='вымышленные'. ИХ В RECONCILED НЕ КЛАДИ.\n\n"
        "🛡️🛡️🛡️ ЗАЩИТА АВТОРСКОГО ГОЛОСА (UC-135 regression audit) 🛡️🛡️🛡️\n"
        "ОТФИЛЬТРУЙ также рекомендации которые «улучшают» стиль Pavel-а в сторону AI-стандарта:\n"
        "  • «убрать повторы / нормализовать ритм» — анафоры это сакральный приём, не избыточность.\n"
        "  • «заменить торжественные глаголы на бытовые» (являет→показывает, нисходит→приходит).\n"
        "  • «убрать «один из самых» / эпические перечисления / троичные нагнетания» — это ритм Кодекса.\n"
        "  • «сжать / убрать излишества» без указания конкретного смыслового дефекта.\n"
        "  • «нормализовать пунктуацию» — авторские многоточия, длинные цепи запятых, короткие рваные предложения сохраняются.\n"
        "Помечай как removed_duplicates с reason='voice-protection'. НЕ КЛАДИ в reconciled.\n\n"
        "ТВОЯ РАБОТА:\n"
        "1. Прочитай ВСЕ рекомендации с их priority_tier (1 = высший).\n"
        "2. Найди СЕМАНТИЧЕСКИЕ ДУБЛИ (два пункта про одно и то же). Оставь тот что в высшем tier.\n"
        "3. Найди ПРОТИВОРЕЧИЯ (mystical_depth «развернуть метафору» vs Толстой «резать»). Реши кто прав по контексту главы — обычно голосовые > Журналист > Синтез > старейшины > технические.\n"
        "4. Сохрани идеологическую целостность (Микомистицизм, не нью-эйдж и не наука).\n"
        "5. ОТФИЛЬТРУЙ ВЫМЫШЛЕННЫЕ ИСТОРИИ — оставляй только рекомендации с реальным контентом Pavel-а или абстрактные стилевые правки.\n"
        "6. Верни JSON:\n"
        "{\n"
        '  "reconciled": [{"id": <orig_index>, "source": "...", "text": "...", "para_idx": N|null, "priority_tier": N, "rationale": "почему оставлен"}],\n'
        '  "removed_duplicates": [{"ids": [N, M], "reason": "..."}],\n'
        '  "conflicts_resolved": [{"between_ids": [N, M], "winner_id": N, "reason": "..."}],\n'
        '  "summary": "что сделал"\n'
        "}\n"
        "Без преамбулы, сразу JSON. Максимум 25 пунктов в reconciled."
    )
    user_msg = "\n".join(parts) + "\n\nОчисти, разреши конфликты, верни JSON. Текст каждого пункта в reconciled — максимум 300 символов (если оригинал длиннее, ужми до сути)."
    raw, usage = call_opus([{"role": "user", "content": user_msg}], system, max_tokens=8000)
    if not raw:
        return {"ok": False, "error": str(usage)}
    # parse JSON
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

    # Подмешаем оригинальный текст в reconciled items (по id)
    for it in parsed.get("reconciled", []):
        idx = it.get("id")
        if isinstance(idx, int) and 1 <= idx <= len(all_recs):
            orig = all_recs[idx - 1]
            it.setdefault("text", orig["text"])
            it.setdefault("source", orig["source"])
            it.setdefault("para_idx", orig.get("para_idx"))
            it.setdefault("priority_tier", orig["priority_tier"])
            it.setdefault("kind", orig.get("kind", ""))

    out = {
        "ok": True,
        "chapter_id": chapter_id,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_input": len(all_recs),
        "reconciled": parsed.get("reconciled", []),
        "removed_duplicates": parsed.get("removed_duplicates", []),
        "conflicts_resolved": parsed.get("conflicts_resolved", []),
        "summary": parsed.get("summary", ""),
        "usage": usage if isinstance(usage, dict) else {},
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{chapter_id}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter-id", required=True)
    ap.add_argument("--full-analysis-json", help="path to JSON file with full-analysis dump")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    fa = {}
    if args.full_analysis_json:
        fa = json.loads(Path(args.full_analysis_json).read_text(encoding="utf-8"))
    else:
        # Грузим прямо с сервера
        with urllib.request.urlopen(f"http://127.0.0.1:7788/api/editor/full-analysis?chapter_id={args.chapter_id}", timeout=30) as r:
            fa = json.loads(r.read().decode("utf-8"))
    res = reconcile(args.chapter_id, fa, force=args.force)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:3000])
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
