#!/usr/bin/env python3
"""Ночной reflection-agent.

Pavel 2026-05-25: «каждую ночь думай что можно улучшить и что было
проигнорировано и как внедрить то что облегчит мне жизнь».

Запускается через launchd в 02:30 ET каждую ночь. Что делает:

1. Читает data/pavel-requests/*.jsonl за последние 7 дней
2. Находит все status=open, status=ignored, status=partial
3. Через Opus генерирует анализ:
   - Какие из этих запросов реально критичны для Pavel-овской работы
   - Какие были забыты Tom-ом (паттерн!)
   - Что предложить улучшить
4. Сохраняет в reports/NIGHTLY-REFLECTION-YYYY-MM-DD.md
5. Создаёт markdown который briefing подцепит автоматически
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def get_oauth_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def collect_recent_requests(days: int = 7) -> list:
    """Загрузить все pavel-requests за последние N дней."""
    log_dir = ROOT / "data" / "pavel-requests"
    if not log_dir.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    requests = []
    for f in sorted(log_dir.glob("*.jsonl"), reverse=True):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts_str = rec.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00") if "T" in ts_str else ts_str + "T00:00:00+00:00")
                except Exception:
                    continue
                if ts.replace(tzinfo=timezone.utc) >= cutoff:
                    requests.append(rec)
        except Exception:
            continue
    return requests


def ask_opus_reflection(requests: list) -> dict:
    """Опус анализирует requests, ищет паттерны."""
    token = get_oauth_token()
    if not token:
        return {"error": "no token"}

    payload = "\n".join(
        f"- [{r.get('ts','')}] [{r.get('status','?')}] {r.get('request','')[:200]}"
        + (f" · note: {r.get('note','')[:150]}" if r.get('note') else "")
        for r in requests
    )

    system = (
        "Ты — рефлексирующий ассистент Tom-а. Tom — AI-помощник Pavel-а "
        "(целитель, пишет Священный Кодекс Микомистицизма). Раз в сутки "
        "анализируешь все запросы Pavel-а за неделю и помогаешь Tom-у "
        "увидеть свои паттерны.\n\n"
        "Дано: список Pavel-овских запросов со статусами done / partial / "
        "open / ignored / wont_fix.\n\n"
        "Твоя задача — короткий честный JSON:\n"
        "{\n"
        '  "what_works_well": ["…что Tom стабильно делает хорошо…"],\n'
        '  "what_was_ignored": ["…явно проигнорированные запросы Pavel-а…"],\n'
        '  "patterns_of_failure": ["…типовые проблемы Tom-а…"],\n'
        '  "what_to_improve_tomorrow": ["…конкретные действия которые Pavel-у '
        'облегчат жизнь, отсортированы по важности…"],\n'
        '  "open_items_critical": ["…items со status=open что критичны…"]\n'
        "}\n\n"
        "Будь честным. Без преамбулы, сразу JSON."
    )
    body = {
        "model": "claude-opus-4-7",
        "max_tokens": 3000,
        "system": system,
        "messages": [{"role": "user", "content": f"Запросы Pavel-а за 7 дней:\n\n{payload}\n\nДай JSON-анализ."}],
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8787/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"opus: {e}"}

    raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        if raw.startswith("json"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    try:
        return json.loads(raw.strip())
    except Exception:
        return {"error": "parse", "raw": raw[:500]}


def write_report(reflection: dict, total_requests: int):
    """Пишет markdown в reports/NIGHTLY-REFLECTION-<date>.md."""
    out_dir = ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    md_path = out_dir / f"NIGHTLY-REFLECTION-{today}.md"

    lines = [
        f"# Ночной отчёт-рефлексия Tom-а — {today}",
        "",
        f"Проанализировано **{total_requests}** запросов Pavel-а за последние 7 дней.",
        "",
    ]

    if reflection.get("error"):
        lines.append(f"_Opus ошибка: {reflection['error']}_")
    else:
        if reflection.get("open_items_critical"):
            lines.append("## 🔴 Критичные open-items (требуют действия)")
            for it in reflection["open_items_critical"]:
                lines.append(f"- {it}")
            lines.append("")
        if reflection.get("what_was_ignored"):
            lines.append("## ⚠ Что Tom явно проигнорировал")
            for it in reflection["what_was_ignored"]:
                lines.append(f"- {it}")
            lines.append("")
        if reflection.get("patterns_of_failure"):
            lines.append("## 🔁 Паттерны проблем Tom-а")
            for it in reflection["patterns_of_failure"]:
                lines.append(f"- {it}")
            lines.append("")
        if reflection.get("what_to_improve_tomorrow"):
            lines.append("## ✨ Что улучшить завтра (приоритет сверху)")
            for it in reflection["what_to_improve_tomorrow"]:
                lines.append(f"- {it}")
            lines.append("")
        if reflection.get("what_works_well"):
            lines.append("## ✅ Что Tom стабильно делает хорошо")
            for it in reflection["what_works_well"]:
                lines.append(f"- {it}")
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    # Также пишем json для briefing.py
    json_path = out_dir / f"NIGHTLY-REFLECTION-{today}.json"
    json_path.write_text(json.dumps({
        "date": today,
        "total_requests": total_requests,
        "reflection": reflection,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    requests = collect_recent_requests(days=args.days)
    if not requests:
        print("No recent requests")
        return 0

    print(f"Analyzing {len(requests)} requests…")
    reflection = ask_opus_reflection(requests)
    md = write_report(reflection, len(requests))
    print(f"Saved: {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
