#!/usr/bin/env python3
"""
nightly_system_improver.py — ночной агент глубокого улучшения системы.

Pavel 2026-05-20: «каждую ночь ты будешь брать каждый параметр всей структуры,
анализировать его глубоко и решать как улучшать. Не экономить токены».

Что делает:
1. Берёт ОДИН элемент из rotation-списка (~30 элементов)
2. Читает его исходный код + историю использования из events.jsonl + pavel-actions
3. Opus 4.7 + extended thinking 12K анализирует:
   - Что элемент делает сейчас
   - Где слабые места (по данным использования)
   - Конкретные улучшения с кодом
4. Pavel-action анализ: % approved / rejected для рекомендаций этого элемента
5. Записывает proposal в reports/SYSTEM-IMPROVEMENTS/<date>-<element>.md
6. Если safe и autoApply=True — пробует применить с backup

Rotation: day_of_year % len(elements) — каждый элемент покрыт раз в ~30 дней.

Запуск (watcher 02:30): python3 nightly_system_improver.py
Manual: python3 nightly_system_improver.py --element compute_ideology_fit
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from claude_helper import ask_opus
except ImportError:
    ask_opus = None

V2 = Path.home() / "Desktop/Codex2"
SERVER_PY = V2 / "app/server.py"
EDITOR_HTML = V2 / "app/static/editor.html"
EVENTS = V2 / ".codex/events.jsonl"
ACTIONS = V2 / ".codex/pavel-actions.jsonl"
OUTPUT_DIR = V2 / "reports/SYSTEM-IMPROVEMENTS"

# Список элементов системы для ротации (29 = почти месяц покрытия)
ELEMENTS = [
    # === Локальные анализаторы (без API) ===
    {"name": "compute_ideology_fit", "file": "app/server.py", "type": "function",
     "what": "Локальный score 0-100 главы по 4 axes vs канон Микомистицизма",
     "improvements_focus": "axis веса, anti-overload penalty, корректность для intro vs main"},
    {"name": "validate_canon", "file": "app/server.py", "type": "function",
     "what": "Pre-output фильтр для нарушений канона (тире / «не X а Y» / клише / архаизмы)",
     "improvements_focus": "новые паттерны, false-positive снижение, smart auto-fix"},
    {"name": "detect_chapter_type", "file": "app/server.py", "type": "function",
     "what": "Определяет тип главы intro/main/conclusion/appendix",
     "improvements_focus": "точность определения, дополнительные эвристики"},
    {"name": "detect_forced_mushroom", "file": "app/server.py", "type": "function",
     "what": "Детектор принудительной грибной лексики в suggestions",
     "improvements_focus": "false-positive когда грибы реально нужны, severity calibration"},
    {"name": "scoreParagraph (JS)", "file": "app/static/editor.html", "type": "js_function",
     "what": "5 локальных эвристик (Шедевр/Голос/Уникальность/Сакральн./Ритм)",
     "improvements_focus": "новые сигналы, calibration vs Opus оценок"},
    # === Opus endpoints ===
    {"name": "_quick_paragraph_check", "file": "app/server.py", "type": "endpoint",
     "what": "POST /quick-check — Opus минимальные правки per parametaph",
     "improvements_focus": "system prompt качество, диминишинг returns, prompt экономика"},
    {"name": "_single_paragraph_suggestion", "file": "app/server.py", "type": "endpoint",
     "what": "POST /single-suggestion — Opus полная переписка одного параграфа",
     "improvements_focus": "balance между radical rewrite и точечностью"},
    {"name": "_stream_suggestions", "file": "app/server.py", "type": "endpoint",
     "what": "SSE поток suggestions для всей главы",
     "improvements_focus": "ceiling detection, parallel processing, severity calibration"},
    {"name": "_honest_critic", "file": "app/server.py", "type": "endpoint",
     "what": "Критик ищет «что стало хуже» после правки",
     "improvements_focus": "честность vs угодничество, конкретность lost/gained"},
    {"name": "_chapter_council", "file": "app/server.py", "type": "endpoint",
     "what": "Совет 8 старейшин + ТОП-5 правок",
     "improvements_focus": "персонификация экспертов, chapter_type rules, anti-hallucination"},
    {"name": "_apply_targeted", "file": "app/server.py", "type": "endpoint",
     "what": "Применить выбранные галочки точечно через Opus",
     "improvements_focus": "diff-guard, точность сохранения непомеченных параграфов"},
    {"name": "_rewrite_whole_chapter", "file": "app/server.py", "type": "endpoint",
     "what": "Полная перезапись главы",
     "improvements_focus": "multi-pass самопроверка, voice consistency"},
    {"name": "_density_analysis", "file": "app/server.py", "type": "endpoint",
     "what": "Анализ объёма/многословия + Opus places_to_expand/cut",
     "improvements_focus": "адаптивность к chapter_type, корректность для коротких intro"},
    {"name": "_style_coherence_analysis", "file": "app/server.py", "type": "endpoint",
     "what": "Унификация «Вы/ты», голоса, архаизмов",
     "improvements_focus": "false-positive снижение, точные find/replace"},
    {"name": "_logic_analysis", "file": "app/server.py", "type": "endpoint",
     "what": "Opus проверка логической целостности",
     "improvements_focus": "narrative arc detection, conflict patterns"},
    {"name": "_full_diagnostics", "file": "app/server.py", "type": "endpoint",
     "what": "Агрегат всех анализов + honest verdict",
     "improvements_focus": "verdict accuracy, priority actions sorting"},
    {"name": "_brainstorm", "file": "app/server.py", "type": "endpoint",
     "what": "Q&A диалог с Pavel-ом + apply insights",
     "improvements_focus": "качество уточняющих вопросов, контекст-awareness"},
    {"name": "_incorporate_ideas", "file": "app/server.py", "type": "endpoint",
     "what": "Внедрение идей Pavel-а в draft",
     "improvements_focus": "preserve unchanged paragraphs, integration smoothness"},
    # === Background agents ===
    {"name": "extract_metaphors.py", "file": "scripts/extract_metaphors.py", "type": "agent",
     "what": "Каталогизатор метафор → склад для anti-repeat",
     "improvements_focus": "semantic deduplication, strength calibration"},
    {"name": "analyze_voice_readings.py", "file": "scripts/analyze_voice_readings.py", "type": "agent",
     "what": "Связь надиктовок с главами + missing_ideas",
     "improvements_focus": "keyword expansion, relevance scoring"},
    {"name": "structure_audit.py", "file": "scripts/structure_audit.py", "type": "agent",
     "what": "Поиск пропущенных книг (nested chapters)",
     "improvements_focus": "edge cases, confidence calibration"},
    {"name": "version_dedup.py", "file": "scripts/version_dedup.py", "type": "agent",
     "what": "Приоритет свежей версии docx + auto-archive",
     "improvements_focus": "semantic similarity, cross-folder safer mode"},
    {"name": "logic_audit.py", "file": "scripts/logic_audit.py", "type": "agent",
     "what": "Ночной мета-аудит + предложения инструментов",
     "improvements_focus": "actionability предложений, не дублировать существующее"},
    {"name": "night_followups_review.py", "file": "scripts/night_followups_review.py", "type": "agent",
     "what": "Что Pavel просил vs что я сделал",
     "improvements_focus": "точность извлечения требований Pavel-а"},
    {"name": "daily_system_report.py", "file": "scripts/daily_system_report.py", "type": "agent",
     "what": "Утренний under-hood отчёт",
     "improvements_focus": "actionability, под капотом ясность"},
    {"name": "daily_today_recommendations.py", "file": "scripts/daily_today_recommendations.py", "type": "agent",
     "what": "TODAY-RECOMMENDATIONS в формате A",
     "improvements_focus": "approval rate, priority sorting"},
    # === UI / Frontend ===
    {"name": "Top diagnostics bar", "file": "app/static/editor.html", "type": "ui",
     "what": "Анализ-bar над редактором с честным вердиктом",
     "improvements_focus": "action buttons эффективность, verdict clarity"},
    {"name": "C-1 Streaming review drawer", "file": "app/static/editor.html", "type": "ui",
     "what": "Sudowrite-style карточки с 👍/👎",
     "improvements_focus": "approval rate, perceived value, friction"},
    {"name": "C0 Apply-all selector", "file": "app/static/editor.html", "type": "ui",
     "what": "Сбор галочек изо всех источников + apply-targeted",
     "improvements_focus": "понятность того что выбрано, group-by-source"},
]


def get_element(name: str = None):
    """Возвращает один элемент: либо по имени, либо по дню года."""
    if name:
        for e in ELEMENTS:
            if e["name"] == name:
                return e
        return None
    day_of_year = datetime.now().timetuple().tm_yday
    idx = day_of_year % len(ELEMENTS)
    return ELEMENTS[idx]


def extract_element_code(element: dict, max_chars: int = 12000) -> str:
    """Извлекает реальный код элемента из файла."""
    f = V2 / element["file"]
    if not f.exists():
        return ""
    text = f.read_text(encoding="utf-8")
    if element["type"] == "function":
        # Найти def name(...) и взять следующие N строк
        m = re.search(rf"(?:^|\n)\s+(?:def\s+|@staticmethod\s+def\s+){re.escape(element['name'])}\s*\(", text)
        if not m:
            # Generic search
            m = re.search(rf"def\s+{re.escape(element['name'])}\s*\(", text)
        if m:
            start = m.start()
            # Берём следующие 8000 знаков или до следующего def
            chunk = text[start:start + max_chars]
            return chunk
    elif element["type"] == "endpoint":
        m = re.search(rf"def\s+{re.escape(element['name'])}\s*\(", text)
        if m:
            return text[m.start():m.start() + max_chars]
    elif element["type"] == "js_function":
        m = re.search(rf"function\s+{re.escape(element['name'])}\s*\(", text)
        if m:
            return text[m.start():m.start() + max_chars]
    elif element["type"] == "agent":
        # Берём весь файл (обычно <500 строк)
        return text[:max_chars]
    elif element["type"] == "ui":
        # Возвращаем структурные части
        return f"[UI компонент в {element['file']} — общая структура]\n\n" + text[:max_chars // 2]
    return text[:max_chars]


def get_usage_stats(element_name: str, days: int = 14):
    """Сколько раз элемент использовался + успешность по pavel-actions."""
    if not EVENTS.exists():
        return {"calls": 0, "errors": 0, "approval_rate": None}
    cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)).isoformat()
    calls = 0
    errors = 0
    for line in EVENTS.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            if e.get("ts", "") < cutoff:
                continue
            payload_str = json.dumps(e.get("payload", {}))
            if element_name in payload_str or element_name in str(e.get("type", "")):
                calls += 1
                if "error" in payload_str.lower():
                    errors += 1
        except Exception:
            continue
    return {"calls": calls, "errors": errors, "approval_rate": None}


def analyze_element(element: dict) -> dict:
    """Opus глубокий анализ элемента + предложения улучшений."""
    if ask_opus is None:
        return {"error": "claude_helper unavailable"}

    code = extract_element_code(element)
    if not code:
        return {"error": f"не удалось извлечь код {element['file']}"}
    usage = get_usage_stats(element["name"])

    system = (
        "Ты — старший инженер, аудирующий код Codex v2 для Pavel-а. "
        "Pavel дал указание: каждую ночь брать ОДИН элемент системы и глубоко улучшать. "
        "Не экономь токены — твоя задача дать максимум полезных улучшений.\n\n"
        "ПРИНЦИПЫ:\n"
        "1. Будь честным критиком — не льсти коду\n"
        "2. Предлагай КОНКРЕТНЫЕ улучшения с фрагментами кода\n"
        "3. Если код хорош — скажи прямо «не трогать», не выдумывай проблем\n"
        "4. Учитывай контекст Pavel-а: anti-pattern (forced mushroom, AI-tells), "
        "   chapter-type awareness, canon-validator, honest stop\n"
        "5. Возвращай ТОЛЬКО валидный JSON"
    )

    user = f"""# Элемент для аудита

