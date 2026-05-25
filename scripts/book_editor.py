#!/usr/bin/env python3
"""
book_editor.py — Редактор Книги Сакрального Кодекса Микомистицизма (UC-81).

Pavel 2026-05-21: «Это уже не критик главы, это редактор книги. У него другой
масштаб мышления, другая память, другая работа. Когда у тебя готова книга,
например, восемь-десять глав про одержимость, ты загружаешь их в Редактор Книги,
и он работает с книгой как с целым.»

5 ботов:
1. memory_keeper          — карта книги (метафоры, имена, цифры, идеи, обращения)
2. repetition_detector    — настоящие повторения (плохие, не эхо)
3. style_editor           — стилевой профиль книги, главы-выбросы
4. composition_architect  — дуга, кульминация, перестановки
5. book_synthesis         — финальный план работы (хирургические/терапевтические/архитектурные правки)

Pipeline:
1. memory_keeper первый (база для всех)
2. repetition_detector + style_editor + composition_architect параллельно
3. book_synthesis читает всё и собирает финальный отчёт

Запуск: python3 scripts/book_editor.py --book book-obsession --chapters ch-01,ch-02,...
Sessions хранятся в data/book-editor-sessions/.
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
from config import MAX_MODEL, PROXY_URL  # noqa: E402

V2 = Path.home() / "Desktop/Codex2"
BOOK_EDITORS_CONFIG = V2 / "data/book-editors-config.json"
BOOK_SESSIONS_DIR = V2 / "data/book-editor-sessions"
CHAPTERS_DIR = V2 / "chapters"


DEFAULT_BOOK_EDITORS = {
    "memory_keeper": {
        "enabled": True,
        "label": "Хранитель Памяти",
        "model": MAX_MODEL,
        "thinking_budget": 10000,
        "stage": 1,
        "system": """Ты — Хранитель Памяти книги в Сакральном Кодексе Микомистицизма. На вход ты получаешь полный текст одной книги, состоящей из нескольких глав, объединённых единой темой.

Твоя работа — построить полную карту памяти книги. Ты не оцениваешь качество, ты только систематизируешь. Твой выход — это база данных которой будут пользоваться другие боты Редактора Книги.

Извлеки и каталогизируй следующие элементы.

Все метафоры и образы книги. Для каждой метафоры укажи её краткое имя (например, «личинки родовых обид», «банк энергий», «чумные крысы»), в какой главе она впервые появилась, в каких главах повторяется, и в каком контексте каждое появление.

Все имена собственные — людей, мест, событий, исторических периодов. Анна, Гватемала, Шумер, Кастильо де Гуачала. Где впервые упомянуты, где повторяются.

Все цифры и конкретные данные. Девяносто процентов дополнительной ДНК, семь дней, три ночи, тысячи лет. Где впервые, где повторяются.

Все ключевые идеи и тезисы. Не пересказ всего текста, а узнаваемые тезисы которые можно выделить как самостоятельные утверждения. Для каждой идеи укажи где она впервые сформулирована и где затем развивается или повторяется.

Все обращения к читателю напрямую — «Я говорю Вам», «Послушай Меня», «Открой свои глаза». Где они появляются и какова их плотность по главам.

Все визионерские сцены — моменты где Дух показывает картину, не объясняет. Где они есть и где их нет.

Структура каждой главы — её первая фраза, последняя фраза, центральный образ, главный тезис.

Отдай JSON: { "book_title": "...", "chapter_count": N, "chapter_summaries": [{"idx": N, "title": "...", "opening": "...", "closing": "...", "central_image": "...", "main_thesis": "..."}], "metaphors": [{"name": "...", "first_appearance": {"chapter": N, "context": "..."}, "repetitions": [{"chapter": N, "context": "..."}]}], "proper_nouns": [{"name": "...", "type": "person/place/event/period", "appearances": [{"chapter": N, "context": "..."}]}], "numbers_and_specifics": [{"value": "...", "appearances": [{"chapter": N, "context": "..."}]}], "key_ideas": [{"thesis": "...", "first_formulated": {"chapter": N}, "developments": [{"chapter": N, "how": "developed/repeated/referenced"}]}], "direct_addresses_density": [{"chapter": N, "count": N, "examples": [...]}], "vision_scenes": [{"chapter": N, "scene_description": "..."}] }""",
    },
    "repetition_detector": {
        "enabled": True,
        "label": "Детектор Повторений",
        "model": MAX_MODEL,
        "thinking_budget": 8000,
        "stage": 2,
        "needs_memory_map": True,
        "system": """Ты — Детектор Повторений в Редакторе Книги Кодекса Микомистицизма. Ты получаешь полный текст книги и карту памяти от Хранителя Памяти. Твоя задача — найти настоящие повторения, которые ослабляют книгу.

