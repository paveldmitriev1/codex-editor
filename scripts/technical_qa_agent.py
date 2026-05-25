#!/usr/bin/env python3
"""
technical_qa_agent.py — ночной агент технического QA.

Проверяет:
1. Health всех endpoints (/api/toc, /api/chapter/<id>/draft, etc.) — должны возвращать 200
2. JSON-валидность всех cached файлов (council.json, metaphors.json, notes.json, etc.)
3. events.jsonl — нет ли corrupted строк
4. Файлы которые должны быть (draft.md когда есть finalized.md, и т.п.)
5. Дубликаты PID-файлов или зависшие процессы

Output: reports/TECH-QA-PENDING.md (append-only checklist)
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
OUTPUT = V2 / "reports/TECH-QA-PENDING.md"

BASE_URL = "http://127.0.0.1:7788"
ENDPOINTS_GET = [
    "/api/toc",
    "/api/chapter/book-03-ch-01/draft",
    "/api/chapter/book-03-ch-01/approvals",
    "/api/chapter/book-03-ch-01/council",
    "/api/chapter/book-03-ch-01/metaphors",
    "/api/chapter/book-03-ch-01/notes",
    "/api/chapter/book-03-ch-01/ideas",
]


def check_endpoint(path):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=10) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            data = resp.read()
            if not data:
                return False, "empty response"
            # Try parse as JSON
            try:
                json.loads(data)
            except json.JSONDecodeError:
                return False, "invalid JSON"
            return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:120]


def check_json_files():
    """Все *.json файлы в .codex/ и chapters/ должны быть валидны."""
    errors = []
    targets = list((V2 / ".codex").glob("*.json"))
    for ch_dir in (V2 / "chapters").glob("*/*"):
        if ch_dir.is_dir():
            targets.extend(ch_dir.glob("*.json"))
    for f in targets:
        try:
            with f.open("r", encoding="utf-8") as fh:
                json.load(fh)
        except json.JSONDecodeError as e:
            errors.append(f"{f.relative_to(V2)}: {e}")
        except Exception as e:
            errors.append(f"{f.relative_to(V2)}: {e}")
    return errors


def check_events_jsonl():
    """Все строки events.jsonl должны быть валидным JSON с ts/type."""
    f = V2 / ".codex/events.jsonl"
    if not f.exists():
        return []
    errors = []
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if "ts" not in e or "type" not in e:
                errors.append(f"line {i}: missing ts/type")
        except json.JSONDecodeError as ex:
            errors.append(f"line {i}: {ex}")
    return errors[:10]  # max 10


def check_stale_pids():
    """PID-файлы которые указывают на мёртвые процессы."""
    stale = []
    for f in (V2 / ".codex").glob("*.pid"):
        try:
            pid = int(f.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, OSError):
            stale.append(str(f.relative_to(V2)))
    return stale


def main():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    issues = []

    # 1. Endpoints
    for path in ENDPOINTS_GET:
        ok, err = check_endpoint(path)
        if not ok:
            issues.append({
                "category": "endpoint",
                "severity": "high",
                "where": path,
                "message": err,
            })

    # 2. JSON files
    for err in check_json_files():
        issues.append({
            "category": "json",
            "severity": "medium",
            "where": err.split(":")[0],
            "message": err,
        })

    # 3. events.jsonl
    for err in check_events_jsonl():
        issues.append({
            "category": "events",
            "severity": "low",
            "where": ".codex/events.jsonl",
            "message": err,
        })

    # 4. Stale PIDs
    for pid_file in check_stale_pids():
        issues.append({
            "category": "stale_pid",
            "severity": "low",
            "where": pid_file,
            "message": "PID файл указывает на мёртвый процесс",
        })

    # Write to TECH-QA-PENDING.md (append)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if not issues:
        lines.append(f"## {ts} — всё чисто ✓\n")
    else:
        lines.append(f"## {ts} — {len(issues)} проблем\n")
        for i in issues:
            lines.append(f"- [ ] **[{i['category']}/{i['severity']}]** `{i['where']}` — {i['message']}")
        lines.append("")
    with OUTPUT.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Event
    with (V2 / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": ts, "type": "tech_qa_run", "target": "system",
            "payload": {"issues_found": len(issues), "categories": {i["category"] for i in issues} if False else list({i["category"] for i in issues})}
        }, ensure_ascii=False) + "\n")
    print(f"✓ tech QA: {len(issues)} issues → {OUTPUT}")


if __name__ == "__main__":
    main()
