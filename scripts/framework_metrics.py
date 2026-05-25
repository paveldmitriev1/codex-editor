#!/usr/bin/env python3
"""
framework_metrics.py — метрики G из IMPROVEMENT-FRAMEWORK.

Pavel в TODAY-RECOMMENDATIONS.md ставит `[x] approve` / `[x] reject` / `[x] defer`.
Этот скрипт парсит markdown, обновляет pavel-actions.jsonl с decision,
и считает 4 метрики качества framework-а:

1. % approved — < 50% значит формат плохой
2. Среднее время propose→implement (часы)
3. % auto-detected vs скриншоты Pavel-а
4. Сколько раз одна и та же тема (за неделю)

Запуск (watcher 23:00 в конце дня): python3 framework_metrics.py
Output: reports/FRAMEWORK-METRICS.md
"""
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

V2 = Path.home() / "Desktop/Codex2"
ACTIONS = V2 / ".codex/pavel-actions.jsonl"
EVENTS = V2 / ".codex/events.jsonl"
TODAY_FILE = V2 / "reports/TODAY-RECOMMENDATIONS.md"
HISTORY_DIR = V2 / "reports/recommendations-history"
OUTPUT = V2 / "reports/FRAMEWORK-METRICS.md"


def parse_today_decisions() -> dict:
    """Парсит TODAY-RECOMMENDATIONS.md → находит approve/reject отметки Pavel-а."""
    if not TODAY_FILE.exists():
        return {}
    text = TODAY_FILE.read_text(encoding="utf-8")
    # Структура: каждая карточка начинается с `## \`ID\`` и заканчивается на `---`
    decisions = {}
    cards = re.split(r"\n## `([^`]+)`", text)
    for i in range(1, len(cards), 2):
        rec_id = cards[i].strip()
        body = cards[i+1] if i+1 < len(cards) else ""
        approved = bool(re.search(r"\[x\]\s+approve", body, re.IGNORECASE))
        rejected = bool(re.search(r"\[x\]\s+reject", body, re.IGNORECASE))
        deferred = bool(re.search(r"\[x\]\s+defer", body, re.IGNORECASE))
        # Извлекаем comment если есть
        m_comment = re.search(r"твой комментарий:\s*([^\n]+)", body, re.IGNORECASE)
        comment = m_comment.group(1).strip() if m_comment else ""
        if approved or rejected or deferred:
            decisions[rec_id] = {
                "approved": approved,
                "rejected": rejected,
                "deferred": deferred,
                "comment": comment,
            }
    return decisions


def load_jsonl(path: Path, since_days: int = 30) -> list:
    if not path.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("ts", "") >= cutoff:
                out.append(r)
        except json.JSONDecodeError:
            pass
    return out


