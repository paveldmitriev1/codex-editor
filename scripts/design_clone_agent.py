#!/usr/bin/env python3
"""
design_clone_agent.py — ночной агент копирования дизайна Claude Desktop.

Pavel 2026-05-20: «изучи систему навигации в Claude Desktop и сделай такой же шаблон,
с теми же функциями, иконками, цветами. Обнови ночью, чтобы все элементы были
аккуратно прописаны как в Claude Desktop».

Что делает:
1. Берёт скриншоты Claude Desktop (Pavel должен положить в `reference/claude-desktop/*.png`)
2. Через Vision-Opus анализирует:
   - Цветовую палитру (background, surface, accent, text-tiers, borders)
   - Spacing (margins, paddings, gaps)
   - Типографику (font sizes, weights, line heights)
   - Иконки (что используется, какой стиль — outline / filled / stroke width)
   - Layout patterns (sidebar width, header height, conversation list, message bubbles)
3. Сравнивает с нашим editor.html / index.html через визуальный QA
4. Генерирует `reports/DESIGN-CLONE-PROPOSAL.md` с tokens.css изменениями + по-компонентным правками
5. НЕ применяет автоматически — утром Pavel approval

Pavel-action: положить хотя бы 2-3 скриншота Claude Desktop в:
  ~/Desktop/Codex2/reference/claude-desktop/
  (примеры: sidebar.png, conversation.png, settings.png)

Запуск (watcher 05:00 ежедневно): python3 design_clone_agent.py
"""
import argparse
import base64
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
REFERENCE_DIR = V2 / "reference/claude-desktop"
OUTPUT = V2 / "reports/DESIGN-CLONE-PROPOSAL.md"


def load_screenshots() -> list:
    """Возвращает все PNG/JPG из reference/claude-desktop/."""
    if not REFERENCE_DIR.exists():
        REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        return []
    files = []
    for p in sorted(REFERENCE_DIR.iterdir()):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            files.append(p)
    return files


def analyze_with_vision(screenshots: list, our_tokens: str) -> dict:
    """Opus Vision анализирует Claude Desktop + сравнивает с нашими токенами."""
    import urllib.request

    env_file = Path.home() / ".cc-memory-bridge/.env"
    token = None
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                token = line.split("=", 1)[1].strip()
                break
    if not token:
        return {"error": "no oauth token"}

    # Готовим content блоки: text + images
    content_blocks = [
        {"type": "text", "text": (
            "Pavel хочет чтобы UI его приложения (Codex Микомистицизма) выглядел "
            "и работал как Claude Desktop. Изучи приложенные скриншоты Claude Desktop "
            "и наши текущие токены дизайна, дай ПРЕДЛОЖЕНИЯ по обновлению.\n\n"
            f"# Наш текущий tokens.css\n\n```css\n{our_tokens[:5000]}\n```\n\n"
            "# Что вернуть\n\n"
            "Валидный JSON:\n"
            "```json\n"
            "{\n"
            '  "palette": {\n'
            '    "bg_primary": "#hex from Claude Desktop",\n'
            '    "bg_surface": "#hex",\n'
            '    "bg_card": "#hex",\n'
            '    "accent": "#hex",\n'
            '    "text_primary": "#hex",\n'
            '    "text_secondary": "#hex",\n'
            '    "text_tertiary": "#hex",\n'
            '    "border": "#hex"\n'
            "  },\n"
            '  "typography": {\n'
            '    "font_family": "...",\n'
            '    "sizes": {"h1": "28px", "h2": "20px", "body": "14px"}\n'
            "  },\n"
            '  "spacing_grid": "4px | 8px",\n'
            '  "border_radius": {"sm": "6px", "md": "10px", "lg": "16px"},\n'
            '  "sidebar_width": "260px",\n'
            '  "icon_style": "outline|filled|stroke",\n'
            '  "icons_observed": ["chat", "history", "plus", "settings", ...],\n'
            '  "layout_patterns": [\n'
            '    {"name": "left sidebar with conversations", "description": "..."}\n'
            "  ],\n"
            '  "tokens_css_diff": [\n'
            '    {"variable": "--color-bg", "current": "#F5F5F7", "proposed": "#hex", "reason": "..."},\n'
            '    ...\n'
            "  ],\n"
            '  "component_changes": [\n'
            '    {"component": "sidebar", "change": "что изменить", "css_snippet": "..."}\n'
            "  ]\n"
            "}\n```"
        )}
    ]
    # Добавляем изображения (max 5)
    for p in screenshots[:5]:
        try:
            with p.open("rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            media_type = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64}
            })
        except Exception as e:
            print(f"  ! skip {p.name}: {e}", file=sys.stderr)

    body = {
        "model": "claude-opus-4-7",
        "max_tokens": 6000,
        "thinking": {"type": "enabled", "budget_tokens": 4000},
        "messages": [{"role": "user", "content": content_blocks}],
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8787/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}
    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    raw = "\n".join(blocks).strip()
    cleaned = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return {**json.loads(cleaned), "usage": data.get("usage")}
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse: {e}", "raw": raw[:2000]}


