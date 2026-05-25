"""
config.py — единый источник правды для конфига Codex v2.

Pavel 2026-05-21: «всегда используем максимальную модель Opus 4.7,
когда выйдет новая — оптимизируешь».

ВСЕ вызовы Anthropic API ДОЛЖНЫ использовать MAX_MODEL.
Хардкод других моделей (claude-opus-4-5, claude-3, claude-sonnet-*, claude-haiku-*)
в production-вызовах ЗАПРЕЩЁН — отлавливается через scripts/model_guard.py.
"""

# ─── МОДЕЛЬ ─────────────────────────────────────────────
# Менять ТОЛЬКО когда выходит новая, более мощная модель.
# Pavel должен подтвердить вручную; model_guard просто алертит.
MAX_MODEL = "claude-opus-4-7"
MAX_MODEL_RELEASED_AT = "2026-04"  # для алертинга про "не пора ли обновиться"

# Fallback модели — РАЗРЕШЕНЫ ТОЛЬКО для health-check и smoke-test
# (когда нужно проверить что proxy жив, а не сжигать Opus-токены).
FALLBACK_HEALTHCHECK_MODEL = "claude-sonnet-4-6"

# ─── PROXY ──────────────────────────────────────────────
PROXY_URL = "http://127.0.0.1:8787"

# ─── PATHS ──────────────────────────────────────────────
from pathlib import Path
V2_ROOT = Path.home() / "Desktop/Codex2"
CANON_PATH = V2_ROOT / "CANON.md"
EVENTS_PATH = V2_ROOT / ".codex/events.jsonl"

# ─── CANON INJECTION LIMITS (UC-65) ────────────────────
# Pavel 2026-05-21: «не нужно 3500 символов канона в каждый запрос — Opus давится»
CANON_INJECT_FULL = 3500       # для _super_rewrite — полный канон
CANON_INJECT_LITE = 1200       # для per-paragraph endpoints — лёгкая версия
CANON_INJECT_NONE = 0          # для технических вызовов

# ─── RULES ──────────────────────────────────────────────
NO_EMOJIS = True               # никакие эмодзи в UI или Opus-ответах
NO_DASH_BETWEEN_SENTENCES = True  # «. — Cap» = AI-tell, запрет
DEFAULT_PAVEL_RHYTHM_WORDS_PER_SENTENCE = 11.7  # из UC-50 measurement
