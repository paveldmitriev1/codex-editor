#!/bin/bash
# overnight_watcher.sh — ночной цикл анализа.
#
# Каждые 10 минут:
#   1) unpack_downloads.py    — распаковывает новые .zip из ~/Downloads
#   2) analyze_corpus.py      — локальный анализ корпуса + % сортировка
#   3) каждые 3 круга (30 мин): fidelity_chapter.py --next (Opus 4.7 + thinking)
#   4) в 06:00 (один раз):     morning_plan_generator.py — синтез всего в план
#
# Стоп: kill $(cat ~/Desktop/Codex2/.codex/watcher.pid)
# Лог:  ~/Desktop/Codex2/.codex/watcher.log

CODEX2="$HOME/Desktop/Codex2"
LOG="$CODEX2/.codex/watcher.log"
PIDFILE="$CODEX2/.codex/watcher.pid"
PLAN_MARKER="$CODEX2/.codex/morning-plan-generated"
INTERVAL=1800   # 30 минут между циклами (Pavel 2026-05-20: «каждые 30 минут перезапускаться, не экономить»)

mkdir -p "$CODEX2/.codex"
echo $$ > "$PIDFILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

log "═══════════════════════════════════"
log "🌙 Watcher запущен (PID $$)"
log "   Модель Opus 4.7, без экономии, каждые 30 мин fidelity на главе"
log "═══════════════════════════════════"