def write_decisions_to_log(decisions: dict):
    """Сохраняет решения Pavel-а в pavel-actions.jsonl."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with ACTIONS.open("a", encoding="utf-8") as f:
        for rec_id, d in decisions.items():
            f.write(json.dumps({
                "ts": ts,
                "action": "recommendation_decision",
                "rec_id": rec_id,
                **d,
            }, ensure_ascii=False) + "\n")


def archive_today():
    """Архивирует текущий TODAY → recommendations-history/."""
    if not TODAY_FILE.exists():
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    target = HISTORY_DIR / f"{today}-TODAY.md"
    target.write_text(TODAY_FILE.read_text(encoding="utf-8"), encoding="utf-8")


def compute_metrics() -> dict:
    actions = load_jsonl(ACTIONS, since_days=7)
    proposed = [a for a in actions if a.get("action") == "recommendation_proposed"]
    decisions = [a for a in actions if a.get("action") == "recommendation_decision"]

    # 1. % approved
    by_id = defaultdict(dict)
    for p in proposed:
        by_id[p["rec_id"]]["proposed"] = p
    for d in decisions:
        by_id[d["rec_id"]]["decision"] = d

    total_with_decision = sum(1 for v in by_id.values() if "decision" in v)
    approved = sum(1 for v in by_id.values() if v.get("decision", {}).get("approved"))
    rejected = sum(1 for v in by_id.values() if v.get("decision", {}).get("rejected"))
    deferred = sum(1 for v in by_id.values() if v.get("decision", {}).get("deferred"))
    pct_approved = (approved / total_with_decision * 100) if total_with_decision else 0

    # 2. Время propose → implement (через события implementation)
    events = load_jsonl(EVENTS, since_days=7)
    # implementation events = chapter_saved/rewrite/apply-fixes etc после approve
    # Упрощённо: время между proposed и (если approve) ближайшим decision
    times_h = []
    for rec_id, v in by_id.items():
        if "proposed" in v and "decision" in v and v["decision"].get("approved"):
            t_prop = datetime.fromisoformat(v["proposed"]["ts"].replace("Z", "+00:00"))
            t_dec = datetime.fromisoformat(v["decision"]["ts"].replace("Z", "+00:00"))
            times_h.append((t_dec - t_prop).total_seconds() / 3600)
    avg_time = sum(times_h) / len(times_h) if times_h else None

    # 3. Auto-detected vs Pavel-reported (примерно)
    auto_events = [e for e in events if e.get("type") in (
        "visual_qa_run", "tech_qa_run", "structure_audit", "version_dedup",
        "logic_audit", "night_followups_review", "auto_fix_applied"
    )]
    pavel_screenshots = sum(1 for a in actions if a.get("action") == "screenshot_reported")
    # Простая proxy метрика — отношение событий auto-find к screenshot-репортам
    auto_ratio = len(auto_events) / max(1, len(auto_events) + pavel_screenshots) * 100

    # 4. Возвраты к одной теме
    by_category = Counter(p.get("category", "?") for p in proposed)
    repeated = {k: v for k, v in by_category.items() if v >= 3}

    return {
        "window_days": 7,
        "proposed_total": len(proposed),
        "with_decision": total_with_decision,
        "approved": approved,
        "rejected": rejected,
        "deferred": deferred,
        "pct_approved": pct_approved,
        "avg_time_hours": avg_time,
        "auto_detection_ratio": auto_ratio,
        "repeated_categories": repeated,
    }


def render_report(metrics: dict, decisions_just_parsed: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# 📊 Framework metrics — {now}")
    lines.append("")
    lines.append("> Раздел G из IMPROVEMENT-FRAMEWORK. Окно: последние 7 дней.")
    lines.append("")

    lines.append("## Метрики недели")
    lines.append("")
    lines.append(f"- **Предложено рекомендаций:** {metrics['proposed_total']}")
    lines.append(f"- **С решением Pavel-а:** {metrics['with_decision']}")
    lines.append(f"  - ✓ Approved: **{metrics['approved']}**")
    lines.append(f"  - ✗ Rejected: {metrics['rejected']}")
    lines.append(f"  - ⏸ Deferred: {metrics['deferred']}")

    pct = metrics["pct_approved"]
    pct_emoji = "✓" if pct >= 50 else "⚠️"
    lines.append(f"- **% Approved:** {pct_emoji} **{pct:.0f}%** (target ≥50% — иначе формат надо менять)")

    if metrics["avg_time_hours"] is not None:
        lines.append(f"- **Среднее время approve → внедрение:** {metrics['avg_time_hours']:.1f}ч")

    lines.append(f"- **Auto-detection ratio:** {metrics['auto_detection_ratio']:.0f}% (target ≥80%)")
    lines.append("")

    if metrics["repeated_categories"]:
        lines.append("## ⚠️ Повторяющиеся темы (3+ за неделю)")
        lines.append("")
        for cat, n in metrics["repeated_categories"].items():
            lines.append(f"- **{cat}:** {n} раз → значит fix не покрыл root cause, копать глубже")
        lines.append("")

    if decisions_just_parsed:
        lines.append(f"## Решения из текущего TODAY ({len(decisions_just_parsed)})")
        lines.append("")
        for rec_id, d in decisions_just_parsed.items():
            status = "✓ approve" if d["approved"] else ("✗ reject" if d["rejected"] else "⏸ defer")
            lines.append(f"- `{rec_id}` — {status}")
            if d.get("comment"):
                lines.append(f"  _{d['comment']}_")
        lines.append("")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    decisions = parse_today_decisions()
    if decisions:
        write_decisions_to_log(decisions)
        archive_today()
        print(f"✓ {len(decisions)} решений сохранено в log + архив TODAY")
    metrics = compute_metrics()
    render_report(metrics, decisions)
    print(f"✓ {OUTPUT}")
    print(f"   approved {metrics['approved']}/{metrics['with_decision']} = {metrics['pct_approved']:.0f}%")


if __name__ == "__main__":
    main()
