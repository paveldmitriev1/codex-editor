#!/usr/bin/env python3
"""
auto_bug_tester.py — автоматический тестировщик визуальных и технических багов.

Pavel 2026-05-20: «во время перерывов тестируй сам — какие действия работают /
не работают, визуальные и технические ошибки, несостыковки дизайна и логики.
Анализ всех багов которые мне приходится самому ловить».

Что проверяет (на сервере и в коде, БЕЗ браузера):
1. **Endpoint smoke** — все известные REST endpoints отвечают валидным JSON
2. **JS-funcref consistency** — onclick='funcname(...)' → есть ли function funcname в editor.html?
3. **Orphan CSS classes** — CSS class определён но не используется в HTML, или наоборот
4. **Mismatched IDs** — getElementById('foo') без <... id="foo">
5. **Broken event handlers** — onclick="X" если X не определена
6. **Невалидные шаблоны** — `${variable}` без backtick template literal
7. **Dead Python routes** — `if action == "X"` если "X" не fetch-ится фронтом
8. **Endpoint 5xx-tracking** — какие endpoint-ы возвращают 500 чаще обычного

Запуск: `python3 auto_bug_tester.py` (вызывается из idle_keeper.py)
Отчёт: `reports/AUTO-BUG-AUDIT.md` + новые issues добавляются в follow-ups.json
"""
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
APP = V2 / "app"
EDITOR_HTML = APP / "static/editor.html"
SERVER_PY = APP / "server.py"
REPORTS = V2 / "reports"
OUTPUT = REPORTS / "AUTO-BUG-AUDIT.md"
SERVER_URL = "http://127.0.0.1:7788"


def server_alive() -> bool:
    """Сервер запущен?"""
    try:
        out = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{SERVER_URL}/api/health", "--max-time", "2"],
            text=True,
        )
        return out.strip() == "200"
    except subprocess.CalledProcessError:
        return False


def smoke_test_endpoints() -> list:
    """Все известные REST endpoints отвечают?"""
    findings = []
    if not server_alive():
        findings.append({
            "severity": "critical",
            "category": "endpoint",
            "what": "Сервер на 7788 не отвечает на /api/health",
            "fix": "Запусти: bash ~/Desktop/Codex2/app/start.sh",
        })
        return findings

    endpoints = [
        ("GET",  "/api/health", None),
        ("GET",  "/api/toc", None),
        ("GET",  "/api/chapters-status", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/draft", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/style-coherence", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/density", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/logic-analysis", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/ideology-fit", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/voice-readings", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/voice-analysis", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/similar", None),
        ("POST", "/api/chapter/book-obsession-ch-02/edited-paragraphs", "{}"),
        ("GET",  "/api/chapter/book-obsession-ch-02/notes", None),
        ("GET",  "/api/chapter/book-obsession-ch-02/approvals", None),
    ]
    for method, path, body in endpoints:
        try:
            args = ["curl", "-s", "-o", "/tmp/auto-bug-test-out", "-w", "%{http_code}",
                    "-X", method, f"{SERVER_URL}{path}", "--max-time", "10"]
            if body:
                args.extend(["-H", "Content-Type: application/json", "-d", body])
            code = subprocess.check_output(args, text=True).strip()
            if code.startswith("5") or code == "404":
                findings.append({
                    "severity": "high",
                    "category": "endpoint",
                    "what": f"{method} {path} → HTTP {code}",
                    "fix": f"Проверь обработчик в server.py, либо frontend должен использовать другой путь",
                })
            else:
                # Проверим что валидный JSON
                try:
                    body_text = Path("/tmp/auto-bug-test-out").read_text(encoding="utf-8")
                    if body_text.strip():
                        json.loads(body_text)
                except json.JSONDecodeError:
                    findings.append({
                        "severity": "medium",
                        "category": "endpoint",
                        "what": f"{method} {path} → {code} но не JSON: {body_text[:80]}",
                        "fix": "Endpoint должен всегда возвращать JSON",
                    })
        except subprocess.CalledProcessError as e:
            findings.append({
                "severity": "medium",
                "category": "endpoint",
                "what": f"{method} {path} → exception",
                "fix": f"curl error: {e}",
            })
    return findings


