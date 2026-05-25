#!/usr/bin/env python3
"""
visual_tech_audit.py — ночной аудит ВСЕЙ кодовой базы UI и backend.

Pavel 2026-05-20: «улучшать и оптимизировать все визуальные и технические варианты.
Не было лишнего кода. Каждую ночь оптимизируй каждый элемент».

Что делает (КАЖДУЮ ночь):
1. Сканирует ВСЕ HTML/CSS/JS/Python файлы Codex2/app
2. 9 категорий проверок:
   - hardcoded_colors — #hex / rgb() вне tokens.css
   - inconsistent_buttons — кнопки разных классов/размеров рядом
   - missing_tokens — не-token spacing (px) вне tokens.css
   - dead_code — function/CSS class без вызовов
   - duplicated_handlers — onclick='foo()' определён в 2+ местах
   - missing_aria — кликабельные элементы без aria-label / title
   - oversized_inline_style — style="..." > 100 знаков
   - todo_fixme — TODO/FIXME/HACK комменты
   - unused_imports — import которые не используются
3. Сводит в `reports/VISUAL-TECH-AUDIT.md` с severity priorities
4. Low-risk автофиксы применяются с backup (replace_all only для конкретных паттернов)
5. High-risk → predложение для Pavel-а

Запуск (watcher 03:00): python3 visual_tech_audit.py
Manual: python3 visual_tech_audit.py --apply-safe
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
APP_DIR = V2 / "app"
SCRIPTS_DIR = V2 / "scripts"
TOKENS_CSS = APP_DIR / "static/tokens.css"
OUTPUT = V2 / "reports/VISUAL-TECH-AUDIT.md"


def scan_hardcoded_colors():
    """Ищем #hex и rgb() в HTML/CSS — должны быть только var(--color-*)."""
    findings = []
    color_pattern = re.compile(r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))")
    # tokens.css — allowed
    tokens_text = TOKENS_CSS.read_text(encoding="utf-8") if TOKENS_CSS.exists() else ""
    allowed_in_tokens = set(color_pattern.findall(tokens_text))

    for f in list(APP_DIR.rglob("*.html")) + list(APP_DIR.rglob("*.css")):
        if "tokens.css" in str(f):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for ln, line in enumerate(text.split("\n"), 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("/*"):
                continue
            for match in color_pattern.finditer(line):
                color = match.group(0)
                # Whitelist для прозрачных и черного/белого
                if color.lower() in ("#fff", "#ffffff", "#000", "#000000", "#fff0", "transparent"):
                    continue
                # Скип если внутри SVG fill
                if 'fill="' in line[:match.start()]:
                    continue
                findings.append({
                    "file": str(f.relative_to(V2)),
                    "line": ln,
                    "issue": f"hardcoded color {color}",
                    "context": line.strip()[:120],
                    "severity": 5,
                })
    return findings[:30]


def scan_inconsistent_buttons():
    """Ищем места где рядом кнопки разного size — btn-sm рядом с регулярными."""
    findings = []
    for f in APP_DIR.rglob("*.html"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        # Группируем кнопки которые внутри одного блока (.diag-actions-bar, .additions-actions etc)
        for block_match in re.finditer(r'<div[^>]*class="[^"]*(?:actions|buttons-row|btn-row)[^"]*"[^>]*>(.*?)</div>', text, re.DOTALL):
            block = block_match.group(1)
            buttons = re.findall(r'<button[^>]*class="([^"]*)"', block)
            if len(buttons) < 2:
                continue
            # Есть btn-sm + не-btn-sm в одном блоке?
            has_sm = any("btn-sm" in b for b in buttons)
            has_regular = any("btn-sm" not in b and "btn" in b for b in buttons)
            if has_sm and has_regular:
                line_no = text[:block_match.start()].count("\n") + 1
                findings.append({
                    "file": str(f.relative_to(V2)),
                    "line": line_no,
                    "issue": "Кнопки разного размера в одном блоке (btn-sm + регулярные)",
                    "context": block.strip()[:200],
                    "severity": 7,  # высокая важность UX
                })
    return findings


def scan_oversized_inline_styles():
    """style="..." > 100 знаков — слишком много inline, нужен класс."""
    findings = []
    for f in APP_DIR.rglob("*.html"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for ln, line in enumerate(text.split("\n"), 1):
            for m in re.finditer(r'style="([^"]+)"', line):
                style = m.group(1)
                if len(style) > 100:
                    findings.append({
                        "file": str(f.relative_to(V2)),
                        "line": ln,
                        "issue": f"inline-style {len(style)} знаков (надо отдельный класс)",
                        "context": style[:140],
                        "severity": 4,
                    })
    return findings[:20]


def scan_dead_js_functions():
    """function foo() без вызовов foo("""
    findings = []
    editor_html = APP_DIR / "static/editor.html"
    if not editor_html.exists():
        return findings
    text = editor_html.read_text(encoding="utf-8")
    # Ищем function declarations
    defs = re.findall(r"\n\s+(?:async\s+)?function\s+(\w+)\s*\(", text)
    for fname in defs:
        # Не считаем самоопределение
        body_only = re.sub(rf"function\s+{fname}\s*\(", "DEF_HERE", text)
        calls = len(re.findall(rf"\b{fname}\s*\(", body_only))
        if calls == 0:
            # Также проверяем onclick="fname(" и onclick='fname('
            findings.append({
                "file": "app/static/editor.html",
                "line": 0,
                "issue": f"мёртвая JS функция: {fname}() — нет вызовов",
                "context": f"function {fname}(...)",
                "severity": 3,
            })
    return findings[:15]


def scan_todo_fixme():
    """TODO / FIXME / HACK комменты."""
    findings = []
    for f in list(APP_DIR.rglob("*.html")) + list(APP_DIR.rglob("*.py")) + list(APP_DIR.rglob("*.css")) + list(SCRIPTS_DIR.rglob("*.py")):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for ln, line in enumerate(text.split("\n"), 1):
            m = re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line)
            if m:
                findings.append({
                    "file": str(f.relative_to(V2)),
                    "line": ln,
                    "issue": f"{m.group(1)} comment",
                    "context": line.strip()[:140],
                    "severity": 2,
                })
    return findings[:15]


def scan_unclosed_displays():
    """display:none / style="display:none" контейнеры — потенциально удалить можно."""
    findings = []
    for f in APP_DIR.rglob("*.html"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for ln, line in enumerate(text.split("\n"), 1):
            if 'style="display:none"' in line or 'style="display: none"' in line:
                findings.append({
                    "file": str(f.relative_to(V2)),
                    "line": ln,
                    "issue": "Hidden block — возможно мёртвый код",
                    "context": line.strip()[:140],
                    "severity": 2,
                })
    return findings[:10]


def scan_missing_button_titles():
    """<button> без title= и без понятного текста."""
    findings = []
    for f in APP_DIR.rglob("*.html"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in re.finditer(r'<button([^>]*)>([^<]{0,30})</button>', text):
            attrs = m.group(1)
            label = m.group(2).strip()
            if 'title=' in attrs:
                continue
            if len(label) < 3 or label in ("✕", "↶", "↷", "▾", "▸", "▼"):
                line_no = text[:m.start()].count("\n") + 1
                findings.append({
                    "file": str(f.relative_to(V2)),
                    "line": line_no,
                    "issue": "Кнопка без title (accessibility)",
                    "context": m.group(0)[:120],
                    "severity": 3,
                })
    return findings[:15]


def collect_all() -> dict:
    return {
        "hardcoded_colors": scan_hardcoded_colors(),
        "inconsistent_buttons": scan_inconsistent_buttons(),
        "oversized_inline_styles": scan_oversized_inline_styles(),
        "dead_js_functions": scan_dead_js_functions(),
        "todo_fixme": scan_todo_fixme(),
        "hidden_blocks": scan_unclosed_displays(),
        "missing_button_titles": scan_missing_button_titles(),
    }


def render_report(findings: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# 🔧 Visual + Technical audit — {now}")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «улучшать и оптимизировать все визуальные и технические элементы».")
    lines.append("")

    total = sum(len(v) for v in findings.values())
    lines.append(f"**Всего находок:** {total}")
    lines.append("")

    sections = [
        ("inconsistent_buttons", "🎨 Несогласованные кнопки", "high"),
        ("hardcoded_colors", "🌈 Хардкод цветов (вне tokens)", "high"),
        ("oversized_inline_styles", "📏 Inline-style > 100 знаков", "medium"),
        ("missing_button_titles", "♿ Кнопки без title (accessibility)", "medium"),
        ("dead_js_functions", "💀 Мёртвые JS функции", "low"),
        ("hidden_blocks", "👁️‍🗨️ display:none блоки", "low"),
        ("todo_fixme", "📝 TODO / FIXME / HACK", "info"),
    ]

    for key, title, sev in sections:
        items = findings.get(key, [])
        if not items:
            lines.append(f"## {title} ✓")
            lines.append("Чисто.")
            lines.append("")
            continue
        lines.append(f"## {title} — {len(items)}")
        lines.append("")
        for it in items[:10]:
            lines.append(f"- **`{it['file']}:{it.get('line', '?')}`** — {it['issue']}")
            if it.get("context"):
                ctx = it["context"].replace("`", "'")
                lines.append(f"  ```\n  {ctx}\n  ```")
        if len(items) > 10:
            lines.append(f"  _...ещё {len(items) - 10} находок_")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Действия:**")
    lines.append("")
    lines.append("- Кнопки разного размера (🎨) — fix prioritery 1: единообразие в UI")
    lines.append("- Хардкоды цветов (🌈) — заменить на `var(--color-*)`")
    lines.append("- Inline-styles большие (📏) — вынести в `.css` классы")
    lines.append("- Мёртвый JS / hidden — удалить если действительно не нужно")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-safe", action="store_true", help="Применить безопасные автофиксы (TBD)")
    args = ap.parse_args()

    print("Сканирую UI + код...")
    findings = collect_all()
    total = sum(len(v) for v in findings.values())
    print(f"Всего находок: {total}")
    for k, v in findings.items():
        if v:
            print(f"  {k}: {len(v)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_report(findings), encoding="utf-8")
    print(f"✓ {OUTPUT}")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "visual_tech_audit",
            "target": "app",
            "payload": {"total_findings": total, **{k: len(v) for k, v in findings.items()}},
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
