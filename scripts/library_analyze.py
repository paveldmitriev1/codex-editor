#!/usr/bin/env python3
"""
library_analyze.py — анализирует загруженную книгу из Библиотеки примеров (UC-96).

Pavel: «закачать книги-примеры (Манифест Грибов, Устав), AI обращается при
написании, читает, использует свой анализ».

Вход: --file-id <ID> (берётся из data/library/index.json).
Извлекает текст (docx/md/txt), отправляет в Opus 4.7 с system prompt
анализатора стиля, сохраняет результат в
data/library/files/<id>__analysis.json.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/Codex2/app"))
try:
    from config import MAX_MODEL, PROXY_URL  # noqa: E402
except Exception:
    MAX_MODEL = "claude-opus-4-7"
    PROXY_URL = "http://127.0.0.1:8787"

V2 = Path.home() / "Desktop/Codex2"
LIB_DIR = V2 / "data/library"
INDEX = LIB_DIR / "index.json"


def get_token():
    env = Path.home() / ".cc-memory-bridge/.env"
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def docx_to_text(path: Path, max_chars: int = 50000) -> str:
    try:
        with zipfile.ZipFile(path, "r") as z:
            with z.open("word/document.xml") as f:
                xml = f.read().decode("utf-8", errors="replace")
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.DOTALL)
        out = "\n".join(texts)
        out = out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        out = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), out)
        return out[:max_chars]
    except Exception as e:
        return f"[docx parse error: {e}]"


def _pdf_to_text_via_quartz(path: Path, max_chars: int) -> str:
    """Использует /usr/bin/osascript + JXA + Quartz.PDFDocument.string.

    Возвращает строку или пустую если не получилось.
    """
    import subprocess
    if sys.platform != "darwin":
        return ""
    script = '''
    ObjC.import("Quartz");
    var url = $.NSURL.fileURLWithPath($.NSString.stringWithUTF8String(__PATH__));
    var pdf = $.PDFDocument.alloc.initWithURL(url);
    if (!pdf || pdf.pageCount === 0) { "" } else {
      var s = ObjC.unwrap(pdf.string);
      s ? s : ""
    }
    '''.replace("__PATH__", json.dumps(str(path)))
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
            capture_output=True, text=True, timeout=60,
        )
        out = (proc.stdout or "").strip()
        if not out:
            return ""
        # Normalize whitespace + truncate
        out = re.sub(r"\r\n", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out[:max_chars]
    except Exception:
        return ""


def pdf_to_text(path: Path, max_chars: int = 200000) -> str:
    """UC-109 PDF text extractor.

    Стратегия:
      1) macOS Quartz PDFKit через osascript JXA — корректно декодирует
         subset-шрифты (Type 0 / CID), потому что Apple-stack знает CMap.
         Это даёт качественный результат для 99% Pavel-овских PDF.
      2) Fallback: pure-stdlib parser (Tj/TJ из content streams), работает
         только для PDF со стандартной кодировкой.
    """
    # Path 1: macOS Quartz
    txt = _pdf_to_text_via_quartz(path, max_chars)
    if txt:
        return txt
    # Path 2: pure-stdlib fallback
    try:
        raw = path.read_bytes()
    except Exception as e:
        return f"[pdf read error: {e}]"

    out_chunks = []

    # Найти все stream-блоки. Каждый предваряется dict-частью где могут быть фильтры.
    # Pattern: «(<<...>>)\s*stream\n...\nendstream»
    # Грубо: вытащим все позиции «stream\n» и «endstream», и контекст ~400 bytes перед stream.
    pos = 0
    while True:
        s_idx = raw.find(b"stream", pos)
        if s_idx < 0:
            break
        # find newline after «stream»
        nl = s_idx + len("stream")
        if nl < len(raw) and raw[nl:nl+2] == b"\r\n":
            nl += 2
        elif nl < len(raw) and raw[nl:nl+1] in (b"\n", b"\r"):
            nl += 1
        e_idx = raw.find(b"endstream", nl)
        if e_idx < 0:
            break
        # walk back from e_idx to drop possible preceding \r\n
        body_end = e_idx
        if body_end > 0 and raw[body_end-1:body_end] == b"\n":
            body_end -= 1
        if body_end > 0 and raw[body_end-1:body_end] == b"\r":
            body_end -= 1
        body = raw[nl:body_end]

        # context (preceding obj header) — look back ~600 bytes for filters
        ctx_start = max(0, s_idx - 800)
        ctx = raw[ctx_start:s_idx]

        # Decode (only handle FlateDecode common case; pass-through otherwise)
        decoded = None
        if b"/FlateDecode" in ctx:
            try:
                decoded = zlib.decompress(body)
            except Exception:
                try:
                    decoded = zlib.decompress(body, -15)  # raw deflate
                except Exception:
                    decoded = None
        else:
            decoded = body

        if decoded:
            text_pieces = _extract_text_from_content_stream(decoded)
            if text_pieces:
                out_chunks.append("\n".join(text_pieces))

        pos = e_idx + len("endstream")
        if sum(len(c) for c in out_chunks) > max_chars + 5000:
            break

    if not out_chunks:
        return "[pdf parse: текст не извлечён (возможно скан/OCR-нужен)]"
    full = "\n\n".join(out_chunks)
    # Normalize whitespace
    full = re.sub(r"[ \t]+", " ", full)
    full = re.sub(r"\n{3,}", "\n\n", full)
    return full[:max_chars]


def _extract_text_from_content_stream(stream: bytes) -> list:
    """Извлекаем строки из PDF content stream.

    Ищем операторы Tj (1 строка), TJ (массив), ', " (с newline-вариантами).
    Строки в PDF: либо `(литерал с escape)` либо `<hex>`.
    """
    out = []
    i = 0
    n = len(stream)
    while i < n:
        c = stream[i:i+1]
        # Литеральная строка (...)
        if c == b"(":
            s, end = _read_literal_string(stream, i)
            # после строки могут быть пробелы и оператор
            j = end
            # пропускаем пробелы
            while j < n and stream[j:j+1] in (b" ", b"\t", b"\r", b"\n"):
                j += 1
            # ищем оператор за этой строкой
            op = _peek_operator(stream, j)
            if op in (b"Tj", b"'", b'"'):
                out.append(_decode_pdf_string(s))
            i = end
            continue
        # Hex string <...>
        if c == b"<" and i+1 < n and stream[i+1:i+2] != b"<":
            end = stream.find(b">", i+1)
            if end < 0:
                i += 1
                continue
            hex_s = stream[i+1:end]
            j = end + 1
            while j < n and stream[j:j+1] in (b" ", b"\t", b"\r", b"\n"):
                j += 1
            op = _peek_operator(stream, j)
            if op in (b"Tj", b"'", b'"'):
                try:
                    txt = bytes.fromhex(hex_s.decode("ascii", "ignore").replace(" ", ""))
                    out.append(txt.decode("utf-16-be", errors="replace") if len(txt) >= 2 and txt[:2] in (b"\xfe\xff",) else txt.decode("latin-1", errors="replace"))
                except Exception:
                    pass
            i = end + 1
            continue
        # Массив TJ: [(...)num(...)num]TJ — собираем все строки внутри []
        if c == b"[":
            end = i + 1
            depth = 1
            while end < n and depth > 0:
                ch = stream[end:end+1]
                if ch == b"(":
                    _, after = _read_literal_string(stream, end)
                    end = after
                    continue
                if ch == b"[":
                    depth += 1
                elif ch == b"]":
                    depth -= 1
                end += 1
            block = stream[i:end]
            j = end
            while j < n and stream[j:j+1] in (b" ", b"\t", b"\r", b"\n"):
                j += 1
            op = _peek_operator(stream, j)
            if op == b"TJ":
                # Extract all literal strings from block
                pieces = []
                k = 1
                while k < len(block) - 1:
                    ck = block[k:k+1]
                    if ck == b"(":
                        s2, e2 = _read_literal_string(block, k)
                        pieces.append(_decode_pdf_string(s2))
                        k = e2
                        continue
                    if ck == b"<":
                        ee = block.find(b">", k+1)
                        if ee < 0:
                            break
                        hex_s = block[k+1:ee]
                        try:
                            txt = bytes.fromhex(hex_s.decode("ascii", "ignore").replace(" ", ""))
                            if len(txt) >= 2 and txt[:2] == b"\xfe\xff":
                                pieces.append(txt.decode("utf-16-be", errors="replace"))
                            else:
                                pieces.append(txt.decode("latin-1", errors="replace"))
                        except Exception:
                            pass
                        k = ee + 1
                        continue
                    k += 1
                if pieces:
                    out.append("".join(pieces))
            i = end
            continue
        i += 1
    return out


def _read_literal_string(buf: bytes, start: int):
    """Читаем (...)  с escape-последовательностями. Возвращаем (bytes_внутри, индекс_после_закрывающей_скобки)."""
    assert buf[start:start+1] == b"("
    i = start + 1
    out = bytearray()
    depth = 1
    while i < len(buf):
        ch = buf[i]
        if ch == 0x5C:  # backslash
            if i + 1 >= len(buf):
                break
            nxt = buf[i+1]
            if nxt == 0x6E:  # \n
                out.append(0x0A); i += 2; continue
            if nxt == 0x72:  # \r
                out.append(0x0D); i += 2; continue
            if nxt == 0x74:  # \t
                out.append(0x09); i += 2; continue
            if nxt == 0x62:  # \b
                out.append(0x08); i += 2; continue
            if nxt == 0x66:  # \f
                out.append(0x0C); i += 2; continue
            if nxt in (0x28, 0x29, 0x5C):  # \( \) \\
                out.append(nxt); i += 2; continue
            # \ddd octal escape
            if 0x30 <= nxt <= 0x37:
                octs = bytearray([nxt])
                j = i + 2
                while j < len(buf) and len(octs) < 3 and 0x30 <= buf[j] <= 0x37:
                    octs.append(buf[j]); j += 1
                try:
                    out.append(int(octs.decode("ascii"), 8) & 0xFF)
                except Exception:
                    pass
                i = j
                continue
            # \\n at end of line → ignore newline
            if nxt in (0x0A, 0x0D):
                i += 2
                continue
            i += 2
            continue
        if ch == 0x28:  # (
            depth += 1
            out.append(ch)
            i += 1
            continue
        if ch == 0x29:  # )
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return bytes(out), i


def _peek_operator(buf: bytes, start: int) -> bytes:
    """Read operator token at start (alphabetic word) up to 3 chars."""
    j = start
    while j < len(buf) and buf[j:j+1].isalpha():
        j += 1
        if j - start >= 3:
            break
    if j == start and start < len(buf) and buf[start:start+1] in (b"'", b'"'):
        return buf[start:start+1]
    return buf[start:j]


def _decode_pdf_string(s: bytes) -> str:
    """Decode PDF byte string. UTF-16-BE if BOM, else PDFDocEncoding-ish (Latin-1 approximation)."""
    if len(s) >= 2 and s[:2] == b"\xfe\xff":
        try:
            return s[2:].decode("utf-16-be", errors="replace")
        except Exception:
            pass
    # PDFDocEncoding ≈ Latin-1 для basic ASCII + кириллица обычно в WinAnsi или CP1251
    try:
        return s.decode("utf-8")
    except Exception:
        pass
    try:
        return s.decode("cp1251")
    except Exception:
        return s.decode("latin-1", errors="replace")


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        return docx_to_text(path)
    if ext == ".pdf":
        return pdf_to_text(path)
    if ext in (".md", ".txt"):
        try:
            return path.read_text(encoding="utf-8")[:200000]
        except Exception as e:
            return f"[read error: {e}]"
    return f"[unsupported ext: {ext}]"


def analyze_text(text: str, filename: str) -> dict:
    token = get_token()
    if not token:
        return {"error": "no OAuth token"}
    system = (
        "Ты анализатор стиля Pavel-а (Хилингода) для Сакрального Кодекса Микомистицизма.\n"
        "Прочитай книгу и составь структурный отчёт по схеме (только валидный JSON):\n"
        "{\n"
        '  "voice": "от какого лица, какие маркеры (Я, Мы, Вы), регистр (formal/informal)",\n'
        '  "rhythm": "средняя длина предложений, частота пауз, использование тире",\n'
        '  "lexicon": "ключевые термины которые повторяются, доктринальный словарь",\n'
        '  "anti_patterns": "чего Pavel НЕ использует: AI-клише, контраст-пары, нейрохимия",\n'
        '  "themes": "главные темы и доктринальная позиция",\n'
        '  "exemplars": ["3-5 эталонных цитат под 50 слов каждая, прямо из текста"],\n'
        '  "summary": "150-300 слов: общая характеристика стиля и почему этот текст образцовый"\n'
        "}\n"
        "Без преамбулы. Сразу JSON."
    )
    user = f"# КНИГА: {filename}\n\n{text[:30000]}\n\n# ЗАДАНИЕ\nПроанализируй стиль по схеме выше."
    body = {
        "model": MAX_MODEL,
        "max_tokens": 4000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        f"{PROXY_URL}/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"}
    except Exception as e:
        return {"error": str(e)}
    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    raw = "\n".join(blocks).strip()
    # Try to parse JSON
    clean = raw
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        if clean.startswith("json"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean
    try:
        result = json.loads(clean.strip())
    except Exception:
        result = {"raw": raw[:3000], "summary": raw[:600]}
    result["usage"] = data.get("usage", {})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file-id", required=True)
    args = parser.parse_args()
    if not INDEX.exists():
        print("index.json не найден")
        return 1
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    entry = next((f for f in idx.get("files", []) if f["id"] == args.file_id), None)
    if not entry:
        print(f"file_id {args.file_id} не найден")
        return 1
    src = V2 / entry["stored_path"]
    if not src.exists():
        print(f"файл не существует: {src}")
        return 1
    print(f"Анализирую {entry['name']}…")
    text = extract_text(src)
    print(f"Извлёк {len(text)} символов, отправляю в Opus 4.7…")
    result = analyze_text(text, entry["name"])
    result["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result["file_id"] = args.file_id
    result["file_name"] = entry["name"]
    out = LIB_DIR / "files" / f"{args.file_id}__analysis.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Готово: {out}")
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
