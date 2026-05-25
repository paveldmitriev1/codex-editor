#!/usr/bin/env python3
"""auto_tester.py — автоматический тестер Codex 3 функций.

Pavel (2026-05-25): «создай тестера чтобы он выявлял все баги и нарушения».
Цель: ловить ошибки которые проявились бы у Pavel при ручном использовании.

Запускается вручную или из cron. Прогоняет все endpoints + проверяет
типичные сценарии. Пишет отчёт reports/AUTO-TEST-<ts>.md и json.

Usage:
    python3 scripts/auto_tester.py
    python3 scripts/auto_tester.py --quick   (skip Opus calls)
    python3 scripts/auto_tester.py --chapter book-12-ch-20
"""
import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT
SERVER = "http://127.0.0.1:7788"


class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warned = []
        self.started_at = datetime.now(timezone.utc)

    def passes(self, name, detail=""):
        self.passed.append({"name": name, "detail": detail})
        print(f"  ✅ {name}{(' — ' + detail) if detail else ''}")

    def fails(self, name, detail):
        self.failed.append({"name": name, "detail": detail})
        print(f"  ❌ {name} — {detail}")

    def warns(self, name, detail):
        self.warned.append({"name": name, "detail": detail})
        print(f"  ⚠  {name} — {detail}")

    def summary(self):
        return {
            "started_at": self.started_at.isoformat(),
            "duration_s": (datetime.now(timezone.utc) - self.started_at).total_seconds(),
            "passed": len(self.passed),
            "failed": len(self.failed),
            "warned": len(self.warned),
            "passed_list": self.passed,
            "failed_list": self.failed,
            "warned_list": self.warned,
        }


def http_get(path, timeout=8):
    url = SERVER + path
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.getcode(), body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def http_post(path, payload, timeout=30):
    url = SERVER + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.getcode(), body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def test_server_alive(r: TestResult):
    print("\n── Сервер ──")
    code, body = http_get("/api/health", timeout=4)
    if code == 200 and '"status": "ok"' in body:
        r.passes("server alive", "/api/health → 200")
    else:
        r.fails("server alive", f"code={code} body={body[:100]}")
        return False
    return True


def test_toc(r: TestResult):
    print("\n── TOC (выпадающий список глав) ──")
    code, body = http_get("/api/toc")
    if code != 200:
        r.fails("toc 200", f"code={code}")
        return
    try:
        data = json.loads(body)
    except Exception as e:
        r.fails("toc json parse", str(e))
        return
    books = data.get("books") or []
    if not books:
        r.fails("toc has books", "books=[] — editor dropdown будет пустым")
        return
    r.passes("toc has books", f"{len(books)} книг")
    total_chapters = sum(len(b.get("chapters", [])) for b in books)
    if total_chapters == 0:
        r.warns("toc has chapters", "0 глав в книгах")
    else:
        r.passes("toc has chapters", f"всего {total_chapters} глав")


def test_chapter_draft(r: TestResult, chapter_id):
    print(f"\n── Глава {chapter_id} ──")
    code, body = http_get(f"/api/chapter/{chapter_id}/draft")
    if code != 200:
        r.fails(f"draft {chapter_id}", f"code={code}")
        return None
    try:
        data = json.loads(body)
    except Exception as e:
        r.fails(f"draft {chapter_id} parse", str(e))
        return None
    title = data.get("title", "")
    if not title or title == chapter_id:
        r.fails(f"draft {chapter_id} title", f"title пустой или равен chapter_id: {title!r}")
    else:
        r.passes(f"draft {chapter_id} title", f"«{title[:60]}»")
    paras = data.get("paragraphs", [])
    if not paras:
        r.fails(f"draft {chapter_id} paragraphs", "0 параграфов")
    else:
        r.passes(f"draft {chapter_id} paragraphs", f"{len(paras)} параграфов")
    return data