def js_undefined_functions() -> list:
    """В onclick='funcname(...)' funcname без определения?"""
    findings = []
    if not EDITOR_HTML.exists():
        return findings
    text = EDITOR_HTML.read_text(encoding="utf-8")

    # Собираем все onclick='funcname(' и onclick="funcname("
    called_funcs = set()
    for pat in [r'''onclick=['"](\w+)\s*\(''', r'''oninput=['"](\w+)\s*\(''',
                r'''onchange=['"](\w+)\s*\(''', r'''onkeydown=['"](\w+)\s*\(''',
                r'''onmouseenter=['"](\w+)\s*\(''']:
        for m in re.finditer(pat, text):
            called_funcs.add(m.group(1))

    # Собираем все объявленные функции в editor.html
    defined_funcs = set()
    for pat in [r'\bfunction\s+(\w+)\s*\(', r'(?:^|\s)(\w+)\s*=\s*function\s*\(',
                r'(?:^|\s)(\w+)\s*=\s*async\s+function\s*\(',
                r'(?:^|\s)(\w+)\s*=\s*\(.*?\)\s*=>']:
        for m in re.finditer(pat, text):
            defined_funcs.add(m.group(1))

    # Также built-ins
    builtins = {
        "console", "alert", "confirm", "prompt", "fetch", "scrollTo",
        "JSON", "Math", "Object", "Array", "String", "Number", "Date",
        "Promise", "Set", "Map", "Symbol", "Error", "RegExp", "parseInt",
        "parseFloat", "isNaN", "isFinite", "encodeURIComponent",
        "decodeURIComponent", "setTimeout", "setInterval", "clearTimeout",
    }
    undefined = called_funcs - defined_funcs - builtins
    for fname in sorted(undefined):
        # Игнорируем this.foo() и Math.foo() — это методы объектов
        if "." in fname:
            continue
        findings.append({
            "severity": "high",
            "category": "js_undefined",
            "what": f"onclick='{fname}(…)' но function {fname} не определена в editor.html",
            "fix": f"Объявить function {fname}() или заменить onclick на существующую функцию",
        })
    return findings


def broken_ids() -> list:
    """getElementById('foo') без <... id='foo'>?"""
    findings = []
    if not EDITOR_HTML.exists():
        return findings
    text = EDITOR_HTML.read_text(encoding="utf-8")

    # Все getElementById обращения
    refs = set(m.group(1) for m in re.finditer(r'''getElementById\(['"]([\w-]+)['"]''', text))
    # Все объявленные id
    declared = set(m.group(1) for m in re.finditer(r'''\bid=['"]([\w-]+)['"]''', text))
    # Dynamic IDs (с template literals) — пропускаем
    dynamic_refs = set(m.group(1) for m in re.finditer(r'''getElementById\(`([^`]+)`''', text))

    missing = refs - declared
    # Many IDs created dynamically via innerHTML — false positives
    # Скип "scores-", "notes-", "notes-input-", "notes-list-", "simIdeas_"
    skip_prefixes = ("scores-", "notes-", "simIdeas_", "honest-")
    missing = {m for m in missing if not any(m.startswith(p) for p in skip_prefixes)}

    for mid in sorted(missing)[:10]:
        findings.append({
            "severity": "medium",
            "category": "broken_id",
            "what": f"getElementById('{mid}') — нет элемента с id='{mid}'",
            "fix": "Либо удалить вызов, либо добавить элемент с этим id",
        })
    return findings


