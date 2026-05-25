#!/usr/bin/env python3
"""
condense_briefing.py — сократить MORNING-BRIEFING.md в 4 раза (UC-99).

Pavel 2026-05-22: «утренний брифинг сократи до минимальных заданий на день
и что произошло за ночь. Сократи в 4 раза».

Идея: исходный брифинг 13K символов → сжимаем до ~3K через Opus 4.7.
Формат:
1. ЧТО ПРОИЗОШЛО ЗА НОЧЬ (5-7 строк)
2. ЗАДАНИЯ НА ДЕНЬ (5-7 пунктов)
3. ВАЖНО (3-5 пунктов)

Запуск каждое утро 06:00 через launchd.
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
from config import MAX_MODEL, PROXY_URL  # noqa: E402

V2 = Path.home() / "Desktop/Codex2"
BRIEFING = V2 / "reports/MORNING-BRIEFING.md"


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def condense(text: str) -> str:
    token = get_token()
    if not token:
        return text
    system = (
        "Ты сжимаешь утренний брифинг Pavel-а в 4 раза. Формат на выходе строго:\n\n"
        "## Что произошло за ночь\n"
        "5-7 строк фактов: кто работал, какие отчёты появились, ключевые цифры.\n\n"
        "## Задания на день\n"
        "5-7 пунктов в приоритете. Каждый пункт одна строка с конкретным действием.\n\n"
        "## Важно\n"
        "3-5 пунктов: предупреждения, заблокированные процессы, что Pavel должен решить.\n\n"
        "Правила: без воды, без преамбулы, без эмодзи, без тире (UC-76). Русский язык."
    )
    user = f"Сократи в 4 раза:\n\n{text[:12000]}"
    body = {
        "model": MAX_MODEL,
        "max_tokens": 2000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
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
    except Exception as e:
        return f"## Ошибка сокращения\n{e}\n\n{text[:3000]}"
    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(blocks).strip()


def main():
    if not BRIEFING.exists():
        print(f"Брифинг не найден: {BRIEFING}")
        return 1
    original = BRIEFING.read_text(encoding="utf-8")
    original_chars = len(original)
    if original_chars < 3500:
        print(f"Брифинг уже короткий ({original_chars} симв), не сокращаю")
        return 0
    print(f"Сокращаю брифинг {original_chars} симв через Opus 4.7…")
    condensed = condense(original)
    # Уберём остатки тире (UC-76)
    import re
    condensed = re.sub(r"\s+—\s+", " ", condensed)
    condensed = re.sub(r"\s+–\s+", " ", condensed)
    condensed = re.sub(r"[\U0001F300-\U0001FAFF]", "", condensed)
    # Сохраняем
    header = f"# Утренний брифинг · {datetime.now().strftime('%Y-%m-%d')}\n\n"
    BRIEFING.write_text(header + condensed + "\n", encoding="utf-8")
    print(f"Готово: {original_chars} → {len(condensed)} симв (×{original_chars / max(len(condensed), 1):.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