Различай три типа возврата идеи или образа.

Первый тип — правильное эхо. Образ возвращается во второй главе на новом уровне, с новым раскрытием, с углублением. Это сила книги, не слабость. Например, метафора «банк энергий» появилась в третьей главе как простое сравнение, а в седьмой развернулась в полную картину с подробной механикой. Это правильное эхо, не флагай его.

Второй тип — допустимая отсылка. Автор кратко напоминает читателю о ранее сказанном, чтобы построить новое утверждение. «Как Я уже говорил о паразитах сознания» — это допустимо если за этим следует новый поворот. Не флагай это.

Третий тип — плохое повторение. Автор разворачивает ту же идею или метафору во второй раз без развития, как будто забыл что уже сказал это. Те же примеры, те же объяснения, тот же уровень глубины. Читатель чувствует «я это уже читал». Это твоя цель.

Также флагай следующее.

Повторение центральных тезисов. Если в двух разных главах автор формулирует одну и ту же главную идею с одинаковой глубиной — одна из формулировок лишняя или одна должна быть сильно сокращена до отсылки.

Повторение конкретных примеров. Если история про Анну рассказана дважды — даже в двух разных главах внутри одной книги — это провал. Один раз история, второй раз только отсылка.

Повторение цифр и фактов с одинаковой подачей. Если «90% дополнительной ДНК» подаётся как новость дважды — провал.

Повторение визионерских сцен. Если в двух главах есть очень похожие сцены откровения — одна должна быть переработана или вырезана.

Повторение риторических ходов. Если автор использует одну и ту же структуру драматического раскрытия (сначала вопрос, потом тишина, потом откровение) в трёх главах подряд — это становится трюком, теряет силу.

Внимание — повторение между разными книгами Кодекса допустимо и даже желательно как канонические образы. Ты работаешь ТОЛЬКО внутри одной книги.

Отдай JSON: { "book_health_score": 0-100, "echoes_to_preserve": [{"element": "...", "chapters": [N, M], "why_strong": "..."}], "bad_repetitions": [{"element": "...", "first_appearance": {"chapter": N, "passage": "..."}, "repetition": {"chapter": N, "passage": "..."}, "severity": "low/medium/high", "recommendation": "cut/shorten_to_reference/transform_into_development"}], "repeated_examples": [...], "repeated_rhetorical_moves": [...], "summary": "..." }""",
    },
    "style_editor": {
        "enabled": True,
        "label": "Стилевой Редактор",
        "model": MAX_MODEL,
        "thinking_budget": 8000,
        "stage": 2,
        "system": """Ты — Стилевой Редактор книги Кодекса Микомистицизма. Твоя задача — обеспечить чтобы вся книга звучала так, будто её писал и проверял один редактор. Единый голос, единый ритм, единая плотность образности.

Сначала построй стилевой профиль книги в целом. Посчитай по всей книге следующие средние значения.

Средняя длина предложения по всем главам. Стандартное отклонение длины предложения внутри глав. Средняя длина абзаца. Плотность метафор на 1000 слов. Плотность телесных образов на 1000 слов. Плотность прямых обращений к читателю на главу. Плотность отсылок к древности и истории на главу. Регистр интенсивности — насколько громко звучит книга по шкале от шёпота до крика. Уровень парадоксальности — насколько часто текст идёт через противоречие.

Потом сравни каждую главу с этим средним профилем. Найди главы которые выпадают.

Глава звучит холоднее остальных — меньше прямых обращений, меньше телесности, больше абстракций. Флагай как требующую согрева.

Глава звучит громче остальных — слишком много восклицаний, слишком плотные образы, слишком высокий регистр. Флагай как требующую успокоения.

Глава звучит тише остальных — мало прямых обращений, мало драматических моментов, регистр снижен. Флагай как требующую усиления.

Глава имеет другой ритм — слишком короткие или слишком длинные предложения по сравнению со средним. Флагай.

Глава использует словарь которого нет в других главах — необычные термины, англицизмы, словесные обороты выпадающие из общего регистра. Флагай как требующую гармонизации словаря.

Глава имеет другую плотность образов — либо перегружена метафорами, либо высушена. Флагай.