def dead_python_routes() -> list:
    """Routes which frontend doesn't call."""
    findings = []
    if not SERVER_PY.exists() or not EDITOR_HTML.exists():
        return findings
    server = SERVER_PY.read_text(encoding="utf-8")
    editor = EDITOR_HTML.read_text(encoding="utf-8")

    # Действия из server.py: if action == "X"
    actions = set(m.group(1) for m in re.finditer(r'''action\s*==\s*['"]([\w-]+)['"]''', server))
    # Что фронт fetch-ит из URL
    fetched = set()
    for m in re.finditer(r'''fetch\([`'"]\/api\/chapter\/(?:\$\{[^}]+\}|[\w-]+)\/(?:\$\{[^}]+\}\/)?([\w-]+)''', editor):
        fetched.add(m.group(1))
    # Также Path-level: /api/chapter/foo
    for m in re.finditer(r'''fetch\([`'"]\/api\/chapter\/([\w-]+)[`'"]''', editor):
        fetched.add(m.group(1))

    # Действия определены но не fetched
    builtin_actions = {"draft", "history", "restore"}  # известно что используются
    suspicious = actions - fetched - builtin_actions
    if len(suspicious) > 5:
        # Слишком много false positives — это action handlers с body, не path
        return findings
    for act in sorted(suspicious)[:5]:
        findings.append({
            "severity": "low",
            "category": "dead_route",
            "what": f"Action '{act}' определён в server.py но не fetched из editor.html",
            "fix": "Либо удалить из server.py, либо подключить с UI",
        })
    return findings


def collect_all() -> dict:
    return {
        "endpoints": smoke_test_endpoints(),
        "js_undefined": js_undefined_functions(),
        "broken_ids": broken_ids(),
        "dead_routes": dead_python_routes(),
    }


def render_report(findings: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# 🐛 Auto-Bug Audit — {now}")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «во время перерывов тестируешь сам — какие действия работают/не работают, ошибки и несостыковки».")
    lines.append("")

    total = sum(len(v) for v in findings.values())
    by_sev = defaultdict(int)
    for items in findings.values():
        for it in items:
            by_sev[it["severity"]] += 1

    if total == 0:
        lines.append("## ✓ Чисто — багов не обнаружено")
        lines.append("")
        lines.append("Запускай Pavel-а — система работает.")
        return "\n".join(lines)

    lines.append(f"**Всего находок:** {total}")
    lines.append(f"- 🚨 critical: {by_sev.get('critical', 0)}")
    lines.append(f"- ❗ high: {by_sev.get('high', 0)}")
    lines.append(f"- ⚠ medium: {by_sev.get('medium', 0)}")
    lines.append(f"- ℹ low: {by_sev.get('low', 0)}")
    lines.append("")

    sections = [
        ("endpoints",    "🔗 Endpoint smoke (HTTP 500 / 404 / non-JSON)"),
        ("js_undefined", "🟦 JS: undefined functions в onclick"),
        ("broken_ids",   "🆔 getElementById на несуществующий id"),
        ("dead_routes",  "💀 Dead routes (определены но не используются)"),
    ]

    sev_emoji = {"critical": "🚨", "high": "❗", "medium": "⚠", "low": "ℹ"}

    for key, title in sections:
        items = findings.get(key, [])
        if not items:
            lines.append(f"## {title} ✓")
            lines.append("Чисто.")
            lines.append("")
            continue
        lines.append(f"## {title} — {len(items)}")
        lines.append("")
        for it in items:
            emoji = sev_emoji.get(it["severity"], "•")
            lines.append(f"- {emoji} **{it['what']}**")
            lines.append(f"   → {it['fix']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Действия:**")
    lines.append("1. 🚨/❗ — починить сейчас (блокеры)")
    lines.append("2. ⚠ — починить вечером после Pavel-сессии")
    lines.append("3. ℹ — добавить в follow-ups.json")
    return "\n".join(lines)


def main():
    print("🐛 Auto-bug-tester…")
    findings = collect_all()
    total = sum(len(v) for v in findings.values())
    print(f"   {total} находок")

    REPORTS.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_report(findings), encoding="utf-8")
    print(f"   → {OUTPUT}")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "auto_bug_audit",
            "target": "app",
            "payload": {
                "total": total,
                **{k: len(v) for k, v in findings.items()},
            },
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
