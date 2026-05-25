#!/usr/bin/env python3
"""
extract_voice.py — извлекает РЕЧЬ Pavel-а из Claude.ai conversations.json архива.

Pavel: реальный голос (его сообщения, sender=human) — это PRIMARY source для Codex.
.docx файлы — SECONDARY (старые модели часто переписывали мысли).

Что делает:
1) Стримит ~557 МБ JSON архив (не грузит в память целиком)
2) Для каждой беседы вытаскивает только sender=human сообщения
3) Фильтрует:
   - --since YYYY-MM-DD (по created_at)
   - --topic-filter (опционально — слова в названии/саммари беседы)
   - --min-len (минимум знаков в сообщении, дефолт 100)
4) Группирует по conversations
5) Сохраняет в Codex2/voice-corpus/raw/<YYYY-MM-DD>__<slug>.md
6) Пишет индексный файл voice-corpus/INDEX.md со ссылками

Запуск:
    # все Pavel-сообщения с 2024-01-01
    python3 extract_voice.py --since 2024-01-01

    # только связанные с Микомистицизмом / Кодексом
    python3 extract_voice.py --since 2024-01-01 --topic-filter codex,микомистицизм,гриб,хилингод,экзорцизм

    # коротко без фильтра топика (всё подряд)
    python3 extract_voice.py --since 2025-01-01 --min-len 200
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


HOME = Path.home()
DEFAULT_ARCHIVE = HOME / "Desktop/data-1c39ff64-36e7-4694-8677-53b37e753ae7-1778787238-0bc3f38f-batch-0000/conversations.json"
DEFAULT_OUT = HOME / "Desktop/Codex2/voice-corpus/raw"

# По умолчанию — тематический фильтр для Codex
DEFAULT_TOPIC_KEYWORDS = [
    "codex", "кодекс", "микомистицизм", "грибн", "грибы", "хилингод",
    "великий дух", "творц", "экзорцизм", "паразит", "псилоциб",
    "церемони", "проводник", "устав", "хридайя", "сердце", "одержимост",
    "сан педро", "псилоцибин", "мицели", "святая", "церковь",
    "manifesto", "manifesto", "scripture", "mystic", "shaman",
]


def slugify(s: str, max_len: int = 60) -> str:
    s = s.lower().strip()
    table = str.maketrans({
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh",
        "з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o",
        "п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts",
        "ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu",
        "я":"ya",
    })
    s = s.translate(table)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:max_len] or "unnamed"


def parse_date(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=None)


def message_text(msg: dict) -> str:
    """Достать текст из message — может быть в text или в content[].text."""
    if msg.get("text"):
        return msg["text"]
    parts = []
    for c in msg.get("content", []):
        if c.get("type") == "text" and c.get("text"):
            parts.append(c["text"])
    return "\n\n".join(parts).strip()


def topic_matches(conv: dict, keywords: list) -> bool:
    if not keywords:
        return True
    haystack = (conv.get("name", "") + " " + conv.get("summary", "")).lower()
    # Также берём первые 5 human-сообщений как сигнал
    for m in conv.get("chat_messages", [])[:10]:
        if m.get("sender") == "human":
            haystack += " " + message_text(m).lower()[:1000]
    return any(kw in haystack for kw in keywords)


def extract(archive: Path, out_dir: Path, since: datetime, keywords: list, min_len: int) -> dict:
    """Стримим JSON-массив беседы за беседой. Стdlib умеет это через ijson… но без ijson
    проще: загружаем как array (557 МБ помещается в память на Mac с 8+ GB)."""
    print(f"📂 Читаю {archive.name}... (~557 МБ)")
    with archive.open("r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"✓ Всего бесед: {len(data)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    index_entries = []
    matched = skipped_topic = skipped_date = 0

    for conv in data:
        try:
            created = parse_date(conv.get("created_at", ""))
        except Exception:
            created = datetime.min
        if since and created.replace(tzinfo=None) < since:
            skipped_date += 1
            continue
        if not topic_matches(conv, keywords):
            skipped_topic += 1
            continue

        # Собираем Pavel-сообщения
        human_msgs = []
        for m in conv.get("chat_messages", []):
            if m.get("sender") != "human":
                continue
            t = message_text(m)
            if len(t) < min_len:
                continue
            human_msgs.append({
                "ts": m.get("created_at", ""),
                "text": t,
            })

        if not human_msgs:
            continue

        # Имя файла
        name = conv.get("name") or "untitled"
        date_str = created.strftime("%Y-%m-%d") if created != datetime.min else "0000-00-00"
        slug = slugify(name)[:50] or "conversation"
        filename = f"{date_str}__{slug}.md"
        out_file = out_dir / filename

        # Создаём контент
        md = [
            f"# {name}",
            "",
            f"**Conversation:** {conv.get('uuid', '?')}",
            f"**Created:** {conv.get('created_at', '?')}",
            f"**Updated:** {conv.get('updated_at', '?')}",
            f"**Pavel messages:** {len(human_msgs)}",
            f"**Total chars:** {sum(len(m['text']) for m in human_msgs)}",
            "",
            "---",
            "",
            "## Сообщения Pavel-а (это его реальный голос — primary source)",
            "",
        ]
        for i, m in enumerate(human_msgs, 1):
            md.append(f"### Message {i} · {m['ts'][:19]}")
            md.append("")
            md.append(m["text"])
            md.append("")
            md.append("---")
            md.append("")

        out_file.write_text("\n".join(md), encoding="utf-8")
        matched += 1
        index_entries.append({
            "file": filename,
            "name": name,
            "date": date_str,
            "msgs": len(human_msgs),
            "chars": sum(len(m["text"]) for m in human_msgs),
        })

        if matched % 50 == 0:
            print(f"  [{matched}] {filename[:80]}")

    print(f"\n✓ Извлечено: {matched} бесед с речью Pavel-а")
    print(f"  Пропущено по дате: {skipped_date}")
    print(f"  Пропущено по теме: {skipped_topic}")

    # Индекс
    index_entries.sort(key=lambda x: x["date"], reverse=True)
    index_lines = [
        f"# Voice Corpus — индекс",
        "",
        f"**Извлечено:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Источник:** `{archive}`",
        f"**Бесед с голосом Pavel-а:** {len(index_entries)}",
        f"**Суммарно символов:** {sum(e['chars'] for e in index_entries):,}",
        f"**Суммарно сообщений:** {sum(e['msgs'] for e in index_entries):,}",
        "",
        "## По датам (новые сверху)",
        "",
        "| Дата | Беседа | Сообщений | Символов |",
        "|---|---|---|---|",
    ]
    for e in index_entries:
        index_lines.append(f"| {e['date']} | [{e['name'][:60]}](raw/{e['file']}) | {e['msgs']} | {e['chars']:,} |")

    (out_dir.parent / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")
    print(f"✓ Индекс: {out_dir.parent / 'INDEX.md'}")

    return {
        "matched": matched,
        "skipped_date": skipped_date,
        "skipped_topic": skipped_topic,
        "total_chars": sum(e["chars"] for e in index_entries),
        "total_msgs": sum(e["msgs"] for e in index_entries),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(DEFAULT_ARCHIVE), help="Path to conversations.json")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory")
    ap.add_argument("--since", default="2024-01-01", help="YYYY-MM-DD")
    ap.add_argument("--topic-filter", default=",".join(DEFAULT_TOPIC_KEYWORDS),
                    help="Comma-separated keywords (или '' для всех)")
    ap.add_argument("--min-len", type=int, default=100, help="Минимум символов в сообщении")
    args = ap.parse_args()

    archive = Path(args.archive).expanduser()
    if not archive.exists():
        print(f"✗ Не найден: {archive}", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.out).expanduser()
    since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
    keywords = [k.strip().lower() for k in args.topic_filter.split(",") if k.strip()] if args.topic_filter else []

    print(f"Архив:    {archive}")
    print(f"Выход:    {out_dir}")
    print(f"С даты:   {args.since}")
    print(f"Ключи:    {len(keywords)} ({', '.join(keywords[:6])}...)")
    print(f"Мин длина: {args.min_len}")
    print()

    stats = extract(archive, out_dir, since, keywords, args.min_len)

    # Event
    events = HOME / "Desktop/Codex2/.codex/events.jsonl"
    events.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "voice_extracted",
        "target": "voice-corpus",
        "payload": stats,
    }
    with events.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