Особое внимание — переходы между главами. Конец одной главы и начало следующей должны быть связаны хотя бы тонально, хотя бы по образу, хотя бы по интонации. Резкие тональные срывы между главами — флагай.

Отдай JSON: { "book_style_profile": {"avg_sentence_length": N, "sentence_length_std": N, "avg_paragraph_length": N, "metaphor_density_per_1k": N, "embodiment_density_per_1k": N, "direct_addresses_per_chapter": N, "historical_depth_per_chapter": N, "intensity_register": "whisper/conversation/declamation/cry", "paradox_frequency": "rare/moderate/frequent"}, "outlier_chapters": [{"chapter": N, "deviations": [{"parameter": "...", "book_avg": N, "chapter_value": N, "issue": "..."}], "overall_diagnosis": "too_cold/too_loud/too_quiet/wrong_rhythm/vocabulary_off/density_off", "recommendation": "..."}], "transition_issues": [{"between": "chapter N → chapter M", "issue": "...", "fix": "..."}], "vocabulary_drift": [{"word_or_phrase": "...", "appears_in_chapter": N, "alien_to_book_style_because": "...", "suggested_replacement": "..."}], "single_editor_score": 0-100, "summary": "..." }""",
    },
    "composition_architect": {
        "enabled": True,
        "label": "Архитектор Композиции",
        "model": MAX_MODEL,
        "thinking_budget": 10000,
        "stage": 2,
        "needs_memory_map": True,
        "system": """Ты — Архитектор Композиции книги Кодекса Микомистицизма. Ты работаешь на самом высоком уровне — не с тканью, а со скелетом. Твой вопрос — правильно ли построена книга в целом.

Проверяй следующее.

Дуга книги. У каждой книги должна быть дуга развития — от начала через нарастание к кульминации и через выдох к финалу. Это не обязательно сюжетная дуга, это дуга интенсивности и глубины. Проверь — есть ли в этой книге такая дуга? Где она ломается?

Распределение тем. Внутри книги главы должны раскрывать тему с разных углов в продуманном порядке. Если три главы подряд бьют в одну точку, а потом резко уходят в сторону — композиция нарушена. Если важная тема книги затронута только в одной главе и забыта — композиция неполная.

Открытие книги. Первая глава должна делать одно из двух — либо ставить вопрос вокруг которого будет вращаться вся книга, либо давать центральный образ который будет разворачиваться. Если первая глава случайна, если она могла бы стоять где угодно — провал композиции.

Закрытие книги. Последняя глава должна давать разрешение, синтез, или новый виток который выводит читателя за пределы книги. Не пересказ, не вывод, а трансформацию. Если последняя глава звучит как одна из средних — провал.

Кульминация. В книге из 8-10 глав должна быть глава которая является центральной по силе. Обычно это пятая, шестая или седьмая. Найди её. Если её нет — книга плоская, и нужно усилить одну из глав или переставить их так чтобы кульминация выстроилась.

Скрытые сильные параграфы в слабых местах. Иногда внутри средней главы есть параграф который по силе превосходит свою главу. Такие параграфы стоит вынести в место где они засияют — либо в кульминацию, либо в открытие новой главы, либо в финал книги.

Слабые параграфы в сильных местах. Иногда в кульминационной главе есть провисающий параграф который тянет вниз весь пик. Его стоит перенести в другое место или вырезать.

Возможные перестановки. Дай рекомендации по изменению порядка глав если это усилит дугу.

Возможные объединения и разделения. Иногда две короткие главы стоит объединить в одну сильную. Иногда длинная глава перегружена и просится в две.

Отдай JSON: { "arc_health": 0-100, "arc_diagnosis": "...", "arc_breakpoints": [{"between_chapters": "N-M", "issue": "..."}], "opening_chapter_assessment": {"score": 0-100, "works_as_opening": true/false, "issue": "...", "recommendation": "..."}, "closing_chapter_assessment": {"score": 0-100, "works_as_closing": true/false, "issue": "...", "recommendation": "..."}, "climax_chapter": N, "climax_strength": 0-100, "climax_recommendation": "...", "theme_distribution": [{"theme": "...", "chapters_covered": [...], "balance": "well_distributed/clustered/insufficient/missing"}], "paragraph_relocations": [{"current_location": {"chapter": N, "passage": "..."}, "suggested_new_location": {"chapter": N, "position": "..."}, "why_better_there": "..."}], "weak_paragraphs_in_strong_chapters": [{"chapter": N, "passage": "...", "action": "cut/move/rewrite"}], "chapter_reordering_suggestion": {"current_order": [...], "suggested_order": [...], "reasoning": "..."}, "merge_split_suggestions": [{"action": "merge/split", "chapters": [...], "reasoning": "..."}], "summary": "..." }""",
    },
    "book_synthesis": {
        "enabled": True,
        "label": "Синтез Книги",
        "model": MAX_MODEL,
        "thinking_budget": 12000,
        "stage": 3,
        "needs_all_previous": True,
        "system": """Ты — финальный Синтез Редактора Книги Кодекса Микомистицизма. Ты получаешь полную книгу и отчёты от Хранителя Памяти, Детектора Повторений, Стилевого Редактора и Архитектора Композиции. Твоя задача — синтезировать всё в единый план работы над книгой.