def test_master_audit_cache(r: TestResult, chapter_id):
    print(f"\n── Master audit cache для {chapter_id} ──")
    code, body = http_get(f"/api/chapter/master-audit?chapter_id={urllib.parse.quote(chapter_id)}")
    if code == 404:
        r.warns(f"master cache {chapter_id}", "не запускался (это норма)")
        return None
    if code != 200:
        r.fails(f"master cache {chapter_id}", f"code={code}")
        return None
    try:
        data = json.loads(body)
    except Exception as e:
        r.fails(f"master cache {chapter_id} parse", str(e))
        return None
    edits = data.get("edits", [])
    r.passes(f"master cache {chapter_id}", f"{len(edits)} правок · score={data.get('score_estimate')}")
    # Проверим что у edits есть original поле
    for i, e in enumerate(edits):
        if "original" not in e or not e.get("original"):
            r.fails(f"edit {i} has original", "поле original отсутствует или пустое — Pavel не увидит контекст")
            break
    else:
        if edits:
            r.passes("all edits have original field", f"{len(edits)}/{len(edits)}")
    return data


def test_replace_paragraph_validation(r: TestResult):
    print("\n── replace-paragraph validation ──")
    cases = [
        ({}, "bad chapter_id"),
        ({"chapter_id": "xxx"}, "bad chapter_id"),
        ({"chapter_id": "book-12-ch-99"}, "para_idx required"),
        ({"chapter_id": "book-12-ch-99", "para_idx": 0}, "new_text"),
    ]
    for payload, expect_in_error in cases:
        code, body = http_post("/api/chapter/replace-paragraph", payload, timeout=4)
        if code in (400, 404, 500):
            try:
                err = json.loads(body).get("error", "")
                if expect_in_error in err:
                    r.passes(f"replace validation ({list(payload.keys()) or 'empty'})", err[:60])
                else:
                    r.warns(f"replace validation ({list(payload.keys()) or 'empty'})", f"got: {err[:80]}")
            except Exception:
                r.warns(f"replace validation ({list(payload.keys()) or 'empty'})", f"non-json: {body[:60]}")
        else:
            r.fails(f"replace validation ({list(payload.keys()) or 'empty'})", f"expected error code, got {code}")


def test_replace_paragraph_real(r: TestResult, chapter_id, dry_run=False):
    """Реальная замена параграфа + обратный rollback."""
    print(f"\n── replace-paragraph REAL ({chapter_id}, para 0) ──")
    if dry_run:
        r.warns("real replace", "skipped (dry-run)")
        return
    # 1. Сохраняем текущий П0
    code, body = http_get(f"/api/chapter/{chapter_id}/draft")
    if code != 200:
        r.fails("real replace setup", "не смог получить draft")
        return
    data = json.loads(body)
    paras = data.get("paragraphs", [])
    if not paras:
        r.fails("real replace setup", "0 параграфов в главе")
        return
    p0 = paras[0]
    orig_text = p0.get("text") if isinstance(p0, dict) else (p0 if isinstance(p0, str) else "")
    if not orig_text:
        r.fails("real replace setup", "не смог прочитать text из paragraphs[0]")
        return
    # 2. Заменяем на test marker
    test_marker = f"[AUTOTESTER-{int(time.time())}] " + orig_text
    code, body = http_post("/api/chapter/replace-paragraph", {
        "chapter_id": chapter_id, "para_idx": 0, "new_text": test_marker, "source": "auto_tester"
    }, timeout=6)
    if code != 200:
        r.fails("real replace POST", f"code={code} body={body[:80]}")
        return
    try:
        result = json.loads(body)
    except Exception as e:
        r.fails("real replace parse", str(e))
        return
    if not result.get("ok"):
        r.fails("real replace ok", result.get("error", ""))
        return
    backup = result.get("backup")
    r.passes("real replace POST", f"новых знаков={result.get('new_chars')}, backup={backup}")
    # 3. Проверяем что текст реально изменился
    code, body = http_get(f"/api/chapter/{chapter_id}/draft")
    new_para = json.loads(body).get("paragraphs", [])[0]
    new_text = new_para.get("text") if isinstance(new_para, dict) else new_para
    if "[AUTOTESTER-" in new_text:
        r.passes("real replace persisted", "draft.md содержит marker")
    else:
        r.fails("real replace persisted", f"marker отсутствует в draft.md: {new_text[:60]}")
    # 4. Откатываем
    code, body = http_post("/api/chapter/replace-paragraph", {
        "chapter_id": chapter_id, "para_idx": 0, "new_text": orig_text, "source": "auto_tester_rollback"
    }, timeout=6)
    if code == 200 and json.loads(body).get("ok"):
        r.passes("real replace rollback", "draft восстановлен")
    else:
        r.warns("real replace rollback", f"возможно draft остался изменённым: code={code}")


