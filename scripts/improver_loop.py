#!/usr/bin/env python3
"""
improver_loop.py — каждые 5 минут улучшение suggestions+логики (Pavel 2026-05-21).

Pavel: «каждые 5 минут перепроверяй если меня нет, продолжай улучшать
предложения и логику».

Запускается через launchd `ai.codex2.improver` каждые 300 сек.
Один цикл = одна задача (не infinite loop — launchd сам управляет).

Логика:
1. Проверить pavel_idle — если активен < 5 мин → SKIP (не мешать)
2. Выбрать одну главу из обсессии по round-robin (по day_of_hour)
3. Выбрать тип улучшения по hour % 4:
   - 0: Resonance — пересчитать, если score < 85
   - 1: Hook&Cliff — пересчитать, если hook<80 или cliff<80
   - 2: Logic — пересчитать, если verdict ≠ "clean"
   - 3: Coherence-in-book — заново сравнить с другими главами
4. Сохранить новую версию (она перезаписывает кэш)
5. Записать в IMPROVER-LOG.md (append)

Запуск:
  python3 scripts/improver_loop.py        — один цикл
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
SCRIPTS = V2 / "scripts"
REPORTS = V2 / "reports"
EVENTS = V2 / ".codex/events.jsonl"
LOG_FILE = REPORTS / "IMPROVER-LOG.md"
HEARTBEAT = V2 / ".codex/heartbeat.json"
PAVEL_ACTIONS = V2 / ".codex/pavel-actions.jsonl"
SERVER_URL = "http://127.0.0.1:7788"

IDLE_THRESHOLD_MIN = 5
TIMEOUT_SEC = 180

(V2 / ".codex").mkdir(parents=True, exist_ok=True)


def log_line(msg: str):
    REPORTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def event(kind: str, payload: dict = None):
    try:
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "type": kind,
                "target": "improver",
                "payload": payload or {},
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def pavel_idle_min() -> float:
    """Сколько минут с последнего действия Pavel в UI."""
    if not PAVEL_ACTIONS.exists():
        return 999.0
    last = None
    try:
        with PAVEL_ACTIONS.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    ts = e.get("ts") or e.get("timestamp")
                    if ts:
                        try:
                            dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
                            if last is None or dt > last:
                                last = dt
                        except ValueError:
                            pass
                except json.JSONDecodeError:
                    pass
    except Exception:
        return 999.0
    if last is None:
        return 999.0
    return (datetime.now(timezone.utc) - last).total_seconds() / 60


def server_alive() -> bool:
    try:
        out = subprocess.check_output(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{SERVER_URL}/api/health", "--max-time", "3"],
            text=True, timeout=5,
        )
        return out.strip() == "200"
    except Exception:
        return False


def list_chapters() -> list:
    """Главы обсессии (приоритет №1)."""
    book = V2 / "chapters/book-obsession"
    if not book.exists():
        return []
    return sorted([d.name for d in book.iterdir() if d.is_dir() and not d.name.startswith(".")])


def pick_target() -> tuple:
    """Выбор (chapter_id, kind) по rotation."""
    chapters = list_chapters()
    if not chapters:
        return None, None
    h = datetime.now().hour
    minute_5 = datetime.now().minute // 5  # 0..11
    # Глава: round-robin по 5-минутным окнам (12 окон в час → каждая глава 1.5×/час при 8 главах)
    ch = chapters[(h * 12 + minute_5) % len(chapters)]
    # Тип: rotation по часам
    kinds = ["resonance", "hook-cliff", "logic-analysis", "coherence"]
    kind = kinds[h % len(kinds)]
    return ch, kind


def needs_improvement(ch: str, kind: str) -> tuple:
    """Returns (needs, reason). Читаем cache и решаем."""
    book = "book-obsession"
    ch_dir = V2 / "chapters" / book / ch
    if kind == "resonance":
        f = ch_dir / "resonance.json"
        if not f.exists():
            return True, "не запущен"
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            score = d.get("overall_resonance", 100)
            if score < 85:
                return True, f"resonance {score} < 85"
            return False, f"resonance {score} OK"
        except Exception:
            return True, "cache повреждён"
    if kind == "hook-cliff":
        f = ch_dir / "hook-cliff.json"
        if not f.exists():
            return True, "не запущен"
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            hook = d.get("hook_strength", 100)
            cliff = d.get("cliffhanger_strength", 100)
            if hook < 80 or cliff < 80:
                return True, f"hook={hook} cliff={cliff} — улучшаем"
            return False, f"hook={hook} cliff={cliff} OK"
        except Exception:
            return True, "cache повреждён"
    if kind == "logic-analysis":
        f = ch_dir / "logic-analysis.json"
        if not f.exists():
            return True, "не запущен"
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            verdict = d.get("verdict", "")
            if verdict not in ("clean", "minor_issues"):
                return True, f"verdict={verdict} — переоценить"
            return False, f"verdict={verdict} OK"
        except Exception:
            return True, "cache повреждён"
    if kind == "coherence":
        # coherence-in-book — это локальный Jaccard, не Opus. Всегда можно пересчитать.
        return True, "coherence обновляем (локально, без Opus tokens)"
    return False, "unknown kind"


def run_improvement(ch: str, kind: str) -> dict:
    """Запускает соответствующий endpoint Opus + ждёт."""
    out = {"ok": False}
    try:
        if kind == "resonance":
            r = subprocess.run(
                ["curl", "-s", "-X", "POST",
                 f"{SERVER_URL}/api/chapter/resonance",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"chapter_id": ch}),
                 "--max-time", str(TIMEOUT_SEC)],
                capture_output=True, text=True, timeout=TIMEOUT_SEC + 10,
            )
            out["raw"] = r.stdout[:200]
            out["ok"] = r.returncode == 0
        elif kind == "hook-cliff":
            r = subprocess.run(
                ["curl", "-s", "-X", "POST",
                 f"{SERVER_URL}/api/chapter/hook-cliff",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"chapter_id": ch}),
                 "--max-time", str(TIMEOUT_SEC)],
                capture_output=True, text=True, timeout=TIMEOUT_SEC + 10,
            )
            out["raw"] = r.stdout[:200]
            out["ok"] = r.returncode == 0
        elif kind == "logic-analysis":
            r = subprocess.run(
                ["curl", "-s", "-X", "POST",
                 f"{SERVER_URL}/api/chapter/logic-analysis",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"chapter_id": ch}),
                 "--max-time", str(TIMEOUT_SEC)],
                capture_output=True, text=True, timeout=TIMEOUT_SEC + 10,
            )
            out["raw"] = r.stdout[:200]
            out["ok"] = r.returncode == 0
        elif kind == "coherence":
            r = subprocess.run(
                ["python3", str(SCRIPTS / "chapter_coherence_in_book.py"),
                 "--chapter", ch],
                capture_output=True, text=True, timeout=60,
            )
            out["raw"] = r.stdout[-200:]
            out["ok"] = r.returncode == 0
    except subprocess.TimeoutExpired:
        out["raw"] = "timeout"
    except Exception as e:
        out["raw"] = str(e)
    return out


def main():
    if not server_alive():
        log_line("⚠ server :7788 мёртв — skip, ждём пока manager поднимет")
        return

    idle = pavel_idle_min()
    if idle < IDLE_THRESHOLD_MIN:
        log_line(f"Pavel активен ({idle:.1f} мин назад) — skip, не мешаем")
        event("improver_skip_pavel_active", {"idle_min": round(idle, 1)})
        return

    ch, kind = pick_target()
    if not ch:
        log_line("⚠ нет глав в book-obsession")
        return

    needs, reason = needs_improvement(ch, kind)
    if not needs:
        log_line(f"⏭ {ch}/{kind}: {reason}")
        event("improver_skip_ok", {"chapter": ch, "kind": kind, "reason": reason})
        return

    log_line(f"▶ {ch}/{kind}: {reason} → улучшаем")
    t0 = time.time()
    result = run_improvement(ch, kind)
    elapsed = time.time() - t0

    status = "✓" if result["ok"] else "✗"
    log_line(f"  {status} {kind} done за {elapsed:.1f}s — {result.get('raw','')[:100]}")
    event("improver_cycle", {
        "chapter": ch,
        "kind": kind,
        "reason": reason,
        "ok": result["ok"],
        "elapsed_sec": round(elapsed, 1),
        "idle_min": round(idle, 1),
    })


if __name__ == "__main__":
    main()