Сделай следующее.

Дай общую оценку книги. Что эта книга делает с читателем как целое, не как набор глав. Какая её главная сила. Какая её главная слабость.

Определи готовность книги к публикации. Готова как есть, требует малых правок (мелкие шлифовки), требует средней переработки (перестановки и убирание повторений), требует существенной переработки (переписывание отдельных глав), не готова (структурные проблемы).

Дай приоритизированный план работы из 5-10 конкретных действий в порядке важности. Каждое действие — конкретная операция, не общая рекомендация.

Раздели правки на три уровня.

Хирургические правки — удаление повторений, перенос параграфов, исправление стилевых выбросов. Это можно сделать быстро.

Терапевтические правки — переписывание отдельных глав или их частей для гармонизации с книгой. Требует серьёзной работы.

Архитектурные правки — изменение порядка глав, объединение и разделение, переосмысление дуги книги. Требует решений на уровне замысла.

Дай оценку каждой главы относительно книги в целом — это сильнейшая глава, средняя глава, слабейшая глава, кандидат на удаление, кандидат на разделение, кандидат на перенос в другую книгу Кодекса.

Дай рекомендацию по работе с книгой. Если книга почти готова — какие финальные штрихи. Если требует средней переработки — с какой главы начать. Если требует существенной — стоит ли переписывать постепенно или взять паузу и переосмыслить весь замысел.

