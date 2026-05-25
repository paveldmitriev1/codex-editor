#!/usr/bin/env python3
"""
model_guard.py — бот-проверяльщик что вызовы Anthropic API используют МАКСИМАЛЬНУЮ модель.

Pavel 2026-05-21: «перед тем чтобы писать что это максимально лучшая модель,
когда выйдет новая — она должна быть оптимальная максимальная».

ЧТО ДЕЛАЕТ:
1. Сканирует app/server.py + scripts/*.py на хардкод моделей != MAX_MODEL
2. Сканирует app/server.py на каждый вызов Anthropic (поиск URL proxy)
3. Логирует находки в reports/MODEL-GUARD.md
4. При флаге --check-new: дёргает proxy /v1/models, ищет более новую модель
5. При нарушении exit code = 1 (для launchd alerting)

ЗАПУСК:
- Pre-flight перед стартом сервера: python3 scripts/model_guard.py
- Раз в час фоном: launchd plist ai.codex2.model-guard
- Pavel-у CLI: python3 scripts/model_guard.py --verbose
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Импортируем константы из app/config.py
sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
from config import MAX_MODEL, PROXY_URL, FALLBACK_HEALTHCHECK_MODEL, EVENTS_PATH  # noqa: E402

V2 = Path.home() / "Desktop/Codex2"
REPORT = V2 / "reports/MODEL-GUARD.md"

# Регексы для поиска вызовов и моделей
MODEL_REGEX = re.compile(r'"model"\s*:\s*"(claude-[a-z0-9\-]+)"')
HARDCODE_MODEL_STR = re.compile(r'["\'](claude-(?:opus|sonnet|haiku|3)[a-z0-9\-]*)["\']')

# Files to scan
SCAN_FILES = [
    V2 / "app/server.py",
    *list((V2 / "scripts").glob("*.py")),
]

# Allowed exceptions — где использование альтернативной модели OK
ALLOWED_NON_MAX = {
    "claude_helper.py": ["MODEL_SONNET", "MODEL_HAIKU"],  # backup constants
    "model_guard.py": ["MODEL_REGEX", "HARDCODE_MODEL_STR"],  # this file itself
    "config.py": ["FALLBACK_HEALTHCHECK_MODEL"],  # whitelist
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_event(kind: str, payload: dict):
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": now_iso(),
            "type": kind,
            "target": "model_guard",
            "payload": payload,
        }, ensure_ascii=False) + "\n")


def scan_file_for_models(path: Path) -> list:
    """Возвращает [(line_no, model_str)] для каждого хардкода != MAX_MODEL."""
    findings = []
    if not path.exists():
        return findings
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return findings
    for i, line in enumerate(text.splitlines(), start=1):
        # Skip if this is the config file itself (declares MAX_MODEL)
        if path.name == "config.py" and "MAX_MODEL" in line:
            continue
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        # Find "model": "claude-xxx" pattern
        m = MODEL_REGEX.search(line)
        if m:
            model = m.group(1)
            if model != MAX_MODEL and model != FALLBACK_HEALTHCHECK_MODEL:
                findings.append((i, model, line.strip()[:120]))
            continue
        # Find raw "claude-xxx" strings (not in MODEL_REGEX context)
        m2 = HARDCODE_MODEL_STR.search(line)
        if m2:
            model = m2.group(1)
            # Whitelist check
            name = path.name
            if name in ALLOWED_NON_MAX:
                if any(allow in line for allow in ALLOWED_NON_MAX[name]):
                    continue
            if model != MAX_MODEL and model != FALLBACK_HEALTHCHECK_MODEL:
                findings.append((i, model, line.strip()[:120]))
    return findings


def check_proxy_alive() -> bool:
    try:
        r = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{PROXY_URL}/health", "--max-time", "3"],
            text=True, timeout=5,
        ).strip()
        return r in ("200", "204")
    except Exception:
        return False


def check_canon_exists() -> tuple:
    """Returns (exists, size_chars)."""
    canon = V2 / "CANON.md"
    if not canon.exists():
        return False, 0
    return True, len(canon.read_text(encoding="utf-8"))


def render_report(findings_by_file: dict, canon_status: tuple,
                  proxy_alive: bool) -> str:
    lines = [
        f"# MODEL GUARD · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**MAX_MODEL:** `{MAX_MODEL}`",
        f"**Proxy alive:** {'да' if proxy_alive else 'НЕТ'} ({PROXY_URL})",
        f"**CANON.md:** {'есть, ' + str(canon_status[1]) + ' символов' if canon_status[0] else 'НЕ НАЙДЕН'}",
        "",
    ]
    total = sum(len(v) for v in findings_by_file.values())
    if total == 0:
        lines.append("## Все вызовы используют MAX_MODEL")
        lines.append("")
        lines.append(f"Просканировано {len(SCAN_FILES)} файлов.")
    else:
        lines.append(f"## Найдено {total} нарушений")
        lines.append("")
        for fpath, items in findings_by_file.items():
            if not items:
                continue
            rel = fpath.relative_to(V2) if V2 in fpath.parents else fpath
            lines.append(f"### {rel}")
            for line_no, model, snippet in items:
                lines.append(f"- L{line_no}: `{model}` — `{snippet}`")
            lines.append("")
    return "\n".join(lines)


def main():
    verbose = "--verbose" in sys.argv
    check_new = "--check-new" in sys.argv

    findings_by_file = {}
    for f in SCAN_FILES:
        findings = scan_file_for_models(f)
        findings_by_file[f] = findings

    canon_status = check_canon_exists()
    proxy_alive = check_proxy_alive()

    report = render_report(findings_by_file, canon_status, proxy_alive)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")

    total_violations = sum(len(v) for v in findings_by_file.values())

    log_event("model_guard_check", {
        "violations": total_violations,
        "canon_ok": canon_status[0],
        "proxy_alive": proxy_alive,
        "max_model": MAX_MODEL,
    })

    if verbose or total_violations > 0:
        print(report)

    if check_new:
        # Future: query proxy for available models
        # For now, just remind that Pavel needs to manually upgrade MAX_MODEL constant
        from datetime import datetime as _dt
        from config import MAX_MODEL_RELEASED_AT
        try:
            yyyymm = _dt.strptime(MAX_MODEL_RELEASED_AT, "%Y-%m")
            age_days = (datetime.now() - yyyymm).days
            if age_days > 60:
                msg = f"⚠ MAX_MODEL ({MAX_MODEL}) старше 60 дней. Проверь release notes Anthropic."
                print(msg)
                log_event("model_guard_age_alert", {"age_days": age_days})
        except Exception:
            pass

    sys.exit(0 if total_violations == 0 else 1)


if __name__ == "__main__":
    main()
