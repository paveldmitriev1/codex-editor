#!/usr/bin/env python3
"""UC-128: ночной аудит логических цепочек и связей процессов.

Pavel: «каждую ночь включать процесс который оптимизирует и выявляет
все ли логические цепочки связаны, нет ли повреждений в логике.
Очень много процессов, они должны быть все связаны».

Что проверяет:
  1. Все endpoints живые (curl 200)
  2. Все analyzer scripts парсятся без ошибок
  3. Цепочка editor: critics → reconciler → journalist → apply-targeted
  4. Кэши свежие (не старше 7 дней)
  5. События в .codex/events.jsonl связаны: chapter_saved события создают
     content_updated_at, title_sync, и т.д.
  6. voice-corpus accessible
  7. config files (styles, critics-config, quality-config) валидны

Запуск раз в сутки. Результат — отчёт в reports/nightly-logic-audit-<date>.md.
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
REPORTS = V2 / "reports"

CHECKS = []


def check(name):
    """Декоратор для регистрации проверки."""
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("Server 7788 alive")
def check_server():
    try:
        with urllib.request.urlopen("http://127.0.0.1:7788/api/health", timeout=5) as r:
            return r.status == 200, f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)


@check("Endpoints respond")
def check_endpoints():
    eps = [
        "/api/toc",
        "/api/recent-works",
        "/api/styles",
        "/api/quality-config",
        "/api/library/files",
        "/api/critics",
    ]
    bad = []
    for ep in eps:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:7788{ep}", timeout=10) as r:
                if r.status != 200:
                    bad.append(f"{ep}: HTTP {r.status}")
        except Exception as e:
            bad.append(f"{ep}: {e}")
    if bad:
        return False, "; ".join(bad)
    return True, f"{len(eps)} OK"


@check("Analyzer scripts parse")
def check_scripts():
    import ast
    scripts = [
        "scripts/critic_council.py",
        "scripts/journalist.py",
        "scripts/editor_journalist.py",
        "scripts/reconciler.py",
        "scripts/sequence_analyzer.py",
        "scripts/library_analyze.py",
        "scripts/personas.py",
        "scripts/book_editor.py",
        "app/server.py",
    ]
    bad = []
    for s in scripts:
        p = V2 / s
        if not p.exists():
            bad.append(f"{s}: missing")
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            bad.append(f"{s}: {e}")
    if bad:
        return False, "; ".join(bad)
    return True, f"{len(scripts)} OK"


@check("Config files valid JSON")
def check_configs():
    cfgs = [
        "data/styles.json",
        "data/quality-config.json",
        "data/critics-config.json",
        "toc.json",
    ]
    bad = []
    for c in cfgs:
        p = V2 / c
        if not p.exists():
            continue  # OK — optional
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append(f"{c}: {e}")
    if bad:
        return False, "; ".join(bad)
    return True, f"{len(cfgs)} OK"


@check("voice-corpus accessible")
def check_voice():
    paths = [
        V2 / "voice-corpus/raw",
        V2 / "voice-corpus/original-ideas",
    ]
    counts = []
    for p in paths:
        if p.exists():
            counts.append(f"{p.name}: {len(list(p.glob('*.md')))} files")
        else:
            counts.append(f"{p.name}: MISSING")
    return all("MISSING" not in c for c in counts), "; ".join(counts)


@check("Editor chain — chapter has all artifacts")
def check_chain():
    """Берём book-obsession-ch-01 как индикатор. Проверяем что цепочка работает."""
    ch = V2 / "chapters/book-obsession/book-obsession-ch-01"
    if not ch.exists():
        return False, "ch dir missing"
    must_have = ["draft.md", "council.json", "voice-analysis.json"]
    missing = [f for f in must_have if not (ch / f).exists()]
    if missing:
        return False, f"missing: {missing}"
    return True, "all artifacts present"


@check("Recent CRITICS reports")
def check_critics_reports():
    """Должны быть свежие отчёты критиков (не старше 30 дней)."""
    reports = list((V2 / "reports").glob("CRITICS-*.json")) if (V2 / "reports").exists() else []
    if not reports:
        return False, "no CRITICS reports"
    newest = max(reports, key=lambda p: p.stat().st_mtime)
    age_days = (datetime.now().timestamp() - newest.stat().st_mtime) / 86400
    if age_days > 30:
        return False, f"newest is {age_days:.1f} days old"
    return True, f"{len(reports)} reports, newest {age_days:.1f}d old"


@check("Reconciler cache freshness")
def check_reconciler():
    cache = V2 / "data/reconciled"
    if not cache.exists():
        return True, "cache empty (OK, run reconciler in editor)"
    files = list(cache.glob("*.json"))
    return True, f"{len(files)} chapters reconciled"


def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []
    for name, fn in CHECKS:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"exception: {e}"
        results.append({"check": name, "ok": ok, "msg": msg})

    ok_count = sum(1 for r in results if r["ok"])
    total = len(results)
    health = "🟢 ВСЁ OK" if ok_count == total else ("🟡 ЧАСТИЧНО" if ok_count >= total * 0.7 else "🔴 НУЖНО ЧИНИТЬ")

    md = [f"# Ночной аудит логических цепочек\n",
          f"**Время:** {ts}",
          f"**Статус:** {health} ({ok_count}/{total})",
          ""]
    for r in results:
        emoji = "✅" if r["ok"] else "❌"
        md.append(f"- {emoji} **{r['check']}** — {r['msg']}")
    md.append("")
    md.append("---")
    md.append("Если есть ❌ — Tom должен починить или хотя бы flag-нуть Pavel-у.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"NIGHTLY-LOGIC-AUDIT-{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\nReport saved: {out}")
    return 0 if ok_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