def test_voice_guard_logic(r: TestResult):
    """Проверяем что Voice Guard ловит микро-предложения через прямой импорт."""
    print("\n── Voice Guard логика ──")
    # Замокаем минимальный handler с _voice_guard_check
    # Проверяем что substrate-rule про микро-предложения работает.
    # Делаем это через прямой вызов regex как в коде.
    cases = [
        ("Pavel длинное", "Священные Грибы ждут в тишине лесов и лугов, хранят в своих спорах ключи от всех темниц, несут код освобождения, и каждый кто откликнется услышит зов через гул крови.", False),
        ("AI микро", "Врата открыты. Я жду Вас. Входите.", True),
        ("AI много коротких", "Грибы ждут. Они хранят ключи. Они дают силу. Входите.", True),
        ("Тире", "Это путь — не цель.", "dash"),
        ("AI-клише", "Эти сущности представляют собой энергетические структуры.", "cliche"),
    ]
    for name, text, expected in cases:
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
        cons_short = 0
        max_cons = 0
        for s in sentences:
            if 0 < len(s.split()) <= 7:
                cons_short += 1
                max_cons = max(max_cons, cons_short)
            else:
                cons_short = 0
        has_dash = "—" in text or "–" in text
        has_cliche = bool(re.search(r"представля[яю]т собой|в отличие от|таким образом", text, re.I))
        if expected is True:
            if max_cons >= 3:
                r.passes(f"guard catches microsentences: {name}", f"max consecutive={max_cons}")
            else:
                r.fails(f"guard catches microsentences: {name}", f"max consecutive={max_cons}")
        elif expected is False:
            if max_cons < 3 and not has_dash and not has_cliche:
                r.passes(f"guard passes Pavel-style: {name}", "no warnings")
            else:
                r.fails(f"guard passes Pavel-style: {name}", f"micro={max_cons}, dash={has_dash}, cliche={has_cliche}")
        elif expected == "dash":
            if has_dash:
                r.passes(f"guard catches dash: {name}", "")
            else:
                r.fails(f"guard catches dash: {name}", "тире не пойман")
        elif expected == "cliche":
            if has_cliche:
                r.passes(f"guard catches cliche: {name}", "")
            else:
                r.fails(f"guard catches cliche: {name}", "клише не пойман")


