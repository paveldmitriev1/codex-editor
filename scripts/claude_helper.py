"""
claude_helper.py — обёртка для Claude API через OAuth-proxy.

Использование:
    from claude_helper import ask_opus
    response = ask_opus(system="...", user="...", max_tokens=8000, thinking_budget=4000)

Безопасность: токен читается из ~/.cc-memory-bridge/.env, НИКОГДА не логируется.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


PROXY_URL = "http://127.0.0.1:8787"
ENV_FILE = Path.home() / ".cc-memory-bridge/.env"
MODEL_OPUS = "claude-opus-4-7"           # Pavel сказал: «не экономь, самая умная модель»
MODEL_SONNET = "claude-sonnet-4-6"        # backup если Opus упирается в лимит
MODEL_HAIKU = "claude-haiku-4-5-20251001"


def _get_token() -> Optional[str]:
    """Читает OAuth-токен из .env. НЕ возвращает в логи."""
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def ask_claude(
    user: str,
    system: str = "",
    model: str = MODEL_OPUS,
    max_tokens: int = 8000,
    thinking_budget: int = 0,
    temperature: float = 1.0,
    timeout: int = 300,
    retries: int = 4,
) -> dict:
    """
    Один запрос к Claude через proxy. Возвращает структуру:
    {
        "text": "...",                  # объединённый text-блок ответа
        "thinking": "...",              # extended thinking (если включено)
        "usage": {...},                 # input/output tokens
        "stop_reason": "...",
        "model": "...",
        "raw": {...},                   # полный ответ
    }
    """
    token = _get_token()
    if not token:
        raise RuntimeError("OAuth token not found in ~/.cc-memory-bridge/.env")

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    if thinking_budget > 0:
        body["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    # Proxy expects token in x-api-key (it rewrites OAuth-tokens to Bearer upstream itself).
    req = urllib.request.Request(
        f"{PROXY_URL}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    import time
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            # Retry на 429 / 5xx (особенно 529 overloaded)
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                wait = 2 ** attempt * 10  # 10, 20, 40, 80 сек
                print(f"  ⚠ HTTP {e.code}, ждём {wait}с (попытка {attempt+1}/{retries})")
                time.sleep(wait)
                # Пересоздать req
                req = urllib.request.Request(
                    f"{PROXY_URL}/v1/messages",
                    data=json.dumps(body).encode("utf-8"),
                    headers={
                        "x-api-key": token,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                last_err = e
                continue
            raise RuntimeError(f"HTTP {e.code}: {err_body[:500]}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                wait = 2 ** attempt * 5
                print(f"  ⚠ Connection error, ждём {wait}с")
                time.sleep(wait)
                last_err = e
                continue
            raise RuntimeError(f"Connection failed: {e.reason}")
    else:
        raise RuntimeError(f"All retries failed: {last_err}")

    # Собрать текст и thinking из content-блоков
    text_parts, thinking_parts = [], []
    for block in data.get("content", []):
        t = block.get("type")
        if t == "text":
            text_parts.append(block.get("text", ""))
        elif t == "thinking":
            thinking_parts.append(block.get("thinking", ""))

    return {
        "text": "".join(text_parts),
        "thinking": "".join(thinking_parts),
        "usage": data.get("usage", {}),
        "stop_reason": data.get("stop_reason"),
        "model": data.get("model"),
        "raw": data,
    }


def ask_opus(user: str, system: str = "", max_tokens: int = 8000, thinking: int = 4000) -> dict:
    """Удобная обёртка для Opus 4.7 с extended thinking по умолчанию."""
    return ask_claude(user=user, system=system, model=MODEL_OPUS,
                       max_tokens=max_tokens, thinking_budget=thinking)


# ─── Тест ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    print("Тестирую через Sonnet (дешёвый прогон чтобы убедиться что auth работает)...")
    try:
        r = ask_claude(
            user="Ответь одним словом: 'ok'.",
            model=MODEL_SONNET,
            max_tokens=20,
            thinking_budget=0,
        )
        print(f"✓ Ответ: {r['text'][:100]}")
        print(f"✓ Модель: {r['model']}")
        print(f"✓ Tokens in/out: {r['usage'].get('input_tokens')}/{r['usage'].get('output_tokens')}")
        print(f"\n✓ Claude API через proxy работает.")
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        sys.exit(1)
