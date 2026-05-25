# Codex Editor

Локальный редактор для глубокой работы над книгой — на стыке писательского ремесла и LLM-ассистента. Создан для проекта Pavel Dmitriev / Hilingod «Сакральный Кодекс Микомистицизма», но архитектурно работает с любой книгой где автору важно сохранить собственный голос и не дать AI «нормализовать» текст под усреднённый стандарт.

## Что это

Python stdlib HTTP-сервер (без внешних зависимостей) на порту `7788`, который читает главы из локальной папки и предоставляет браузерный редактор с подключённым Anthropic Claude (Opus). Особенность — multi-layer защита авторского голоса: каждый Opus-промпт получает «substrate» из канона книги, эталона стиля, библиотеки примеров, голосовых надиктовок автора и его исходных сообщений из чата.

## Архитектура (фаза 3+)

```
Editor UI (editor.html)
   │
   ↓
Server (app/server.py) ── port 7788
   │
   ├─→ Master-Auditor (/api/chapter/master-audit)
   │      один Opus call с _pavel_substrate(chapter_id)
   │      возвращает строго 3-5 правок
   │
   ├─→ Critics Council (5 ключевых критиков + synthesis)
   │      voice_purity, ai_tells, mystical_depth, rhythm, sacred_lexicon
   │
   ├─→ Personas (3 современные перспективы)
   │      Огилви (headline), Роган (личный опыт), Тиль (contrarian)
   │
   └─→ Reconciler / Sequence / Journalist Q&A (по запросу)

Opus вызывается через локальный OAuth-прокси (port 8787) —
эта часть отдельный проект, не входит в этот репо.
```

## Установка

### Предварительно

- Python 3.9+ (использует только stdlib, никакого `pip install`)
- macOS / Linux (на Windows работает, но не тестировал)
- Доступ к Claude API. Самый дешёвый вариант — OAuth-прокси под Claude Max или прямой Anthropic API ключ.

### Запуск

```bash
git clone <url-to-this-repo> codex-editor
cd codex-editor
python3 app/server.py
```

Редактор откроется на <http://127.0.0.1:7788>.

Сервер ожидает увидеть:
- `~/.cc-memory-bridge/.env` с `CLAUDE_CODE_OAUTH_TOKEN=...` (если используется OAuth-прокси)
- ИЛИ adapter в `app/server.py` который вы напишите под свой API-провайдер
- Локальный OAuth-прокси по `http://127.0.0.1:8787/v1/messages` (Anthropic-совместимый API)

### Где живёт контент

Чтобы код приложения был чистым, контент автора не лежит в этом репо. Структура:

```
~/Desktop/Codex2/             ← этот репо (только код и конфиги)
   ├── app/                   server.py + static editor.html
   ├── scripts/               critic_council, reconciler, personas, journalist
   ├── data/                  конфиги: critics-config.json, styles.json
   ├── data/library/files/    пустая (заполни своими стилевыми примерами)
   ├── chapters/.canon/       стилевой эталон (доктринальный)
   └── CANON.md               единая книга-канон

~/Desktop/Codex-Content/      ← рукописи автора (НЕ в git)
   ├── chapters/              все книги, главы, drafts
   ├── voice-corpus/          голосовые надиктовки
   ├── voice-index.jsonl      индекс сообщений из Claude.ai-экспорта
   └── ...
```

Чтобы работать над главой, копируешь её в `~/Desktop/Codex2/chapters/<book>/<chapter>/` и она появляется в редакторе. После работы — обратно в `Codex-Content/`.

## Ключевые endpoints

| Endpoint | Что делает |
|---|---|
| `GET  /editor.html?chapter=<id>` | UI редактора |
| `POST /api/chapter/master-audit` | главный путь — Мастер возвращает 3-5 правок |
| `POST /api/critics/run` | 5 критиков + synthesis в фоне |
| `POST /api/personas/run` | 3 персоны (Огилви, Роган, Тиль) |
| `POST /api/chapter/<id>/apply-targeted` | применить выбранные правки в текст |
| `GET  /api/jobs/active?chapter_id=…` | активные фоновые операции |

## Структура

- `app/server.py` — единый HTTP-handler (~8000 строк, всё в одном классе). Главные методы: `_pavel_substrate`, `_master_audit`, `_apply_targeted`, `_super_rewrite`.
- `app/static/editor.html` — UI с inline JS, без сборки. Render-логика для master-audit карточки в `renderMasterAudit`.
- `scripts/critic_council.py` — 5 критиков с разными промптами + synthesis.
- `scripts/personas.py` — Огилви / Роган / Тиль читают главу с разных позиций.
- `scripts/reconciler.py` — убирает конфликты между рекомендациями (запускается реже после Фазы 3).
- `scripts/editor_journalist.py` — Q&A с автором перед применением правок.

## Что было до этого

Этот репо — результат Фазы 1-4 переработки. До этого был «оркестр без дирижёра»: 15 критиков, 5 персон, reconciler сшивает 50+ правок. Автор жаловался на «слишком много рекомендаций и противоречий». Решение: один Мастер-аудитор вместо оркестра. Канон, стиль, голос — в одном substrate.

## Известные шероховатости

- `app/server.py` монолитный, ~8000 строк в одном классе. Кандидат на разделение по модулям.
- `app/static/editor.html` ~3000 строк inline JS. Кандидат на вынос в отдельные .js файлы.
- Нет автотестов. Только AST-валидация Python + `node --check` для JS.
- Журналист Q&A и sequence-analyzer пока подключены, но в Фазе 3 решили использовать их редко.

## Лицензия

MIT.

## Контакт

`paveldmitriev1` на GitHub.