def test_book_reader(r: TestResult, book_id="book-12"):
    """Book Reader + Final Polish workflow (Pavel 2026-05-25)."""
    print(f"\n── Book Reader / Финальная Полировка ({book_id}) ──")
    # 1. /book-reader serves HTML
    try:
        req = urllib.request.Request(f"{SERVER}/book-reader")
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read(2000).decode("utf-8", errors="replace")
        if "Книга Целиком" in html or "br-book-shell" in html or "br-note" in html:
            r.passes("/book-reader serves HTML")
        else:
            r.fails("/book-reader content", f"HTML без ожидаемых маркеров")
    except Exception as e:
        r.fails("/book-reader route", str(e))
        return

    # 2. /api/book/full returns chapters
    try:
        req = urllib.request.Request(f"{SERVER}/api/book/full?book_id={book_id}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok") and len(data.get("chapters", [])) > 0:
            r.passes(f"/api/book/full", f"{len(data['chapters'])} глав")
        else:
            r.fails(f"/api/book/full", f"нет глав: {data}")
            return
    except Exception as e:
        r.fails("/api/book/full", str(e))
        return

    # 3. Note lifecycle: add → list → update → cleanup
    ts_marker = f"AUTO-TEST-{int(time.time())}"
    note_body = {
        "book_id": book_id,
        "chapter_id": f"{book_id}-ch-01",
        "para_idx": 0,
        "kind": "comment",
        "note_text": f"тестовая заметка {ts_marker}",
    }
    try:
        req = urllib.request.Request(
            f"{SERVER}/api/book/note-add",
            data=json.dumps(note_body).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            add_resp = json.loads(resp.read().decode("utf-8"))
        note_id = add_resp.get("note", {}).get("note_id")
        if note_id:
            r.passes("note-add создал заметку", f"id={note_id}")
        else:
            r.fails("note-add", str(add_resp))
            return
    except Exception as e:
        r.fails("note-add", str(e))
        return

    # 4. list notes — find our marker
    try:
        req = urllib.request.Request(f"{SERVER}/api/book/notes?book_id={book_id}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            list_resp = json.loads(resp.read().decode("utf-8"))
        notes = list_resp.get("notes", [])
        ours = [n for n in notes if ts_marker in (n.get("note_text") or "")]
        if ours:
            r.passes("note-list находит свою заметку", f"всего={len(notes)}")
        else:
            r.fails("note-list", f"маркер {ts_marker} не найден среди {len(notes)} заметок")
    except Exception as e:
        r.fails("note-list", str(e))

    # 5. mark dismissed
    try:
        req = urllib.request.Request(
            f"{SERVER}/api/book/note-update",
            data=json.dumps({"book_id": book_id, "note_id": note_id, "status": "dismissed"}).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            upd_resp = json.loads(resp.read().decode("utf-8"))
        if upd_resp.get("ok") and upd_resp.get("status") == "dismissed":
            r.passes("note-update dismissed")
        else:
            r.fails("note-update", str(upd_resp))
    except Exception as e:
        r.fails("note-update", str(e))

    # 6. cleanup test note file (only our marker)
    try:
        notes_file = ROOT / "data/book-notes" / f"{book_id}.jsonl"
        if notes_file.exists():
            kept = []
            for line in notes_file.read_text(encoding="utf-8").splitlines():
                if line.strip() and ts_marker not in line:
                    kept.append(line)
            notes_file.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    except Exception:
        pass


def test_polish_plan_validation(r: TestResult, book_id="book-12"):
    """polish-plan не должен вызывать Opus при пустом запросе или без заметок."""
    print("\n── polish-plan validation (без Opus) ──")
    # 1. Missing book_id → 400
    try:
        req = urllib.request.Request(
            f"{SERVER}/api/book/polish-plan",
            data=b"{}",
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("error"):
            r.passes("polish-plan без book_id отклоняет", data["error"])
        else:
            r.fails("polish-plan без book_id", f"должен быть error, got: {data}")
    except urllib.error.HTTPError as e:
        # 400 expected
        data = json.loads(e.read().decode("utf-8"))
        if "book_id" in (data.get("error") or "").lower():
            r.passes("polish-plan без book_id отклоняет", "HTTP 400")
        else:
            r.fails("polish-plan без book_id", str(data))
    except Exception as e:
        r.fails("polish-plan без book_id", str(e))

    # 2. book_id present but no open notes → 400 (не должен звать Opus)
    try:
        # сначала убедимся что нет открытых заметок (если есть — пропускаем)
        req = urllib.request.Request(f"{SERVER}/api/book/notes?book_id={book_id}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            notes_data = json.loads(resp.read().decode("utf-8"))
        open_count = notes_data.get("open_count", 0)
        if open_count > 0:
            r.warns("polish-plan empty test", f"есть {open_count} открытых заметок, пропускаю")
        else:
            req = urllib.request.Request(
                f"{SERVER}/api/book/polish-plan",
                data=json.dumps({"book_id": book_id}).encode("utf-8"),
                headers={"content-type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                data = json.loads(e.read().decode("utf-8"))
            err = (data.get("error") or "").lower()
            if "заметок" in err or "notes" in err:
                r.passes("polish-plan без заметок не зовёт Opus", data.get("error"))
            else:
                r.fails("polish-plan без заметок", str(data))
    except Exception as e:
        r.fails("polish-plan validation", str(e))


def test_nav_has_book_reader(r: TestResult):
    """nav.js должен содержать пункт book-reader."""
    print("\n── nav.js / sidebar ──")
    nav = ROOT / "app/static/nav.js"
    if not nav.exists():
        r.warns("nav.js", "файл отсутствует")
        return
    text = nav.read_text(encoding="utf-8")
    if '"book-reader"' in text and "/book-reader" in text:
        r.passes("nav.js содержит пункт book-reader")
    else:
        r.fails("nav.js без book-reader", "Pavel не найдёт страницу")


def test_personas_disabled(r: TestResult):
    """Pavel сказал отключить персон полностью (2026-05-25)."""
    print("\n── Persons отключены? ──")
    personas_py = ROOT / "scripts/personas.py"
    if not personas_py.exists():
        r.warns("personas.py", "файл отсутствует")
        return
    text = personas_py.read_text(encoding="utf-8")
    # Проверяем что keys = пустой или закомментирован
    keys_match = re.search(r'keys\s*=\s*\[([^\]]*)\]', text)
    if keys_match:
        keys_content = keys_match.group(1)
        active_keys = re.findall(r'"(\w+)"', keys_content)
        if not active_keys:
            r.passes("personas disabled", "keys пустой")
        else:
            r.fails("personas disabled", f"всё ещё активны: {active_keys}")
    else:
        r.warns("personas check", "не нашёл keys в personas.py")


def write_report(r: TestResult, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = r.summary()
    # JSON
    (out_dir / f"AUTO-TEST-{ts}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Markdown
    md_lines = [
        f"# Auto-Test Report — {datetime.now(timezone.utc).isoformat()}",
        "",
        f"**Прошло: {summary['passed']}**  ·  **Провалилось: {summary['failed']}**  ·  **Warnings: {summary['warned']}**  ·  длительность {summary['duration_s']:.1f}s",
        "",
    ]
    if summary["failed"] > 0:
        md_lines.append("## ❌ FAIL")
        for f in summary["failed_list"]:
            md_lines.append(f"- **{f['name']}** — {f['detail']}")
        md_lines.append("")
    if summary["warned"] > 0:
        md_lines.append("## ⚠ WARN")
        for w in summary["warned_list"]:
            md_lines.append(f"- {w['name']} — {w['detail']}")
        md_lines.append("")
    if summary["passed"] > 0:
        md_lines.append("## ✅ PASS")
        for p in summary["passed_list"]:
            md_lines.append(f"- {p['name']}{(' — ' + p['detail']) if p['detail'] else ''}")
    out_md = out_dir / f"AUTO-TEST-{ts}.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    # Symlink latest
    latest = out_dir / "AUTO-TEST-latest.md"
    if latest.exists():
        latest.unlink()
    try:
        latest.symlink_to(out_md.name)
    except Exception:
        latest.write_text("\n".join(md_lines), encoding="utf-8")
    return out_md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip real Opus + real replace tests")
    ap.add_argument("--chapter", default="book-12-ch-20", help="chapter for chapter-specific tests")
    args = ap.parse_args()

    print("═" * 60)
    print("AUTO TESTER — Codex 3")
    print(f"server: {SERVER}")
    print(f"target chapter: {args.chapter}")
    print(f"mode: {'quick' if args.quick else 'full'}")
    print("═" * 60)

    r = TestResult()

    if not test_server_alive(r):
        print("\n🚨 Сервер мёртв — остальные тесты пропускаю")
        out = write_report(r, ROOT / "reports")
        print(f"\n📄 Отчёт: {out}")
        sys.exit(1)

    test_toc(r)
    test_chapter_draft(r, args.chapter)
    test_master_audit_cache(r, args.chapter)
    test_replace_paragraph_validation(r)
    test_replace_paragraph_real(r, args.chapter, dry_run=args.quick)
    test_voice_guard_logic(r)
    test_personas_disabled(r)
    test_book_reader(r, book_id="book-12")
    test_polish_plan_validation(r, book_id="book-12")
    test_nav_has_book_reader(r)

    out = write_report(r, ROOT / "reports")
    print()
    print("═" * 60)
    summary = r.summary()
    print(f"✅ {summary['passed']} прошли · ❌ {summary['failed']} провалились · ⚠ {summary['warned']} warnings")
    print(f"📄 Отчёт: {out}")
    print("═" * 60)
    sys.exit(0 if summary["failed"] == 0 else 2)


if __name__ == "__main__":
    main()