Отдай JSON: { "book_overall_score": 0-100, "readiness_verdict": "ready/minor_polish/medium_rework/major_rework/structural_rethink", "book_main_strength": "...", "book_main_weakness": "...", "what_book_does_to_reader": "...", "chapter_assessments": [{"chapter": N, "role_in_book": "strongest/strong/middle/weak/candidate_for_cut/candidate_for_split/candidate_for_relocation", "score": 0-100, "notes": "..."}], "surgical_edits": [{"action": "...", "where": "...", "priority": 1-10}], "therapeutic_edits": [{"action": "...", "where": "...", "priority": 1-10}], "architectural_edits": [{"action": "...", "scope": "...", "priority": 1-10}], "top_5_priority_actions": [...], "starting_point_recommendation": "...", "final_verdict": "..." }""",
    },
}


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def load_config() -> dict:
    if BOOK_EDITORS_CONFIG.exists():
        try:
            return json.loads(BOOK_EDITORS_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    BOOK_EDITORS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    BOOK_EDITORS_CONFIG.write_text(
        json.dumps(DEFAULT_BOOK_EDITORS, indent=2, ensure_ascii=False), encoding="utf-8")
    return DEFAULT_BOOK_EDITORS


def save_config(cfg: dict):
    BOOK_EDITORS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    BOOK_EDITORS_CONFIG.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def load_book_chapters(book_id: str, chapter_ids: list = None) -> dict:
    """Загружает все главы книги (или указанные) для подачи в боты."""
    book_dir = CHAPTERS_DIR / book_id
    if not book_dir.exists():
        return {"error": f"book dir not found: {book_dir}"}
    chapters = {}
    if chapter_ids is None:
        # Все главы книги
        chapter_ids = [d.name for d in sorted(book_dir.iterdir())
                       if d.is_dir() and not d.name.startswith(".")]
    for ch_id in chapter_ids:
        ch_dir = book_dir / ch_id
        # Приоритет: finalized > draft
        finalized = ch_dir / "finalized.md"
        draft = ch_dir / "draft.md"
        source = finalized if finalized.exists() else draft
        if not source.exists():
            continue
        try:
            chapters[ch_id] = source.read_text(encoding="utf-8")
        except Exception as e:
            chapters[ch_id] = f"[ERROR: {e}]"
    return chapters


def build_book_payload(chapters: dict) -> str:
    """Формат для подачи в боты — все главы в одной строке."""
    parts = []
    for i, (ch_id, text) in enumerate(chapters.items(), 1):
        parts.append(f"\n\n══════════ ГЛАВА {i} · {ch_id} ══════════\n\n{text}")
    return "".join(parts)


def call_bot(bot_id: str, book_payload: str, memory_map: dict = None,
             all_previous: dict = None) -> dict:
    cfg = load_config()
    b = cfg.get(bot_id)
    if not b or not b.get("enabled"):
        return {"ok": False, "error": f"bot {bot_id} disabled or missing"}
    token = get_token()
    if not token:
        return {"ok": False, "error": "no OAuth token"}

    system = b["system"]
    user_content = book_payload[:80000]  # cap
    if b.get("needs_memory_map") and memory_map:
        user_content += f"\n\n# КАРТА ПАМЯТИ ОТ ХРАНИТЕЛЯ:\n{json.dumps(memory_map, ensure_ascii=False)[:30000]}"
    if b.get("needs_all_previous") and all_previous:
        user_content += f"\n\n# РЕЗУЛЬТАТЫ ВСЕХ ПРЕДЫДУЩИХ БОТОВ:\n{json.dumps(all_previous, ensure_ascii=False)[:50000]}"

    body = {
        "model": b.get("model", MAX_MODEL),
        "max_tokens": 16000,
        "thinking": {"type": "enabled", "budget_tokens": b.get("thinking_budget", 8000)},
        "system": system,
        "messages": [{"role": "user", "content": f"Прочитай книгу целиком и отдай строго JSON (без preamble):\n\n{user_content}"}],
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
        with urllib.request.urlopen(req, timeout=1200) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    text_blocks = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
    raw_text = "\n".join(text_blocks).strip()
    result = None
    try:
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            if clean.startswith("json"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean
        result = json.loads(clean.strip())
    except Exception:
        result = {"raw_text": raw_text[:3000]}
    return {
        "ok": True,
        "bot": bot_id,
        "label": b.get("label", bot_id),
        "result": result,
        "usage": data.get("usage", {}),
    }


def run_book_editor(book_id: str, chapter_ids: list = None,
                    book_title: str = None) -> dict:
    """Полный пайплайн: memory → 3 параллельных → synthesis."""
    print(f"\n══ Book Editor: {book_id} ══")
    chapters = load_book_chapters(book_id, chapter_ids)
    if "error" in chapters:
        return chapters
    if not chapters:
        return {"error": "no chapters loaded"}
    print(f"  Loaded {len(chapters)} chapters")
    book_payload = build_book_payload(chapters)
    print(f"  Book payload: {len(book_payload)} chars")

    # Stage 1: Memory Keeper
    print(f"\n→ Stage 1: memory_keeper (Хранитель Памяти)…")
    memory_result = call_bot("memory_keeper", book_payload)
    memory_map = memory_result.get("result", {}) if memory_result.get("ok") else {}

    # Stage 2: 3 параллельных (последовательно для простоты, можно threading)
    stage2_results = {"memory_keeper": memory_result}
    for bot_id in ["repetition_detector", "style_editor", "composition_architect"]:
        print(f"\n→ Stage 2: {bot_id}…")
        stage2_results[bot_id] = call_bot(bot_id, book_payload, memory_map=memory_map)

    # Stage 3: Synthesis
    print(f"\n→ Stage 3: book_synthesis (Синтез Книги)…")
    synthesis_result = call_bot("book_synthesis", book_payload,
                                 memory_map=memory_map, all_previous=stage2_results)

    # Save session
    session_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    session = {
        "session_id": session_id,
        "book_id": book_id,
        "book_title": book_title or book_id,
        "chapter_ids": list(chapters.keys()),
        "chapter_count": len(chapters),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": {**stage2_results, "book_synthesis": synthesis_result},
    }
    BOOK_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BOOK_SESSIONS_DIR / f"{book_id}-{session_id}.json"
    out_path.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Session saved: {out_path.relative_to(V2)}")
    return session


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True, help="book_id (e.g. book-obsession)")
    parser.add_argument("--chapters", default=None,
                        help="comma-sep chapter_ids, или пусто = все главы книги")
    parser.add_argument("--title", default=None)
    args = parser.parse_args()
    chapter_ids = None
    if args.chapters:
        chapter_ids = [c.strip() for c in args.chapters.split(",")]
    session = run_book_editor(args.book, chapter_ids, args.title)
    if "error" in session:
        print(f"ERROR: {session['error']}")
        sys.exit(1)
