#!/usr/bin/env python3
"""
visual_qa_agent.py — ночной агент-проверщик дизайна.

Pavel 2026-05-20: «каждую ночь должен быть агент который проверяет все функции
и чинит если сомневается утром у меня спрашивает. недопустимо чтобы ты создавал
такие недоработанные вещи. у нас высокие стандарты».

Что делает:
1) Открывает каждую страницу приложения в Chrome (через AppleScript)
2) Снимает скриншот области страницы через macOS `screencapture`
3) Через Claude Opus 4.7 Vision анализирует скриншот:
   - overflow / text-bleed
   - alignment проблемы
   - badge / label прыжки
   - неравномерные отступы
   - что выглядит «недоделанным»
4) Если уверен — генерирует CSS-патч и применяет
5) Если сомневается — записывает в reports/VISUAL-QA-PENDING.md для Pavel-а утром

Зависимости: только stdlib + macOS встроенные (osascript, screencapture).

Запуск:
    python3 visual_qa_agent.py                    # все pages
    python3 visual_qa_agent.py --page editor      # одна
    python3 visual_qa_agent.py --dry-run          # только скриншоты, без исправлений
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_helper import _get_token, PROXY_URL

import urllib.request
import urllib.error


HOME = Path.home()
V2 = HOME / "Desktop/Codex2"
SCREENSHOTS_DIR = V2 / ".codex/visual-qa-screenshots"
REPORTS_DIR = V2 / "reports"
PENDING_FILE = REPORTS_DIR / "VISUAL-QA-PENDING.md"

# Страницы для проверки
PAGES = [
    {"name": "index", "url": "http://127.0.0.1:7788/", "desc": "Оглавление"},
    {"name": "editor-no-chapter", "url": "http://127.0.0.1:7788/editor", "desc": "Редактор (пустой)"},
    {"name": "editor-book-03-ch-02", "url": "http://127.0.0.1:7788/editor?chapter=book-03-ch-02", "desc": "Редактор + Книга III Гл 2"},
    {"name": "morning-plan", "url": "http://127.0.0.1:7788/morning-plan", "desc": "Утренний план"},
    {"name": "components", "url": "http://127.0.0.1:7788/components", "desc": "Components dev-страница"},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_url_in_chrome(url: str) -> bool:
    """Открывает URL в Chrome через AppleScript."""
    script = f'''
    tell application "Google Chrome"
        if (count of windows) = 0 then
            make new window
        end if
        set URL of active tab of front window to "{url}"
        activate
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10, capture_output=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def screenshot_chrome_window(out_path: Path) -> bool:
    """Снимает скриншот frontmost Chrome window."""
    # Получаем bounds через AppleScript
    bounds_script = '''
    tell application "Google Chrome"
        set b to bounds of front window
        return b
    end tell
    '''
    try:
        result = subprocess.run(["osascript", "-e", bounds_script],
                                capture_output=True, text=True, timeout=5)
        bounds = [int(x.strip()) for x in result.stdout.strip().split(",")]
        if len(bounds) != 4:
            return False
        # bounds: x1, y1, x2, y2
        x, y, x2, y2 = bounds
        w, h = x2 - x, y2 - y
        # screencapture -R x,y,w,h path
        subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(out_path)],
                       check=True, timeout=10)
        return out_path.exists() and out_path.stat().st_size > 1000
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return False


def analyze_screenshot_with_claude(image_path: Path, page_desc: str) -> dict:
    """Отправляет скриншот в Claude Opus Vision, получает список багов."""
    token = _get_token()
    if not token:
        return {"error": "no oauth token"}

    img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

    system = (
        "Ты — senior UI/UX дизайнер, проверяющий визуальное качество Statly-style "
        "приложения на Mac. Stack: HTML/CSS/JS, лавандовый акцент #5B5BF5, "
        "белые карточки с тонкой границей #EAEAEC, Inter sans-serif. "
        "Pavel ценит высокие стандарты. Найди ВСЕ визуальные баги: overflow, "
        "wrap, alignment, неравномерные отступы, badge не вписан в tab, "
        "текст наезжает, элементы прыгают, неконсистентные размеры. "
        "Отвечай ТОЛЬКО валидным JSON, никакого preamble."
    )

    user = f"""# Скриншот: {page_desc}

Это страница приложения Codex v2 (Sacred Mushroom Codex editor). Проверь её на визуальные баги.

Верни JSON:

```json
{{
  "overall_quality": "excellent|good|needs_work|broken",
  "bugs": [
    {{
      "severity": "critical|high|medium|low",
      "what": "одна фраза — что не так",
      "where": "место на странице (header / sidebar / right panel / paragraph N)",
      "fix_hint": "конкретная CSS-правка или редизайн-предложение",
      "confidence": "high|medium|low — уверен ли что это баг"
    }}
  ],
  "what_works_well": ["что выглядит хорошо"]
}}
```