ITERATION=0
while true; do
    ITERATION=$((ITERATION + 1))
    log ""
    log "── Iteration $ITERATION ($(date '+%H:%M')) ──"

    # 1) Распаковка новых
    log "→ unpack_downloads.py"
    python3 "$CODEX2/scripts/unpack_downloads.py" >> "$LOG" 2>&1 || log "   ✗ unpack failed"

    # 2) Анализ корпуса (обновляет style-scan)
    log "→ analyze_corpus.py"
    python3 "$CODEX2/scripts/analyze_corpus.py" >> "$LOG" 2>&1 && log "   ✓ корпус обновлён" || log "   ✗ analyze failed"

    # 3) Каждую итерацию (10 мин) — fidelity на 2 главах через Opus (Pavel: не экономить)
    log "→ fidelity_chapter.py --next (Opus 4.7) ×2 главы"
    python3 "$CODEX2/scripts/fidelity_chapter.py" --next >> "$LOG" 2>&1 && log "   ✓ fidelity #1 отработал" || log "   ✗ fidelity #1 failed"
    python3 "$CODEX2/scripts/fidelity_chapter.py" --next >> "$LOG" 2>&1 && log "   ✓ fidelity #2 отработал" || log "   ✗ fidelity #2 failed"

    # 3.5) Timesheet — каждую итерацию обновлять отчёт о работе
    python3 "$CODEX2/scripts/timesheet.py" >> "$LOG" 2>&1 || true

    # 3.6) Cross-chapter similarity — каждые 30 мин если есть свежие original-ideas
    if [ $((ITERATION % 3)) -eq 0 ] && [ -d "$CODEX2/voice-corpus/original-ideas" ]; then
        log "→ cross_chapter_similarity (re-compute)"
        python3 "$CODEX2/scripts/cross_chapter_similarity.py" >> "$LOG" 2>&1 || log "   ✗ similarity failed"
    fi

    # 3.64) Pre-warm voice analysis для приоритетной книги (book-obsession)
    # Pavel: «приоритет №1 — закончить эту книгу». Сначала покрываем её главы.
    log "→ pre-warm voice-analysis для book-obsession"
    PRIORITY_NEXT_VOICE=$(python3 -c "
from pathlib import Path
V2 = Path.home() / 'Desktop/Codex2'
for ch_dir in sorted((V2 / 'chapters/book-obsession').iterdir()):
    if not ch_dir.is_dir(): continue
    if not (ch_dir / 'voice-analysis.json').exists():
        print(ch_dir.name)
        break
" 2>/dev/null)
    if [ -n "$PRIORITY_NEXT_VOICE" ]; then
        log "   target: $PRIORITY_NEXT_VOICE"
        timeout_pid=$$
        python3 "$CODEX2/scripts/analyze_voice_readings.py" --chapter "$PRIORITY_NEXT_VOICE" --force >> "$LOG" 2>&1 &
        VOICE_PID=$!
        # ждём максимум 180 сек чтобы цикл не залип
        for i in $(seq 1 36); do
            if ! kill -0 $VOICE_PID 2>/dev/null; then break; fi
            sleep 5
        done
        if kill -0 $VOICE_PID 2>/dev/null; then
            kill $VOICE_PID 2>/dev/null
            log "   ✗ timeout 180s — kill voice analysis"
        else
            log "   ✓ $PRIORITY_NEXT_VOICE voice проанализирован"
        fi
    else
        log "   все главы book-obsession покрыты voice-analysis"
    fi

    # 3.65) Метафоры — извлекаем по одной главе за итерацию (склад уникальных)
    log "→ extract_metaphors --next (одна глава без metaphors.json)"
    NEXT_META=$(python3 -c "
from pathlib import Path
V2 = Path.home() / 'Desktop/Codex2'
SRC = V2 / 'sources'; CH = V2 / 'chapters'
targets = []
for book in CH.iterdir():
    if not book.is_dir() or book.name.startswith('.'): continue
    for c in book.iterdir():
        if (c / 'draft.md').exists() and not (c / 'metaphors.json').exists():
            targets.append(c.name)
for book in SRC.iterdir():
    if not book.is_dir() or book.name.startswith('.'): continue
    for c in book.iterdir():
        if c.name in targets: continue
        if (c / 'from-grant').exists():
            ch_dir = CH / book.name / c.name
            if not (ch_dir / 'metaphors.json').exists():
                targets.append(c.name)
targets = [t for t in targets if not t.startswith('ustav')]  # Устав не редактируем
print(sorted(targets)[0] if targets else '')
" 2>/dev/null)
    if [ -n "$NEXT_META" ]; then
        log "   target: $NEXT_META"
        python3 "$CODEX2/scripts/extract_metaphors.py" --chapter "$NEXT_META" >> "$LOG" 2>&1 && log "   ✓ метафоры $NEXT_META извлечены" || log "   ✗ метафоры $NEXT_META failed"
    else
        log "   все главы покрыты — склад полон"
    fi

    # 3.7) Pavel-Learning Agent — каждые 60 мин (если есть свежие edits)
    if [ $((ITERATION % 6)) -eq 0 ] && [ -f "$CODEX2/.codex/pavel-edits.jsonl" ]; then
        log "→ learn_pavel_style (трешхолд 20% — пропустит если меньше)"
        python3 "$CODEX2/scripts/learn_pavel_style.py" >> "$LOG" 2>&1 || log "   ✗ learn_pavel failed"
    fi

    # 3.8) Visual QA agent — КАЖДЫЙ цикл (Pavel 2026-05-20: «всю ночь искать визуальные баги»)
    log "→ visual_qa_agent (Vision check всех страниц)"
    python3 "$CODEX2/scripts/visual_qa_agent.py" >> "$LOG" 2>&1 || log "   ✗ visual_qa failed"

    # 3.85) Technical QA agent — endpoints + JS console errors
    if [ -f "$CODEX2/scripts/technical_qa_agent.py" ]; then
        log "→ technical_qa_agent (endpoints + console)"
        python3 "$CODEX2/scripts/technical_qa_agent.py" >> "$LOG" 2>&1 || log "   ✗ tech_qa failed"
    fi

    # 3.9) Auto-fix agent — пробует починить самые явные баги
    if [ -f "$CODEX2/scripts/auto_fix_agent.py" ]; then
        log "→ auto_fix_agent (применить безопасные правки)"
        python3 "$CODEX2/scripts/auto_fix_agent.py" --apply-safe >> "$LOG" 2>&1 || log "   ✗ auto_fix failed"
    fi

    # 3.92) В 01:30 — Version dedup (Pavel 2026-05-20: «приоритет свежей версии по дате»)
    DEDUP_MARKER="$CODEX2/.codex/version-dedup-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "01" ] && [ ! -f "$DEDUP_MARKER" ]; then
        log "🔄 01:30+ — Version dedup (приоритет свежей версии)"
        python3 "$CODEX2/scripts/version_dedup.py" --apply >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$DEDUP_MARKER"
            log "   ✓ VERSION-DEDUP применён"
        fi
    fi

    # 3.945) В 03:00 — Visual + Technical audit (Pavel 2026-05-20: «оптимизировать каждый визуальный и технический элемент»)
    VT_AUDIT_MARKER="$CODEX2/.codex/vt-audit-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "03" ] && [ ! -f "$VT_AUDIT_MARKER" ]; then
        log "🔧 03:00+ — Visual + Technical audit (сканирование всего UI/кода)"
        python3 "$CODEX2/scripts/visual_tech_audit.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$VT_AUDIT_MARKER"
            log "   ✓ VISUAL-TECH-AUDIT готов"
        fi
    fi

    # 3.94) В 02:30 — Nightly system improver (Pavel 2026-05-20: «каждую ночь брать элемент структуры и улучшать»)
    IMPROVER_MARKER="$CODEX2/.codex/improver-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "02" ] && [ ! -f "$IMPROVER_MARKER" ]; then
        log "🔧 02:30+ — Nightly system improver (deep analysis одного элемента)"
        python3 "$CODEX2/scripts/nightly_system_improver.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$IMPROVER_MARKER"
            log "   ✓ SYSTEM-IMPROVEMENT proposal готов"
        fi
    fi

    # 3.93) В 02:00 — Structure audit (Pavel 2026-05-20: «всю ночь проверяй пропавшие книги»)
    STRUCTURE_MARKER="$CODEX2/.codex/structure-audit-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "02" ] && [ ! -f "$STRUCTURE_MARKER" ]; then
        log "🔍 02:00+ — Structure audit (Opus анализ вложенных книг)"
        python3 "$CODEX2/scripts/structure_audit.py" --opus >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$STRUCTURE_MARKER"
            log "   ✓ STRUCTURE-AUDIT готов"
        fi
    fi

    # 3.98) В 05:00 — Design clone agent (Pavel 2026-05-20: «изучи Claude Desktop ночью»)
    DESIGN_MARKER="$CODEX2/.codex/design-clone-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "05" ] && [ ! -f "$DESIGN_MARKER" ]; then
        log "🎨 05:00+ — Design clone agent (Claude Desktop reference)"
        python3 "$CODEX2/scripts/design_clone_agent.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$DESIGN_MARKER"
            log "   ✓ DESIGN-CLONE-PROPOSAL готов"
        fi
    fi

    # 3.97) В 04:00 — Logic audit (Pavel 2026-05-20: «ночью анализируй логику, придумывай инструменты»)
    LOGIC_MARKER="$CODEX2/.codex/logic-audit-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "04" ] && [ ! -f "$LOGIC_MARKER" ]; then
        log "🧠 04:00+ — Logic audit (мета-анализ + bug-detection tools)"
        python3 "$CODEX2/scripts/logic_audit.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$LOGIC_MARKER"
            log "   ✓ LOGIC-AUDIT готов"
        fi
    fi

    # 3.95) В 03:30 — Night follow-ups review (Pavel 2026-05-20: «ночью проверяй что я просил»)
    FOLLOWUPS_MARKER="$CODEX2/.codex/followups-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "03" ] && [ ! -f "$FOLLOWUPS_MARKER" ]; then
        log "🔍 03:30+ — Night follow-ups review"
        python3 "$CODEX2/scripts/night_followups_review.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$FOLLOWUPS_MARKER"
            log "   ✓ NIGHT-FOLLOWUPS готов"
        fi
    fi

    # 4) В 06:00 (один раз) — morning plan
    HOUR=$(date +%H)
    if [ "$HOUR" = "06" ] && [ ! -f "$PLAN_MARKER" ]; then
        log "🌅 06:00 наступило — генерирую MORNING PLAN"
        python3 "$CODEX2/scripts/morning_plan_generator.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$PLAN_MARKER"
            log "   ✓✓ MORNING PLAN готов: reports/MORNING-PLAN.md"
        else
            log "   ✗ morning plan failed — попробую в следующей итерации"
        fi
    fi

    # 4b) В 06:30 (после morning plan) — DAILY IMPROVEMENTS (Pavel 2026-05-20)
    IMPR_MARKER="$CODEX2/.codex/improvements-generated"
    if [ "$HOUR" = "06" ] && [ -f "$PLAN_MARKER" ] && [ ! -f "$IMPR_MARKER" ]; then
        log "💡 06:30+ — генерирую DAILY-IMPROVEMENTS"
        python3 "$CODEX2/scripts/daily_improvements.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$IMPR_MARKER"
            log "   ✓✓ DAILY-IMPROVEMENTS готов"
        fi
    fi

    # 4c) В 06:45 (после improvements) — DAILY PLAN на сегодня (2-4 часа Pavel)
    PLAN_TODAY_MARKER="$CODEX2/.codex/daily-plan-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "06" ] && [ -f "$IMPR_MARKER" ] && [ ! -f "$PLAN_TODAY_MARKER" ]; then
        log "📅 06:45+ — генерирую DAILY PLAN на сегодня"
        python3 "$CODEX2/scripts/daily_plan.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$PLAN_TODAY_MARKER"
            log "   ✓✓ DAILY PLAN готов (см. reports/DAILY-PLAN-TODAY.md)"
        fi
    fi

    # 4cc) В 06:50 — SYSTEM UNDER-HOOD REPORT (Pavel: «накручивай логику системы каждое утро»)
    SYSREP_MARKER="$CODEX2/.codex/sysreport-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "06" ] && [ ! -f "$SYSREP_MARKER" ]; then
        log "🔧 06:50+ — генерирую SYSTEM-UNDER-HOOD"
        python3 "$CODEX2/scripts/daily_system_report.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$SYSREP_MARKER"
            log "   ✓✓ SYSTEM-UNDER-HOOD готов"
        fi
    fi

    # 4ee) В 07:30 — TODAY-RECOMMENDATIONS (Pavel-утверждённый framework формат А)
    TODAY_MARKER="$CODEX2/.codex/today-recs-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "07" ] && [ ! -f "$TODAY_MARKER" ]; then
        log "🎯 07:30+ — TODAY-RECOMMENDATIONS (framework формат А)"
        python3 "$CODEX2/scripts/daily_today_recommendations.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$TODAY_MARKER"
            log "   ✓ TODAY-RECOMMENDATIONS готов"
        fi
    fi

    # 4f) В 23:00 — FRAMEWORK-METRICS (парсинг approve/reject + метрики G)
    METRICS_MARKER="$CODEX2/.codex/metrics-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "23" ] && [ ! -f "$METRICS_MARKER" ]; then
        log "📊 23:00+ — FRAMEWORK-METRICS (раздел G + архив TODAY)"
        python3 "$CODEX2/scripts/framework_metrics.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$METRICS_MARKER"
            log "   ✓ FRAMEWORK-METRICS готов"
        fi
    fi

    # 4d) В 07:00 — DAILY RECOMMENDATIONS (Quick wins + numbered improvements)
    RECS_MARKER="$CODEX2/.codex/daily-recs-$(date +%Y-%m-%d).marker"
    if [ "$HOUR" = "07" ] && [ ! -f "$RECS_MARKER" ]; then
        log "💡 07:00+ — генерирую DAILY-RECOMMENDATIONS"
        python3 "$CODEX2/scripts/daily_recommendations.py" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            touch "$RECS_MARKER"
            log "   ✓✓ DAILY-RECOMMENDATIONS готов"
        fi
    fi

    # 5) Краткая сводка
    if [ -f "$CODEX2/reports/overnight-style-scan.md" ]; then
        N=$(grep -oE "Файлов проанализировано: \*\*[0-9]+\*\*" "$CODEX2/reports/overnight-style-scan.md" | grep -oE "[0-9]+")
        STRONG=$(grep -oE "Strong match.*: \*\*[0-9]+\*\*" "$CODEX2/reports/overnight-style-scan.md" | grep -oE "[0-9]+")
        OFF=$(grep -oE "Off-topic.*: \*\*[0-9]+\*\*" "$CODEX2/reports/overnight-style-scan.md" | grep -oE "[0-9]+")
        FID_DONE=$(ls "$CODEX2/reports/fidelity/" 2>/dev/null | wc -l | tr -d ' ')
        log "   📊 файлы:$N  strong:$STRONG  off:$OFF  fidelity-отчётов:$FID_DONE"
    fi

    log "→ сплю $INTERVAL сек, во время сна каждые 5 мин — idle_keeper..."
    # Pavel 2026-05-20 STANDING RULE: при простое 5+ мин — автозапуск полезной задачи
    SLEPT=0
    while [ $SLEPT -lt $INTERVAL ]; do
        sleep 300  # 5 минут
        SLEPT=$((SLEPT + 300))
        python3 "$CODEX2/scripts/idle_keeper.py" >> "$LOG" 2>&1 || true
    done
done
