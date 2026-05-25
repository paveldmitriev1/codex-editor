# Pavel Requests Log

**Цель:** централизованное место где сохраняются все Pavel-овские запросы,
требования, недовольства, идеи. Каждый — с датой, моим ответом, статусом.
Используется ночным reflection-агентом для анализа «что было важно но не сделано».

## Структура

- `YYYY-MM-DD.jsonl` — один файл на день, JSONL формат
- Каждая строка: `{ts, request, my_response_summary, status, files_changed, commits}`

## Status values

- `done` — сделано и работает
- `partial` — частично сделано
- `open` — не сделано
- `ignored` — Tom проигнорировал/забыл (red flag для reflection)
- `wont_fix` — намеренно отложено (с объяснением)