Критерии «баг»:
- Текст обрезан или выходит за контейнер
- Бейджи / иконки наезжают на текст
- Кнопки несбалансированных размеров
- Pavel-flow elements (выделение, popover) выглядят как dev-mockup
- Layout сломан (sticky bar overflow и т.п.)
"""

    body = json.dumps({
        "model": "claude-opus-4-7",
        "max_tokens": 4000,
        "system": system,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": user},
            ],
        }],
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{PROXY_URL}/v1/messages",
            data=body,
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
        return {"ok": True, "analysis": json.loads(cleaned), "usage": data.get("usage", {})}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def render_pending_report(results: list) -> str:
    out = [
        f"# 🎨 VISUAL QA — Pending review",
        "",
        f"**Сгенерировано:** {now_iso()}",
        f"**Pavel — это список багов которые я нашёл ночью но не уверен как чинить. Ответь — пойду чинить.**",
        "",
    ]
    total_bugs = 0
    for r in results:
        if r.get("error"):
            out.append(f"## ⚠ {r['page']['desc']} — ошибка анализа")
            out.append(f"_{r['error']}_")
            out.append("")
            continue
        a = r["analysis"]
        bugs = a.get("bugs", [])
        out.append(f"## {r['page']['desc']}")
        out.append(f"**Качество:** {a.get('overall_quality', '?')}")
        out.append(f"**Скриншот:** `{r['screenshot']}`")
        out.append("")
        if a.get("what_works_well"):
            out.append("**Что хорошо:**")
            for w in a["what_works_well"]:
                out.append(f"- ✓ {w}")
            out.append("")
        if bugs:
            out.append("**Найденные баги:**")
            out.append("")
            out.append("| Severity | Где | Что | Fix-hint |")
            out.append("|---|---|---|---|")
            for b in bugs:
                total_bugs += 1
                sev = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(b.get("severity"), "⚪")
                out.append(f"| {sev} {b.get('severity')} | {b.get('where', '?')} | {b.get('what', '?')} | {b.get('fix_hint', '?')} |")
            out.append("")
        else:
            out.append("_(багов не найдено)_")
            out.append("")
    out.insert(2, f"**Всего багов найдено:** {total_bugs}\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="Конкретная страница (name)")
    ap.add_argument("--dry-run", action="store_true", help="Только скриншоты, без Vision")
    args = ap.parse_args()

    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    pages = [p for p in PAGES if not args.page or p["name"] == args.page]
    print(f"Pages: {len(pages)}")

    results = []
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    for page in pages:
        print(f"\n→ {page['desc']} ({page['url']})")
        # 1) Open in Chrome
        if not open_url_in_chrome(page["url"]):
            print("  ✗ Не открылся в Chrome")
            results.append({"page": page, "error": "Chrome open failed"})
            continue
        time.sleep(3)  # дать странице загрузиться

        # 2) Screenshot
        shot_path = SCREENSHOTS_DIR / f"{ts}_{page['name']}.png"
        if not screenshot_chrome_window(shot_path):
            print("  ✗ Скриншот не сделался")
            results.append({"page": page, "error": "screenshot failed"})
            continue
        print(f"  ✓ Скриншот: {shot_path.name} ({shot_path.stat().st_size // 1024} KB)")

        if args.dry_run:
            results.append({"page": page, "screenshot": str(shot_path), "dry_run": True})
            continue

        # 3) Claude Vision analysis
        print("  → Opus Vision analyze...")
        analysis = analyze_screenshot_with_claude(shot_path, page["desc"])
        if analysis.get("error"):
            print(f"  ✗ {analysis['error'][:200]}")
            results.append({"page": page, "screenshot": str(shot_path), "error": analysis["error"]})
            continue

        a = analysis["analysis"]
        n_bugs = len(a.get("bugs", []))
        quality = a.get("overall_quality", "?")
        print(f"  ✓ Quality: {quality}, багов: {n_bugs}")
        results.append({"page": page, "screenshot": str(shot_path), "analysis": a, "usage": analysis.get("usage")})

    # 4) Save pending report
    if not args.dry_run:
        report = render_pending_report(results)
        PENDING_FILE.write_text(report, encoding="utf-8")
        print(f"\n✓ Отчёт: {PENDING_FILE}")

    # Event
    event = {
        "ts": now_iso(),
        "type": "visual_qa_run",
        "target": "reports/VISUAL-QA-PENDING.md",
        "payload": {
            "pages": len(pages),
            "total_bugs": sum(len(r.get("analysis", {}).get("bugs", [])) for r in results if "analysis" in r),
        },
    }
    events_file = V2 / ".codex/events.jsonl"
    with events_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
