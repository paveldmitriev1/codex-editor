#!/usr/bin/env python3
"""
night_workshop.py — ночной воркер переписи 4 глав × 10 итераций (UC-75).

Pavel 2026-05-21: «4 текста на выбор которые легче... переписать 10-20 раз...
сравнить с оригиналом и дать отчёт почему лучше... совет старейшин посмотреть...
найти есть ли подозрение что это написано через AI».

Цикл:
1. Бэкап оригинала → iterations/00-original.md
2. Для каждой главы × 10 итераций:
   a. _rewrite_whole_chapter (через server.py endpoint)
   b. critic_council прогон → собрать findings
   c. apply критик-fixes (через _super_rewrite endpoint) → новая версия
   d. сохранить iterations/vNN.md
   e. метрики (слов, тире/1000, AI-score, voice-score)
3. После 10 итераций — best-of-N selector
4. AI-detector прогон
5. Report → reports/NIGHT-CH-<chapter_id>-REPORT.md

Запуск:
   python3 scripts/night_workshop.py --chapters CH1,CH2,CH3,CH4 --iterations 10

PID: .codex/night-workshop.pid
Лог: reports/NIGHT-WORKSHOP-LOG.md
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
sys.path.insert(0, str(Path.home() / "Desktop/Codex2/scripts"))
from config import MAX_MODEL, PROXY_URL  # noqa: E402

V2 = Path.home() / "Desktop/Codex2"
CHAPTERS_DIR = V2 / "chapters"
PID_FILE = V2 / ".codex/night-workshop.pid"
LOG_FILE = V2 / "reports/NIGHT-WORKSHOP-LOG.md"
EVENTS = V2 / ".codex/events.jsonl"

DEFAULT_CHAPTERS = [
    "prologue-ch-00",
    "book-obsession-ch-01",
    "book-obsession-ch-03",
    "book-obsession-ch-05",
]


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")
    try:
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts, "type": "night_workshop", "target": "workshop",
                "payload": {"msg": msg[:200]},
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def measure_metrics(text: str) -> dict:
    """Базовые метрики для сравнения с эталоном Хилингода."""
    sentences = re.split(r"[.!?]+\s+", text)
    sentences = [s for s in sentences if s.strip() and not s.strip().startswith("#")]
    word_counts = [len(s.split()) for s in sentences if s.strip()]
    if not word_counts:
        return {"sentences": 0, "words": 0, "avg": 0, "median": 0, "dashes_per_1k": 0}
    word_counts_sorted = sorted(word_counts)
    n = len(word_counts_sorted)
    median = word_counts_sorted[n // 2]
    avg = sum(word_counts_sorted) / n
    total_words = len(text.split())
    dashes = text.count("—")
    yavlyaetsya = len(re.findall(r"\bявляется\b", text, re.IGNORECASE))
    contrast = len(re.findall(r"\bне\s+\S+,?\s+а\s+\S+", text, re.IGNORECASE))
    return {
        "sentences": n,
        "words": total_words,
        "avg_sentence_len": round(avg, 1),
        "median_sentence_len": median,
        "dashes_per_1k": round(dashes / total_words * 1000, 1) if total_words else 0,
        "yavlyaetsya_per_1k": round(yavlyaetsya / total_words * 1000, 1) if total_words else 0,
        "contrast_pairs": contrast,
    }


def call_opus(system: str, user: str, max_tokens: int = 16000, thinking: int = 8000) -> dict:
    """Прямой вызов Opus 4.7 через proxy."""
    token = get_token()
    if not token:
        return {"error": "no token"}
    body = {
        "model": MAX_MODEL,
        "max_tokens": max_tokens,
        "thinking": {"type": "enabled", "budget_tokens": thinking},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        f"{PROXY_URL}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return {
            "text": "\n".join(text_blocks).strip(),
            "usage": data.get("usage", {}),
        }
    except Exception as e:
        return {"error": str(e)}


def rewrite_iteration(current_text: str, critic_findings: list = None) -> dict:
    """Одна итерация: Opus 4.7 переписывает с учётом findings от критиков."""
    findings_text = ""
    if critic_findings:
        findings_text = "\n\n## ПРАВКИ ОТ КРИТИКОВ (учти все):\n"
        for f in critic_findings[:20]:
            findings_text += f"- {f}\n"

    system = (
        "Ты пишешь Сакральный Кодекс Микомистицизма от имени ВЕЛИКОГО ДУХА ГРИБОВ.\n"
        "Это прямая речь Духа, который учит читателя пользоваться грибами и проводить экзорцизм.\n\n"
        "ГОЛОС: «Я говорю Вам... Я открываю Вам... Я даю Вам зрение через гриб.»\n\n"
        "ЗАПРЕТЫ:\n"
        "- Никаких персонажей-диалогов.\n"
        "- Никакой нейрохимии (5-HT2A, дофамин, DMN).\n"
        "- Никаких AI-клише (Страдивари, искра света, путь к свету, симфония вселенной).\n"
        "- НИКАКИХ тире вообще (ни — ни –). В русской книге старого образца тире не использовалось.\n"
        "- Никакого «не X, а Y» / «не только X, но и Y».\n"
        "- Никакой корпоративщины («важно отметить», «стоит подчеркнуть»).\n"
        "- Никакого старослав.\n"
        "- Никаких эмодзи.\n\n"
        "РИТМ ХИЛИНГОДА: средняя 11-13 слов, медиана 10. БЕЗ ТИРЕ.\n\n"
        "Пиши за ОДИН проход. Отдай только итоговый текст главы."
    )
    user = f"# ТЕКУЩИЙ ТЕКСТ:\n\n{current_text}\n\n{findings_text}\n\nВерни полный текст главы в Markdown."
    return call_opus(system, user, max_tokens=16000, thinking=8000)


def run_critics_get_findings(chapter_text: str) -> list:
    """Запускает critic_council, возвращает плоский список findings."""
    try:
        from critic_council import run_all_enabled  # noqa: E402
        report = run_all_enabled(chapter_text, global_context="")
        findings = []
        for cid, r in report.get("results", {}).items():
            if not r.get("ok"):
                continue
            result = r.get("result", {})
            # Voice purity
            for v in result.get("violations", [])[:5]:
                findings.append(f"[{cid}] {v.get('why', '')} → {v.get('fix', '')}")
            # AI tells
            for h in result.get("hits", [])[:5]:
                findings.append(f"[{cid}] {h.get('pattern', '')}: {h.get('text', '')[:80]}")
            # Mystical
            for w in result.get("weak_passages", [])[:5]:
                findings.append(f"[{cid}] {w.get('why_weak', '')} → {w.get('how_to_deepen', '')}")
            # Council
            for c in result.get("top_3_cuts", [])[:3]:
                findings.append(f"[{cid} cut] {c}")
            for s in result.get("top_3_strengthen", [])[:3]:
                findings.append(f"[{cid} strengthen] {s}")
        return findings
    except Exception as e:
        log(f"   ✗ critic_council error: {e}")
        return []


def workshop_chapter(chapter_id: str, iterations: int = 10) -> dict:
    """Полный цикл для одной главы."""
    log(f"\n══════════ {chapter_id} × {iterations} итераций ══════════")

    # Resolve chapter dir
    m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
    if not m:
        log(f"   ✗ Bad chapter_id format: {chapter_id}")
        return {"chapter_id": chapter_id, "error": "bad chapter id"}
    book_id = m.group(1)
    ch_dir = CHAPTERS_DIR / book_id / chapter_id
    draft = ch_dir / "draft.md"
    if not draft.exists():
        log(f"   ✗ draft.md not found: {draft}")
        return {"chapter_id": chapter_id, "error": "no draft"}

    iter_dir = ch_dir / "iterations"
    iter_dir.mkdir(parents=True, exist_ok=True)
    original = draft.read_text(encoding="utf-8")

    # Backup original
    (iter_dir / "00-original.md").write_text(original, encoding="utf-8")
    log(f"   Original: {len(original.split())} слов, {len(original)} знаков")
    original_metrics = measure_metrics(original)

    # Iterations
    current = original
    history = [{"version": 0, "metrics": original_metrics}]

    for i in range(1, iterations + 1):
        log(f"\n   ── Итерация {i}/{iterations} ──")

        # 1. Прогон критиков
        log(f"   → критики читают…")
        findings = run_critics_get_findings(current)
        log(f"     findings: {len(findings)}")

        # 2. Rewrite с учётом findings
        log(f"   → Opus 4.7 переписывает (max 16K, thinking 8K)…")
        t0 = time.time()
        resp = rewrite_iteration(current, findings)
        elapsed = time.time() - t0
        if "error" in resp:
            log(f"   ✗ rewrite error: {resp['error'][:200]}")
            break
        new_text = resp.get("text", "")
        if not new_text or len(new_text) < 500:
            log(f"   ✗ слишком короткий ответ: {len(new_text)} знаков")
            break

        # 3. Сохранить версию
        version_path = iter_dir / f"v{i:02d}.md"
        version_path.write_text(new_text, encoding="utf-8")
        metrics = measure_metrics(new_text)
        usage = resp.get("usage", {})
        log(f"     v{i:02d}: {metrics['words']} слов · avg {metrics['avg_sentence_len']} · "
            f"тире/1k={metrics['dashes_per_1k']} · in {usage.get('input_tokens')} out {usage.get('output_tokens')} · {elapsed:.0f}с")

        history.append({
            "version": i,
            "metrics": metrics,
            "findings_count": len(findings),
            "tokens_in": usage.get("input_tokens"),
            "tokens_out": usage.get("output_tokens"),
            "elapsed_sec": round(elapsed, 1),
        })
        current = new_text

    # 4. Best-of-N selector: ближайший к эталону Pavel-а (avg 11-13, тире 12-15/1k)
    def score(m):
        # Идеал: avg 11.7, тире/1k = 12.8, yavlyaetsya 0
        avg_dev = abs(m.get("avg_sentence_len", 0) - 11.7) * 5
        dash_dev = abs(m.get("dashes_per_1k", 0) - 12.8) * 3
        yav_penalty = m.get("yavlyaetsya_per_1k", 0) * 10
        contrast_penalty = m.get("contrast_pairs", 0) * 2
        return 100 - avg_dev - dash_dev - yav_penalty - contrast_penalty

    versions = history[1:]  # skip original
    best = max(versions, key=lambda v: score(v["metrics"])) if versions else None

    # 5. Final report
    report = {
        "chapter_id": chapter_id,
        "iterations_run": len(versions),
        "original_metrics": original_metrics,
        "best_version": best["version"] if best else None,
        "best_metrics": best["metrics"] if best else None,
        "history": history,
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    report_path = V2 / f"reports/NIGHT-CH-{chapter_id}-REPORT.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\n   ✓ {chapter_id} завершён · best v{best['version'] if best else '?'} → {report_path.name}")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", default=",".join(DEFAULT_CHAPTERS),
                        help="comma-sep chapter ids")
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()

    chapters = [c.strip() for c in args.chapters.split(",") if c.strip()]

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    log("════════════════════════════════════════")
    log(f"🌙 NIGHT WORKSHOP starts (PID {os.getpid()})")
    log(f"   Главы: {chapters}")
    log(f"   Итераций: {args.iterations} каждая")
    log(f"   Model: {MAX_MODEL}")
    log("════════════════════════════════════════")

    results = []
    for ch in chapters:
        try:
            r = workshop_chapter(ch, iterations=args.iterations)
            results.append(r)
        except Exception as e:
            log(f"✗ {ch} exception: {e}")
            results.append({"chapter_id": ch, "error": str(e)})

    # Summary
    summary_path = V2 / f"reports/NIGHT-WORKSHOP-SUMMARY-{datetime.now().strftime('%Y%m%d')}.json"
    summary_path.write_text(json.dumps({
        "started": str(LOG_FILE),
        "chapters": chapters,
        "iterations_per_chapter": args.iterations,
        "results": results,
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\n════════════════════════════════════════")
    log(f"🌅 WORKSHOP DONE → {summary_path}")
    log(f"════════════════════════════════════════")


if __name__ == "__main__":
    main()