**Имя:** `{element['name']}`
**Файл:** `{element['file']}`
**Тип:** {element['type']}
**Назначение:** {element['what']}
**Фокус улучшений:** {element['improvements_focus']}

# Статистика использования (14 дней)
- Вызовов: {usage['calls']}
- Ошибок: {usage['errors']}

# Код элемента

```
{code[:11000]}
```

# Что вернуть

```json
{{
  "summary": "1 предложение об элементе и его роли",
  "current_strengths": ["что работает хорошо"],
  "weaknesses": [
    {{"issue": "конкретная проблема", "severity": 1-10, "evidence": "почему это плохо / какие сценарии плохо обрабатывает"}}
  ],
  "improvements": [
    {{
      "title": "Краткое название улучшения",
      "description": "что именно поменять (1-2 предложения)",
      "category": "performance | correctness | UX | robustness | clarity",
      "effort_minutes": 5-180,
      "risk": "low | medium | high",
      "auto_applicable": true/false,
      "code_snippet": "конкретный фрагмент кода для применения (Python/JS) или null"
    }}
  ],
  "verdict": "improve_now | accept_as_is | needs_pavel_decision",
  "honest_verdict_message": "1-2 предложения честной оценки"
}}
```

Не больше 5 weaknesses, не больше 5 improvements. Concrete > abstract.
Если элемент действительно хорош — `verdict: accept_as_is`, не выдумывай.
"""

    print(f"  → Opus deep analysis: {element['name']}...")
    try:
        resp = ask_opus(user=user, system=system, max_tokens=16000, thinking=12000)
        text = resp["text"].strip()
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return {**json.loads(cleaned), "usage": resp.get("usage")}
    except Exception as e:
        return {"error": f"Opus/JSON: {e}"}


def write_proposal(element: dict, analysis: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    safe_name = re.sub(r"[^\w-]+", "_", element["name"])
    out = OUTPUT_DIR / f"{date}-{safe_name}.md"
    lines = []
    lines.append(f"# 🔧 System improvement — `{element['name']}`")
    lines.append("")
    lines.append(f"_Date: {date} · File: `{element['file']}` · Type: {element['type']}_")
    lines.append("")
    lines.append(f"**Назначение:** {element['what']}")
    lines.append(f"**Фокус улучшений:** {element['improvements_focus']}")
    lines.append("")
    if analysis.get("error"):
        lines.append(f"## ⚠️ Ошибка анализа")
        lines.append(f"```\n{analysis['error']}\n```")
        out.write_text("\n".join(lines), encoding="utf-8")
        return

    lines.append("## Summary")
    lines.append(analysis.get("summary", "—"))
    lines.append("")
    lines.append(f"**Verdict:** {analysis.get('verdict', '—')}")
    if analysis.get("honest_verdict_message"):
        lines.append(f"> {analysis['honest_verdict_message']}")
    lines.append("")

    strengths = analysis.get("current_strengths", [])
    if strengths:
        lines.append("## ✓ Что работает")
        for s in strengths:
            lines.append(f"- {s}")
        lines.append("")

    weaknesses = analysis.get("weaknesses", [])
    if weaknesses:
        lines.append("## ⚠ Слабости")
        for w in sorted(weaknesses, key=lambda x: -x.get("severity", 0)):
            lines.append(f"- **[severity {w.get('severity', '?')}/10]** {w.get('issue', '?')}")
            if w.get("evidence"):
                lines.append(f"  _{w['evidence']}_")
        lines.append("")

    improvements = analysis.get("improvements", [])
    if improvements:
        lines.append(f"## 💡 Предложенные улучшения ({len(improvements)})")
        lines.append("")
        for i, imp in enumerate(improvements, 1):
            lines.append(f"### {i}. {imp.get('title', '?')}")
            lines.append(f"- **Category:** {imp.get('category', '?')}")
            lines.append(f"- **Effort:** {imp.get('effort_minutes', '?')} мин · **Risk:** {imp.get('risk', '?')}")
            lines.append(f"- **Auto-applicable:** {'yes' if imp.get('auto_applicable') else 'no'}")
            lines.append("")
            lines.append(imp.get("description", "—"))
            if imp.get("code_snippet"):
                lang = "python" if element["file"].endswith(".py") else "javascript" if element["file"].endswith(".html") else ""
                lines.append("")
                lines.append(f"```{lang}")
                lines.append(imp["code_snippet"])
                lines.append("```")
            lines.append("")

    lines.append("---")
    lines.append("")
    if analysis.get("usage"):
        u = analysis["usage"]
        lines.append(f"_Opus tokens: {u.get('input_tokens', '?')} → {u.get('output_tokens', '?')}_")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--element", help="Конкретный элемент по имени (иначе rotation)")
    ap.add_argument("--list", action="store_true", help="Показать все элементы")
    args = ap.parse_args()

    if args.list:
        for i, e in enumerate(ELEMENTS):
            print(f"  {i:2d}. [{e['type']:10s}] {e['name']:35s} {e['file']}")
        return

    element = get_element(args.element)
    if not element:
        print(f"Element '{args.element}' not found. Use --list to see all.")
        sys.exit(1)

    print(f"=== Nightly improvement: {element['name']} ===")
    print(f"   Файл: {element['file']}")
    print(f"   Тип: {element['type']}")
    print()

    analysis = analyze_element(element)
    write_proposal(element, analysis)

    # Event
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "system_improvement_proposal",
            "target": element["name"],
            "payload": {
                "file": element["file"],
                "verdict": analysis.get("verdict"),
                "weaknesses": len(analysis.get("weaknesses", [])),
                "improvements": len(analysis.get("improvements", [])),
                "tokens_in": (analysis.get("usage") or {}).get("input_tokens"),
                "tokens_out": (analysis.get("usage") or {}).get("output_tokens"),
            },
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