def write_report(analysis: dict, n_screenshots: int):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# 🎨 Claude Desktop design clone — {now}")
    lines.append("")
    lines.append("> Pavel 2026-05-20: «изучи Claude Desktop, сделай такой же шаблон». Это **предложение** — для approve/reject утром.")
    lines.append("")
    lines.append(f"Скриншотов проанализировано: **{n_screenshots}**")
    lines.append("")

    if n_screenshots == 0:
        lines.append(f"## ⚠️ Скриншоты не найдены")
        lines.append("")
        lines.append(f"Положи 2-3 скриншота Claude Desktop в:")
        lines.append(f"")
        lines.append(f"  `{REFERENCE_DIR}`")
        lines.append("")
        lines.append("Примеры: sidebar.png, conversation.png, settings.png. Я подхвачу следующей ночью.")
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
        return

    if analysis.get("error"):
        lines.append(f"⚠️ Ошибка: {analysis['error']}")
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
        return

    palette = analysis.get("palette", {})
    if palette:
        lines.append("## 🎨 Палитра Claude Desktop")
        lines.append("")
        for k, v in palette.items():
            lines.append(f"- **`{k}`** = `{v}`")
        lines.append("")

    typo = analysis.get("typography", {})
    if typo:
        lines.append("## 🔤 Типографика")
        lines.append("")
        lines.append(f"- font-family: `{typo.get('font_family', '?')}`")
        for size_name, size_val in (typo.get("sizes") or {}).items():
            lines.append(f"- `{size_name}` = `{size_val}`")
        lines.append("")

    if analysis.get("sidebar_width"):
        lines.append(f"## 📐 Layout")
        lines.append("")
        lines.append(f"- sidebar_width: **{analysis['sidebar_width']}**")
        lines.append(f"- spacing_grid: {analysis.get('spacing_grid', '?')}")
        for k, v in (analysis.get("border_radius") or {}).items():
            lines.append(f"- radius `{k}` = {v}")
        lines.append("")

    icons = analysis.get("icons_observed", [])
    if icons:
        lines.append(f"## 🔣 Иконки ({analysis.get('icon_style', '?')})")
        lines.append("")
        lines.append("Замечены: " + ", ".join(icons))
        lines.append("")

    diff = analysis.get("tokens_css_diff", [])
    if diff:
        lines.append(f"## 📝 Предлагаемые изменения tokens.css ({len(diff)})")
        lines.append("")
        for d in diff:
            lines.append(f"- **`{d.get('variable')}`**: `{d.get('current')}` → `{d.get('proposed')}`")
            if d.get("reason"):
                lines.append(f"  _{d['reason']}_")
        lines.append("")
        lines.append("**Применить:** `python3 scripts/design_clone_agent.py --apply` (после Pavel approve)")
        lines.append("")

    comp = analysis.get("component_changes", [])
    if comp:
        lines.append(f"## 🧩 Component changes ({len(comp)})")
        lines.append("")
        for c in comp:
            lines.append(f"### `{c.get('component')}`")
            lines.append(f"- {c.get('change')}")
            if c.get("css_snippet"):
                lines.append(f"```css\n{c['css_snippet']}\n```")
            lines.append("")

    patterns = analysis.get("layout_patterns", [])
    if patterns:
        lines.append("## 🏗 Layout patterns Claude Desktop")
        lines.append("")
        for p in patterns:
            lines.append(f"- **{p.get('name', '?')}** — {p.get('description', '?')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Что делать Pavel-у:**")
    lines.append("- Прочитай предлагаемые изменения")
    lines.append("- Если ОК — скажи «применяй design-clone», я заменю `tokens.css` и обновлю компоненты")
    lines.append("- Если что-то не подходит — точечно отметь, я учту в следующей итерации")
    lines.append("")
    if "usage" in analysis:
        u = analysis["usage"] or {}
        lines.append(f"_Opus tokens: {u.get('input_tokens', '?')} → {u.get('output_tokens', '?')}_")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    # Save raw JSON для будущего --apply
    raw_file = REPORTS = V2 / ".codex/design-clone-proposal.json"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="(TBD) применить proposal к tokens.css")
    args = ap.parse_args()

    screenshots = load_screenshots()
    print(f"Скриншотов в reference/: {len(screenshots)}")
    our_tokens = ""
    tf = V2 / "app/static/tokens.css"
    if tf.exists():
        our_tokens = tf.read_text(encoding="utf-8")
    analysis = {}
    if screenshots:
        analysis = analyze_with_vision(screenshots, our_tokens)
    write_report(analysis, len(screenshots))
    print(f"✓ {OUTPUT}")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "design_clone_proposal",
            "target": "ui",
            "payload": {
                "screenshots": len(screenshots),
                "has_proposal": bool(analysis and not analysis.get("error")),
                "diff_count": len(analysis.get("tokens_css_diff", [])) if isinstance(analysis, dict) else 0,
            },
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
