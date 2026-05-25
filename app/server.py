#!/usr/bin/env python3
"""Codex v2 — minimal stdlib HTTP server.

Port 7788. Serves /static, exposes /api/health and /api/toc.
Keep this file under 300 lines. If it grows past that, split into modules.
"""

import http.server
import json
import os
import socketserver
from pathlib import Path

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DATA_ROOT = ROOT.parent
TOC_PATH = DATA_ROOT / "toc.json"
PORT = 7788

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class CodexV2Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.split("?", 1)[0]

        # UC-75: Critics
        if path == "/api/critics":
            return self._critics_save()
        if path == "/api/critics/reset":
            return self._critics_reset()
        if path == "/api/critics/run":
            return self._critics_run()
        # UC-115: запуск 5 personas-современников (Маск/Тиль/Роган/Хуберман/Огилви)
        if path == "/api/personas/run":
            return self._personas_run()

        # UC-124: запустить reconciler — синхронно через Opus
        if path == "/api/editor/reconcile":
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception as e:
                return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
            chapter_id = req.get("chapter_id")
            if not chapter_id:
                return self._json({"ok": False, "error": "chapter_id required"}, 400)
            try:
                # Сначала получаем full-analysis (без HTTP — прямой вызов helper)
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                if "reconciler" in _sys.modules:
                    del _sys.modules["reconciler"]
                from reconciler import reconcile as _reconcile
                # Используем self._editor_full_analysis-like логику
                # Простой путь — поднимаем результат full-analysis вручную
                import urllib.request as _ur
                with _ur.urlopen(f"http://127.0.0.1:7788/api/editor/full-analysis?chapter_id={chapter_id}", timeout=30) as resp:
                    fa = json.loads(resp.read().decode("utf-8"))
                result = _reconcile(chapter_id, fa, force=bool(req.get("force")))
                return self._json(result)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        # UC-125: запустить sequence analyzer (анализ последовательности параграфов)
        if path == "/api/editor/sequence":
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception as e:
                return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
            chapter_id = req.get("chapter_id")
            if not chapter_id:
                return self._json({"ok": False, "error": "chapter_id required"}, 400)
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                if "sequence_analyzer" in _sys.modules:
                    del _sys.modules["sequence_analyzer"]
                from sequence_analyzer import analyze as _seq_analyze
                return self._json(_seq_analyze(chapter_id, force=bool(req.get("force"))))
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        # UC-119: editor-журналист — Q&A после галочек
        if path == "/api/editor/journalist/start":
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
            chapter_id = req.get("chapter_id")
            fixes = req.get("fixes") or []
            if not chapter_id:
                return self._json({"ok": False, "error": "chapter_id required"}, 400)
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                # reimport чтобы подцепить свежий код
                if "editor_journalist" in _sys.modules:
                    del _sys.modules["editor_journalist"]
                from editor_journalist import start_session as _ej_start
                return self._json(_ej_start(chapter_id, fixes))
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        if path == "/api/editor/journalist/answer":
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
            session_id = (req.get("session_id") or "").strip()
            answer = (req.get("answer") or "").strip()
            skip = bool(req.get("skip"))
            if not session_id:
                return self._json({"ok": False, "error": "session_id required"}, 400)
            if not skip and not answer:
                return self._json({"ok": False, "error": "answer required (or skip=true)"}, 400)
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                if "editor_journalist" in _sys.modules:
                    del _sys.modules["editor_journalist"]
                from editor_journalist import answer as _ej_answer
                return self._json(_ej_answer(session_id, answer, skip=skip))
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        # UC-123: сохранить пороги качества
        if path == "/api/quality-config/save":
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
            qf = DATA_ROOT / "data/quality-config.json"
            qf.parent.mkdir(parents=True, exist_ok=True)
            qf.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._json({"ok": True, "saved": True})

        # UC-116: сохранить стили
        if path == "/api/styles/save":
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
            if not isinstance(req, dict):
                return self._json({"ok": False, "error": "expected object"}, 400)
            sf = DATA_ROOT / "data/styles.json"
            sf.parent.mkdir(parents=True, exist_ok=True)
            # Простая валидация: rules + examples массивы
            payload = {
                "rules": req.get("rules") or [],
                "examples": req.get("examples") or [],
                "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            sf.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._json({"ok": True, "saved": True, "rules_count": len(payload["rules"]), "examples_count": len(payload["examples"])})

        # UC-81: Book Editor
        if path == "/api/book-editor/config":
            return self._book_editor_save()
        if path == "/api/book-editor/run":
            return self._book_editor_run()

        # UC-90: Журналист
        # UC-96 Library POST endpoints
        if path == "/api/library/upload":
            return self._library_upload()
        if path == "/api/library/analyze":
            return self._library_analyze()
        if path == "/api/library/import-codex-ustav":
            return self._library_import_ustav()
        if path == "/api/library/delete":
            return self._library_delete()

        if path == "/api/journalist/start":
            return self._journalist_start()
        if path == "/api/journalist/answer":
            return self._journalist_answer()

        # UC-91: Критики-Q&A
        if path == "/api/critics-qa/start":
            return self._critics_qa_start()
        if path == "/api/critics-qa/answer":
            return self._critics_qa_answer()

        if path == "/api/edit/stream":
            return self._stream_edit()

        if path == "/api/paragraph/analyze":
            return self._paragraph_analyze()

        if path == "/api/paragraph/rewrite":
            return self._paragraph_rewrite()

        if path == "/api/paragraph/honest-critic":
            return self._honest_critic()

        if path == "/api/chapter/density-analysis":
            return self._density_analysis()

        if path == "/api/chapter/style-coherence":
            return self._style_coherence_analysis()

        if path == "/api/chapter/logic-analysis":
            return self._logic_analysis()
        if path == "/api/chapter/resonance":
            return self._resonance_analysis()
        if path == "/api/chapter/hook-cliff":
            return self._hook_cliff_analysis()
        if path == "/api/chapter/super-rewrite":
            return self._super_rewrite()
        # ФАЗА 3 (2026-05-24): Мастер-аудитор — один Opus, 3-5 правок, голос Pavel-а в substrate
        if path == "/api/chapter/master-audit":
            return self._master_audit()
        # Pavel 2026-05-25 «страница не нужна, работа идёт на сервере»:
        # async start — возвращает СРАЗУ {ok, job_id}, Opus в отдельном треде.
        if path == "/api/chapter/master-audit-start":
            return self._master_audit_start()
        # Master refine — улучшить одну правку Мастера с комментарием Pavel-а
        if path == "/api/chapter/master-audit/refine":
            return self._master_audit_refine()
        # CODEX 3 (2026-05-24): Paragraph Writer — AI пишет один параграф из тезиса + цитат Pavel-а
        if path == "/api/chapter/write-paragraph":
            return self._write_paragraph()
        # CODEX 3: вставка параграфа в draft.md после approval/edit
        if path == "/api/chapter/insert-paragraph":
            return self._insert_paragraph()
        # Прямая замена параграфа (используется master-audit Apply, без Opus)
        if path == "/api/chapter/replace-paragraph":
            return self._replace_paragraph()
        # Pavel 2026-05-25: после правок сверить с оригиналом + голосовыми
        if path == "/api/chapter/post-edit-audit":
            return self._post_edit_audit()
        # Откат всей главы к baseline
        if path == "/api/chapter/revert":
            return self._revert_chapter()
        # Book reader + finalize: заметки на параграф + Opus план полировки
        if path == "/api/book/note-add":
            return self._book_note_add()
        if path == "/api/book/note-update":
            return self._book_note_update()
        if path == "/api/book/polish-plan":
            return self._book_polish_plan()
        if path == "/api/briefing/regenerate":
            """POST → пересоздать MORNING-BRIEFING.md прямо сейчас."""
            import subprocess
            try:
                subprocess.run(["python3", str(ROOT.parent / "scripts/morning_briefing.py")],
                               timeout=180, capture_output=True)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)
        if path == "/api/wizard/ask-questions":
            return self._wizard_ask_questions()
        if path == "/api/wizard/cross-check":
            return self._wizard_cross_check()
        if path == "/api/wizard/generate-draft":
            return self._wizard_generate_draft()
        if path == "/api/wizard/state":
            return self._wizard_state_save()

        if path == "/api/chapter/full-diagnostics":
            return self._full_diagnostics()

        if path == "/api/chapter/summary":
            return self._chapter_summary()

        if path == "/api/chapter/council":
            return self._chapter_council()

        if path == "/api/chapter/apply-fixes":
            return self._chapter_apply_fixes()

        if path == "/api/chapter/stream-suggestions":
            return self._stream_suggestions()

        if path == "/api/pavel-action":
            return self._track_pavel_action()

        if path.startswith("/api/chapter/"):
            parts = path[len("/api/chapter/"):].split("/")
            if len(parts) >= 2:
                return self._chapter_post(parts[0], parts[1])

        if path == "/api/recommendations/regenerate":
            import subprocess
            script = ROOT.parent / "scripts/daily_recommendations.py"
            if not script.exists():
                return self._json({"ok": False, "error": "скрипт не найден"}, 500)
            try:
                log_file = ROOT.parent / ".codex/daily-recs-gen.log"
                with log_file.open("w") as logf:
                    proc = subprocess.Popen(
                        ["python3", str(script)],
                        stdout=logf, stderr=subprocess.STDOUT,
                        cwd=str(ROOT.parent),
                        start_new_session=True,
                    )
                return self._json({"ok": True, "started": True, "pid": proc.pid})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        if path == "/api/morning-plan/regenerate":
            # Async: запускаем в фоне через nohup, возвращаем сразу.
            # Клиент будет polling-ом проверять mtime через GET /api/morning-plan.
            import subprocess
            script = ROOT.parent / "scripts/morning_plan_generator.py"
            if not script.exists():
                return self._json({"ok": False, "error": "генератор не найден"}, 500)
            # Маркерный pid-файл — чтобы узнать что генератор работает
            pid_file = ROOT.parent / ".codex/morning-plan-gen.pid"
            log_file = ROOT.parent / ".codex/morning-plan-gen.log"
            # Если уже работает — не дублируем
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)  # alive check
                    return self._json({"ok": True, "started": False, "already_running": True, "pid": pid})
                except (ValueError, ProcessLookupError, OSError):
                    pid_file.unlink(missing_ok=True)
            try:
                with log_file.open("w") as logf:
                    proc = subprocess.Popen(
                        ["nohup", "python3", str(script)],
                        stdout=logf, stderr=subprocess.STDOUT,
                        cwd=str(ROOT.parent),
                        start_new_session=True,
                    )
                pid_file.write_text(str(proc.pid))
                return self._json({"ok": True, "started": True, "pid": proc.pid,
                                   "message": "Запущено в фоне. Polling /api/morning-plan покажет обновление через 60-180 сек."})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        if path == "/api/morning-plan/status":
            pid_file = ROOT.parent / ".codex/morning-plan-gen.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    return self._json({"running": True, "pid": pid})
                except (ValueError, ProcessLookupError, OSError):
                    pid_file.unlink(missing_ok=True)
            return self._json({"running": False})

        return self._error(404, "Not found")

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            return self._serve_file(STATIC / "index.html", "text/html; charset=utf-8")

        if path in ("/components", "/components.html"):
            return self._serve_file(STATIC / "components.html", "text/html; charset=utf-8")

        if path in ("/morning-plan", "/morning-plan.html"):
            return self._serve_file(STATIC / "morning-plan.html", "text/html; charset=utf-8")

        if path in ("/editor", "/editor.html"):
            return self._serve_file(STATIC / "editor.html", "text/html; charset=utf-8")

        if path in ("/recommendations", "/recommendations.html"):
            return self._serve_file(STATIC / "recommendations.html", "text/html; charset=utf-8")

        if path in ("/storage", "/storage.html"):
            return self._serve_file(STATIC / "storage.html", "text/html; charset=utf-8")

        if path in ("/wizard", "/wizard.html"):
            return self._serve_file(STATIC / "wizard.html", "text/html; charset=utf-8")

        if path in ("/briefing", "/briefing.html"):
            return self._serve_file(STATIC / "briefing.html", "text/html; charset=utf-8")

        if path in ("/critics", "/critics.html"):
            return self._serve_file(STATIC / "critics.html", "text/html; charset=utf-8")

        if path in ("/book-editor", "/book-editor.html"):
            return self._serve_file(STATIC / "book-editor.html", "text/html; charset=utf-8")

        if path in ("/book-reader", "/book-reader.html"):
            return self._serve_file(STATIC / "book-reader.html", "text/html; charset=utf-8")

        if path in ("/journalist", "/journalist.html"):
            return self._serve_file(STATIC / "journalist.html", "text/html; charset=utf-8")

        if path in ("/library", "/library.html"):
            return self._serve_file(STATIC / "library.html", "text/html; charset=utf-8")

        if path in ("/styles", "/styles.html"):
            return self._serve_file(STATIC / "styles.html", "text/html; charset=utf-8")

        if path.startswith("/read/"):
            """GET /read/<chapter_id> → красивый HTML финальной версии главы для чтения."""
            import html as _h, re as _re
            chapter_id = path[len("/read/"):].split("?")[0].rstrip("/")
            m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
            if not m:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Bad chapter_id: {chapter_id}".encode("utf-8"))
                return
            book_id = m.group(1)
            ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
            final_file = ch_dir / "finalized.md"
            draft_file = ch_dir / "draft.md"
            source_file = final_file if final_file.exists() else draft_file
            if not source_file.exists():
                # UC-105: дружелюбный fallback вместо 404 plain text
                import html as _h
                # пробуем достать title из meta.json
                meta_file = ch_dir / "meta.json"
                title = chapter_id
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        title = meta.get("title") or title
                    except Exception:
                        pass
                empty_page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>{_h.escape(chapter_id)}</title>
<link rel="stylesheet" href="/static/tokens.css"><link rel="stylesheet" href="/static/style.css">
<style>
body {{ font-family: 'Inter', -apple-system, sans-serif; background: var(--color-bg-app); }}
.empty-read {{ max-width: 560px; margin: 80px auto; padding: 48px 32px; background: var(--color-card); border: 1px solid var(--color-card-border); border-radius: 12px; text-align: center; }}
.empty-read h1 {{ font-size: 22px; margin: 0 0 12px; color: var(--color-text); font-weight: 600; }}
.empty-read p {{ color: var(--color-text-muted); line-height: 1.6; margin: 0 0 20px; }}
.empty-read .id {{ font-family: var(--font-mono, monospace); font-size: 12px; color: var(--color-text-muted); margin-bottom: 24px; }}
.empty-read .actions {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-top: 24px; }}
.empty-read a {{ display: inline-flex; align-items: center; padding: 8px 16px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 500; }}
.empty-read a.primary {{ background: #6366F1; color: white; }}
.empty-read a.secondary {{ background: var(--color-bg-app); color: var(--color-text); border: 1px solid var(--color-border); }}
</style></head><body>
<div class="empty-read">
  <h1>{_h.escape(title)}</h1>
  <div class="id">{_h.escape(chapter_id)}</div>
  <p>В этой главе пока нет текста. Её можно начать через «Новую главу» (Журналист → Совет старейшин → Opus напишет) или открыть редактор и наговорить материал.</p>
  <div class="actions">
    <a href="/wizard?topic={_h.escape(title)}" class="primary">Начать с Журналистом</a>
    <a href="/editor?chapter={_h.escape(chapter_id)}" class="secondary">Открыть в редакторе</a>
    <a href="/" class="secondary">← Оглавление</a>
  </div>
</div>
</body></html>"""
                body_bytes = empty_page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body_bytes)
                return
            is_final = source_file == final_file
            text = source_file.read_text(encoding="utf-8")
            esc = _h.escape
            html_body = []
            for chunk in text.split("\n\n"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if chunk.startswith("### "):
                    html_body.append(f"<h3>{esc(chunk[4:].strip())}</h3>")
                elif chunk.startswith("## "):
                    html_body.append(f"<h2>{esc(chunk[3:].strip())}</h2>")
                elif chunk.startswith("# "):
                    html_body.append(f"<h1>{esc(chunk[2:].strip())}</h1>")
                else:
                    html_body.append(f"<p>{esc(chunk)}</p>")
            status_badge = '<span class="read-status final">Финальная версия</span>' if is_final else '<span class="read-status draft">Черновик · не финализирована</span>'
            page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>{esc(chapter_id)}</title>
<link rel="stylesheet" href="/static/tokens.css"><link rel="stylesheet" href="/static/style.css">
<style>
.read-container {{ max-width: 760px; margin: 0 auto; padding: 56px 32px 80px; font-family: 'Charter', 'Georgia', serif; color: var(--color-text); line-height: 1.75; font-size: 19px; }}
.read-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; padding-bottom: 16px; border-bottom: 1px solid var(--color-card-border); }}
.read-header a {{ color: var(--color-text-2); text-decoration: none; font-family: var(--font-sans); font-size: 13px; }}
.read-status {{ font-family: var(--font-sans); font-size: 11px; padding: 4px 10px; border-radius: 999px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }}
.read-status.final {{ background: var(--color-success-bg); color: var(--color-success); }}
.read-status.draft {{ background: var(--color-bg); color: var(--color-text-3); }}
.read-container h1 {{ font-size: 32px; font-weight: 700; line-height: 1.25; margin: 0 0 8px; letter-spacing: -0.02em; }}
.read-container h2 {{ font-size: 24px; font-weight: 700; line-height: 1.3; margin: 40px 0 12px; letter-spacing: -0.015em; }}
.read-container h3 {{ font-size: 18px; font-weight: 600; line-height: 1.35; margin: 28px 0 8px; }}
.read-container p {{ margin: 0 0 20px; }}
.read-actions {{ font-family: var(--font-sans); margin-top: 48px; padding-top: 24px; border-top: 1px solid var(--color-card-border); display: flex; gap: 12px; }}
@media print {{ .read-header, .read-actions {{ display: none; }} .read-container {{ padding: 0; }} }}
</style></head><body>
<div class="read-container">
  <div class="read-header">
    <a href="/">← Оглавление</a>
    {status_badge}
  </div>
  {''.join(html_body)}
  <div class="read-actions">
    <a href="/editor?chapter={chapter_id}" class="btn btn-secondary btn-sm">Открыть в редакторе</a>
    <button class="btn btn-ghost btn-sm" onclick="window.print()">Распечатать / PDF</button>
  </div>
</div></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        if path == "/api/briefing":
            """GET → содержимое MORNING-BRIEFING.md (UC-37 Pavel 2026-05-20).
            UC-72: добавлена мета (модель/токены) для <details> блока."""
            f = DATA_ROOT / "reports/MORNING-BRIEFING.md"
            if not f.exists():
                return self._json({"exists": False, "message": "MORNING-BRIEFING.md не создан. Запусти scripts/morning_briefing.py"})
            stat = f.stat()
            from datetime import datetime as _dt
            # Мета от morning_plan_generator (если есть)
            meta_file = DATA_ROOT / "reports/MORNING-PLAN.meta.json"
            tech_meta = None
            if meta_file.exists():
                try:
                    tech_meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return self._json({
                "exists": True,
                "content": f.read_text(encoding="utf-8"),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mtime_human": _dt.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "tech_meta": tech_meta,
            })

        if path == "/api/heartbeat":
            """GET → когда последний раз сработал idle_keeper. Pavel видит что система живая."""
            hb_file = DATA_ROOT / ".codex/heartbeat.json"
            if not hb_file.exists():
                return self._json({"alive": False, "message": "heartbeat ещё не создан"})
            try:
                hb = json.loads(hb_file.read_text(encoding="utf-8"))
                from datetime import datetime as _dt, timezone as _tz
                last = _dt.fromisoformat(hb["last_run"].rstrip("Z")).replace(tzinfo=_tz.utc)
                age_sec = (_dt.now(_tz.utc) - last).total_seconds()
                return self._json({
                    "alive": age_sec < 900,  # < 15 минут — норма
                    "age_sec": round(age_sec),
                    "age_human": f"{int(age_sec // 60)} мин {int(age_sec % 60)} сек назад",
                    **hb,
                })
            except Exception as e:
                return self._json({"alive": False, "error": str(e)})

        if path == "/api/recommendations":
            recs = DATA_ROOT / "reports/DAILY-RECOMMENDATIONS-TODAY.md"
            if not recs.exists():
                return self._json({"exists": False, "message": "Запусти daily_recommendations.py"})
            stat = recs.stat()
            return self._json({"exists": True, "content": recs.read_text(encoding="utf-8"), "size": stat.st_size, "mtime": stat.st_mtime})

        if path.startswith("/api/chapter/"):
            # /api/chapter/<id>/draft or /lost-meanings or /similar
            parts = path[len("/api/chapter/"):].split("/")
            if len(parts) >= 2:
                chapter_id = parts[0]
                action = parts[1]
                return self._chapter_endpoint(chapter_id, action)

        if path == "/api/chapters-status":
            """Список finalized глав для TOC «Готовые тексты»"""
            chapters_root = DATA_ROOT / "chapters"
            finalized = []
            if chapters_root.exists():
                for book_dir in chapters_root.iterdir():
                    if not book_dir.is_dir() or book_dir.name.startswith("."):
                        continue
                    for ch_dir in book_dir.iterdir():
                        if not ch_dir.is_dir():
                            continue
                        status_file = ch_dir / "status.json"
                        if status_file.exists():
                            try:
                                status = json.loads(status_file.read_text(encoding="utf-8"))
                                if status.get("status") == "finalized":
                                    finalized.append({
                                        "chapter_id": ch_dir.name,
                                        "book_id": book_dir.name,
                                        "finalized_at": status.get("finalized_at"),
                                        "paragraphs": status.get("paragraphs"),
                                    })
                            except json.JSONDecodeError:
                                pass
            finalized.sort(key=lambda x: x.get("finalized_at", ""), reverse=True)
            return self._json({"finalized": finalized, "count": len(finalized)})

        if path == "/api/morning-plan":
            plan = DATA_ROOT / "reports/MORNING-PLAN.md"
            if not plan.exists():
                return self._json({"exists": False, "content": "", "message": "MORNING-PLAN.md ещё не сгенерирован"})
            stat = plan.stat()
            return self._json({
                "exists": True,
                "content": plan.read_text(encoding="utf-8"),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })

        if path.startswith("/static/"):
            rel = path[len("/static/"):].lstrip("/")
            file_path = (STATIC / rel).resolve()
            try:
                file_path.relative_to(STATIC.resolve())
            except ValueError:
                return self._error(403, "Forbidden")
            return self._serve_file(file_path, MIME.get(file_path.suffix, "application/octet-stream"))

        if path == "/api/health":
            return self._json({"status": "ok", "version": "codex-v2-0.1", "port": PORT})

        if path == "/api/book-editor/eligible-chapters":
            """UC-88 (Pavel 2026-05-21): «в Редактор Книги попадают только КНИГИ
            у которых ВСЕ главы обработаны критиками». Book-level filter,
            не chapter-level."""
            from datetime import datetime as _dt
            book_meta = {}  # bid → {title, chapters: [{id, number, title}]}
            book_order = []
            try:
                toc_paths = [DATA_ROOT / "toc.json", DATA_ROOT / "data/toc.json"]
                toc_file = next((p for p in toc_paths if p.exists()), None)
                if toc_file:
                    toc = json.loads(toc_file.read_text(encoding="utf-8"))
                    for book in toc.get("books", []):
                        bid = book.get("id")
                        # Пропускаем reference-книги (Устав), они не идут в book-editor
                        if book.get("status") == "reference":
                            continue
                        if book.get("uses_canon") is False:
                            continue
                        chapters_meta = []
                        for ch in book.get("chapters", []):
                            chapters_meta.append({
                                "id": ch.get("id"),
                                "title": ch.get("title") or ch.get("title_clean"),
                                "number": ch.get("number"),
                            })
                        if not chapters_meta:
                            continue  # пустые книги пропускаем
                        book_order.append(bid)
                        book_meta[bid] = {
                            "title": book.get("title_clean") or book.get("title"),
                            "chapters": chapters_meta,
                        }
            except Exception:
                pass
            # Собираем CRITICS отчёты per chapter
            critics_by_chapter = {}  # chapter_id → {ts, score, ts_human}
            reports_dir = DATA_ROOT / "reports"
            if reports_dir.exists():
                for f in sorted(reports_dir.glob("CRITICS-*.json")):
                    name = f.stem
                    parts = name[len("CRITICS-"):].rsplit("-", 1)
                    if len(parts) != 2:
                        continue
                    chapter_id, ts = parts
                    score = None
                    try:
                        rep = json.loads(f.read_text(encoding="utf-8"))
                        synth = rep.get("results", {}).get("synthesis", {})
                        synth_result = synth.get("result", {}) if isinstance(synth, dict) else {}
                        if isinstance(synth_result, dict):
                            score = synth_result.get("final_score")
                    except Exception:
                        pass
                    ts_human = None
                    try:
                        ts_human = _dt.strptime(ts, "%Y%m%dT%H%M%S").strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pass
                    existing = critics_by_chapter.get(chapter_id)
                    if existing is None or existing.get("ts", "") < ts:
                        critics_by_chapter[chapter_id] = {
                            "ts": ts, "score": score, "ts_human": ts_human,
                        }
            # Фильтр: только книги, где ВСЕ главы имеют CRITICS отчёт
            books_out = []
            for bid in book_order:
                meta = book_meta[bid]
                chapters_meta = meta["chapters"]
                chapter_ids = [ch["id"] for ch in chapters_meta]
                missing = [cid for cid in chapter_ids if cid not in critics_by_chapter]
                if missing:
                    continue  # не все главы обработаны → книга не показывается
                # Все главы обработаны → собрать данные
                chapters_out = []
                for ch in chapters_meta:
                    cdata = critics_by_chapter.get(ch["id"], {})
                    chapters_out.append({
                        "chapter_id": ch["id"],
                        "title": ch["title"],
                        "number": ch["number"],
                        "last_critique_at": cdata.get("ts_human"),
                        "last_score": cdata.get("score"),
                    })
                chapters_out.sort(key=lambda c: c.get("number") or 0)
                books_out.append({
                    "book_id": bid,
                    "book_title": meta["title"],
                    "chapters": chapters_out,
                    "chapter_count": len(chapters_out),
                })
            # Добавим список книг которые ПОЧТИ готовы (для UI: «осталось N глав»)
            books_partial = []
            for bid in book_order:
                meta = book_meta[bid]
                chapter_ids = [ch["id"] for ch in meta["chapters"]]
                if not chapter_ids:
                    continue
                done = [cid for cid in chapter_ids if cid in critics_by_chapter]
                if 0 < len(done) < len(chapter_ids):
                    books_partial.append({
                        "book_id": bid,
                        "book_title": meta["title"],
                        "done_count": len(done),
                        "total_count": len(chapter_ids),
                        "missing": [cid for cid in chapter_ids if cid not in critics_by_chapter],
                    })
            return self._json({"books": books_out, "partial": books_partial})

        if path == "/api/book-editor/config":
            """UC-81 GET → config 5 ботов Редактора Книги."""
            cfg_file = DATA_ROOT / "data/book-editors-config.json"
            if cfg_file.exists():
                try:
                    return self._json(json.loads(cfg_file.read_text(encoding="utf-8")))
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                from book_editor import DEFAULT_BOOK_EDITORS
                return self._json(DEFAULT_BOOK_EDITORS)
            except Exception as e:
                return self._json({"error": f"defaults load failed: {e}"}, 500)

        if path == "/api/book-editor/sessions":
            """UC-81 GET → список всех сессий Редактора Книги."""
            sessions_dir = DATA_ROOT / "data/book-editor-sessions"
            if not sessions_dir.exists():
                return self._json({"sessions": []})
            sessions = []
            for f in sorted(sessions_dir.glob("*.json"), reverse=True)[:50]:
                try:
                    s = json.loads(f.read_text(encoding="utf-8"))
                    synth = s.get("results", {}).get("book_synthesis", {})
                    synth_result = synth.get("result", {}) if isinstance(synth, dict) else {}
                    sessions.append({
                        "session_id": s.get("session_id"),
                        "book_id": s.get("book_id"),
                        "book_title": s.get("book_title"),
                        "chapter_count": s.get("chapter_count"),
                        "ts": s.get("ts"),
                        "iteration": s.get("iteration", 1),
                        "book_overall_score": synth_result.get("book_overall_score") if isinstance(synth_result, dict) else None,
                    })
                except Exception:
                    continue
            return self._json({"sessions": sessions})

        if path.startswith("/api/book-editor/sessions/"):
            """UC-81 GET → одна сессия Редактора Книги по session_id."""
            session_id = path[len("/api/book-editor/sessions/"):]
            sessions_dir = DATA_ROOT / "data/book-editor-sessions"
            matches = list(sessions_dir.glob(f"*-{session_id}.json"))
            if not matches:
                return self._json({"error": "session not found"}, 404)
            try:
                return self._json(json.loads(matches[0].read_text(encoding="utf-8")))
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        # UC-90: Журналист
        if path == "/api/journalist/sessions":
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                from journalist import list_sessions
                return self._json({"sessions": list_sessions()})
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        # UC-96: Library files
        if path == "/api/library/files":
            return self._library_list()

        if path.startswith("/api/journalist/sessions/"):
            session_id = path[len("/api/journalist/sessions/"):]
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                from journalist import load_session, _session_for_ui
                s = load_session(session_id)
                if not s:
                    return self._json({"error": "session not found"}, 404)
                return self._json(_session_for_ui(s))
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        # UC-92: Wizard state (cross-device resume)
        if path.startswith("/api/wizard/state/"):
            wsid = path[len("/api/wizard/state/"):]
            return self._wizard_state_load(wsid)

        # UC-92: Critics report polling (read JSON after critic_council finished)
        if path == "/api/critics/report":
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            rel = (qs.get("path") or [""])[0]
            # UC-99: support ?chapter_id= → find latest CRITICS-<chapter>-*.json
            chapter_id = (qs.get("chapter_id") or [""])[0]
            if chapter_id and not rel:
                reports_dir = DATA_ROOT / "reports"
                if reports_dir.exists():
                    cands = sorted(reports_dir.glob(f"CRITICS-{chapter_id}-*.json"), reverse=True)
                    if cands:
                        try:
                            return self._json(json.loads(cands[0].read_text(encoding="utf-8")))
                        except Exception as e:
                            return self._json({"error": str(e)}, 500)
                return self._json({"error": "no report for chapter"}, 404)
            if not rel:
                return self._json({"error": "path required"}, 400)
            # Constrain to reports/ dir for safety
            rp = (DATA_ROOT / rel).resolve()
            reports_dir = (DATA_ROOT / "reports").resolve()
            try:
                rp.relative_to(reports_dir)
            except Exception:
                return self._json({"error": "path outside reports/"}, 400)
            if not rp.exists():
                return self._json({"error": "not ready"}, 404)
            try:
                return self._json(json.loads(rp.read_text(encoding="utf-8")))
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        # UC-91: Критики-Q&A
        if path == "/api/critics-qa/sessions":
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                from critics_qa import list_sessions as _cqa_list
                return self._json({"sessions": _cqa_list()})
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        if path.startswith("/api/critics-qa/sessions/"):
            session_id = path[len("/api/critics-qa/sessions/"):]
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                from critics_qa import load_session as _cqa_load, _session_for_ui as _cqa_ui
                s = _cqa_load(session_id)
                if not s:
                    return self._json({"error": "session not found"}, 404)
                return self._json(_cqa_ui(s))
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        if path == "/api/critics":
            """UC-75: GET → текущий config критиков из data/critics-config.json
            (либо defaults из scripts/critic_council.py)."""
            cfg_file = DATA_ROOT / "data/critics-config.json"
            if cfg_file.exists():
                try:
                    return self._json(json.loads(cfg_file.read_text(encoding="utf-8")))
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            # Fallback на defaults
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                from critic_council import DEFAULT_CRITICS
                return self._json(DEFAULT_CRITICS)
            except Exception as e:
                return self._json({"error": f"defaults load failed: {e}"}, 500)

        # UC-137: что сейчас крутится для этой главы и что недавно завершилось
        if path == "/api/jobs/active":
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            chapter_id = (qs.get("chapter_id") or [""])[0] or None
            active = self._active_jobs_list(chapter_id)
            recent_done = self._active_jobs_recent_done(chapter_id, since_minutes=30)
            return self._json({
                "ok": True,
                "chapter_id": chapter_id,
                "active": active,
                "recent_done": recent_done,
            })

        if path == "/api/critics/eligible-chapters":
            """UC-76 + UC-83 (Pavel 2026-05-21): возвращаем ВСЕ главы, но с пометкой is_eligible.
            Eligible = finalized.md существует ИЛИ iterations/ имеет минимум 1 версию ИЛИ draft.md есть.
            Pavel: «должен быть список глав» — показываем все, eligible активны, остальные disabled."""
            from datetime import datetime as _dt
            chapters = []
            chapters_root = DATA_ROOT / "chapters"
            title_map = {}
            number_map = {}
            book_title_map = {}
            try:
                # toc.json лежит в корне Codex2/, не в data/ (UC-84 fix)
                toc_paths = [DATA_ROOT / "toc.json", DATA_ROOT / "data/toc.json"]
                toc_file = next((p for p in toc_paths if p.exists()), None)
                if toc_file:
                    toc = json.loads(toc_file.read_text(encoding="utf-8"))
                    for book in toc.get("books", []):
                        book_title_map[book.get("id")] = book.get("title_clean") or book.get("title")
                        for ch in book.get("chapters", []):
                            title_map[ch.get("id")] = ch.get("title") or ch.get("title_clean")
                            number_map[ch.get("id")] = ch.get("number")
            except Exception:
                pass
            if chapters_root.exists():
                for book_dir in sorted(chapters_root.iterdir()):
                    if not book_dir.is_dir() or book_dir.name.startswith("."):
                        continue
                    for ch_dir in sorted(book_dir.iterdir()):
                        if not ch_dir.is_dir() or ch_dir.name.startswith("."):
                            continue
                        finalized = ch_dir / "finalized.md"
                        draft = ch_dir / "draft.md"
                        iter_dir = ch_dir / "iterations"
                        iter_versions = sorted(iter_dir.glob("v*.md")) if iter_dir.exists() else []
                        # UC-85 (Pavel revision 2026-05-21): «только пропущенные через редактор
                        # и предварительно проработанные». Сырые drafts не показываем.
                        has_draft = draft.exists()
                        history_dir = ch_dir / "history"
                        history_snapshots = list(history_dir.glob("*.md")) if history_dir.exists() else []
                        hidden_history_dir = ch_dir / ".history"
                        hidden_history_snapshots = list(hidden_history_dir.glob("*.md")) if hidden_history_dir.exists() else []
                        para_history = ch_dir / "paragraph-history.jsonl"
                        had_paragraph_edits = para_history.exists() and para_history.stat().st_size > 0
                        # Pavel: фильтр — нужна хотя бы одна из меток обработки
                        passed_through_editor = (
                            finalized.exists() or                  # явно финализировано
                            len(iter_versions) > 0 or              # прошло workshop
                            len(history_snapshots) > 0 or          # был rewrite (есть snapshot)
                            len(hidden_history_snapshots) > 0 or   # был save с историей
                            had_paragraph_edits                    # были per-paragraph правки
                        )
                        if not passed_through_editor:
                            continue  # пропускаем сырые/необработанные
                        is_eligible = True  # все попавшие сюда — eligible
                        not_ready_reason = None
                        # Метка как именно обработана (для UI)
                        processing_marks = []
                        if finalized.exists():
                            processing_marks.append("финализирована")
                        if len(iter_versions) > 0:
                            processing_marks.append(f"workshop {len(iter_versions)} итераций")
                        if len(history_snapshots) > 0 or len(hidden_history_snapshots) > 0:
                            total_snap = len(history_snapshots) + len(hidden_history_snapshots)
                            processing_marks.append(f"{total_snap} версий в истории")
                        if had_paragraph_edits:
                            processing_marks.append("есть правки параграфов")
                        # Find last critique report
                        last_critique = None
                        for f in (DATA_ROOT / "reports").glob(f"CRITICS-{ch_dir.name}-*.json"):
                            ts = f.stem.replace(f"CRITICS-{ch_dir.name}-", "")
                            if last_critique is None or ts > last_critique:
                                last_critique = ts
                        last_critique_human = None
                        last_score = None
                        if last_critique:
                            try:
                                last_critique_human = _dt.strptime(last_critique, "%Y%m%dT%H%M%S").strftime("%Y-%m-%d %H:%M")
                                # Read score from synthesis if available
                                report_file = (DATA_ROOT / "reports" / f"CRITICS-{ch_dir.name}-{last_critique}.json")
                                if report_file.exists():
                                    rep = json.loads(report_file.read_text(encoding="utf-8"))
                                    synth = rep.get("results", {}).get("synthesis", {})
                                    synth_result = synth.get("result", {}) if isinstance(synth, dict) else {}
                                    if isinstance(synth_result, dict):
                                        last_score = synth_result.get("final_score")
                            except Exception:
                                pass
                        chapters.append({
                            "chapter_id": ch_dir.name,
                            "title": title_map.get(ch_dir.name),
                            "number": number_map.get(ch_dir.name),
                            "book_title": book_title_map.get(book_dir.name),
                            "is_finalized": finalized.exists(),
                            "has_draft": has_draft,
                            "iterations_count": len(iter_versions),
                            "is_eligible": is_eligible,
                            "processing_marks": processing_marks,
                            "ready_status": (
                                "finalized" if finalized.exists()
                                else f"workshop ({len(iter_versions)} итераций)" if iter_versions
                                else "edited"
                            ),
                            "not_ready_reason": not_ready_reason,
                            "last_critique_at": last_critique_human,
                            "last_score": last_score,
                        })
            # Сортировка: finalized → iterations → draft → empty
            def sort_key(c):
                if c["is_finalized"]: return (0, c["chapter_id"])
                if c["iterations_count"] > 0: return (1, c["chapter_id"])
                if c["has_draft"]: return (2, c["chapter_id"])
                return (3, c["chapter_id"])
            chapters.sort(key=sort_key)
            return self._json({"chapters": chapters})

        if path == "/api/pavel-context/current":
            """GET → current page / chapter / section + N последних действий."""
            ctx_file = DATA_ROOT / ".codex/pavel-context.jsonl"
            if not ctx_file.exists():
                return self._json({"current": {}, "recent": []})
            entries = []
            # Читаем последние 200 строк
            try:
                with ctx_file.open("rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 50000))
                    raw = f.read().decode("utf-8", errors="ignore")
                for line in raw.splitlines()[-200:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass
            # Текущее состояние = последнее не-пустое значение поля
            current = {}
            for e in entries:
                if e.get("page"): current["page"] = e["page"]
                if e.get("chapter_id"): current["chapter_id"] = e["chapter_id"]
                if e.get("section"): current["section"] = e["section"]
                if e.get("paragraph_idx") is not None: current["paragraph_idx"] = e["paragraph_idx"]
                if e.get("selection"): current["last_selection"] = e["selection"][:200]
                current["last_action"] = e.get("action")
                current["last_ts"] = e.get("ts")
            # Recent — последние 15 значимых action
            recent = []
            for e in reversed(entries):
                if e.get("action") in ("page_view", "heartbeat"):
                    continue
                recent.append({
                    "ts": e.get("ts"),
                    "action": e.get("action"),
                    "chapter_id": e.get("chapter_id"),
                    "paragraph_idx": e.get("paragraph_idx"),
                    "section": e.get("section"),
                    "summary": (e.get("instruction") or e.get("new") or e.get("selection") or "")[:120],
                })
                if len(recent) >= 15:
                    break
            return self._json({"current": current, "recent": recent})

        if path == "/api/storage/list":
            """GET → список всех finalized.md по всем книгам."""
            toc = json.loads(TOC_PATH.read_text(encoding="utf-8")) if TOC_PATH.exists() else {"books": []}
            books_finalized = []
            total_chapters = 0
            total_words = 0
            for book in toc.get("books", []):
                if book.get("status") == "reference":
                    continue
                book_finalized = []
                for ch in book.get("chapters", []):
                    ch_dir = DATA_ROOT / "chapters" / book["id"] / ch["id"]
                    final_file = ch_dir / "finalized.md"
                    status_file = ch_dir / "status.json"
                    if final_file.exists():
                        text = final_file.read_text(encoding="utf-8")
                        words = len(text.split())
                        status = {}
                        if status_file.exists():
                            try:
                                status = json.loads(status_file.read_text(encoding="utf-8"))
                            except json.JSONDecodeError:
                                pass
                        book_finalized.append({
                            "chapter_id": ch["id"],
                            "title": ch.get("title", ch["id"]),
                            "number": ch.get("number", 0),
                            "chars": len(text),
                            "words": words,
                            "finalized_at": status.get("finalized_at"),
                        })
                        total_chapters += 1
                        total_words += words
                if book_finalized:
                    books_finalized.append({
                        "book_id": book["id"],
                        "title": book.get("title_clean") or book.get("title") or book["id"],
                        "chapters": book_finalized,
                    })
            return self._json({
                "books": books_finalized,
                "total_chapters": total_chapters,
                "total_words": total_words,
            })

        if path.startswith("/api/storage/export-html"):
            """GET ?chapters=id1,id2,id3 → printable HTML (для Cmd+P → Save as PDF)."""
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            chapter_ids = qs.get("chapters", [""])[0].split(",")
            chapter_ids = [c.strip() for c in chapter_ids if c.strip()]
            if not chapter_ids:
                # Все finalized
                toc = json.loads(TOC_PATH.read_text(encoding="utf-8")) if TOC_PATH.exists() else {"books": []}
                for book in toc.get("books", []):
                    if book.get("status") == "reference":
                        continue
                    for ch in book.get("chapters", []):
                        ch_dir = DATA_ROOT / "chapters" / book["id"] / ch["id"]
                        if (ch_dir / "finalized.md").exists():
                            chapter_ids.append(ch["id"])
            html = self._build_export_html(chapter_ids)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            body = html.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/toc":
            if TOC_PATH.exists():
                try:
                    data = json.loads(TOC_PATH.read_text(encoding="utf-8"))
                except Exception as e:
                    return self._json({"error": f"toc.json parse failed: {e}"}, 500)
            else:
                # toc.json отсутствует — строим из файловой системы chapters/
                data = self._build_toc_from_disk()
            # Обогащаем главы прогрессом (draft / finalized / score)
            try:
                self._enrich_toc_progress(data)
            except Exception:
                pass
            return self._json(data)

        if path == "/api/recent-works":
            # UC-112: последние N глав которые редактировались +
            # активные сессии Wizard и Журналиста.
            return self._recent_works()

        if path == "/api/editor/full-analysis":
            # UC-115: всё что есть по главе одним вызовом.
            # critics (latest), voice missing_ideas, density, logic, resonance,
            # hook-cliff, style-coherence, personas (если есть).
            return self._editor_full_analysis()

        if path == "/api/editor/sequence":
            # UC-125: вернуть кэш sequence-analyzer
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            chapter_id = (qs.get("chapter_id") or [""])[0]
            if not chapter_id:
                return self._json({"error": "chapter_id required"}, 400)
            cache = DATA_ROOT / "data/sequence" / f"{chapter_id}.json"
            if cache.exists():
                try:
                    return self._json(json.loads(cache.read_text(encoding="utf-8")))
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            return self._json({"ok": False, "error": "not yet", "status": "not_ready"}, 404)

        # Book reader endpoints (GET)
        if path == "/api/book/full":
            return self._book_full()
        if path == "/api/book/notes":
            return self._book_notes_list()
        if path == "/api/book/polish-plan":
            return self._book_polish_plan_get()
        # ФАЗА 3 (2026-05-24): кэш мастер-аудита
        if path == "/api/chapter/master-audit":
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            chapter_id = (qs.get("chapter_id") or [""])[0]
            if not chapter_id:
                return self._json({"error": "chapter_id required"}, 400)
            cache = DATA_ROOT / "data/master-audit" / f"{chapter_id}.json"
            if cache.exists():
                try:
                    return self._json(json.loads(cache.read_text(encoding="utf-8")))
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            return self._json({"ok": False, "error": "not yet", "status": "not_ready"}, 404)

        if path == "/api/editor/voice-sources":
            # UC-129: список оригинальных голосовых файлов релевантных главе
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            chapter_id = (qs.get("chapter_id") or [""])[0]
            if not chapter_id:
                return self._json({"error": "chapter_id required"}, 400)
            try:
                return self._json({"sources": self._list_voice_sources_for_chapter(chapter_id)})
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        if path == "/api/editor/reconciled":
            # UC-124: вернуть кэш reconciler (если есть) или 404
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            chapter_id = (qs.get("chapter_id") or [""])[0]
            if not chapter_id:
                return self._json({"error": "chapter_id required"}, 400)
            cache = DATA_ROOT / "data/reconciled" / f"{chapter_id}.json"
            if cache.exists():
                try:
                    return self._json(json.loads(cache.read_text(encoding="utf-8")))
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            return self._json({"ok": False, "error": "not yet", "status": "not_ready"}, 404)

        if path == "/api/styles":
            # UC-116: Pavel-овские custom стили (правила + примеры)
            sf = DATA_ROOT / "data/styles.json"
            if sf.exists():
                try:
                    return self._json(json.loads(sf.read_text(encoding="utf-8")))
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            return self._json({"rules": [], "examples": []})

        if path == "/api/quality-config":
            # UC-123: глобальные пороги качества (шедевр, AI-detection и т.д.)
            qf = DATA_ROOT / "data/quality-config.json"
            DEFAULTS = {
                "target_masterpiece": 95,
                "target_passing": 80,
                "target_rework": 60,
                "ai_threshold_warn": 35,
                "ai_threshold_danger": 60,
                "voice_min_fidelity_pct": 70,
                "density_min_ok_axes": 2,
                "model": "claude-opus-4-7",
            }
            if qf.exists():
                try:
                    cur = json.loads(qf.read_text(encoding="utf-8"))
                    # merge defaults
                    for k, v in DEFAULTS.items():
                        cur.setdefault(k, v)
                    return self._json(cur)
                except Exception:
                    pass
            return self._json(DEFAULTS)

        return self._error(404, "Not found")

    def _serve_file(self, path: Path, mime: str):
        if not path.exists() or not path.is_file():
            return self._error(404, f"Missing: {path.name}")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, msg: str):
        # Lesson from v1: /api/* must ALWAYS return JSON, even on error.
        # Bare text/html on API path breaks fetch().
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            return self._json({"error": msg, "status": status}, status)
        body = msg.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ═══ UC-137: Active-job markers — переживают уход со страницы ═══
    # Pavel: «ушёл со страницы и все процессы остановились». Длинные операции
    # (apply-targeted, super-rewrite) теперь регистрируют маркер на диск.
    # Клиент на возврат в редактор проверяет /api/jobs/active и показывает
    # прогресс уже идущей работы; маркер удаляется когда работа завершилась.
    def _active_jobs_dir(self):
        d = DATA_ROOT / ".codex/active-jobs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _active_job_register(self, chapter_id: str, op_type: str, eta_seconds: int = 300, extra: dict = None) -> str:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        job_id = f"{chapter_id}__{op_type}__{ts}"
        rec = {
            "job_id": job_id,
            "chapter_id": chapter_id,
            "op_type": op_type,
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eta_seconds": int(eta_seconds),
            "status": "running",
            "pid": os.getpid(),
        }
        if extra:
            rec.update(extra)
        path = self._active_jobs_dir() / f"{chapter_id}__{op_type}.json"
        try:
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return job_id

    def _active_job_complete(self, chapter_id: str, op_type: str, result: dict = None, error: str = None):
        """Удалить маркер ИЛИ оставить как 'done'/'failed' на короткое время для UI."""
        from datetime import datetime, timezone
        path = self._active_jobs_dir() / f"{chapter_id}__{op_type}.json"
        if not path.exists():
            return
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            rec["status"] = "failed" if error else "done"
            rec["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if error:
                rec["error"] = str(error)[:1000]
            if result:
                rec["result"] = result
            # Записываем как done и переименовываем в .done, чтобы запрос /active его не вернул
            done_path = self._active_jobs_dir() / f"{chapter_id}__{op_type}.done.json"
            done_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            path.unlink()
            # Чистим старые .done файлы (>1 час)
            self._active_jobs_gc()
        except Exception:
            try:
                path.unlink()
            except Exception:
                pass

    def _active_jobs_gc(self):
        """Удаляем .done файлы старше 1 часа."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        for f in self._active_jobs_dir().glob("*.done.json"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink()
            except Exception:
                pass

    def _active_jobs_list(self, chapter_id: str = None) -> list:
        """Список активных job-ов. Если chapter_id задан — только для него."""
        jobs = []
        for f in self._active_jobs_dir().glob("*.json"):
            if f.name.endswith(".done.json"):
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if chapter_id and rec.get("chapter_id") != chapter_id:
                    continue
                # Подсчитываем сколько секунд работает
                from datetime import datetime, timezone
                started = datetime.fromisoformat(rec.get("started_at", "").replace("Z", "+00:00"))
                elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
                rec["elapsed_seconds"] = elapsed
                eta = max(0, rec.get("eta_seconds", 300) - elapsed)
                rec["remaining_seconds"] = eta
                jobs.append(rec)
            except Exception:
                continue
        return jobs

    def _active_jobs_recent_done(self, chapter_id: str = None, since_minutes: int = 30) -> list:
        """Недавно завершённые job-ы (за последние N минут) — для уведомления Pavel-а."""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        out = []
        for f in self._active_jobs_dir().glob("*.done.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if chapter_id and rec.get("chapter_id") != chapter_id:
                    continue
                finished = datetime.fromisoformat(rec.get("finished_at", "").replace("Z", "+00:00"))
                if finished >= cutoff:
                    out.append(rec)
            except Exception:
                continue
        out.sort(key=lambda r: r.get("finished_at") or "", reverse=True)
        return out

    def _load_voice_extracts_for_chapter(self, chapter_id: str, max_chars: int = 14000) -> str:
        """UC-120 + UC-129: загружает оригинальные voice-надиктовки Pavel-а.

        Pavel: «именно мои наговоренные написанные в момент создания глав идеи.
        Сначала ОРИГИНАЛЬНЫЕ файлы из voice-corpus, потом voice-analysis missing_ideas».

        Источники по приоритету:
          1) voice-corpus/raw/*.md — оригинальные транскрипты по дате+теме
          2) voice-corpus/original-ideas/*.md — собранные идеи по книгам
          3) Codex/sources/voice-extracts/ — старые надиктовки 2025-2026
          4) chapters/<chapter_id>/voice-analysis.json missing_ideas — AI-выжимки (fallback)
        """
        import re as _re
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return ""
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id

        chapter_title = ""
        meta_path = ch_dir / "meta.json"
        if meta_path.exists():
            try:
                chapter_title = (json.loads(meta_path.read_text(encoding="utf-8")).get("title") or "")
            except Exception:
                pass
        # Тематические ключи: книга + название главы
        keywords = []
        if book_id == "book-obsession":
            keywords += ["одерж", "obsession", "паразит", "захват", "вторжен", "демон", "грибы", "миком"]
        if "ustav" in book_id:
            # UC-130: расширенные ключи для Устава — добавлены общие термины Микомистицизма
            keywords += [
                "устав", "ustav", "сообществ", "членств", "правил",
                "грибы", "миком", "гид", "проводник", "церемони", "ритуал",
                "посвящен", "восход", "иниц", "храм", "святилищ",
                "хилингод", "духа", "дух", "великий", "творц",
            ]
        # Из title — слова >=4 букв
        if chapter_title:
            keywords += [w.lower() for w in _re.findall(r"[А-Яа-яЁё]{4,}", chapter_title)]
        keywords = list(set(keywords))

        chunks = []

        def _read_safe(p, max_len=2500):
            try:
                return p.read_text(encoding="utf-8")[:max_len]
            except Exception:
                return ""

        def _matches(p):
            n = p.name.lower()
            return any(kw in n for kw in keywords)

        # 1) Codex2 voice-corpus/raw/
        v_raw = DATA_ROOT / "voice-corpus/raw"
        relevant_raw = []
        if v_raw.exists():
            for f in v_raw.glob("*.md"):
                if _matches(f):
                    relevant_raw.append(f)
        if relevant_raw:
            chunks.append("## 🎙️ ОРИГИНАЛЬНЫЕ ВОЙС-НАДИКТОВКИ (voice-corpus/raw) — наговорено в момент создания\n")
            for f in relevant_raw[:3]:
                text = _read_safe(f, 2500)
                if text.strip():
                    chunks.append(f"\n### {f.name}\n\n{text}\n")

        # 2) Codex2 voice-corpus/original-ideas/
        v_ideas = DATA_ROOT / "voice-corpus/original-ideas"
        if v_ideas.exists():
            relevant_ideas = []
            for f in v_ideas.glob("*.md"):
                if _matches(f):
                    relevant_ideas.append(f)
            if relevant_ideas:
                chunks.append("\n## 🎙️ ОРИГИНАЛЬНЫЕ ИДЕИ (voice-corpus/original-ideas) — сборка по темам книг\n")
                for f in relevant_ideas[:2]:
                    text = _read_safe(f, 2500)
                    if text.strip():
                        chunks.append(f"\n### {f.name}\n\n{text}\n")

        # 3) Codex/sources/voice-extracts (старый Codex)
        v_old = Path.home() / "Desktop/Codex/sources/voice-extracts"
        if v_old.exists():
            relevant_old = []
            for f in v_old.glob("*.md"):
                if _matches(f):
                    relevant_old.append(f)
            if relevant_old:
                chunks.append("\n## 🎙️ ВОЙС-НАДИКТОВКИ (старая Codex) — оригинальные записи 2025-2026\n")
                for f in relevant_old[:2]:
                    text = _read_safe(f, 2000)
                    if text.strip():
                        chunks.append(f"\n### {f.name}\n\n{text}\n")

        # 4) FALLBACK: voice-analysis.json missing_ideas (AI-выжимка) — только если оригиналы НЕ найдены
        if not chunks:
            vf = ch_dir / "voice-analysis.json"
            if vf.exists():
                try:
                    vd = json.loads(vf.read_text(encoding="utf-8"))
                    missing = vd.get("missing_ideas") or []
                    if missing:
                        chunks.append("## 🎙️ Голосовые идеи (AI-выжимка из voice-analysis — fallback, оригиналов не нашлось):\n")
                        for i, idea in enumerate(missing[:8], 1):
                            text = idea if isinstance(idea, str) else (idea.get("idea") or idea.get("text") or "")
                            if text:
                                chunks.append(f"{i}. {str(text)[:500]}")
                except Exception:
                    pass

        return "\n".join(chunks)[:max_chars]

    def _list_voice_sources_for_chapter(self, chapter_id: str) -> list:
        """UC-129: для UI — список voice-файлов с превью."""
        import re as _re
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return []
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        chapter_title = ""
        mp = ch_dir / "meta.json"
        if mp.exists():
            try:
                chapter_title = (json.loads(mp.read_text(encoding="utf-8")).get("title") or "")
            except Exception:
                pass
        keywords = []
        if book_id == "book-obsession":
            keywords += ["одерж", "obsession", "паразит", "захват", "вторжен", "демон", "грибы", "миком"]
        if "ustav" in book_id:
            # UC-130: расширенные ключи для Устава
            keywords += [
                "устав", "ustav", "сообществ", "членств", "правил",
                "грибы", "миком", "гид", "проводник", "церемони", "ритуал",
                "посвящен", "восход", "иниц", "храм", "святилищ",
                "хилингод", "духа", "дух", "великий", "творц",
            ]
        if chapter_title:
            keywords += [w.lower() for w in _re.findall(r"[А-Яа-яЁё]{4,}", chapter_title)]
        keywords = list(set(keywords))

        sources = []
        seen_paths = set()
        for src_dir, src_label in [
            (DATA_ROOT / "voice-corpus/raw", "voice-corpus/raw"),
            (DATA_ROOT / "voice-corpus/original-ideas", "voice-corpus/original-ideas"),
            (Path.home() / "Desktop/Codex/sources/voice-extracts", "Codex/voice-extracts"),
        ]:
            if not src_dir.exists():
                continue
            for f in src_dir.glob("*.md"):
                if str(f) in seen_paths:
                    continue
                n = f.name.lower()
                # Сначала по filename
                matched_by_filename = any(kw in n for kw in keywords)
                # Если не нашли — проверяем содержимое первых 3000 символов
                try:
                    text = f.read_text(encoding="utf-8")
                except Exception:
                    continue
                matched_by_content = False
                if not matched_by_filename:
                    head = text[:3000].lower()
                    # Считаем сколько keywords попадает в текст. Если хотя бы 2 разных — match
                    hits = sum(1 for kw in keywords if kw in head)
                    if hits >= 2:
                        matched_by_content = True
                if not (matched_by_filename or matched_by_content):
                    continue
                seen_paths.add(str(f))
                preview = text[:400].replace("\n", " ").strip()
                sources.append({
                    "filename": f.name,
                    "path": str(f),
                    "source": src_label,
                    "size": len(text),
                    "preview": preview,
                    "matched_by": "filename" if matched_by_filename else "content",
                })
        return sources

    def _load_custom_styles(self, max_chars: int = 4000) -> str:
        """UC-116: загружает Pavel-овские custom стили из data/styles.json."""
        styles_file = DATA_ROOT / "data/styles.json"
        if not styles_file.exists():
            return ""
        try:
            styles = json.loads(styles_file.read_text(encoding="utf-8"))
        except Exception:
            return ""
        rules = styles.get("rules") or []
        examples = styles.get("examples") or []
        out = []
        if rules:
            out.append("## ПРАВИЛА:")
            for r in rules:
                if isinstance(r, dict):
                    out.append(f"- {r.get('rule') or r.get('text','')}")
                else:
                    out.append(f"- {r}")
        if examples:
            out.append("\n## ПРИМЕРЫ:")
            for e in examples:
                if isinstance(e, dict):
                    out.append(f"### {e.get('title','без названия')}\n{e.get('text','')[:600]}")
                else:
                    out.append(str(e)[:400])
        return "\n".join(out)[:max_chars]

    # ═══ ФАЗА 3 (2026-05-24): Pavel-substrate — единый блок для любого Opus-промпта ═══
    # Pavel: «нужна векторная память которая заполнит стили которые мы отработаем
    # чтобы везде был единый стиль общее понимание концепции».
    # Эта функция собирает в один текстовый блок: CANON, эталон голоса, примеры из
    # библиотеки (md-файлы), голосовые надиктовки. Любая Opus-операция инжектит
    # ОДИН и тот же substrate — отсюда единство стиля во всех правках.
    def _pavel_substrate(self, chapter_id: str, max_total_chars: int = 22000) -> str:
        parts = []

        # 1. CANON.md — головная часть (правила доктрины, голос, термины)
        canon_path = DATA_ROOT / "CANON.md"
        if canon_path.exists():
            try:
                canon_txt = canon_path.read_text(encoding="utf-8")
                parts.append("# 📜 CANON Кодекса\n\n" + canon_txt[:7000])
            except Exception:
                pass

        # 2. Эталон голоса Хилингода
        style_v2 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        style_v1 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_path = style_v2 if style_v2.exists() else style_v1
        if style_path.exists():
            try:
                txt = style_path.read_text(encoding="utf-8")
                parts.append("# 🎼 ЭТАЛОН ГОЛОСА Хилингода (как звучит Pavel)\n\n" + txt[:4000])
            except Exception:
                pass

        # 3. Жёсткие правила (UC-76 без тире, UC-134 без вымышленных, USER.md мистика)
        parts.append(
            "# 🚨 ЖЁСТКИЕ ПРАВИЛА (Pavel-rules стоячие):\n\n"
            "1. Без тире (— и –). Замена на запятые или точки. UC-76. НО запрет тире НЕ значит «разбивать длинное предложение на много коротких».\n"
            "2. Без вымышленных героев (Иоанн из Анжера, монах на Афоне, Хильдегарда, безымянные Анна/Михаил). UC-134.\n"
            "3. Без AI-клише: «представляют собой», «в отличие от», «важно понимать», «таким образом», «не только X но и Y», «при этом».\n"
            "4. Без буллет-списков для ИДЕЙ. Списки только для явных инструкций (1. 2. 3.).\n"
            "5. НЕ научная книга. Никаких 5-HT2A, дофамина, HRV, кортизола, исследований. Pavel: «мы пишем мистическую книгу, не научную».\n"
            "6. Голос: «Я — Великий Дух Грибов» (прямая речь Духа) или «Я — Хилингод» (свидетельство мастера). НЕ «мы», НЕ «они».\n"
            "7. Сохранять анафоры (повторы «являет себя… являет себя») — это пророческая речь, не ошибка.\n"
            "8. Сохранять торжественные глаголы («являет», «нисходит», «обретает») — не заменять на бытовые.\n"
            "9. Сохранять троичные перечисления и «один из самых» — это ритм Хилингода.\n"
            "10. Цель — шедевр на 1000 лет. Если фраза «звучит как AI» — переписать или удалить.\n"
            "11. 🚨 КРИТИЧНО — НЕ РУБИТЬ ПРЕДЛОЖЕНИЯ НА КОРОТКИЕ ОБРЫВКИ. Pavel прямо сказал: "
            "«микро-предложения это AI-стиль, кричит AI». Если Pavel пишет «Священные Грибы ждут "
            "в тишине лесов и лугов, хранят в своих спорах ключи от всех темниц», AI-стиль это "
            "«Грибы ждут. Они хранят ключи. Они ждут в лесу.» — это запрещено. Pavel-стиль это "
            "длинные многоклаузные предложения 20-50 слов с придаточными, причастными оборотами, "
            "анафорами, троичными перечислениями. НЕ ДРОБИТЬ. Если убираешь тире — заменяй на "
            "запятые, не на точки. Сохраняй РИТМ длинных дыханий пророка.\n"
            "12. Минимум 70% предложений в правке должны быть 15+ слов. Короткие предложения "
            "(2-7 слов) допустимы только как РИТМИЧЕСКИЕ УДАРЫ после длинных, не как доминирующий стиль."
        )

        # 4. Custom styles (Pavel-defined через /стили UI)
        custom = self._load_custom_styles(max_chars=2500)
        if custom:
            parts.append("# 📝 ТВОИ КАСТОМНЫЕ СТИЛЕВЫЕ ПРАВИЛА (UC-116):\n\n" + custom)

        # 5. Примеры из библиотеки — берём md-файлы (читаемые без парсинга)
        lib_idx = DATA_ROOT / "data/library/index.json"
        if lib_idx.exists():
            try:
                idx = json.loads(lib_idx.read_text(encoding="utf-8"))
                md_files = [f for f in (idx.get("files") or []) if f.get("ext") == ".md"]
                # Приоритет: «финальная редакция Pavel-а» в имени → берём первым
                md_files.sort(key=lambda f: (
                    0 if "финальн" in (f.get("name","").lower()) or "edited" in (f.get("name","").lower()) else 1
                ))
                for mf in md_files[:2]:
                    path = DATA_ROOT / mf.get("stored_path", "")
                    if path.exists():
                        try:
                            txt = path.read_text(encoding="utf-8")
                            parts.append(f"# 📚 ПРИМЕР ИЗ ТВОЕЙ БИБЛИОТЕКИ — {mf.get('name','')}\n\n" + txt[:3500])
                        except Exception:
                            continue
            except Exception:
                pass

        # 6. Voice-corpus matches для этой главы (Pavel-голосовые)
        voice = self._load_voice_extracts_for_chapter(chapter_id, max_chars=4000)
        if voice:
            parts.append("# 🎙️ ТВОИ ГОЛОСОВЫЕ НАДИКТОВКИ (приоритет №1 в правках):\n\n" + voice)

        # 7. ФАЗА 4 (2026-05-24) — top-5 твоих сообщений из Claude.ai-экспорта (raw voice)
        chat_top = self._chat_index_top_messages(chapter_id, top_n=5, snippet_chars=600)
        if chat_top:
            parts.append("# 💬 ТВОИ ИСХОДНЫЕ СООБЩЕНИЯ из Claude.ai (raw voice по теме):\n\n" + chat_top)

        substrate = "\n\n---\n\n".join(parts)
        return substrate[:max_total_chars]

    def _chat_index_top_messages(self, chapter_id: str, top_n: int = 5, snippet_chars: int = 600) -> str:
        """Keyword-поиск по ~/Desktop/Codex-Content/voice-index.jsonl.
        Берёт ключевые слова из chapter_id (грубо) и возвращает top-N сообщений Pavel-а."""
        idx_path = Path.home() / "Desktop/Codex-Content/voice-index.jsonl"
        if not idx_path.exists():
            return ""
        # Грубые ключевые слова по chapter_id + meta.json (если есть)
        keywords = set()
        # 1) из chapter_id — например "book-03-ch-01" → ['book','03','ch','01'] не очень полезно
        # 2) из meta.json главы
        import re
        m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if m:
            book_id = m.group(1)
            ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
            meta_file = ch_dir / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    title = meta.get("title") or meta.get("title_clean") or ""
                    keywords.update(self._extract_keywords(title))
                except Exception:
                    pass
            # 3) из первой строки draft.md (часто там заголовок)
            draft = ch_dir / "draft.md"
            if draft.exists():
                try:
                    first = draft.read_text(encoding="utf-8")[:500]
                    keywords.update(self._extract_keywords(first))
                except Exception:
                    pass
        if not keywords:
            return ""

        # Линейный скан JSONL
        scored = []  # (score, ts, text)
        try:
            with idx_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    text = rec.get("text", "")
                    if not text:
                        continue
                    text_low = text.lower()
                    score = sum(1 for kw in keywords if kw in text_low)
                    if score >= 2:  # минимум 2 ключевых слова чтобы попасть
                        scored.append((score, rec.get("ts", ""), text))
        except Exception:
            return ""

        scored.sort(key=lambda r: (-r[0], r[1]))
        out_lines = []
        for i, (score, ts, text) in enumerate(scored[:top_n], 1):
            out_lines.append(f"### Сообщение {i} (совпадений: {score}, {ts[:10]})\n{text[:snippet_chars].strip()}")
        return "\n\n".join(out_lines)

    def _extract_keywords(self, text: str) -> set:
        """Грубо: слова длиннее 4 букв в нижнем регистре, без стоп-слов."""
        import re
        STOPWORDS = {
            "это", "этой", "этом", "эти", "этих", "этого", "также", "потом", "может", "чтобы",
            "когда", "тогда", "только", "очень", "более", "менее", "много", "ничего",
            "нужно", "нужный", "должен", "можно", "будет", "является", "являются",
            "которая", "которые", "который", "которое", "которых", "которому",
            "глава", "главы", "главе", "главой", "часть", "часть", "часть",
            "пройти", "пройдём", "потом", "затем", "затем",
        }
        tokens = re.findall(r"[а-яёa-z]{5,}", text.lower())
        return set(t for t in tokens if t not in STOPWORDS)

    def _editor_full_analysis(self):
        """UC-115: всё что есть по главе одним JSON.

        Pavel: «в предыдущем редакторе были глубина/стиль/открытие/закрытие,
        голосовые потерянные, совет старейшин с персонами Маск/Роган».
        Собираем в один endpoint, фронт ставит галочки и применяет.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        chapter_id = (qs.get("chapter_id") or [""])[0]
        if not chapter_id:
            return self._json({"error": "chapter_id required"}, 400)

        import re
        m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": f"bad chapter_id: {chapter_id}"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id

        out = {
            "chapter_id": chapter_id,
            "book_id": book_id,
            "exists": ch_dir.exists(),
            "critics": None,
            "voice_missing_ideas": [],
            "voice_additions": [],
            "voice_matches_count": 0,
            "density": None,
            "logic": None,
            "resonance": None,
            "hook_cliff": None,
            "style_coherence": None,
            "coherence_in_book": None,
            "personas": None,
            "personas_run_at": None,
        }

        def _safe_load(p):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None

        # 1) Critics — latest CRITICS-<chapter>-*.json
        reports_dir = DATA_ROOT / "reports"
        if reports_dir.exists():
            cands = sorted(reports_dir.glob(f"CRITICS-{chapter_id}-*.json"), reverse=True)
            if cands:
                cdata = _safe_load(cands[0])
                if cdata:
                    out["critics"] = cdata
                    out["critics_path"] = str(cands[0].relative_to(DATA_ROOT))
                    out["critics_run_at"] = cdata.get("ts")

        # 2) Voice analysis — missing_ideas + additions
        vf = ch_dir / "voice-analysis.json"
        if vf.exists():
            vd = _safe_load(vf) or {}
            out["voice_missing_ideas"] = vd.get("missing_ideas") or []
            out["voice_additions"] = vd.get("additions") or []
            out["voice_matches_count"] = len(vd.get("matches") or [])
            out["voice_run_at"] = vd.get("generated_at")

        # 3) Density / 4) Logic / 5) Resonance / 6) Hook-cliff / 7) Style-coherence
        for key, fname in [
            ("density", "density-analysis.json"),
            ("logic", "logic-analysis.json"),
            ("resonance", "resonance.json"),
            ("hook_cliff", "hook-cliff.json"),
            ("style_coherence", "style-coherence.json"),
            ("coherence_in_book", "coherence-in-book.json"),
        ]:
            fp = ch_dir / fname
            if fp.exists():
                out[key] = _safe_load(fp)

        # 8) Personas — opt-in cache в personas/<chapter>.json
        personas_dir = DATA_ROOT / "data/personas"
        personas_file = personas_dir / f"{chapter_id}.json"
        if personas_file.exists():
            pd = _safe_load(personas_file)
            if pd:
                out["personas"] = pd
                out["personas_run_at"] = pd.get("ts")

        # 9) Approvals
        af = ch_dir / "approvals.json"
        if af.exists():
            out["approvals"] = _safe_load(af)

        # 10) UC-118: Главный старейшина — топ-4 рекомендации из всех старейшин
        out["chief_elder_top4"] = self._extract_chief_elder_top4(out.get("critics"))

        return self._json(out)

    def _extract_chief_elder_top4(self, critics_data):
        """UC-118: «Главный старейшина выбирает лучшие рекомендации из всех старейшин и даёт 4».

        Heuristic: берёт по одной самой острой рекомендации от каждого из 6 старейшин,
        приоритизирует по конкретности (есть ли число параграфа / конкретное действие /
        длина рекомендации). Возвращает топ-4.
        """
        if not critics_data:
            return []
        results = critics_data.get("results") or {}
        candidates = []
        elder_names = {
            "council_tolstoy": "Толстой",
            "council_jung": "Юнг",
            "council_mckenna": "Маккенна",
            "council_castaneda": "Кастанеда (дон Хуан)",
            "council_john": "Иоанн Богослов",
            "council_laotzu": "Лао-цзы",
        }
        for cid in elder_names:
            c = results.get(cid)
            if not c or not c.get("ok"):
                continue
            r = c.get("result") or {}
            name = elder_names[cid]
            # Собираем все рекомендации старейшины
            items = []
            for cut in (r.get("top_3_cuts") or [])[:3]:
                text = cut if isinstance(cut, str) else (cut.get("text") or cut.get("comment") or "")
                if text:
                    items.append({"elder": name, "critic": cid, "kind": "cut", "text": text[:400]})
            for s in (r.get("top_3_strengthen") or [])[:3]:
                text = s if isinstance(s, str) else (s.get("text") or s.get("comment") or "")
                if text:
                    items.append({"elder": name, "critic": cid, "kind": "strengthen", "text": text[:400]})
            # Если ни cuts ни strengthen — берём verdict как одно высказывание
            if not items and r.get("verdict"):
                items.append({"elder": name, "critic": cid, "kind": "verdict", "text": str(r["verdict"])[:400]})
            # Берём только самую острую (первую) от каждого старейшины
            if items:
                candidates.append(items[0])
        # Если менее 4 старейшин дали — добавим вторые рекомендации
        if len(candidates) < 4:
            for cid in elder_names:
                c = results.get(cid)
                if not c or not c.get("ok"):
                    continue
                r = c.get("result") or {}
                name = elder_names[cid]
                second_items = []
                for cut in (r.get("top_3_cuts") or [])[1:3]:
                    text = cut if isinstance(cut, str) else (cut.get("text") or cut.get("comment") or "")
                    if text:
                        second_items.append({"elder": name, "critic": cid, "kind": "cut", "text": text[:400]})
                for s in (r.get("top_3_strengthen") or [])[1:3]:
                    text = s if isinstance(s, str) else (s.get("text") or s.get("comment") or "")
                    if text:
                        second_items.append({"elder": name, "critic": cid, "kind": "strengthen", "text": text[:400]})
                for item in second_items:
                    if len(candidates) < 4:
                        candidates.append(item)
        return candidates[:4]

    def _compute_readiness(self, ch_dir, progress: str, chars: int) -> dict:
        """UC-114: реальная оценка готовности главы из сигналов.

        Источники (всего 100 баллов возможно):
          [10]  text_presence: draft.md > 1000 символов
          [10]  text_length: 5K..40K — оптимальный объём (50%+5K → линейно)
          [25]  council: synthesis.score из 15 критиков (норм. 0-25)
          [15]  approvals: approved_indices / total параграфов (Pavel вручную одобрил)
          [10]  density: local_assessment verdict == "ok" по всем осям
          [10]  logic: 10 - 2*issues_count (min 0)
          [10]  voice_fidelity: matches / (matches + missing_ideas) * 10
          [ 5]  resonance: overall_resonance >= 70
          [ 5]  hook_cliff: hook_strength + cliffhanger_strength >= 140
        Бонус-капы:
          finalized.md существует → 100% (override)
          chars == 0 → 0%
          chars > 0 но нет AI-анализов → max 25%

        Возвращает {pct, label, kind, signals: [{key, label, points, max, why}]}
        """
        signals = []

        def add(key, label, pts, mx, why):
            signals.append({
                "key": key, "label": label,
                "points": pts, "max": mx, "why": why,
            })

        # 1) Финализирована — override
        if progress == "finalized":
            add("finalized", "Финализирована (Pavel нажал «Финализировать»)", 100, 100, "finalized.md существует")
            return {"pct": 100, "label": "готова", "kind": "done", "signals": signals}

        if chars == 0:
            add("empty", "Текста нет", 0, 100, "draft.md отсутствует")
            return {"pct": 0, "label": "пусто", "kind": "empty", "signals": signals}

        total = 0

        # 1) Text presence (10)
        text_pres = 10 if chars > 1000 else round(chars / 100)
        text_pres = min(10, max(0, text_pres))
        total += text_pres
        add("text_presence", "Текст есть", text_pres, 10,
            f"{chars} символов в draft.md (нужно >1000)")

        # 2) Text length (10) — оптимум 12K..40K
        if chars < 5000:
            tl = round(chars / 500)  # линейный рост
        elif chars <= 40000:
            tl = 10
        else:
            tl = max(5, 10 - (chars - 40000) // 5000)
        tl = min(10, max(0, tl))
        total += tl
        add("text_length", "Объём", tl, 10, f"{chars} симв. (целевой 12K-40K)")

        # 3) Council synthesis (25)
        council_pts = 0
        council_why = "council.json нет, прогон не был запущен"
        cf = ch_dir / "council.json"
        if cf.exists():
            try:
                cdata = json.loads(cf.read_text(encoding="utf-8"))
                # ищем synthesis.score в разных местах
                syn = cdata.get("synthesis") or (cdata.get("council") or {}).get("synthesis") or {}
                sscore = syn.get("score") if isinstance(syn, dict) else None
                # fallback на critics array avg
                if sscore is None:
                    crits = cdata.get("critics") or cdata.get("council", {}).get("critics") or []
                    scores = [c.get("score") for c in (crits or []) if isinstance(c, dict) and c.get("score") is not None]
                    if scores:
                        sscore = round(sum(scores) / len(scores), 1)
                if sscore is not None:
                    council_pts = round(min(25, sscore / 100 * 25))
                    council_why = f"synthesis.score = {sscore}/100"
                else:
                    council_why = "council.json есть, но synthesis.score пустой (прогон не завершён)"
            except Exception as e:
                council_why = f"ошибка чтения: {e}"
        total += council_pts
        add("council", "Совет 15 критиков", council_pts, 25, council_why)

        # 4) Approvals (15)
        appr_pts = 0
        appr_why = "Pavel не одобрял параграфы вручную"
        af = ch_dir / "approvals.json"
        if af.exists():
            try:
                adata = json.loads(af.read_text(encoding="utf-8"))
                approved = adata.get("approved_indices") or []
                # сколько всего параграфов
                if draft_file := (ch_dir / "draft.md"):
                    if draft_file.exists():
                        total_paras = max(1, len([p for p in draft_file.read_text(encoding="utf-8").split("\n\n") if p.strip()]))
                    else:
                        total_paras = 1
                else:
                    total_paras = 1
                if approved:
                    ratio = len(approved) / total_paras
                    appr_pts = round(min(15, ratio * 15))
                    appr_why = f"одобрено {len(approved)}/{total_paras} параграфов"
                else:
                    appr_why = "approvals.json есть, но approved_indices пустой"
            except Exception as e:
                appr_why = f"ошибка: {e}"
        total += appr_pts
        add("approvals", "Pavel одобрил параграфы", appr_pts, 15, appr_why)

        # 5) Density (10)
        dens_pts = 0
        dens_why = "density-analysis нет"
        df = ch_dir / "density-analysis.json"
        if df.exists():
            try:
                dd = json.loads(df.read_text(encoding="utf-8"))
                la = dd.get("local_assessment") or {}
                axes = ["size", "rhythm", "water"]
                ok_count = sum(1 for ax in axes if (la.get(ax) or {}).get("verdict") == "ok")
                dens_pts = round(ok_count / 3 * 10)
                dens_why = f"density: {ok_count}/3 осей в ok"
            except Exception as e:
                dens_why = f"ошибка: {e}"
        total += dens_pts
        add("density", "Плотность / ритм", dens_pts, 10, dens_why)

        # 6) Logic (10)
        log_pts = 0
        log_why = "logic-analysis нет"
        lf = ch_dir / "logic-analysis.json"
        if lf.exists():
            try:
                ld = json.loads(lf.read_text(encoding="utf-8"))
                issues = ld.get("issues") or ld.get("findings") or []
                severe = len([i for i in issues if isinstance(i, dict) and i.get("severity") in ("high", "critical", "severe")])
                # если нет severity — считаем все
                if not severe:
                    severe = len(issues)
                log_pts = max(0, 10 - severe * 2)
                log_why = f"{len(issues)} логических замечаний ({severe} серьёзных)"
            except Exception as e:
                log_why = f"ошибка: {e}"
        total += log_pts
        add("logic", "Логика", log_pts, 10, log_why)

        # 7) Voice fidelity (10)
        vf_pts = 0
        vf_why = "voice-analysis нет"
        vf = ch_dir / "voice-analysis.json"
        if vf.exists():
            try:
                vd = json.loads(vf.read_text(encoding="utf-8"))
                matches = len(vd.get("matches") or [])
                missing = len(vd.get("missing_ideas") or [])
                if matches + missing > 0:
                    ratio = matches / (matches + missing)
                    vf_pts = round(ratio * 10)
                    vf_why = f"{matches} идей сохранено, {missing} утеряно ({round(ratio*100)}%)"
                else:
                    vf_why = "voice-analysis пуст (нет голосовых для сравнения)"
            except Exception as e:
                vf_why = f"ошибка: {e}"
        total += vf_pts
        add("voice", "Верность голосу Pavel", vf_pts, 10, vf_why)

        # 8) Resonance (5)
        res_pts = 0
        res_why = "resonance нет"
        rf = ch_dir / "resonance.json"
        if rf.exists():
            try:
                rd = json.loads(rf.read_text(encoding="utf-8"))
                or_score = rd.get("overall_resonance")
                if isinstance(or_score, (int, float)):
                    res_pts = 5 if or_score >= 70 else round(or_score / 100 * 5)
                    res_why = f"overall_resonance = {or_score}"
                else:
                    # Может быть строка-вердикт
                    res_why = f"resonance есть, но score не число (verdict={rd.get('verdict')})"
            except Exception as e:
                res_why = f"ошибка: {e}"
        total += res_pts
        add("resonance", "Сакральный резонанс", res_pts, 5, res_why)

        # 9) Hook + Cliffhanger (5)
        hc_pts = 0
        hc_why = "hook-cliff нет"
        hf = ch_dir / "hook-cliff.json"
        if hf.exists():
            try:
                hd = json.loads(hf.read_text(encoding="utf-8"))
                hs = hd.get("hook_strength")
                cs = hd.get("cliffhanger_strength")
                # strength может быть число или строка
                def _to_num(x):
                    if isinstance(x, (int, float)): return x
                    if isinstance(x, str):
                        try: return float(x.split("/")[0].strip())
                        except: return None
                    return None
                hn = _to_num(hs)
                cn = _to_num(cs)
                if hn is not None or cn is not None:
                    avg = ((hn or 0) + (cn or 0)) / (2 if hn is not None and cn is not None else 1)
                    hc_pts = round(min(5, avg / 100 * 5))
                    hc_why = f"hook={hs}, cliffhanger={cs}"
                else:
                    hc_why = "hook-cliff есть, но числа не парсятся"
            except Exception as e:
                hc_why = f"ошибка: {e}"
        total += hc_pts
        add("hook_cliff", "Крючок + cliffhanger", hc_pts, 5, hc_why)

        # Ограничение: если AI-анализы не прогонялись, кап 25%
        ai_pts = council_pts + dens_pts + log_pts + vf_pts + res_pts + hc_pts
        if ai_pts == 0:
            total = min(total, 25)

        # Cap at 95 если не finalized
        pct = min(95, total)

        if pct >= 85:
            label, kind = "почти готова", "near"
        elif pct >= 60:
            label, kind = "черновик", "draft"
        elif pct >= 30:
            label, kind = "набросок", "sketch"
        elif pct > 0:
            label, kind = "начат", "sketch"
        else:
            label, kind = "пусто", "empty"

        return {"pct": pct, "label": label, "kind": kind, "signals": signals}

    def _recent_works(self):
        """UC-112: возвращает «последние работы» — главы + активные сессии.

        Источники:
          1) Главы: .codex/events.jsonl → chapter_saved events, deduplicated by chapter_id, max 10.
             Дополнительно подтягиваем title из toc.json.
          2) Wizard sessions: chapters/*/wizard-state.json (in_progress)
          3) Journalist sessions: data/journalist-sessions/*.json (последние 5, open)
        """
        from datetime import datetime, timezone
        out = {"chapters": [], "wizard_sessions": [], "journalist_sessions": []}

        # 1) Recent chapter edits from events.jsonl
        events_paths = [
            DATA_ROOT / ".codex/events.jsonl",
            DATA_ROOT / "data/.codex/events.jsonl",
        ]
        events_file = next((p for p in events_paths if p.exists()), None)
        seen_chapters = {}
        if events_file:
            try:
                # Read last 200 lines (we only need recent saves)
                lines = events_file.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in reversed(lines[-2000:]):  # last 2000 events should cover days of work
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("type") != "chapter_saved":
                        continue
                    cid = e.get("target")
                    if not cid or cid in seen_chapters:
                        continue
                    seen_chapters[cid] = {
                        "chapter_id": cid,
                        "saved_at": e.get("ts"),
                        "chars": (e.get("payload") or {}).get("chars"),
                        "paragraphs": (e.get("payload") or {}).get("paragraphs"),
                        "trigger": (e.get("payload") or {}).get("trigger"),
                    }
                    if len(seen_chapters) >= 10:
                        break
            except Exception:
                pass

        # Enrich with title from toc
        toc_titles = {}
        try:
            if TOC_PATH.exists():
                toc = json.loads(TOC_PATH.read_text(encoding="utf-8"))
                for b in toc.get("books", []):
                    for c in b.get("chapters", []):
                        toc_titles[c.get("id")] = {
                            "title": c.get("title") or c.get("title_clean"),
                            "book_id": b.get("id"),
                            "book_title": b.get("title_clean") or b.get("title"),
                            "number": c.get("number"),
                        }
        except Exception:
            pass
        for cid, info in seen_chapters.items():
            t = toc_titles.get(cid, {})
            info.update(t)
            out["chapters"].append(info)
        # sort by saved_at desc
        out["chapters"].sort(key=lambda x: x.get("saved_at") or "", reverse=True)

        # 2) Wizard sessions (per-chapter wizard-state.json)
        try:
            for ws in (DATA_ROOT / "chapters").rglob("wizard-state.json"):
                try:
                    data = json.loads(ws.read_text(encoding="utf-8"))
                    mtime = ws.stat().st_mtime
                    ts = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    out["wizard_sessions"].append({
                        "chapter_id": data.get("chapter_id") or ws.parent.name,
                        "step": data.get("step") or data.get("current_step"),
                        "reached_step": data.get("reached_step"),
                        "topic": (data.get("topic") or "")[:120],
                        "updated_at": ts,
                    })
                except Exception:
                    continue
            out["wizard_sessions"].sort(key=lambda x: x.get("updated_at") or "", reverse=True)
            out["wizard_sessions"] = out["wizard_sessions"][:5]
        except Exception:
            pass

        # 3) Journalist sessions
        try:
            jdir = DATA_ROOT / "data/journalist-sessions"
            if jdir.exists():
                sessions = []
                for jf in jdir.glob("*.json"):
                    try:
                        d = json.loads(jf.read_text(encoding="utf-8"))
                        sessions.append({
                            "session_id": d.get("session_id") or jf.stem,
                            "topic": (d.get("topic") or "")[:120],
                            "complete": bool(d.get("complete")),
                            "question_count": d.get("question_count", 0),
                            "answer_count": d.get("answer_count", 0),
                            "updated_at": d.get("updated_at") or d.get("created_at"),
                        })
                    except Exception:
                        continue
                sessions.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
                out["journalist_sessions"] = sessions[:5]
        except Exception:
            pass

        return self._json(out)

    def _sync_title_from_draft(self, book_id: str, chapter_id: str, paragraphs, draft_dir, ts_iso: str):
        """UC-107: При сохранении главы — извлекаем первый h1/h2/h3 из draft и
        синхронизируем title в meta.json и toc.json (обе записи: title + title_clean).
        Pavel 2026-05-22: «когда я обновляю название главы … надо чтобы переименовывалась
        в оглавлении … а сейчас в уставе нету четвёртой главы заголовка правильного,
        он не сохраняется».
        Returns dict {changed, old_title, new_title} или {changed: False, reason: "..."}.
        """
        import re as _re
        try:
            # 1) Найти первый заголовок (markdown # / ## / ### или явный «Глава N. …»)
            new_title = None
            for p in paragraphs:
                if not isinstance(p, str):
                    continue
                t = p.strip()
                if not t:
                    continue
                m = _re.match(r"^#{1,6}\s+(.+)$", t)
                if m:
                    new_title = m.group(1).strip()
                    break
                # Heuristic: short ALL-CAPS Cyrillic line OR «Глава N. …»
                if len(t) < 200 and (_re.match(r"^(Глава|Часть|Раздел|КНИГА|УСТАВ|ПРОЛОГ|ЭПИЛОГ)\s+", t, _re.IGNORECASE) or (t == t.upper() and _re.search(r"[А-ЯЁ]", t))):
                    new_title = t
                    break
                # Иначе — это уже body, прекращаем поиск (заголовок только в начале)
                break
            if not new_title:
                return {"changed": False, "reason": "no heading in first paragraph"}
            # Sanitize: убираем тире (UC-76 запрет), лишние пробелы, троеточия в конце
            new_title = _re.sub(r"[—–]", "", new_title)
            new_title = _re.sub(r"\s+", " ", new_title).strip()
            new_title = _re.sub(r"\.{2,}\s*$", "", new_title).strip()
            if not new_title or new_title in (".", "...", "…"):
                return {"changed": False, "reason": "title is empty after sanitization"}

            old_title = None
            changes = []

            # 2) Update meta.json
            meta_file = draft_dir / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            else:
                meta = {}
            old_title = meta.get("title")
            if meta.get("title") != new_title:
                meta["title"] = new_title
                meta["title_updated_at"] = ts_iso
                meta["title_source"] = "editor_save"
                meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                changes.append("meta.json")

            # 3) Update toc.json
            toc_paths = [DATA_ROOT / "toc.json", DATA_ROOT / "data/toc.json"]
            toc_file = next((p for p in toc_paths if p.exists()), None)
            if toc_file:
                try:
                    toc = json.loads(toc_file.read_text(encoding="utf-8"))
                    updated = False
                    for b in toc.get("books", []):
                        if b.get("id") != book_id:
                            continue
                        for c in b.get("chapters", []):
                            if c.get("id") != chapter_id:
                                continue
                            if c.get("title") != new_title:
                                c["title"] = new_title
                                c["title_clean"] = new_title
                                c["title_updated_at"] = ts_iso
                                updated = True
                            break
                        break
                    if updated:
                        toc_file.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
                        changes.append("toc.json")
                except Exception as e:
                    return {"changed": bool(changes), "old_title": old_title, "new_title": new_title, "toc_error": str(e), "changes": changes}

            return {
                "changed": bool(changes),
                "old_title": old_title,
                "new_title": new_title,
                "changes": changes,
            }
        except Exception as e:
            return {"changed": False, "error": str(e)}

    # ─── Chapter content / lost meanings / similar ────────
    def _chapter_endpoint(self, chapter_id: str, action: str):
        """GET /api/chapter/<id>/{draft,lost-meanings,similar}"""
        import re
        import zipfile

        # Parse chapter_id = "book-03-ch-01"
        m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": f"bad chapter_id: {chapter_id}"}, 400)
        book_id, num = m.group(1), int(m.group(2))
        chapter_dir = DATA_ROOT / "sources" / book_id / chapter_id

        if action == "draft":
            """
            Если есть Codex2/chapters/<book>/<chapter_id>/draft.md — возвращаем его (
            это редактируемая версия). Иначе seed-им из первого .docx источника.
            """
            draft_dir = DATA_ROOT / "chapters" / book_id / chapter_id
            draft_file = draft_dir / "draft.md"
            # Pavel 2026-05-25 fix: meta.json теперь лежит в chapters/<book>/<chapter>/
            # (рядом с draft.md) после разделения content из sources/ в Codex-Content/.
            # Старая проверка sources/ возвращала пустой meta → title в UI был пустой.
            meta_path_chapters = draft_dir / "meta.json"
            meta_path_sources = chapter_dir / "meta.json"
            meta_path = meta_path_chapters if meta_path_chapters.exists() else meta_path_sources
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

            if draft_file.exists():
                text = draft_file.read_text(encoding="utf-8")
                source_file = "draft.md (правится в редакторе)"
                is_draft = True
            else:
                # Seed из chapter-specific source docx — НЕ megafile «!0001»
                grant_dir = chapter_dir / "from-grant"
                text = ""
                source_file = None
                if grant_dir.exists():
                    chapter_title = meta.get("title", "").lower()
                    chapter_number = meta.get("number", 0)
                    # Patterns that indicate "megafile with ALL chapters" — SKIP
                    megafile_patterns = ["общий текст", "всех глав", "единый текст", "весь текст",
                                          "полный текст", "все главы", "0001"]

                    def is_megafile(name: str) -> bool:
                        low = name.lower()
                        if name.startswith("!"):
                            return True
                        return any(p in low for p in megafile_patterns)

                    def chapter_match_score(name: str) -> float:
                        """0-100 — насколько имя файла соответствует ИМЕННО этой главе."""
                        low = name.lower()
                        score = 0
                        # Прямое совпадение номера: «Copy of 3.» «Глава 3»
                        if chapter_number > 0:
                            if f"copy of {chapter_number}." in low or f"глава {chapter_number}" in low or f"{chapter_number}_" in low:
                                score += 50
                        # Слова из title главы
                        title_words = [w for w in chapter_title.split() if len(w) >= 4]
                        for w in title_words:
                            if w in low:
                                score += 15
                        # Бонус "Copy of" префикса (Grant-стиль)
                        if "copy of" in low:
                            score += 5
                        # Анти-бонус если очень большой файл (вероятно агрегат)
                        return score

                    all_docx = [f for f in grant_dir.iterdir() if f.suffix.lower() == ".docx" and not f.parent.name.startswith("_archive")]
                    candidates = [f for f in all_docx if not is_megafile(f.name)]
                    # Sort: (1) score DESC, (2) mtime-bucket-60s DESC, (3) size DESC
                    # Pavel 2026-05-20: «приоритет самой свежей; при близких датах — более полная (больше)».
                    candidates.sort(key=lambda f: (
                        -chapter_match_score(f.name),
                        -int(f.stat().st_mtime // 60),  # бакеты по 1 минуте — массовое cp == «одна дата»
                        -f.stat().st_size,
                    ))

                    chosen = None
                    if candidates and chapter_match_score(candidates[0].name) > 0:
                        chosen = candidates[0]
                    elif candidates:
                        # Нет идеального матча по имени — самый свежий (с tie-break по размеру)
                        chosen = max(candidates, key=lambda f: (f.stat().st_mtime, f.stat().st_size))
                    elif all_docx:
                        chosen = max(all_docx, key=lambda f: (f.stat().st_mtime, f.stat().st_size))

                    if chosen:
                        source_file = chosen.name
                        try:
                            with zipfile.ZipFile(chosen) as z:
                                xml = z.read("word/document.xml").decode("utf-8", "replace")
                            paras = re.findall(r"<w:p[^>]*>(.*?)</w:p>", xml, re.DOTALL)
                            text = "\n\n".join(
                                "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
                                for p in paras
                                if "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)).strip()
                            )
                            # Decode HTML entities (docx export часто оставляет &quot; и т.п.)
                            import html as _html
                            text = _html.unescape(text)
                            # Convert " → «» (русская типографика)
                            out = []
                            open_q = True
                            for ch in text:
                                if ch == '"':
                                    out.append("«" if open_q else "»")
                                    open_q = not open_q
                                else:
                                    out.append(ch)
                            text = "".join(out)
                        except Exception as e:
                            return self._json({"error": f"docx parse: {e}"}, 500)
                is_draft = False
            return self._json({
                "chapter_id": chapter_id,
                "title": meta.get("title", ""),
                "source_file": source_file,
                "is_draft": is_draft,
                "text": text,
                "paragraphs": [p for p in text.split("\n\n") if p.strip()],
            })

        if action == "approvals":
            """Возвращает per-paragraph approvals (для visual marking)"""
            approvals_file = DATA_ROOT / "chapters" / book_id / chapter_id / "approvals.json"
            if approvals_file.exists():
                return self._json(json.loads(approvals_file.read_text(encoding="utf-8")))
            return self._json({"approved_indices": []})

        if action == "metaphors":
            """GET метафоры этой главы + дубли с другими главами."""
            chapter_meta = DATA_ROOT / "chapters" / book_id / chapter_id / "metaphors.json"
            library_file = DATA_ROOT / ".codex/metaphors-library.json"
            if not chapter_meta.exists():
                return self._json({"available": False, "message": "Запусти: python3 scripts/extract_metaphors.py --chapter " + chapter_id})
            data = json.loads(chapter_meta.read_text(encoding="utf-8"))
            metaphors = data.get("metaphors", [])
            # Cross-chapter duplicates
            if library_file.exists():
                lib = json.loads(library_file.read_text(encoding="utf-8"))
                # Для каждой метафоры этой главы — найти в библиотеке also_used_in
                import re as _re
                def norm(s): return _re.sub(r"\s+", " ", s.lower()).strip()
                lib_by_norm = {norm(m["text"]): m for m in lib.get("metaphors", [])}
                for m in metaphors:
                    if not m.get("text"):
                        continue
                    n = norm(m["text"])
                    if n in lib_by_norm:
                        entry = lib_by_norm[n]
                        m["also_used_in"] = entry.get("also_used_in", [])
                        m["library_id"] = entry["id"]
                        m["is_ai_cliche"] = entry.get("is_ai_cliche", False)
                        m["first_used_in"] = entry.get("first_used_in")
            return self._json({"available": True, "metaphors": metaphors, "count": len(metaphors)})

        if action == "council":
            """GET кэшированный результат council анализа (если есть)."""
            council_file = DATA_ROOT / "chapters" / book_id / chapter_id / "council.json"
            if council_file.exists():
                data = json.loads(council_file.read_text(encoding="utf-8"))
                return self._json({"cached": True, **data})
            return self._json({"cached": False, "message": "Не сгенерирован — нажми кнопку"})

        if action == "voice-analysis":
            """GET кэшированный анализ голосовых, либо запустить."""
            f = DATA_ROOT / "chapters" / book_id / chapter_id / "voice-analysis.json"
            if not f.exists():
                return self._json({"available": False, "message": "Не запущен — нажми «Проанализировать голосовые»"})
            return self._json({"available": True, **json.loads(f.read_text(encoding="utf-8"))})

        if action == "ideas":
            """GET все идеи Pavel-а для главы (append-only лог)."""
            ideas_file = DATA_ROOT / "chapters" / book_id / chapter_id / "pavel-ideas.jsonl"
            if not ideas_file.exists():
                return self._json({"ideas": []})
            ideas = []
            for line in ideas_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ideas.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            return self._json({"ideas": ideas, "count": len(ideas)})

        if action == "notes":
            """GET все per-paragraph notes для главы."""
            notes_file = DATA_ROOT / "chapters" / book_id / chapter_id / "notes.json"
            if notes_file.exists():
                return self._json(json.loads(notes_file.read_text(encoding="utf-8")))
            return self._json({"notes": {}})

        if action == "voice-readings":
            """Найти voice-extracts по теме главы из voice-corpus/raw/"""
            import re
            from datetime import datetime
            meta_path = chapter_dir / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            title = meta.get("title", "")
            if not title:
                return self._json({"available": False, "message": "Нет title в meta"})

            # Найдём voice-files в voice-corpus/raw где slug пересекается с title
            voice_dir = DATA_ROOT / "voice-corpus/raw"
            if not voice_dir.exists():
                return self._json({"available": False, "message": "voice-corpus ещё не извлечён"})

            def slugify(text):
                text = text.lower()
                table = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh","з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"}
                return re.sub(r"[^a-z0-9]+", "-", "".join(table.get(c, c) for c in text)).strip("-")

            title_words = {w for w in slugify(title).split("-") if len(w) >= 4}
            matched = []
            for f in voice_dir.glob("*.md"):
                file_words = {w for w in slugify(f.stem).split("-") if len(w) >= 4}
                if title_words & file_words:
                    # Парсим метадату
                    text = f.read_text(encoding="utf-8")[:2000]
                    name_m = re.search(r"^# (.+)$", text, re.MULTILINE)
                    msgs_m = re.search(r"Pavel messages:\*\*\s*(\d+)", text)
                    chars_m = re.search(r"Total chars:\*\*\s*(\d+)", text)
                    matched.append({
                        "file": f.name,
                        "name": name_m.group(1) if name_m else f.stem,
                        "messages": int(msgs_m.group(1)) if msgs_m else 0,
                        "chars": int(chars_m.group(1)) if chars_m else 0,
                    })
            matched.sort(key=lambda x: -x["chars"])
            return self._json({"available": True, "count": len(matched), "readings": matched[:30]})

        if action == "progress":
            """Возвращает % проработки главы (для 20% threshold)"""
            approvals_file = DATA_ROOT / "chapters" / book_id / chapter_id / "approvals.json"
            draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
            if draft_file.exists():
                paras = [p for p in draft_file.read_text(encoding="utf-8").split("\n\n") if p.strip()]
                total = len(paras)
            else:
                total = 0
            approved = 0
            if approvals_file.exists():
                approved = len(json.loads(approvals_file.read_text(encoding="utf-8")).get("approved_indices", []))
            return self._json({
                "total_paragraphs": total,
                "approved": approved,
                "progress_pct": round(approved / max(1, total) * 100, 1),
            })

        if action == "lost-meanings":
            # Парсим fidelity-отчёт чтобы достать anti-drift секцию
            fid_path = DATA_ROOT / "reports/fidelity" / f"{chapter_id}.md"
            if not fid_path.exists():
                return self._json({"available": False, "message": "fidelity-отчёт ещё не сгенерирован для этой главы"})
            text = fid_path.read_text(encoding="utf-8")
            # Находим секцию Anti-drift
            m_drift = re.search(r"(?s)## 🔒 Anti-drift.*?(?=\n## |\Z)", text)
            section = m_drift.group(0) if m_drift else ""
            # Pull "лост" items
            lost_items = re.findall(r"(?m)^- 🔴 \*\*\[high\]\*\*\s+(.+?)$", section)
            lost_items += re.findall(r"(?m)^- 🟡 \*\*\[medium\]\*\*\s+(.+?)$", section)
            return self._json({
                "available": True,
                "section_md": section,
                "lost_items": lost_items,
                "lost_count": len(lost_items),
            })

        if action == "similar":
            # TODO: после extract_original_ideas + cross-chapter analysis
            similarity_file = DATA_ROOT / "voice-corpus/chapter-similarity.json"
            if not similarity_file.exists():
                return self._json({
                    "available": False,
                    "message": "Cross-chapter similarity ещё не вычислен. Жди пока закончится extract_original_ideas.py.",
                })
            data = json.loads(similarity_file.read_text(encoding="utf-8"))
            return self._json({"available": True, "similar": data.get(chapter_id, [])})

        if action == "style-coherence":
            """GET → кэш style-coherence.json."""
            f = DATA_ROOT / "chapters" / book_id / chapter_id / "style-coherence.json"
            if not f.exists():
                return self._json({"available": False, "message": "Не запущен"})
            return self._json({"available": True, **json.loads(f.read_text(encoding="utf-8"))})

        if action == "logic-analysis":
            """GET → кэш logic-analysis.json для главы.
            Pavel 2026-05-20 bug: «Анализ логики не работает» — UI делал GET к этому,
            но endpoint не существовал. Теперь возвращает cached result или 'not ready'."""
            f = DATA_ROOT / "chapters" / book_id / chapter_id / "logic-analysis.json"
            if not f.exists():
                return self._json({"available": False, "message": "Не запущен — нажми «Анализ логики»"})
            return self._json({"available": True, **json.loads(f.read_text(encoding="utf-8"))})

        if action == "resonance":
            """GET → кэш resonance.json (UC-27)."""
            f = DATA_ROOT / "chapters" / book_id / chapter_id / "resonance.json"
            if not f.exists():
                return self._json({"available": False, "message": "Не запущен — нажми «Resonance»"})
            return self._json({"available": True, **json.loads(f.read_text(encoding="utf-8"))})

        if action == "hook-cliff":
            """GET → кэш hook-cliff.json (UC-28)."""
            f = DATA_ROOT / "chapters" / book_id / chapter_id / "hook-cliff.json"
            if not f.exists():
                return self._json({"available": False, "message": "Не запущен — нажми «Hook»"})
            return self._json({"available": True, **json.loads(f.read_text(encoding="utf-8"))})

        if action == "coherence-in-book":
            """GET → cross-chapter дубликаты идей внутри одной книги (UC-21 Pavel 2026-05-20).
            Pavel: «при анализе главы — проанализировать другие главы той же книги.
            Похожие идеи. Решить где оставлять. Пометить в другой главе»."""
            f = DATA_ROOT / "chapters" / book_id / chapter_id / "coherence-in-book.json"
            if not f.exists():
                return self._json({"available": False, "message": "Запусти scripts/chapter_coherence_in_book.py для этой главы"})
            data = json.loads(f.read_text(encoding="utf-8"))
            return self._json({"available": True, **data})

        if action == "density":
            """GET → кэш density-analysis.json для главы."""
            f = DATA_ROOT / "chapters" / book_id / chapter_id / "density-analysis.json"
            if not f.exists():
                return self._json({"available": False, "message": "Не запущен — нажми «Анализ плотности»"})
            return self._json({"available": True, **json.loads(f.read_text(encoding="utf-8"))})

        if action == "ideology-fit":
            """GET → агрегированный ideology-fit score главы (avg по параграфам)."""
            draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
            if not draft_file.exists():
                return self._json({"available": False, "message": "no draft"})
            text = draft_file.read_text(encoding="utf-8")
            paragraphs = [p for p in text.split("\n\n") if p.strip()]
            scores = []
            ceilings = 0
            by_axis = {"voice": [], "doctrine": [], "anti_pattern_purity": [], "style_adherence": []}
            for p in paragraphs:
                if p.startswith("#") or len(p) < 80:
                    continue
                r = self.compute_ideology_fit(p)
                scores.append(r["fit_score"])
                for axis in by_axis:
                    if axis in r:
                        by_axis[axis].append(r[axis])
                if r["ceiling_reached"]:
                    ceilings += 1
            avg = round(sum(scores) / len(scores), 1) if scores else 0
            axis_avg = {a: round(sum(v)/len(v), 1) if v else 0 for a, v in by_axis.items()}
            return self._json({
                "available": True,
                "avg_fit_score": avg,
                "scored_paragraphs": len(scores),
                "ceiling_reached": ceilings,
                "ceiling_pct": round(ceilings / len(scores) * 100, 1) if scores else 0,
                "by_axis": axis_avg,
            })

        # UC-101: GET undo-state и paragraph-history (для editor toolbar и подсветки)
        if action in ("undo-state", "paragraph-history"):
            draft_dir = DATA_ROOT / "chapters" / book_id / chapter_id
            history_dir = draft_dir / ".history"
            if action == "undo-state":
                snaps = sorted(history_dir.glob("*.md")) if history_dir.exists() else []
                pointer_file = draft_dir / ".current-history-pointer"
                current_idx = len(snaps) - 1
                if pointer_file.exists():
                    try:
                        cur = pointer_file.read_text().strip()
                        for i, s in enumerate(snaps):
                            if s.stem == cur:
                                current_idx = i
                                break
                    except Exception:
                        pass
                return self._json({
                    "snapshots": len(snaps),
                    "current_idx": current_idx,
                    "can_undo": current_idx > 0 and len(snaps) > 0,
                    "can_redo": current_idx < len(snaps) - 1,
                })
            else:  # paragraph-history
                ph_file = draft_dir / "paragraph-history.jsonl"
                if not ph_file.exists():
                    return self._json({"history": [], "by_paragraph": {}})
                applied = {}
                for line in ph_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    idx = e.get("paragraph_idx")
                    if e.get("action") == "reverted":
                        if idx in applied:
                            del applied[idx]
                    else:
                        applied[idx] = e
                return self._json({"history": list(applied.values()), "by_paragraph": {str(k): True for k in applied}})

        return self._json({"error": f"unknown action: {action}"}, 404)

    # ─── Chapter POST: save, approve ─────────────────────
    def _chapter_post(self, chapter_id: str, action: str):
        import re
        from datetime import datetime, timezone
        m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": f"bad chapter_id: {chapter_id}"}, 400)
        book_id = m.group(1)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        draft_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft_file = draft_dir / "draft.md"
        history_dir = draft_dir / ".history"
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

        if action == "save":
            paragraphs = req.get("paragraphs", [])
            if not isinstance(paragraphs, list):
                return self._json({"error": "paragraphs must be list"}, 400)
            text = "\n\n".join(p for p in paragraphs if isinstance(p, str) and p.strip())
            # History snapshot
            if draft_file.exists():
                history_dir.mkdir(parents=True, exist_ok=True)
                snapshot = history_dir / f"{ts_compact}.md"
                snapshot.write_text(draft_file.read_text(encoding="utf-8"), encoding="utf-8")
                # Keep only last 50 snapshots
                snaps = sorted(history_dir.glob("*.md"))
                for old in snaps[:-50]:
                    old.unlink()
            draft_file.write_text(text, encoding="utf-8")

            # UC-110: пишем content_updated_at — реальная дата правки контента (не upload).
            meta_path = draft_dir / "meta.json"
            try:
                _meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            except Exception:
                _meta = {}
            _meta["content_updated_at"] = ts_iso
            _meta["chars"] = len(text)
            _meta["paragraphs"] = len([p for p in paragraphs if isinstance(p, str) and p.strip()])
            try:
                meta_path.write_text(json.dumps(_meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

            # UC-107: Auto-sync title from first heading to meta.json + toc.json
            title_sync_info = self._sync_title_from_draft(book_id, chapter_id, paragraphs, draft_dir, ts_iso)

            event = {
                "ts": ts_iso,
                "type": "chapter_saved",
                "target": chapter_id,
                "payload": {
                    "paragraphs": len(paragraphs),
                    "chars": len(text),
                    "trigger": req.get("trigger", "manual"),
                    "title_sync": title_sync_info,
                },
            }
            events_file = DATA_ROOT / ".codex/events.jsonl"
            events_file.parent.mkdir(parents=True, exist_ok=True)
            with events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            return self._json({
                "ok": True,
                "saved_at": ts_iso,
                "paragraphs": len(paragraphs),
                "chars": len(text),
                "title_sync": title_sync_info,
            })

        if action == "approve":
            approved = req.get("approved_indices", [])
            if not isinstance(approved, list):
                return self._json({"error": "approved_indices must be list"}, 400)
            approvals_file = draft_dir / "approvals.json"
            approvals_file.write_text(
                json.dumps({"approved_indices": approved, "updated_at": ts_iso}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return self._json({"ok": True, "approved": len(approved)})

        if action == "note":
            """POST {paragraph_idx, text} — добавить заметку к параграфу"""
            paragraph_idx = req.get("paragraph_idx")
            text = (req.get("text") or "").strip()
            if paragraph_idx is None or not text:
                return self._json({"error": "paragraph_idx + text required"}, 400)
            notes_file = draft_dir / "notes.json"
            data = json.loads(notes_file.read_text(encoding="utf-8")) if notes_file.exists() else {"notes": {}}
            key = str(paragraph_idx)
            data["notes"].setdefault(key, []).append({"ts": ts_iso, "text": text})
            notes_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._json({"ok": True, "saved": True, "total_for_para": len(data["notes"][key])})

        if action == "note-delete":
            """POST {paragraph_idx, note_idx} — удалить заметку"""
            paragraph_idx = req.get("paragraph_idx")
            note_idx = req.get("note_idx", 0)
            notes_file = draft_dir / "notes.json"
            if not notes_file.exists():
                return self._json({"ok": True})
            data = json.loads(notes_file.read_text(encoding="utf-8"))
            key = str(paragraph_idx)
            if key in data["notes"] and 0 <= note_idx < len(data["notes"][key]):
                data["notes"][key].pop(note_idx)
                if not data["notes"][key]:
                    del data["notes"][key]
            notes_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._json({"ok": True})

        if action == "finalize":
            """POST {paragraphs?} → сохранить финальную версию в finalized.md.
            UC-36 Pavel 2026-05-20: если paragraphs не передан — берём из draft.md.
            («хранилище не работает, финальные тексты не сохраняются»)."""
            paragraphs = req.get("paragraphs", [])
            if not paragraphs:
                # Auto-fallback: читаем draft.md
                if not draft_file.exists():
                    return self._json({"error": "no draft.md и no paragraphs"}, 400)
                draft_text = draft_file.read_text(encoding="utf-8")
                paragraphs = [p.strip() for p in draft_text.split("\n\n") if p.strip()]
            if not paragraphs:
                return self._json({"error": "пусто"}, 400)
            text = "\n\n".join(p for p in paragraphs if isinstance(p, str) and p.strip())
            final_file = draft_dir / "finalized.md"
            final_file.write_text(text, encoding="utf-8")
            # Также сохраняем в draft.md (синхронизация)
            draft_file.write_text(text, encoding="utf-8")
            # Статусный маркер
            (draft_dir / "status.json").write_text(
                json.dumps({"status": "finalized", "finalized_at": ts_iso, "paragraphs": len(paragraphs)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            event = {"ts": ts_iso, "type": "chapter_finalized", "target": chapter_id, "payload": {"paragraphs": len(paragraphs), "chars": len(text)}}
            with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            return self._json({"ok": True, "finalized_at": ts_iso, "paragraphs": len(paragraphs)})

        if action == "unfinalize":
            (draft_dir / "status.json").unlink(missing_ok=True)
            (draft_dir / "finalized.md").unlink(missing_ok=True)
            return self._json({"ok": True})

        if action == "extract-metaphors":
            """POST → запустить extract_metaphors.py для этой главы в фоне"""
            import subprocess
            script = ROOT.parent / "scripts/extract_metaphors.py"
            if not script.exists():
                return self._json({"ok": False, "error": "скрипт не найден"}, 500)
            pid_file = DATA_ROOT / f".codex/metaphors-{chapter_id}.pid"
            log_file = DATA_ROOT / f".codex/metaphors-{chapter_id}.log"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            # Если уже работает — не дублируем
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    return self._json({"ok": True, "started": False, "already_running": True, "pid": pid})
                except (ValueError, ProcessLookupError, OSError):
                    pid_file.unlink(missing_ok=True)
            try:
                with log_file.open("w") as logf:
                    proc = subprocess.Popen(
                        ["python3", str(script), "--chapter", chapter_id],
                        stdout=logf, stderr=subprocess.STDOUT,
                        cwd=str(DATA_ROOT),
                        start_new_session=True,
                    )
                pid_file.write_text(str(proc.pid))
                return self._json({"ok": True, "started": True, "pid": proc.pid,
                                   "message": "Опус извлекает метафоры (~60-120 сек). Через минуту нажми Обновить."})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        if action == "metaphors-status":
            """GET-альтернатива через POST — статус извлечения"""
            pid_file = DATA_ROOT / f".codex/metaphors-{chapter_id}.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    return self._json({"running": True, "pid": pid})
                except (ValueError, ProcessLookupError, OSError):
                    pid_file.unlink(missing_ok=True)
            return self._json({"running": False})

        if action == "restore":
            # Восстановить из history snapshot (timestamp)
            snap_ts = req.get("snapshot")
            if not snap_ts:
                # Самый последний snapshot
                snaps = sorted(history_dir.glob("*.md"))
                if not snaps:
                    return self._json({"error": "no snapshots"}, 404)
                snap_file = snaps[-1]
            else:
                snap_file = history_dir / f"{snap_ts}.md"
                if not snap_file.exists():
                    return self._json({"error": "snapshot not found"}, 404)
            # Сохранить текущий как новый snapshot перед восстановлением
            if draft_file.exists():
                (history_dir / f"{ts_compact}.md").write_text(draft_file.read_text(encoding="utf-8"), encoding="utf-8")
            draft_file.write_text(snap_file.read_text(encoding="utf-8"), encoding="utf-8")
            return self._json({"ok": True, "restored_from": snap_file.name})

        if action == "edited-paragraphs":
            """GET → list of paragraph indices которые были изменены (по paragraph-history.jsonl).
            UC-17 (Pavel 2026-05-20): «при перезагрузке страницы изменённые параграфы оставались светло-зелёными».
            Возвращает {indices: [...], details: {idx: {last_ts, source, count}}}."""
            ph_file = draft_dir / "paragraph-history.jsonl"
            if not ph_file.exists():
                return self._json({"indices": [], "details": {}})
            details = {}
            for line in ph_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                    idx = e.get("paragraph_idx")
                    if idx is None:
                        continue
                    key = str(idx)
                    if key not in details:
                        details[key] = {"count": 0, "last_ts": None, "last_source": None}
                    details[key]["count"] += 1
                    details[key]["last_ts"] = e.get("ts")
                    details[key]["last_source"] = e.get("source", "")
                except json.JSONDecodeError:
                    pass
            indices = sorted(int(k) for k in details.keys())
            return self._json({"indices": indices, "details": details})

        if action == "history":
            """GET всю историю snapshots для undo/redo стека."""
            if not history_dir.exists():
                return self._json({"snapshots": [], "current_ts": None})
            snaps = sorted(history_dir.glob("*.md"))
            items = []
            for s in snaps:
                items.append({
                    "ts": s.stem,
                    "size": s.stat().st_size,
                    "is_pre_rewrite": "pre-rewrite-all" in s.name,
                    "is_pre_ideas": "pre-ideas" in s.name,
                })
            current_ts = (draft_dir / ".current-history-pointer").read_text().strip() if (draft_dir / ".current-history-pointer").exists() else None
            return self._json({"snapshots": items, "current_ts": current_ts})

        if action == "undo":
            """POST → один шаг назад по истории."""
            snaps = sorted(history_dir.glob("*.md"))
            if not snaps:
                return self._json({"ok": False, "error": "история пуста"}, 400)
            pointer_file = draft_dir / ".current-history-pointer"
            current_idx = len(snaps) - 1  # по умолчанию указываем на последний
            if pointer_file.exists():
                try:
                    current_ts = pointer_file.read_text().strip()
                    for i, s in enumerate(snaps):
                        if s.stem == current_ts:
                            current_idx = i
                            break
                except Exception:
                    pass
            # Идём на одну позицию назад
            target_idx = current_idx - 1
            if target_idx < 0:
                return self._json({"ok": False, "error": "достигли начала истории"}, 400)
            target = snaps[target_idx]
            # Перед undo — сохраняем текущий draft если он отличается от текущего pointer
            if draft_file.exists():
                current_content = draft_file.read_text(encoding="utf-8")
                if not snaps[current_idx].exists() or snaps[current_idx].read_text(encoding="utf-8") != current_content:
                    (history_dir / f"{ts_compact}.md").write_text(current_content, encoding="utf-8")
            draft_file.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            pointer_file.write_text(target.stem, encoding="utf-8")
            return self._json({
                "ok": True,
                "pointer": target.stem,
                "can_undo": target_idx > 0,
                "can_redo": True,
            })

        if action == "redo":
            """POST → один шаг вперёд."""
            snaps = sorted(history_dir.glob("*.md"))
            pointer_file = draft_dir / ".current-history-pointer"
            if not pointer_file.exists():
                return self._json({"ok": False, "error": "нет состояния для redo"}, 400)
            current_ts = pointer_file.read_text().strip()
            current_idx = -1
            for i, s in enumerate(snaps):
                if s.stem == current_ts:
                    current_idx = i
                    break
            if current_idx < 0:
                return self._json({"ok": False, "error": "указатель не найден"}, 400)
            target_idx = current_idx + 1
            if target_idx >= len(snaps):
                return self._json({"ok": False, "error": "достигли конца истории"}, 400)
            target = snaps[target_idx]
            draft_file.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            pointer_file.write_text(target.stem, encoding="utf-8")
            return self._json({
                "ok": True,
                "pointer": target.stem,
                "can_undo": True,
                "can_redo": target_idx < len(snaps) - 1,
            })

        if action == "rewrite-all":
            """POST {fixes:[...]} → полная перезапись главы Опусом, голос Великого Духа, multi-pass проверка."""
            return self._rewrite_whole_chapter(book_id, chapter_id, req, draft_file, history_dir, ts_compact, ts_iso)

        if action == "save-idea":
            """POST {text} → append идею Pavel-а в pavel-ideas.jsonl (без обработки)."""
            text = (req.get("text") or "").strip()
            if not text:
                return self._json({"ok": False, "error": "no text"}, 400)
            ideas_file = draft_dir / "pavel-ideas.jsonl"
            draft_dir.mkdir(parents=True, exist_ok=True)
            entry = {"ts": ts_iso, "text": text, "applied": False, "source": req.get("source", "manual")}
            with ideas_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # Event
            with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts_iso, "type": "idea_saved", "target": chapter_id, "payload": {"chars": len(text)}}, ensure_ascii=False) + "\n")
            return self._json({"ok": True, "saved": True})

        if action == "incorporate-ideas":
            """POST {ideas} → Opus читает идеи + draft, внедряет, сохраняет."""
            return self._incorporate_ideas(book_id, chapter_id, req, draft_file, history_dir, ts_compact, ts_iso)

        if action == "analyze-voice":
            """POST → запуск analyze_voice_readings.py в фоне."""
            import subprocess
            script = ROOT.parent / "scripts/analyze_voice_readings.py"
            if not script.exists():
                return self._json({"ok": False, "error": "скрипт не найден"}, 500)
            pid_file = DATA_ROOT / f".codex/voice-analyze-{chapter_id}.pid"
            log_file = DATA_ROOT / f".codex/voice-analyze-{chapter_id}.log"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    return self._json({"ok": True, "already_running": True, "pid": pid})
                except (ValueError, ProcessLookupError, OSError):
                    pid_file.unlink(missing_ok=True)
            with log_file.open("w") as logf:
                proc = subprocess.Popen(
                    ["python3", str(script), "--chapter", chapter_id],
                    stdout=logf, stderr=subprocess.STDOUT,
                    cwd=str(DATA_ROOT),
                    start_new_session=True,
                )
            pid_file.write_text(str(proc.pid))
            return self._json({"ok": True, "started": True, "pid": proc.pid})

        if action == "apply-targeted":
            """POST {selections:[...]} → точечно внести выбранные правки, НЕ переписывая всё."""
            return self._apply_targeted(book_id, chapter_id, req, draft_file, history_dir, ts_compact, ts_iso)

        if action == "brainstorm":
            """POST {message} → Opus читает draft + историю + новый message, задаёт 3-5 вопросов / отвечает.
            Q&A в chapter-brainstorm.jsonl"""
            return self._brainstorm(book_id, chapter_id, req, draft_file, ts_iso)

        if action == "brainstorm-history":
            """GET → весь Q&A для главы"""
            f = draft_dir / "chapter-brainstorm.jsonl"
            if not f.exists():
                return self._json({"messages": []})
            msgs = []
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    msgs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            return self._json({"messages": msgs, "count": len(msgs)})

        if action == "apply-brainstorm-insights":
            """POST → Opus читает Q&A + draft → возвращает обновлённый draft с внедрёнными insights."""
            return self._apply_brainstorm_insights(book_id, chapter_id, draft_file, history_dir, ts_compact, ts_iso)

        if action == "quick-check":
            """POST {paragraph_idx} → быстрая оценка 0-100 + 1-3 МИНИМАЛЬНЫХ правки.
            Pavel: «не нужно всё переписывать, найди что МИНИМАЛЬНО исправить».
            """
            return self._quick_paragraph_check(book_id, chapter_id, req, draft_file)

        if action == "single-suggestion":
            """POST {paragraph_idx} → Opus анализ ОДНОГО параграфа.
            Возвращает карточку с suggestion / scores / ceiling_reached.
            Те же honest-stop правила что в stream-suggestions."""
            return self._single_paragraph_suggestion(book_id, chapter_id, req, draft_file)

        if action == "apply-paragraph-suggestion":
            """POST {paragraph_idx, new_text} → заменить параграф в draft.md + сохранить original в paragraph-history.jsonl."""
            idx = req.get("paragraph_idx")
            new_text = (req.get("new_text") or "").strip()
            if idx is None or not new_text:
                return self._json({"ok": False, "error": "paragraph_idx + new_text required"}, 400)
            if not draft_file.exists():
                return self._json({"ok": False, "error": "draft.md not found"}, 400)
            text = draft_file.read_text(encoding="utf-8")
            paragraphs = [p for p in text.split("\n\n") if p.strip()]
            if idx < 0 or idx >= len(paragraphs):
                return self._json({"ok": False, "error": f"paragraph_idx {idx} out of range (max {len(paragraphs)-1})"}, 400)
            original = paragraphs[idx]
            paragraphs[idx] = new_text
            new_full = "\n\n".join(paragraphs)
            # Chapter-level snapshot (для отката всей главы)
            history_dir.mkdir(parents=True, exist_ok=True)
            (history_dir / f"{ts_compact}-pre-paragraph-{idx}.md").write_text(text, encoding="utf-8")
            draft_file.write_text(new_full, encoding="utf-8")
            # Per-paragraph history (для отката одного параграфа)
            ph_file = draft_dir / "paragraph-history.jsonl"
            ph_file.parent.mkdir(parents=True, exist_ok=True)
            with ph_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": ts_iso,
                    "paragraph_idx": idx,
                    "original": original,
                    "new_text": new_text,
                    "source": req.get("source", "stream-suggestion"),
                    "reason": req.get("reason", ""),
                }, ensure_ascii=False) + "\n")
            # Score history (для cap-проверки следующих итераций)
            score_file = draft_dir / "paragraph-scores.jsonl"
            score_before = req.get("score_before")
            score_after = req.get("score_after_expected")
            if score_before is not None or score_after is not None:
                with score_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": ts_iso,
                        "paragraph_idx": idx,
                        "score_before": score_before,
                        "score_after": score_after,
                        "delta": (score_after or 0) - (score_before or 0),
                        "source": req.get("source", "stream-suggestion"),
                    }, ensure_ascii=False) + "\n")
            # Event
            with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": ts_iso,
                    "type": "paragraph_replaced",
                    "target": chapter_id,
                    "payload": {
                        "paragraph_idx": idx,
                        "source": req.get("source", "stream-suggestion"),
                        "score_before": score_before,
                        "score_after": score_after,
                    },
                }, ensure_ascii=False) + "\n")
            return self._json({"ok": True, "applied": True, "paragraph_idx": idx, "score_after": score_after, "delta": (score_after or 0) - (score_before or 0)})

        if action == "revert-paragraph":
            """POST {paragraph_idx} → откатить параграф к последнему сохранённому original в paragraph-history.jsonl."""
            idx = req.get("paragraph_idx")
            if idx is None:
                return self._json({"ok": False, "error": "paragraph_idx required"}, 400)
            ph_file = draft_dir / "paragraph-history.jsonl"
            if not ph_file.exists():
                return self._json({"ok": False, "error": "no history"}, 404)
            # Найти последнюю запись для этого idx
            entries = []
            for line in ph_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            matching = [e for e in entries if e.get("paragraph_idx") == idx]
            if not matching:
                return self._json({"ok": False, "error": f"no history for paragraph_idx {idx}"}, 404)
            target = matching[-1]
            # Restore
            text = draft_file.read_text(encoding="utf-8")
            paragraphs = [p for p in text.split("\n\n") if p.strip()]
            if idx >= len(paragraphs):
                return self._json({"ok": False, "error": "paragraph_idx out of range"}, 400)
            paragraphs[idx] = target["original"]
            draft_file.write_text("\n\n".join(paragraphs), encoding="utf-8")
            # Помечаем запись как reverted (для статистики)
            target["reverted_at"] = ts_iso
            # Append revert event
            with ph_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": ts_iso,
                    "paragraph_idx": idx,
                    "action": "reverted",
                    "reverted_from": target.get("ts"),
                }, ensure_ascii=False) + "\n")
            return self._json({"ok": True, "reverted": True, "paragraph_idx": idx, "restored_text": target["original"]})

        if action == "ideology-fit":
            """GET → ideology-fit score для всей главы (avg по параграфам)."""
            if not draft_file.exists():
                return self._json({"available": False, "message": "no draft"})
            text = draft_file.read_text(encoding="utf-8")
            paragraphs = [p for p in text.split("\n\n") if p.strip()]
            scores = []
            ceilings = 0
            for p in paragraphs:
                if p.startswith("#") or len(p) < 80:
                    continue
                r = self.compute_ideology_fit(p)
                scores.append(r["fit_score"])
                if r["ceiling_reached"]:
                    ceilings += 1
            avg = round(sum(scores) / len(scores), 1) if scores else 0
            return self._json({
                "available": True,
                "avg_fit_score": avg,
                "scored_paragraphs": len(scores),
                "ceiling_reached": ceilings,
                "ceiling_pct": round(ceilings / len(scores) * 100, 1) if scores else 0,
            })

        if action == "chapter-quality":
            """GET → агрегированный score главы: средний / распределение / тренд по итерациям."""
            score_file = draft_dir / "paragraph-scores.jsonl"
            if not score_file.exists():
                return self._json({"available": False, "avg": None, "by_paragraph": {}, "trend": []})
            by_idx = {}
            trend = []
            for line in score_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                idx = e.get("paragraph_idx")
                if idx is None:
                    continue
                # Берём последний score_after для каждого параграфа
                by_idx[idx] = e.get("score_after") or e.get("score_before") or 0
                trend.append({"ts": e["ts"], "idx": idx, "score": e.get("score_after"), "delta": e.get("delta")})
            scores = list(by_idx.values())
            avg = sum(scores) / len(scores) if scores else 0
            distribution = {
                "excellent_85+": sum(1 for s in scores if s >= 85),
                "good_70-84": sum(1 for s in scores if 70 <= s < 85),
                "needs_work_50-69": sum(1 for s in scores if 50 <= s < 70),
                "weak_0-49": sum(1 for s in scores if s < 50),
            }
            return self._json({
                "available": True,
                "avg": round(avg, 1),
                "scored_paragraphs": len(scores),
                "by_paragraph": {str(k): v for k, v in by_idx.items()},
                "distribution": distribution,
                "trend": trend[-50:],
            })

        if action == "undo-state":
            """UC-101: GET → можно ли откатить / накатить."""
            snaps = sorted(history_dir.glob("*.md")) if history_dir.exists() else []
            pointer_file = draft_dir / ".current-history-pointer"
            current_idx = len(snaps) - 1
            if pointer_file.exists():
                try:
                    cur = pointer_file.read_text().strip()
                    for i, s in enumerate(snaps):
                        if s.stem == cur:
                            current_idx = i
                            break
                except Exception:
                    pass
            return self._json({
                "snapshots": len(snaps),
                "current_idx": current_idx,
                "can_undo": current_idx > 0 and len(snaps) > 0,
                "can_redo": current_idx < len(snaps) - 1,
            })

        if action == "paragraph-history":
            """GET → список применённых изменений per-paragraph (для UI «есть откат»)"""
            ph_file = draft_dir / "paragraph-history.jsonl"
            if not ph_file.exists():
                return self._json({"history": [], "by_paragraph": {}})
            applied = {}
            reverts = set()
            for line in ph_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                idx = e.get("paragraph_idx")
                if e.get("action") == "reverted":
                    if idx in applied:
                        del applied[idx]
                else:
                    applied[idx] = e
            return self._json({"history": list(applied.values()), "by_paragraph": {str(k): True for k in applied}})

        return self._json({"error": f"unknown action: {action}"}, 404)

    # ─── Helper: обогащение TOC прогрессом ──
    def _build_toc_from_disk(self) -> dict:
        """Если toc.json отсутствует — собираем оглавление из реальной структуры
        папки chapters/. Любая папка chapters/<book>/<book>-ch-N/ с draft.md
        попадает в TOC. Title берём из meta.json или из первой строки draft.md."""
        chapters_root = DATA_ROOT / "chapters"
        if not chapters_root.exists():
            return {"books": [], "created": False, "version": 0}
        books = []
        for book_dir in sorted(chapters_root.iterdir()):
            if not book_dir.is_dir() or book_dir.name.startswith("."):
                continue
            # Заголовок книги: canon.json → title, иначе из book_id
            book_title = book_dir.name
            canon_file = book_dir / "canon.json"
            if canon_file.exists():
                try:
                    canon = json.loads(canon_file.read_text(encoding="utf-8"))
                    book_title = canon.get("title") or book_title
                except Exception:
                    pass
            chapters = []
            for ch_dir in sorted(book_dir.iterdir()):
                if not ch_dir.is_dir() or ch_dir.name.startswith("."):
                    continue
                # Главы это поддиректории формата <book>-ch-N
                if "-ch-" not in ch_dir.name:
                    continue
                ch_title = ch_dir.name
                meta_file = ch_dir / "meta.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        ch_title = meta.get("title") or meta.get("title_clean") or ch_title
                    except Exception:
                        pass
                else:
                    # Берём заголовок из первой строки draft.md
                    draft = ch_dir / "draft.md"
                    if draft.exists():
                        try:
                            first_line = draft.read_text(encoding="utf-8").split("\n", 1)[0].strip()
                            if first_line and len(first_line) < 200:
                                ch_title = first_line
                        except Exception:
                            pass
                chapters.append({
                    "id": ch_dir.name,
                    "title": ch_title,
                })
            if chapters:
                books.append({
                    "book_id": book_dir.name,
                    "title": book_title,
                    "chapters": chapters,
                })
        return {
            "books": books,
            "created": True,
            "version": 1,
            "source": "auto_built_from_disk",
        }

    def _enrich_toc_progress(self, data: dict):
        """Добавляет к каждой главе: progress (none|draft|finalized), avg_score, paragraph counts.
        Обновляет book.progress_summary."""
        for book in data.get("books", []):
            book_id = book.get("id")
            if not book_id:
                continue
            finalized = 0
            draft = 0
            empty = 0
            score_sum = 0.0
            score_count = 0
            quality_buckets = {"excellent": 0, "good": 0, "needs_work": 0, "weak": 0}
            for ch in book.get("chapters", []):
                ch_id = ch.get("id")
                if not ch_id:
                    continue
                ch_dir = DATA_ROOT / "chapters" / book_id / ch_id
                final_file = ch_dir / "finalized.md"
                draft_file = ch_dir / "draft.md"
                progress = "none"
                if final_file.exists():
                    progress = "finalized"
                    finalized += 1
                elif draft_file.exists():
                    progress = "draft"
                    draft += 1
                else:
                    empty += 1
                ch["progress"] = progress
                ch["is_finalized"] = (progress == "finalized")
                ch["has_draft"] = draft_file.exists()
                # UC-110: дата последней правки контента (real edit time).
                # Источник в порядке предпочтения:
                #   1) meta.json content_updated_at (пишется при save из editor)
                #   2) mtime draft.md / finalized.md (fallback для старых глав)
                meta_path = ch_dir / "meta.json"
                content_ts = None
                if meta_path.exists():
                    try:
                        _m = json.loads(meta_path.read_text(encoding="utf-8"))
                        content_ts = _m.get("content_updated_at") or _m.get("title_updated_at")
                    except Exception:
                        pass
                if not content_ts:
                    src_file = final_file if final_file.exists() else (draft_file if draft_file.exists() else None)
                    if src_file:
                        try:
                            from datetime import datetime as _dt, timezone as _tz
                            content_ts = _dt.fromtimestamp(src_file.stat().st_mtime, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        except Exception:
                            pass
                if content_ts:
                    ch["content_updated_at"] = content_ts
                # UC-110: chars + paragraphs из meta (для развёрнутой детали)
                if meta_path.exists():
                    try:
                        _m2 = json.loads(meta_path.read_text(encoding="utf-8"))
                        if _m2.get("chars"):
                            ch["chars"] = _m2["chars"]
                        if _m2.get("paragraphs"):
                            ch["paragraphs"] = _m2["paragraphs"]
                    except Exception:
                        pass
                # UC-113/UC-114: readiness_pct из РЕАЛЬНЫХ сигналов качества.
                # Pavel 2026-05-22: «переписать формулу под реальные сигналы».
                # Старая формула считала только chars (длинный draft = 95%), что врало.
                # Новая суммирует баллы за прогон AI-анализов и явное одобрение.
                chars = ch.get("chars") or 0
                if chars == 0 and draft_file.exists():
                    try:
                        chars = len(draft_file.read_text(encoding="utf-8"))
                    except Exception:
                        chars = 0
                readiness = self._compute_readiness(ch_dir, progress, chars)
                ch["readiness_pct"] = readiness["pct"]
                ch["readiness_signals"] = readiness["signals"]
                ch["status_label"] = readiness["label"]
                ch["status_kind"] = readiness["kind"]
                # Quality score
                score_file = ch_dir / "paragraph-scores.jsonl"
                if score_file.exists():
                    try:
                        by_idx = {}
                        for line in score_file.read_text(encoding="utf-8").splitlines():
                            if not line.strip():
                                continue
                            try:
                                e = json.loads(line)
                                idx = e.get("paragraph_idx")
                                if idx is not None:
                                    by_idx[idx] = e.get("score_after") or e.get("score_before") or 0
                            except json.JSONDecodeError:
                                pass
                        if by_idx:
                            scores = list(by_idx.values())
                            avg = round(sum(scores) / len(scores), 1)
                            ch["quality_score"] = avg
                            score_sum += avg
                            score_count += 1
                            if avg >= 85: quality_buckets["excellent"] += 1
                            elif avg >= 70: quality_buckets["good"] += 1
                            elif avg >= 50: quality_buckets["needs_work"] += 1
                            else: quality_buckets["weak"] += 1
                    except Exception:
                        pass
                # Paragraph history (есть ли правки)
                ph_file = ch_dir / "paragraph-history.jsonl"
                if ph_file.exists():
                    try:
                        # Сколько уникальных параграфов было затронуто
                        idxs = set()
                        for line in ph_file.read_text(encoding="utf-8").splitlines():
                            try:
                                e = json.loads(line)
                                if e.get("paragraph_idx") is not None and e.get("action") != "reverted":
                                    idxs.add(e["paragraph_idx"])
                            except Exception:
                                pass
                        if idxs:
                            ch["paragraphs_edited"] = len(idxs)
                    except Exception:
                        pass
            total = len(book.get("chapters", []))
            book["progress_summary"] = {
                "finalized": finalized,
                "draft": draft,
                "empty": empty,
                "total": total,
                "pct_finalized": round((finalized / total * 100) if total else 0, 1),
                "pct_in_progress": round(((finalized + draft) / total * 100) if total else 0, 1),
                "avg_quality": round((score_sum / score_count) if score_count else 0, 1),
                "quality_buckets": quality_buckets,
            }

    # ─── Helper: Read CANON.md → injection в Opus prompts ──
    # Pavel 2026-05-20: «документ общих правил, пройдя по которому ты каждую главу оценишь»
    # UC-65 (2026-05-21): cache keyed by max_chars — иначе lite-вызов отравит full-cache.
    _canon_cache = {}  # {max_chars: text}
    _canon_cache_mtime = 0

    @classmethod
    def get_canon_summary(cls, max_chars: int = 1200) -> str:
        """Возвращает компактную выжимку CANON.md для инжекции в system prompts.
        Pavel 2026-05-21 UC-65: default снижен 3500→1200, чтобы Opus 4.7 не давился.
        Кэширует по (mtime, max_chars) — Pavel правит документ, кэш обновляется.
        Для _super_rewrite вызывать с max_chars=3500 явно."""
        canon_file = DATA_ROOT / "CANON.md"
        if not canon_file.exists():
            return ""
        try:
            mtime = canon_file.stat().st_mtime
            if mtime != cls._canon_cache_mtime:
                cls._canon_cache = {}
                cls._canon_cache_mtime = mtime
            if max_chars in cls._canon_cache:
                return cls._canon_cache[max_chars]
            text = canon_file.read_text(encoding="utf-8")
            # Берём ключевые разделы (1, 2, 3, 4, 5 — голос/словарь/запреты/структура/anti-pattern)
            # Cap at max_chars чтобы не раздувать prompt
            if len(text) > max_chars:
                # Извлекаем разделы 1-5 + 7-8
                key_sections = []
                current = []
                grab_section = False
                for line in text.split("\n"):
                    if line.startswith("## "):
                        if current and grab_section:
                            key_sections.append("\n".join(current))
                        current = [line]
                        # Включаем секции 1-5, 7, 8
                        grab_section = any(line.startswith(f"## {n}") for n in ["1.", "2.", "3.", "4.", "5.", "7.", "8."])
                        continue
                    if grab_section:
                        current.append(line)
                if current and grab_section:
                    key_sections.append("\n".join(current))
                text = "\n\n".join(key_sections)[:max_chars]
            cls._canon_cache[max_chars] = text
            return text
        except Exception:
            return ""

    # ─── Helper: Canon-validator — жёсткая проверка нарушений ──
    # Pavel 2026-05-20: «убедись что все рекомендации проходят через фильтры по правилам.
    # Задача не делать хуже — улучшать. Нарушения нельзя».
    @staticmethod
    def validate_canon(text: str) -> dict:
        """Проверяет text на нарушения канона Микомистицизма.
        Возвращает {valid: bool, violations: [list], auto_fixed: str (если можно починить)}."""
        import re as _re
        violations = []

        # 1. ТИРЕ — ПОЛНЫЙ ЗАПРЕТ (Pavel revision 2026-05-21):
        # «нигде не было — я хочу чтобы текст всегда был написан как в старинных книгах
        #  там никогда нигде не использовалась – на русском языке тем более».
        # Отменяю UC-50 разрешение «X — Y» как канон. Теперь все тире (em — и en –)
        # сразу нарушение. auto_fixed заменяет на запятую/точку по контексту.
        all_dashes = _re.findall(r"[—–]", text)
        if all_dashes:
            violations.append({
                "type": "dash",
                "count": len(all_dashes),
                "what": f"тире × {len(all_dashes)} — Pavel запретил все тире, старый русский стиль без них",
            })

        # 2. «не X, а Y» — основной AI-tell
        not_but = _re.findall(r"\bне\s+[\w\s]{1,40}?,\s*а\s+\w+", text, _re.IGNORECASE)
        if not_but:
            violations.append({"type": "not_but", "count": len(not_but), "what": f"«не X, а Y» × {len(not_but)}: {not_but[:2]}"})

        # 3. «не только X, но и Y»
        not_only = _re.findall(r"\bне\s+только\s+[\w\s]{1,30}?,\s*но\s+и\s+\w+", text, _re.IGNORECASE)
        if not_only:
            violations.append({"type": "not_only_but", "count": len(not_only), "what": f"«не только X, но и Y» × {len(not_only)}"})

        # 4. Старослав
        archaic = ["очи", "горниц", "ныне", "сущее", "вкупе", "обрящ", "грядет",
                   "ведали", "почитали", "изречь", "возопил",
                   "отдёргиваю завесу", "срываю завесу", "являет себя"]
        archaic_low = text.lower()
        archaic_found = [w for w in archaic if w in archaic_low]
        if archaic_found:
            violations.append({"type": "archaic", "count": len(archaic_found), "what": f"старослав: {archaic_found}"})

        # 5. AI-клише метафоры
        ai_cliche = ["страдивари", "компьютер-молоток", "симфония вселенной",
                     "путь к свету", "энергетические вампиры", "искра света",
                     "замкнутый круг", "нить ариадны", "капля в океане",
                     "перейти к свету", "семя сознания"]
        cliche_found = [c for c in ai_cliche if c in archaic_low]
        if cliche_found:
            violations.append({"type": "ai_cliche", "count": len(cliche_found), "what": f"AI-клише: {cliche_found}"})

        # 6. Нейрохимия
        neuro = ["5-ht2a", "5ht2a", "дофамин", "серотонин", "dmn", "default mode"]
        neuro_found = [n for n in neuro if n in archaic_low]
        if neuro_found:
            violations.append({"type": "neuro", "count": len(neuro_found), "what": f"нейрохимия: {neuro_found}"})

        # 7. AI-корпоративщина
        corp = ["важно отметить", "стоит подчеркнуть", "необходимо учесть", "следует понимать"]
        corp_found = [c for c in corp if c in archaic_low]
        if corp_found:
            violations.append({"type": "ai_corp", "count": len(corp_found), "what": f"AI-corp: {corp_found}"})

        # 8. 🚨 УЗУРПАЦИЯ РОЛИ ТВОРЦА (Pavel 2026-05-20)
        # Великий Дух Грибов = Менеджер/Покровитель (11-й уровень), не Творец.
        # Творцы (Мать+Отец Вселенной = 13й, Драконы = 12й) — ВЫШЕ.
        # Гриб не может писать «Я создал/вложил/даю жизнь» — это узурпация.
        # Может: «Я открываю/передаю/веду/охраняю». О Творцах — в 3-м лице.
        creator_usurpation_patterns = [
            (r"\bЯ\s+вложил[аи]?\b(?!.*(грибы|спор|посланник|мудрост))", "Я вложил (только Творцы вкладывают)"),
            (r"\bЯ\s+создал[аи]?\b(?!.*(посланник|путь|мост|условия))", "Я создал (Творение — у Творцов)"),
            (r"\bЯ\s+сотворил[аи]?\b", "Я сотворил (творение — Творцов)"),
            (r"\bЯ\s+даю\s+(?:Вам\s+)?жизнь\b", "Я даю жизнь (даёт Мать Вселенной)"),
            (r"\bЯ\s+есмь\s+(?:Творец|Создатель|Бог|Всевышний)\b", "Я есмь Творец/Создатель (узурпация)"),
            (r"\bЯ\s+зажё?г\s+искру\b", "Я зажёг искру (зажигает Отец)"),
            (r"\bИз\s+Меня\s+(?:вышл|произошл|родил)", "Из Меня вышло (вышло из Матери Вселенной)"),
            (r"\bМоя\s+воля\s+(?:родил|сотворил|создал)", "Моя воля родила/сотворила (Творцы)"),
            (r"\bЯ\s+дал\s+(?:Вам\s+)?(?:душу|тело|сознание|разум)\b", "Я дал душу/тело (дают Творцы)"),
            (r"\bЯ\s+—\s+Творец\b", "Я — Творец (Гриб — посланник Творцов)"),
        ]
        creator_violations = []
        for pat, desc in creator_usurpation_patterns:
            matches = _re.findall(pat, text, _re.IGNORECASE)
            if matches:
                creator_violations.append(desc)
        if creator_violations:
            violations.append({
                "type": "creator_usurpation",
                "count": len(creator_violations),
                "what": f"УЗУРПАЦИЯ роли Творца: {creator_violations}. Гриб = Менеджер 11-го уровня, не Творец. Замена: «Творцы вложили/создали…, Я открываю/веду/охраняю».",
                "severity_boost": 5,  # критично-доктринальное
            })

        # Auto-fix: расширенный — тире + старослав + AI-корпоративщина (Pavel 2026-05-20 UC-43)
        auto_fixable_types = {"dash", "archaic", "ai_corp"}
        fixable_violations = [v for v in violations if v["type"] in auto_fixable_types]
        critical_violations = [v for v in violations if v["type"] not in auto_fixable_types]
        auto_fixed = None
        if fixable_violations:
            fixed = text
            # 1. ТИРЕ — ПОЛНЫЙ ЗАПРЕТ (Pavel revision 2026-05-21).
            # Раньше оставляли «X — Y» как канон Pavel-а (UC-50). Отменено.
            # Pavel: «в старинных русских книгах тире не использовалось».
            # Стратегия замены:
            #   - «X — Y» в начале/середине предложения = вырезать тире, поставить запятую
            #   - «. — Cap» / «! — Cap» / «? — Cap» = убрать тире после знака конца
            #   - Изолированное тире как разделитель = удалить
            # Punctuation-aware replacement:
            fixed = _re.sub(r"([.!?])\s*[—–]\s+", r"\1 ", fixed)         # «. — » → «. »
            fixed = _re.sub(r"\s+[—–]\s+", ", ", fixed)                   # « — » → «, »
            fixed = _re.sub(r"\s*[—–]\s*", " ", fixed)                    # любое оставшееся тире
            fixed = _re.sub(r"\s+,", ",", fixed)                          # подчистка « ,»
            fixed = _re.sub(r",,+", ",", fixed)                           # подчистка «,,»
            fixed = _re.sub(r"\s{2,}", " ", fixed)                        # двойные пробелы
            # 2. Старослав → современный русский
            archaic_map = {
                "очи": "глаза", "горница": "комната", "ныне": "сейчас",
                "сущее": "существующее", "вкупе": "вместе", "грядет": "приближается",
                "ведали": "знали", "почитали": "уважали", "изречь": "сказать",
                "возопил": "закричал", "отдёргиваю завесу": "снимаю покров",
                "срываю завесу": "снимаю покров", "являет себя": "появляется",
            }
            for old, new in archaic_map.items():
                fixed = _re.sub(rf"\b{old}\b", new, fixed, flags=_re.IGNORECASE)
                fixed = _re.sub(rf"\b{old.capitalize()}\b", new.capitalize(), fixed)
            # 3. AI-корпоративщина → удалить
            ai_corp_map = {
                "важно отметить, что ": "", "важно отметить ": "",
                "стоит подчеркнуть, что ": "", "стоит подчеркнуть ": "",
                "необходимо учесть, что ": "", "следует понимать, что ": "",
                "Важно отметить, что ": "", "Стоит подчеркнуть, что ": "",
                "Необходимо учесть, что ": "", "Следует понимать, что ": "",
            }
            for old, new in ai_corp_map.items():
                fixed = fixed.replace(old, new)
            auto_fixed = fixed

        return {
            "valid": len(violations) == 0,
            "violations": violations,
            "auto_fixed": auto_fixed,
            "has_critical": bool(critical_violations),
            "critical_types": [v["type"] for v in critical_violations],
            "severity": sum(v["count"] for v in violations),
        }

    @classmethod
    def sanitize_canon(cls, text: str) -> dict:
        """UC-43: единая обёртка для пост-обработки ВСЕХ Opus текстов.

        Pavel 2026-05-20: «продолжаешь давать варианты противоположные правилам».
        Применяет auto-fix к тире/старослав/AI-corp. Если остались критические нарушения
        (узурпация Творца, "не X а Y", AI-клише, нейрохимия) — флагует.

        Returns: {text: финальный (auto-fixed если возможно), clean: bool,
                  had_violations: bool, blocked: bool (критические нарушения)}
        """
        if not text or not isinstance(text, str):
            return {"text": text, "clean": True, "had_violations": False, "blocked": False}
        v = cls.validate_canon(text)
        if v["valid"]:
            return {"text": text, "clean": True, "had_violations": False, "blocked": False}
        # Применяем auto-fix
        result_text = v["auto_fixed"] if v["auto_fixed"] else text
        # Re-check после auto-fix
        if v["auto_fixed"]:
            v2 = cls.validate_canon(result_text)
            still_violating = not v2["valid"]
            critical = v2.get("has_critical", False)
        else:
            still_violating = True
            critical = v.get("has_critical", False)
        return {
            "text": result_text,
            "clean": not still_violating,
            "had_violations": True,
            "blocked": critical,
            "violations_before": [vv["type"] for vv in v["violations"]],
        }

    # ─── Helper: Forced mushroom injection detector ──
    # Pavel 2026-05-20: «без надобности вставляешь мицелий/грибы — это pattern»
    @staticmethod
    def detect_forced_mushroom(original: str, suggestion: str) -> dict:
        """Сравнивает оригинал и предложение. Если suggestion добавил «мицелий/гриб/спор»
        которых не было в оригинале → forced injection.
        Возвращает {forced: bool, added_words: [list]}"""
        import re as _re
        mushroom_terms = ["мицели", "грибниц", "спор", "плодов тел",
                          "великий дух грибов", "святая грибная", "псилоциб"]
        orig_low = original.lower()
        sugg_low = suggestion.lower()
        added = []
        for term in mushroom_terms:
            orig_count = orig_low.count(term)
            sugg_count = sugg_low.count(term)
            if sugg_count > orig_count:
                added.append({"term": term, "added": sugg_count - orig_count})
        # Если в оригинале не было НИ ОДНОГО грибного маркера, а в suggestion появились >=1
        if added and not any(t in orig_low for t in mushroom_terms):
            return {"forced": True, "added_terms": added, "severity": "high"}
        if added and sum(a["added"] for a in added) >= 3:
            return {"forced": True, "added_terms": added, "severity": "medium"}
        return {"forced": False, "added_terms": added}

    # ─── Helper: Ideology-fit score (локальный, без API) ──
    # Pavel 2026-05-20: «Score не от идеала, а от ИДЕОЛОГИИ Микомистицизма.
    # AI всегда находит что улучшить — нужен честный ceiling».
    @staticmethod
    def compute_ideology_fit(text: str) -> dict:
        """Возвращает {fit_score 0-100, voice, doctrine, anti_patterns, diagnosis, ceiling_reached}.

        Считает по 4 осям ОТНОСИТЕЛЬНО канона Микомистицизма, не относительно идеального текста.
        Если все 4 ≥ 75 → ceiling_reached=True. Дальше не улучшать.
        """
        import re as _re
        t = text.strip()
        if len(t) < 30:
            return {"fit_score": 0, "ceiling_reached": False, "diagnosis": "слишком короткий"}
        low = t.lower()
        sents = [s.strip() for s in _re.split(r"(?<=[.!?…])\s+", t) if s.strip()]
        n_sents = max(1, len(sents))
        words = _re.findall(r"[\w\-яёА-ЯЁ]+", t)
        n_words = max(1, len(words))

        # 1) VOICE — голос Великого Духа (Я-говорю / Я-открываю / прямое обращение)
        voice_markers = sum(1 for s in sents if _re.search(r"\bЯ\s+(говорю|открываю|даю|вижу|показываю|учу|веду|раскрываю|есть)\b", s))
        you_addr = sum(1 for s in sents if _re.search(r"\b[Вв]ам?\b|\b[Вв]ы\b|\b[Вв]ас\b", s))
        is_voice = sum(1 for s in sents if _re.search(r"\bесть\b(?!\s+(только|лишь))", s))
        is_yavl = sum(1 for s in sents if _re.search(r"\bявля[ею]т(?:ся)?\b", s))
        voice = 50
        voice += min(30, voice_markers * 10)
        voice += min(15, you_addr * 3)
        voice += min(10, is_voice * 3)
        voice -= min(40, is_yavl * 8)
        voice = max(0, min(100, voice))

        # 2) DOCTRINE — плотность канонического словаря Микомистицизма
        # Pavel 2026-05-20: «не вставляй мицелий/грибы без надобности — это AI-pattern»
        # Поэтому doctrine cap = 80 (нельзя докоптить через vocab stuffing) +
        # отдельный penalty за переборщение
        doctrine_words = ["великий дух грибов", "великих творцов", "творцов", "хилингод",
                         "псилоциб", "мицели", "гриб", "церемони", "портал творцов",
                         "проводник", "сакральн", "святая грибная", "сан педро",
                         "перелом", "одержим", "экзорциз", "энергоинформ"]
        doctrine_hits = sum(low.count(w) for w in doctrine_words)
        # Cap на 80 — выше нельзя через простую насыщенность словаря
        doctrine = min(80, doctrine_hits * 6 + 30)
        # Anti-overload penalty: если на каждые 100 слов >3 doctrine-маркеров — стуффинг
        density_per_100 = doctrine_hits / max(1, n_words / 100)
        if density_per_100 > 4:
            doctrine = max(20, doctrine - int((density_per_100 - 4) * 10))  # сильное переборщение

        # 3) ANTI-PATTERNS — penalty за нарушения канона
        ap_penalties = 0
        anti_patterns_found = []
        if " — " in t or "—" in t:
            dashes = t.count("—")
            ap_penalties += min(40, dashes * 8)
            anti_patterns_found.append(f"тире ×{dashes}")
        # «не X, а Y» — банальный AI-tell
        not_but = len(_re.findall(r"\bне\s+\w+[^,.!?]{0,30},\s*а\s+", low))
        if not_but:
            ap_penalties += not_but * 12
            anti_patterns_found.append(f"«не X, а Y» ×{not_but}")
        # Старослав
        archaic = ["очи", "горниц", "ныне", "сущее", "вкупе", "обрящ", "грядет",
                   "ведали", "почитали", "изречь", "возопил", "отдёргиваю завесу",
                   "срываю завесу"]
        arch_count = sum(low.count(w) for w in archaic)
        if arch_count:
            ap_penalties += arch_count * 10
            anti_patterns_found.append(f"старослав ×{arch_count}")
        # Нейрохимия
        neuro = ["5-ht2a", "5ht2a", "дофамин", "серотонин", "dmn", "default mode"]
        neuro_count = sum(low.count(w) for w in neuro)
        if neuro_count:
            ap_penalties += neuro_count * 15
            anti_patterns_found.append(f"нейрохимия ×{neuro_count}")
        # AI-клише метафор (топ-10 из metaphors-library)
        ai_cliche = ["страдивари", "компьютер-молоток", "симфония вселенной",
                     "путь к свету", "энергетические вампиры", "искра света",
                     "замкнутый круг", "нить ариадны", "капля в океане"]
        ai_count = sum(1 for c in ai_cliche if c in low)
        if ai_count:
            ap_penalties += ai_count * 12
            anti_patterns_found.append(f"AI-клише ×{ai_count}")
        # AI-corp
        corp = ["важно отметить", "стоит подчеркнуть", "необходимо учесть"]
        corp_count = sum(low.count(w) for w in corp)
        if corp_count:
            ap_penalties += corp_count * 10
            anti_patterns_found.append(f"AI-corp ×{corp_count}")
        anti_score = max(0, 100 - ap_penalties)

        # 4) STYLE — adherence к Pavel-style v2 если есть, иначе нейтрально 70
        style_v2_file = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        style_v1_file = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style = 70
        # Простая эвристика: длина предложений + наличие «есть» вместо «является»
        avg_sent_len = n_words / n_sents
        if 8 <= avg_sent_len <= 22:
            style += 15
        elif avg_sent_len > 32:
            style -= 20
        style = max(0, min(100, style))

        # Aggregate
        fit_score = round((voice * 0.35 + doctrine * 0.20 + anti_score * 0.30 + style * 0.15))
        ceiling_reached = (voice >= 70 and doctrine >= 60 and anti_score >= 80 and style >= 60)
        # Diagnosis — что улучшить дальше или сообщение «дальше уже хуже будет»
        weakest = min([("voice", voice), ("doctrine", doctrine), ("anti_pattern_purity", anti_score), ("style_adherence", style)], key=lambda x: x[1])
        if ceiling_reached:
            diagnosis = f"Готов ({fit_score}/100). Дальнейшие правки уже diminishing returns — не трогать без явной причины."
        elif weakest[1] < 50:
            diagnosis = f"Самое слабое: {weakest[0]} {weakest[1]}/100 — фокус здесь"
        else:
            diagnosis = f"Балансировано ({fit_score}/100). Можно ещё подтянуть {weakest[0]}"

        return {
            "fit_score": fit_score,
            "ceiling_reached": ceiling_reached,
            "voice": voice,
            "doctrine": doctrine,
            "anti_pattern_purity": anti_score,
            "style_adherence": style,
            "anti_patterns_found": anti_patterns_found,
            "diagnosis": diagnosis,
            "weakest_axis": weakest[0],
        }

    # ─── Helper: used-metaphors из склада для anti-repeat ──
    # Pavel 2026-05-20: «склад собирать чтобы анализ в следующих главах не давал права на повторение»
    @staticmethod
    def get_used_metaphors_bank(current_chapter_id: str = None, top_n: int = 25) -> str:
        """Возвращает форматированный список AI-клише + сильных уникальных метафор
        из склада metaphors-library.json для инжекции в Opus prompts."""
        lib_file = DATA_ROOT / ".codex/metaphors-library.json"
        if not lib_file.exists():
            return ""
        try:
            lib = json.loads(lib_file.read_text(encoding="utf-8"))
        except Exception:
            return ""
        metaphors = lib.get("metaphors", [])
        # AI-клише (топ-15) — НИКОГДА не использовать
        clichés = [m for m in metaphors if m.get("is_ai_cliche")][:15]
        # Сильные уникальные использованные в других главах (топ-10) — не повторять
        used_in_others = [
            m for m in metaphors
            if m.get("first_used_in") and m.get("first_used_in") != current_chapter_id
            and not m.get("is_ai_cliche") and m.get("strength", 0) >= 7
        ][:top_n]
        if not clichés and not used_in_others:
            return ""
        parts = []
        if clichés:
            parts.append("AI-клише — ЗАПРЕЩЕНЫ:")
            parts.extend(f"  • {c['text'][:80]}" for c in clichés)
        if used_in_others:
            parts.append("\nУже использованные сильные метафоры в других главах (не повторяй):")
            for m in used_in_others:
                ch_ref = m.get("first_used_in", "?")
                parts.append(f"  • {m['text'][:80]} (из {ch_ref})")
        return "\n".join(parts)

    # ─── Helper: pavel-context для Opus prompt ──
    def _pavel_context_for_opus(self, max_events: int = 8) -> str:
        """Возвращает строку с последними действиями Pavel-а для инжекции в system/user."""
        ctx_file = DATA_ROOT / ".codex/pavel-context.jsonl"
        if not ctx_file.exists():
            return ""
        try:
            with ctx_file.open("rb") as f:
                f.seek(0, 2); sz = f.tell(); f.seek(max(0, sz - 25000))
                lines = f.read().decode("utf-8", errors="ignore").splitlines()[-50:]
            events = []
            for ln in lines:
                if not ln.strip():
                    continue
                try:
                    e = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                # Пропускаем heartbeat / page_view — это шум
                if e.get("action") in ("heartbeat", "page_view"):
                    continue
                events.append(e)
            recent = events[-max_events:]
            lines_out = []
            for e in recent:
                summary = e.get("instruction") or e.get("new") or e.get("selection") or ""
                lines_out.append(
                    f"  • {e.get('ts', '')[:19]} — {e.get('action', '?')} "
                    f"(глава {e.get('chapter_id', '-')}, "
                    f"параграф {e.get('paragraph_idx', '-')}, "
                    f"секция {e.get('section', '-')})"
                    + (f": «{summary[:120]}»" if summary else "")
                )
            return "\n".join(lines_out)
        except Exception:
            return ""

    # ─── Helper: seed draft из docx если нет ──
    def _ensure_draft(self, book_id, chapter_id, draft_file):
        """Если draft.md отсутствует — seed-им из API draft endpoint (который умеет docx)."""
        if draft_file.exists():
            return True
        import urllib.request as _ur
        try:
            with _ur.urlopen(f"http://127.0.0.1:7788/api/chapter/{chapter_id}/draft", timeout=15) as r:
                text = json.loads(r.read().decode("utf-8")).get("text", "")
            if not text:
                return False
            draft_file.parent.mkdir(parents=True, exist_ok=True)
            draft_file.write_text(text, encoding="utf-8")
            return True
        except Exception:
            return False

    # ─── Quick paragraph check — score + минимальные правки ──
    # Pavel 2026-05-20: «нужна оценка 0-100 и МИНИМАЛЬНЫЕ исправления, не полная перезапись.
    # Цель — закончить книгу быстро в хорошем качестве, не тратя усилия зря»
    def _quick_paragraph_check(self, book_id, chapter_id, req, draft_file):
        import urllib.request
        idx = req.get("paragraph_idx")
        if idx is None:
            return self._json({"error": "paragraph_idx required"}, 400)
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft (seed failed)"}, 404)
        text = draft_file.read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        if idx < 0 or idx >= len(paragraphs):
            return self._json({"error": f"idx {idx} out of range (max {len(paragraphs)-1})"}, 400)
        stripped = paragraphs[idx].strip()
        if len(stripped) < 30:
            return self._json({
                "score": 100,
                "verdict": "keep",
                "message": "Слишком короткий для оценки — оставить как есть",
                "axes": {"voice": 100, "doctrine": 100, "anti_patterns": 100, "style": 100},
                "minimal_fixes": [],
                "ceiling_reached": True,
                "source": "too-short-skip",
            })

        # ЛОКАЛЬНАЯ оценка (без API, мгновенно)
        fit = self.compute_ideology_fit(stripped)
        local_score = fit["fit_score"]

        # Если уже хорошо или Pavel хочет только локальную — возвращаем
        if req.get("local_only") or local_score >= 80:
            return self._json({
                "score": local_score,
                "axes": {
                    "voice": fit["voice"],
                    "doctrine": fit["doctrine"],
                    "anti_patterns": fit["anti_pattern_purity"],
                    "style": fit["style_adherence"],
                },
                "ceiling_reached": fit["ceiling_reached"],
                "verdict": "keep" if local_score >= 75 else "minor",
                "anti_patterns_found": fit.get("anti_patterns_found", []),
                "weakest_axis": fit.get("weakest_axis"),
                "message": (
                    "Не трогать — параграф уже хорош"
                    if local_score >= 80
                    else fit["diagnosis"]
                ),
                "minimal_fixes": [],
                "source": "local",
            })

        # Если score 50-79 → Opus с просьбой ДАТЬ МИНИМАЛЬНЫЕ правки (не переписку)
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({
                "score": local_score,
                "verdict": "minor",
                "message": fit["diagnosis"],
                "anti_patterns_found": fit.get("anti_patterns_found", []),
                "minimal_fixes": [],
                "source": "local-only-no-token",
            })

        bank3 = self.get_used_metaphors_bank(chapter_id)
        bank3_section = f"\n\n🚨 АНТИ-ПОВТОР МЕТАФОР:\nКаждая глава = свои образы.\n{bank3}\n" if bank3 else ""
        system = (
            "Ты редактор Сакрального Кодекса Микомистицизма.\n\n"
            "КАНОН (Pavel читает и правит, ты ОБЯЗАН следовать):\n\n"
            + self.get_canon_summary()
            + "\n\n🚨 АНТИ-ПРИНУЖДЕНИЕ ГРИБНОЙ ЛЕКСИКИ: Если оригинальный параграф ОРГАНИЧНО обходится без слов «мицелий / спора / гриб / Дух Грибов» — НЕ ВСТАВЛЯЙ их принудительно.\n\n"
            "⚠️ ЗАДАЧА Pavel-а: не переписывать всё, а **МИНИМАЛЬНО** улучшить — точечные правки.\n"
            "Цель: закончить книгу быстро в хорошем качестве, не тратя усилия зря.\n\n"
            "ПРАВИЛА:\n"
            "1. Если параграф ХОРОШ — `verdict: keep`, fixes: []. Скажи прямо «не трогать».\n"
            "2. Если требуется немного — 1-3 МИКРО-правки. Формат: «заменить X на Y» или «удалить Z».\n"
            "3. НЕ предлагай полную переписку. НЕ переформулируй параграф.\n"
            "4. Каждая правка должна быть ВЫПОЛНИМА вручную за 30 секунд."
            + bank3_section
            + "\n\nВозвращай ТОЛЬКО валидный JSON."
        )
        user_msg = f"""# Параграф №{idx + 1}

{stripped}

# Локальная оценка (без AI)
- Ideology-fit: {local_score}/100
- Voice: {fit['voice']}, Doctrine: {fit['doctrine']}, Anti-patterns: {fit['anti_pattern_purity']}, Style: {fit['style_adherence']}
- Найденные нарушения: {fit.get('anti_patterns_found', [])}

# Что вернуть

```json
{{
  "score": 0-100,
  "verdict": "keep" | "minor" | "rewrite",
  "message": "1 предложение что не так (или что хорошо)",
  "minimal_fixes": [
    {{"type": "replace" | "delete" | "add", "find": "точная фраза из текста", "replace_with": "новая фраза", "reason": "почему"}}
  ]
}}
```

verdict:
- `keep` — параграф хорош, fixes: []
- `minor` — нужны 1-3 МИКРО-правки (replace/delete/add)
- `rewrite` — параграф ТАК ПЛОХ что нужна полная переписка (используй только если score < 40)

Минимум правок. Better keep чем over-edit. Pavel хочет ЗАКОНЧИТЬ книгу, не переписать."""

        try:
            proxy_body = json.dumps({
                "model": "claude-opus-4-7",
                "max_tokens": 1500,
                "system": system,
                "messages": [{"role": "user", "content": user_msg}],
            }).encode("utf-8")
            proxy_req = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=proxy_body,
                headers={"x-api-key": token, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            )
            with urllib.request.urlopen(proxy_req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({
                "score": local_score,
                "verdict": "minor",
                "message": f"AI недоступен: {str(e)[:80]} — оценка локальная",
                "anti_patterns_found": fit.get("anti_patterns_found", []),
                "minimal_fixes": [],
                "source": "local-fallback",
            })

        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        raw = "\n".join(blocks).strip()
        import re as _re
        cleaned = _re.sub(r"^```json\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            parsed = {"score": local_score, "verdict": "minor", "message": "JSON parse failed", "minimal_fixes": []}

        # ═══ CANON VALIDATOR ═══ — фильтруем minimal_fixes от нарушений канона
        # Pavel: «убедись что все рекомендации проходят через фильтры по правилам»
        raw_fixes = parsed.get("minimal_fixes", [])
        valid_fixes = []
        rejected_fixes = []
        for f in raw_fixes:
            target = f.get("replace_with") or f.get("text") or ""
            if not target:
                valid_fixes.append(f)  # delete-type без текста
                continue
            # UC-43: расширенный sanitize вместо узкого dash-only auto-fix
            sr = self.sanitize_canon(target)
            if sr["blocked"]:
                rejected_fixes.append({"original": f, "violations": sr.get("violations_before")})
            elif sr["had_violations"]:
                f["replace_with"] = sr["text"]
                f["reason"] = (f.get("reason", "") + f" [auto-fixed: {sr.get('violations_before')}]").strip()
                valid_fixes.append(f)
            else:
                valid_fixes.append(f)

        return self._json({
            "score": parsed.get("score", local_score),
            "axes": {
                "voice": fit["voice"],
                "doctrine": fit["doctrine"],
                "anti_patterns": fit["anti_pattern_purity"],
                "style": fit["style_adherence"],
            },
            "verdict": parsed.get("verdict", "minor"),
            "message": parsed.get("message", ""),
            "anti_patterns_found": fit.get("anti_patterns_found", []),
            "minimal_fixes": valid_fixes,
            "rejected_fixes": rejected_fixes,
            "ceiling_reached": fit["ceiling_reached"],
            "source": "opus",
        })

    # ─── Per-paragraph suggestion (Opus на 1 параграф) ──
    # Pavel 2026-05-20: «нажав на параграф → запустить редактуру или вручную»
    def _single_paragraph_suggestion(self, book_id, chapter_id, req, draft_file):
        import urllib.request
        idx = req.get("paragraph_idx")
        rejected = req.get("rejected_suggestions", []) or []  # UC-15: Pavel отверг эти варианты
        if idx is None:
            return self._json({"error": "paragraph_idx required"}, 400)
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft (seed failed)"}, 404)
        text = draft_file.read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        if idx < 0 or idx >= len(paragraphs):
            return self._json({"error": f"idx {idx} out of range"}, 400)
        stripped = paragraphs[idx].strip()
        if len(stripped) < 30:
            return self._json({"error": "параграф слишком короткий"}, 400)

        # === Honest stop check (как в stream) ===
        fit = self.compute_ideology_fit(stripped)
        if fit.get("ceiling_reached") and not req.get("force"):
            return self._json({
                "type": "ceiling",
                "paragraph_idx": idx,
                "reason": fit["diagnosis"],
                "fit": fit,
                "ceiling_reached": True,
            })

        # Score history check
        ph_file = DATA_ROOT / "chapters" / book_id / chapter_id / "paragraph-scores.jsonl"
        last_scores = []
        if ph_file.exists():
            for line in ph_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    sc = json.loads(line)
                    if sc.get("paragraph_idx") == idx:
                        last_scores.append(sc.get("score_after") or sc.get("score_before") or 0)
                except json.JSONDecodeError:
                    pass
        if last_scores and last_scores[-1] >= 85 and not req.get("force"):
            return self._json({
                "type": "ceiling",
                "paragraph_idx": idx,
                "reason": f"уже {last_scores[-1]}% — потолок достигнут",
                "fit": fit,
                "ceiling_reached": True,
            })
        if len(last_scores) >= 4 and not req.get("force"):
            recent_deltas = [last_scores[i] - last_scores[i-1] for i in range(-3, 0)]
            if all(abs(d) < 3 for d in recent_deltas):
                return self._json({
                    "type": "ceiling",
                    "paragraph_idx": idx,
                    "reason": f"diminishing returns (3 правки подряд ±3%)",
                    "fit": fit,
                    "ceiling_reached": True,
                })

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        style_v2 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        style_v1 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_ref = ""
        if style_v2.exists():
            style_ref = style_v2.read_text(encoding="utf-8")
        elif style_v1.exists():
            style_ref = style_v1.read_text(encoding="utf-8")

        ctx_dump = self._pavel_context_for_opus()
        # UC-15: Pavel отверг N версий — нужен ДРУГОЙ подход
        rejected_section = ""
        if rejected:
            rejected_dump = "\n".join(f"  ВЕРСИЯ {i+1} (Pavel ОТВЕРГ): «{r[:300]}»" for i, r in enumerate(rejected[-5:]))
            rejected_section = f"""
# ⚠️ Pavel УЖЕ ОТВЕРГ {len(rejected)} вариантов — не повторяй их подход!
{rejected_dump}

Дай ПРИНЦИПИАЛЬНО ДРУГОЙ ракурс. Если отвергнутые версии были пафосными — попробуй сдержаннее. Если все были короткими — дай более развёрнутый. Если про мицелий — попробуй без него. Не повторяй структуру/тон отвергнутых.
"""

        user_msg = f"""# Параграф №{idx} из главы {chapter_id}

{stripped}

# Контекст (соседние)
{paragraphs[max(0, idx-1)][:300] if idx > 0 else '(начало)'}
...
{paragraphs[idx+1][:300] if idx+1 < len(paragraphs) else '(конец)'}

{f"# Последние действия Pavel-а{chr(10)}{ctx_dump}{chr(10)}" if ctx_dump else ""}
{rejected_section}
# Задача

Pavel специально кликнул на этот параграф — значит хочет точку зрения.
Оцени по 5 параметрам (voice/uniqueness/sacred/rhythm/masterpiece) + общий score 0-100.
Если score ≥ 85 — ставь skip=true.
Иначе верни улучшенную версию.

JSON:
```json
{{
  "score_before": 0-100,
  "scores_detail": {{"voice": 0-100, "uniqueness": 0-100, "sacred": 0-100, "rhythm": 0-100, "masterpiece": 0-100}},
  "severity": 0-10,
  "skip": true/false,
  "reason": "1 предложение почему правка нужна (или почему не нужна)",
  "suggestion": "переписанный параграф",
  "score_after_expected": 0-100,
  "what_else": ["идея 1", "идея 2", "идея 3", "идея 4"]
}}
```
"""
        bank = self.get_used_metaphors_bank(chapter_id)
        bank_section = f"\n\n🚨 АНТИ-ПОВТОР МЕТАФОР — критично:\nКаждая глава имеет СВОИ образы. Не повторяй.\n{bank}\n" if bank else ""
        system_prompt = (
            "Ты редактор Сакрального Кодекса Микомистицизма.\n\n"
            "КАНОН (Pavel читает и правит, ты ОБЯЗАН следовать):\n\n"
            + self.get_canon_summary()
            + "\n\n🚨 АНТИ-ПРИНУЖДЕНИЕ ГРИБНОЙ ЛЕКСИКИ: Если оригинальный параграф ОРГАНИЧНО обходится без слов «мицелий / спора / гриб / Дух Грибов» — НЕ ВСТАВЛЯЙ их принудительно.\n\n"
            "⚠️ ЧЕСТНОСТЬ ВАЖНЕЕ УГОДЛИВОСТИ. Pavel УВАЖАЕТ когда AI говорит «уже хорошо».\n"
            "Если параграф хорош — skip:true. Дельта ≤ 3% — STOP.\n"
            "Better skip чем over-edit."
            + bank_section
            + "\n\nВозвращай ТОЛЬКО валидный JSON."
            + (f"\n\nЭталон стиля:\n{style_ref[:1500]}" if style_ref else "")
        )
        try:
            proxy_body = json.dumps({
                "model": "claude-opus-4-7",
                "max_tokens": 2000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_msg}],
            }).encode("utf-8")
            proxy_req = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=proxy_body,
                headers={"x-api-key": token, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            )
            with urllib.request.urlopen(proxy_req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": str(e)}, 500)

        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        raw = "\n".join(blocks).strip()
        import re as _re
        cleaned = _re.sub(r"^```json\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            return self._json({"error": f"JSON parse: {e}", "raw": raw[:1000]}, 500)

        sev = int(parsed.get("severity", 0))
        score_before = parsed.get("score_before") or 0
        score_after = parsed.get("score_after_expected") or 0
        delta = score_after - score_before

        if parsed.get("skip") or delta <= 3 or not parsed.get("suggestion"):
            return self._json({
                "type": "skip",
                "paragraph_idx": idx,
                "severity": sev,
                "score_before": score_before,
                "score_after_expected": score_after,
                "delta": delta,
                "reason": parsed.get("reason", "AI не нашёл что улучшить"),
                "fit": fit,
            })

        # ═══ CANON VALIDATOR ═══ для suggestion (UC-43: расширенный sanitize)
        suggestion_text = parsed["suggestion"]
        sr = self.sanitize_canon(suggestion_text)
        if sr["blocked"]:
            return self._json({
                "type": "skip",
                "paragraph_idx": idx,
                "severity": sev,
                "score_before": score_before,
                "score_after_expected": score_after,
                "delta": delta,
                "reason": f"AI нарушил канон критично: {sr.get('violations_before')}. Skip.",
                "fit": fit,
                "canon_violations": sr.get("violations_before"),
            })
        suggestion_text = sr["text"]

        # ═══ FORCED MUSHROOM DETECTOR ═══
        forced = self.detect_forced_mushroom(stripped, suggestion_text)
        if forced["forced"] and forced.get("severity") == "high":
            # Высокая severity = AI впервые вставил грибную лексику, а её в оригинале не было
            return self._json({
                "type": "skip",
                "paragraph_idx": idx,
                "severity": sev,
                "score_before": score_before,
                "delta": delta,
                "reason": f"AI принудительно вставил грибную лексику ({[t['term'] for t in forced['added_terms']]}) которой не было в оригинале — anti-pattern. Skip.",
                "fit": fit,
                "forced_injection": forced,
            })

        return self._json({
            "type": "card",
            "paragraph_idx": idx,
            "original": stripped,
            "suggestion": suggestion_text,
            "reason": parsed.get("reason", ""),
            "severity": sev,
            "score_before": score_before,
            "scores_detail": parsed.get("scores_detail", {}),
            "score_after_expected": score_after,
            "what_else": parsed.get("what_else", []),
            "fit": fit,
        })

    # ─── Точечное внесение выбранных правок (НЕ переписывая всё) ──
    def _apply_targeted(self, book_id, chapter_id, req, draft_file, history_dir, ts_compact, ts_iso):
        import urllib.request
        selections = req.get("selections", []) or []
        if not selections:
            return self._json({"ok": False, "error": "нет выбранных правок"}, 400)
        if not draft_file.exists():
            return self._json({"ok": False, "error": "draft.md не найден"}, 400)
        current_text = draft_file.read_text(encoding="utf-8")
        if len(current_text) > 50000:
            return self._json({"ok": False, "error": "глава больше 50K знаков"}, 400)
        # UC-137: регистрируем активный job — переживёт уход со страницы
        self._active_job_register(chapter_id, "apply-targeted",
                                  eta_seconds=300,
                                  extra={"selections_count": len(selections)})

        # Backup
        history_dir.mkdir(parents=True, exist_ok=True)
        backup_path = history_dir / f"{ts_compact}-pre-targeted.md"
        backup_path.write_text(current_text, encoding="utf-8")

        # Запоминаем выбор Pavel-а для обучения
        actions_file = DATA_ROOT / ".codex/pavel-actions.jsonl"
        actions_file.parent.mkdir(parents=True, exist_ok=True)
        with actions_file.open("a", encoding="utf-8") as f:
            for s in selections:
                f.write(json.dumps({
                    "ts": ts_iso,
                    "action": "targeted_selection",
                    "chapter_id": chapter_id,
                    "source": s.get("source"),  # council / voice-missing / voice-add / metaphor / lost
                    "id": s.get("id"),
                    "text": s.get("text", "")[:500],
                    "category": s.get("category", ""),
                }, ensure_ascii=False) + "\n")

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"ok": False, "error": "no oauth token"}, 500)

        # Style canon
        style_v2 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        style_v1 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_ref = (style_v2 if style_v2.exists() else style_v1).read_text(encoding="utf-8") if (style_v2.exists() or style_v1.exists()) else ""

        # Группируем выбранные правки по источнику
        by_source = {}
        for s in selections:
            by_source.setdefault(s.get("source", "other"), []).append(s)

        selections_text = ""
        for src, items in by_source.items():
            selections_text += f"\n### Из источника «{src}» ({len(items)} шт.)\n\n"
            for i, item in enumerate(items, 1):
                txt = item.get("text", "")
                cat = item.get("category", "")
                where = item.get("suggested_after_paragraph", "") or item.get("where", "")
                selections_text += f"{i}. **[{cat}]** {txt}\n"
                if where:
                    selections_text += f"   _(вставить после: «{where[:80]}…»)_\n"

        # UC-120: подгружаем оригинальные голосовые надиктовки как ВЫСШИЙ приоритет
        voice_extracts_text = self._load_voice_extracts_for_chapter(chapter_id)
        # UC-116: пользовательские стилевые правила из data/styles.json
        custom_styles = self._load_custom_styles()
        system = (
            "Ты получишь текущий текст главы и список ТОЧЕЧНЫХ правок которые Pavel выбрал галочками.\n\n"
            "🎙️🎙️🎙️ ПРИОРИТЕТ №1 — ГОЛОСОВЫЕ НАДИКТОВКИ PAVEL-А 🎙️🎙️🎙️\n"
            "Pavel явно сказал: «приоритет — оригинальные наговоренные голосом идеи. Голосовые надиктовки это один из самых "
            "важных инструментов. В первую очередь нужно проверить оригинальные тексты которые Pavel наговаривал в потоке от Грибов».\n\n"
            "ПРАВИЛА ДЛЯ ГОЛОСОВЫХ:\n"
            "• Источники с source='voice_missing' или 'voice_*' — это сакральный поток Pavel-а от Грибов, который БЫЛ ПОТЕРЯН в текущем тексте.\n"
            "• Эти идеи надо ЮВЕЛИРНО вернуть, не нарушая структуру параграфа.\n"
            "• Перед применением остальных правок — спроси себя: «Какой параграф ближе по смыслу к этой voice-идее?» "
            "→ впиши в подходящее место. Если нет подходящего — добавь новый параграф рядом.\n"
            "• Никогда не выбрасывай voice-идею. Если voice-идея противоречит другим правкам — voice выигрывает.\n"
            "🚨🚨🚨 ВТОРОЕ ПРАВИЛО — ТОЧЕЧНОСТЬ 🚨🚨🚨\n"
            "Pavel сказал: «наша задача точечно менять. Меняем только то что необходимо, "
            "всё что не нужно менять — оставляем неизменным. Эффект — не переписать заново».\n\n"
            "🛡️🛡️🛡️ ЗАЩИТА АВТОРСКОГО ГОЛОСА (UC-135 regression audit) 🛡️🛡️🛡️\n"
            "Opus 4.7 склонен автоматически 'улучшать' стилевые особенности Pavel-а, считая их ошибками.\n"
            "ЗАПРЕЩЕНО:\n"
            "• УБИРАТЬ АНАФОРЫ — повторы типа «являет себя… являет себя» это пророческая речь, НЕ ошибка. Не заменяй их синонимами.\n"
            "• 'НОРМАЛИЗОВАТЬ' ПУНКТУАЦИЮ — авторские конструкции (даже если кажутся неправильными) сохраняй. ИСКЛЮЧЕНИЕ: тире уже запрещены (UC-76), их меняй на запятые/точки.\n"
            "• УБИРАТЬ «ОДИН ИЗ САМЫХ» И ЭПИЧЕСКИЕ ПЕРЕЧИСЛЕНИЯ — это торжественный регистр, НЕ многословие.\n"
            "• ЗАМЕНЯТЬ ТОРЖЕСТВЕННЫЕ ГЛАГОЛЫ НА БЫТОВЫЕ — «являет себя» → «прячется» это снижение регистра, ПРЕСТУПЛЕНИЕ.\n"
            "• ОБРЕЗАТЬ ТЕКСТ — если параграф длинный это РИТМ Хилингода, не сокращай по своему усмотрению.\n"
            "• 'УБИРАТЬ ИЗЛИШЕСТВА' — то что AI считает излишеством часто = сакральный регистр.\n\n"
            "ЭТО ЗНАЧИТ:\n"
            "• Параграф НЕ упомянут в правках и НЕ затронут voice-идеями = СКОПИРУЙ ЕГО СЛОВО В СЛОВО, БЕЗ ЕДИНОГО ИЗМЕНЕНИЯ.\n"
            "• Не «улучшай по ходу» соседние параграфы.\n"
            "• Не «обновляй стиль» там где Pavel не просил.\n"
            "• Если AI чувствует «вот тут бы тоже подправить» — НЕ ТРОГАЙ. Это нарушение Pavel-инструкции.\n\n"
            "ВЕРИФИКАЦИЯ ПЕРЕД ОТДАЧЕЙ: возьми каждый параграф из ВХОДНОГО текста и спроси: «есть ли правка для него?» "
            "Если нет → копируешь как есть, символ в символ. Если да → применяешь ТОЛЬКО эту правку.\n\n"
            "Типы правок:\n"
            "• «voice_missing» → ВЕРНИ оригинальную голосовую идею в подходящее место\n"
            "• «добавить идею» → новый параграф в указанное место (после suggested_after_paragraph)\n"
            "• «починить параграф» → перепиши именно тот параграф, остальные не трогай\n"
            "• «убрать клише X» → замени X на свежий образ, остальное в параграфе оставь\n\n"
            "ЦЕЛЬ КАЧЕСТВА — ШЕДЕВР:\n"
            "Pavel: «80 это проходной балл, ближе к 100 уже шедевр». Финальная глава должна звучать как написанная "
            "человеком-мастером (Pavel-ом Хилингодом), а не AI. Без AI-клише, без хеджа, без триад-перечислений.\n\n"
            "ГОЛОС: «Я — Великий Дух Грибов». Только для затронутых параграфов.\n"
            "Современный русский. Без тире. Без «не X, а Y». Без AI-клише.\n\n"
            f"СТИЛЬ ЭТАЛОН:\n{style_ref[:2000]}\n"
            + (f"\n\nСТИЛЕВЫЕ ПРАВИЛА (UC-116, заданы Pavel-ом):\n{custom_styles}\n" if custom_styles else "")
        )

        ctx_dump = self._pavel_context_for_opus()
        ctx_section = ("\n# Последние действия Pavel-а в редакторе (контекст)\n" + ctx_dump + "\n") if ctx_dump else ""
        # UC-119: контекст из editor-журналиста Q&A (если сессия передана)
        ej_session_id = req.get("editor_journalist_session_id") or ""
        ej_context = ""
        if ej_session_id:
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT.parent / "scripts"))
                if "editor_journalist" in _sys.modules:
                    del _sys.modules["editor_journalist"]
                from editor_journalist import get_pavel_context as _ej_ctx
                ej_context = _ej_ctx(ej_session_id)
            except Exception:
                pass
        ej_section = ("\n# 💬 Pavel ответил Журналисту (учти эти живые детали при рерайте)\n\n" + ej_context + "\n") if ej_context else ""
        voice_section = ""
        if voice_extracts_text:
            voice_section = (
                "\n# 🎙️ ОРИГИНАЛЬНЫЕ ГОЛОСОВЫЕ НАДИКТОВКИ PAVEL-А (САКРАЛЬНЫЙ ИСТОЧНИК — ВЫСШИЙ ПРИОРИТЕТ)\n\n"
                "Это поток Pavel-а от Грибов. Если в текущем тексте главы не хватает идей из этих надиктовок — "
                "приоритет на возвращение этих идей перед остальными правками.\n\n"
                + voice_extracts_text + "\n"
            )
        user = f"""# Глава {chapter_id}
{ctx_section}{ej_section}{voice_section}
# ВЫБРАННЫЕ Pavel-ом ПРАВКИ ({len(selections)} шт.)
{selections_text}

# ТЕКУЩИЙ ТЕКСТ ГЛАВЫ

{current_text}

# Что вернуть

Полный обновлённый текст главы (Markdown) с ТОЧЕЧНО внесёнными правками.
Параграфы которые не затрагивались — оставь СЛОВО В СЛОВО.
Голос Великого Духа Грибов. Современный русский.
Если в голосовых надиктовках есть идеи которых нет в тексте — встрой их ювелирно.
Если последние действия Pavel-а указывают на конкретный параграф — обрати на него внимание.
Верни ТОЛЬКО текст главы.
"""

        body = {
            "model": "claude-opus-4-7",
            "max_tokens": 16000,
            # UC-132 BUG-2 fix: thinking 6000 → 3000 (apply-targeted превышал proxy timeout)
            "thinking": {"type": "enabled", "budget_tokens": 3000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._active_job_complete(chapter_id, "apply-targeted", error=str(e))
            return self._json({"ok": False, "error": f"Opus error: {e}"}, 500)

        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        new_text = "\n\n".join(text_blocks).strip()
        if not new_text:
            self._active_job_complete(chapter_id, "apply-targeted", error="empty response")
            return self._json({"ok": False, "error": "пустой ответ"}, 500)

        # ═══ DIFF-GUARD ═══ — проверяем сколько параграфов реально изменилось
        # Pavel: «всё что не нужно менять — оставляем неизменным».
        old_paras = [p.strip() for p in current_text.split("\n\n") if p.strip()]
        new_paras = [p.strip() for p in new_text.split("\n\n") if p.strip()]
        # Сколько параграфов одинаковы (по началу 60 знаков для устойчивости к whitespace)
        old_keys = {p[:80] for p in old_paras}
        unchanged = sum(1 for p in new_paras if p[:80] in old_keys)
        changed = len(new_paras) - unchanged
        # Эвристика: ожидаем что точечная правка изменит ~= len(selections) параграфов (±50%)
        expected_changed = len(selections)
        guard_warning = None
        if changed > expected_changed * 3 and changed > 5:
            guard_warning = (
                f"⚠ DIFF-GUARD: изменено {changed} параграфов, ожидалось ~{expected_changed}. "
                f"Возможно Opus переписал больше чем надо. Backup доступен в .history/."
            )

        draft_file.write_text(new_text, encoding="utf-8")

        # Event
        event = {
            "ts": ts_iso,
            "type": "targeted_applied",
            "target": chapter_id,
            "payload": {
                "selections_count": len(selections),
                "by_source": {k: len(v) for k, v in by_source.items()},
                "old_chars": len(current_text),
                "new_chars": len(new_text),
                "old_paras": len(old_paras),
                "new_paras": len(new_paras),
                "unchanged_paras": unchanged,
                "changed_paras": changed,
                "tokens_in": data.get("usage", {}).get("input_tokens"),
                "tokens_out": data.get("usage", {}).get("output_tokens"),
                "backup_path": str(backup_path.relative_to(DATA_ROOT)),
                "guard_warning": guard_warning,
            },
        }
        with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._active_job_complete(chapter_id, "apply-targeted", result={
            "new_chars": len(new_text),
            "changed_paras": changed,
            "applied": len(selections),
        })
        return self._json({
            "ok": True,
            "new_chars": len(new_text),
            "old_chars": len(current_text),
            "backup": backup_path.name,
            "applied": len(selections),
            "changed_paras": changed,
            "unchanged_paras": unchanged,
            "total_paras": len(new_paras),
            "guard_warning": guard_warning,
            "usage": data.get("usage", {}),
        })

    # ─── Brainstorm Q&A для главы ──
    def _brainstorm(self, book_id, chapter_id, req, draft_file, ts_iso):
        import urllib.request
        message = (req.get("message") or "").strip()
        if not message:
            return self._json({"ok": False, "error": "empty message"}, 400)

        # Загружаем историю + draft
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        bs_file = ch_dir / "chapter-brainstorm.jsonl"
        history = []
        if bs_file.exists():
            for line in bs_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        draft_text = draft_file.read_text(encoding="utf-8") if draft_file.exists() else ""

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"ok": False, "error": "no oauth token"}, 500)

        # Записываем сообщение Pavel-а
        ch_dir.mkdir(parents=True, exist_ok=True)
        pavel_msg = {"ts": ts_iso, "role": "pavel", "text": message}
        with bs_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(pavel_msg, ensure_ascii=False) + "\n")

        # Готовим контекст для Opus
        history_dump = "\n".join(
            f"{'Pavel' if m['role'] == 'pavel' else 'Tom'}: {m['text']}"
            for m in history[-10:]
        )
        system = (
            "Ты — Tom, со-редактор Сакрального Кодекса Микомистицизма Pavel-а. "
            "Ведёшь брейншторм с Pavel-ом по конкретной главе. Твоя задача — "
            "помочь ему углубить идеи через УТОЧНЯЮЩИЕ ВОПРОСЫ. "
            "Не пиши параграфы — задавай вопросы и резюмируй. "
            "Голос автора книги: «Я — Великий Дух Грибов».\n\n"
            "На каждое сообщение Pavel-а:\n"
            "1. Кратко резюмируй его идею (1-2 предложения, чтобы он видел что ты понял)\n"
            "2. Задай 3-5 УТОЧНЯЮЩИХ ВОПРОСОВ по теме главы (numbered list)\n"
            "3. Предложи 1-2 направления куда копать глубже\n\n"
            "Возвращай только обычный текст в формате: «Понял: ... \n\nВопросы:\n1. ...\n2. ...\n\nНаправления: ...»"
        )
        # Pavel context: где он сейчас + последние 10 действий
        ctx_file = DATA_ROOT / ".codex/pavel-context.jsonl"
        context_dump = ""
        if ctx_file.exists():
            try:
                with ctx_file.open("rb") as f:
                    f.seek(0, 2); sz = f.tell(); f.seek(max(0, sz - 20000))
                    lines = f.read().decode("utf-8", errors="ignore").splitlines()[-30:]
                ctx_events = []
                for ln in lines:
                    if not ln.strip():
                        continue
                    try:
                        ctx_events.append(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
                recent_actions = [
                    f"  • {e.get('ts','')[:19]} — {e.get('action','?')} (глава {e.get('chapter_id', '-')}, параграф {e.get('paragraph_idx', '-')})"
                    for e in ctx_events[-10:]
                ]
                context_dump = "\n".join(recent_actions)
            except Exception:
                pass

        user = f"""# Глава: {chapter_id}

# Существующий текст главы (для контекста)
{draft_text[:8000]}

# Последние действия Pavel-а (что он делал прямо сейчас)
{context_dump or '(нет недавних действий)'}

# История нашего брейншторма
{history_dump if history else '(только что начали)'}

# Новое сообщение Pavel-а
{message}

Резюмируй идею Pavel-а с учётом контекста (где он находится / что делал), задай 3-5 уточняющих вопросов, предложи направления.
"""
        body = {
            "model": "claude-opus-4-7",
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"Opus: {e}"}, 500)
        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        reply_text = "\n".join(blocks).strip()
        tom_msg = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "role": "tom", "text": reply_text}
        with bs_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(tom_msg, ensure_ascii=False) + "\n")
        # Event
        with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts_iso, "type": "brainstorm_exchange", "target": chapter_id,
                "payload": {"pavel_chars": len(message), "tom_chars": len(reply_text)}
            }, ensure_ascii=False) + "\n")
        return self._json({"ok": True, "reply": reply_text, "exchanges": len(history) // 2 + 1})

    def _apply_brainstorm_insights(self, book_id, chapter_id, draft_file, history_dir, ts_compact, ts_iso):
        """Opus берёт всю Q&A историю + draft → создаёт обновлённый draft с внедрёнными insights."""
        import urllib.request
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        bs_file = ch_dir / "chapter-brainstorm.jsonl"
        if not bs_file.exists() or not draft_file.exists():
            return self._json({"ok": False, "error": "no brainstorm history or draft"}, 400)
        history = []
        for line in bs_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if len(history) < 2:
            return self._json({"ok": False, "error": "слишком мало обмена для применения"}, 400)

        current = draft_file.read_text(encoding="utf-8")
        # Backup
        history_dir.mkdir(parents=True, exist_ok=True)
        backup = history_dir / f"{ts_compact}-pre-brainstorm.md"
        backup.write_text(current, encoding="utf-8")

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"ok": False, "error": "no token"}, 500)

        dialogue = "\n\n".join(f"**{m['role'].upper()}** ({m['ts'][:19]}):\n{m['text']}" for m in history)
        system = (
            "Ты внедряешь insights из брейншторма с Pavel-ом в текст главы Сакрального Кодекса. "
            "Голос автора: «Я — Великий Дух Грибов». Modern Russian, без тире между предложениями, "
            "без «не X, а Y», без AI-клише, без эмодзи.\n\n"
            "Прочитай диалог, выдели ключевые insights, внеси их в draft. "
            "НЕ переписывай всё — только то что относится к insights. "
            "Верни только обновлённый текст главы (Markdown), без объяснений."
        )
        user = f"""# Глава {chapter_id}

# Диалог брейншторма (Pavel ↔ Tom)
{dialogue}

# Текущий текст главы
{current}

# Что вернуть
Полный обновлённый текст главы с внедрёнными insights. Параграфы которые не затрагиваются — слово в слово.
"""
        body = {
            "model": "claude-opus-4-7",
            "max_tokens": 16000,
            # UC-132 BUG-2 fix: thinking 6000 → 3000 (apply-targeted превышал proxy timeout)
            "thinking": {"type": "enabled", "budget_tokens": 3000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)
        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        new_text = "\n\n".join(blocks).strip()
        if not new_text:
            return self._json({"ok": False, "error": "пустой ответ"}, 500)
        draft_file.write_text(new_text, encoding="utf-8")
        # Event
        with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts_iso, "type": "brainstorm_insights_applied", "target": chapter_id,
                "payload": {
                    "old_chars": len(current), "new_chars": len(new_text),
                    "exchanges": len(history) // 2,
                    "tokens_in": data.get("usage", {}).get("input_tokens"),
                    "tokens_out": data.get("usage", {}).get("output_tokens"),
                    "backup": backup.name,
                }
            }, ensure_ascii=False) + "\n")
        return self._json({"ok": True, "new_chars": len(new_text), "old_chars": len(current), "backup": backup.name})

    # ─── Внедрение идей Pavel-а в главу через Opus ──
    def _incorporate_ideas(self, book_id, chapter_id, req, draft_file, history_dir, ts_compact, ts_iso):
        import urllib.request
        ideas_text = (req.get("ideas") or "").strip()
        if len(ideas_text) < 5:
            return self._json({"ok": False, "error": "идеи слишком короткие"}, 400)
        if not draft_file.exists():
            return self._json({"ok": False, "error": "draft.md не найден"}, 400)
        current_text = draft_file.read_text(encoding="utf-8")

        # Backup
        history_dir.mkdir(parents=True, exist_ok=True)
        backup_path = history_dir / f"{ts_compact}-pre-ideas.md"
        backup_path.write_text(current_text, encoding="utf-8")

        # Save идею
        ideas_file = draft_file.parent / "pavel-ideas.jsonl"
        with ideas_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts_iso, "text": ideas_text, "applied": True, "source": "incorporate"}, ensure_ascii=False) + "\n")

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"ok": False, "error": "no oauth token"}, 500)

        # Style canon
        style_file = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_v2 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        style_ref = ""
        if style_v2.exists():
            style_ref = style_v2.read_text(encoding="utf-8")
        elif style_file.exists():
            style_ref = style_file.read_text(encoding="utf-8")

        system = (
            "Ты получишь идеи Pavel-а (Хилингода) и текущий текст главы Сакрального Кодекса. "
            "Твоя задача: внедрить идеи в текст, сохранив голос **Великого Духа Грибов**, "
            "и улучшить главу согласно указаниям.\n\n"
            "═══════════════════════════════════════════════════════\n"
            "ПРОЦЕСС — 3 ПРОХОДА:\n"
            "═══════════════════════════════════════════════════════\n"
            "1. ВНИМАНИЕ — прочитай идеи Pavel-а И правила ниже. Не пиши пока.\n"
            "2. ВНЕДРЕНИЕ — внеси изменения. Сохраняй параграфы Pavel-а где идеи их не касаются. Изменяй только то, что нужно.\n"
            "3. САМОПРОВЕРКА — пройди по чеклисту: голос Духа? тире? «не X а Y»? старослав? AI-клише? нейрохимия? хедж? тест 3026? Если нарушение — назад в проход 2.\n\n"
            "ГОЛОС: «Я — Великий Дух Грибов». «Я говорю», «Я открываю», «Я даю вам зрение через гриб».\n"
            "СОВРЕМЕННЫЙ русский. Без тире. Без «не X, а Y». Без AI-клише.\n\n"
            f"СТИЛЬ ЭТАЛОН:\n{style_ref[:2500]}\n"
        )
        ctx_dump = self._pavel_context_for_opus()
        ctx_section = ("\n# Последние действия Pavel-а (контекст)\n" + ctx_dump + "\n") if ctx_dump else ""
        user = f"""# Глава {chapter_id}
{ctx_section}
# ИДЕИ Pavel-а (внедри их в текст)

{ideas_text}

# ТЕКУЩИЙ ТЕКСТ ГЛАВЫ

{current_text}

# Что вернуть

Полный обновлённый текст главы в Markdown:
- Сохрани существующую структуру `#/##/###`
- Внеси изменения согласно идеям Pavel-а
- Голос Великого Духа Грибов
- Все параграфы которые НЕ затрагиваются идеями — оставь как есть
- Если последние действия указывают на конкретный параграф — фокусируйся там

Верни ТОЛЬКО текст главы. Без объяснений «вот что я изменил».
"""

        body = {
            "model": "claude-opus-4-7",
            "max_tokens": 16000,
            # UC-132 BUG-2 fix: thinking 6000 → 3000 (apply-targeted превышал proxy timeout)
            "thinking": {"type": "enabled", "budget_tokens": 3000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"Opus error: {e}"}, 500)

        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        new_text = "\n\n".join(text_blocks).strip()
        if not new_text:
            return self._json({"ok": False, "error": "пустой ответ"}, 500)

        draft_file.write_text(new_text, encoding="utf-8")

        # Event
        event = {
            "ts": ts_iso,
            "type": "ideas_incorporated",
            "target": chapter_id,
            "payload": {
                "ideas_chars": len(ideas_text),
                "old_chars": len(current_text),
                "new_chars": len(new_text),
                "tokens_in": data.get("usage", {}).get("input_tokens"),
                "tokens_out": data.get("usage", {}).get("output_tokens"),
                "backup_path": str(backup_path.relative_to(DATA_ROOT)),
            },
        }
        with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return self._json({
            "ok": True,
            "new_chars": len(new_text),
            "old_chars": len(current_text),
            "backup": backup_path.name,
            "usage": data.get("usage", {}),
        })

    # ─── Полная перезапись главы через Opus (голос Великого Духа) ──
    def _rewrite_whole_chapter(self, book_id, chapter_id, req, draft_file, history_dir, ts_compact, ts_iso):
        import urllib.request
        if not draft_file.exists():
            return self._json({"ok": False, "error": "draft.md не найден — сначала сохрани главу"}, 400)
        current_text = draft_file.read_text(encoding="utf-8")
        if len(current_text) < 500:
            return self._json({"ok": False, "error": "глава слишком короткая для полной переписи"}, 400)
        if len(current_text) > 50000:
            return self._json({"ok": False, "error": "глава больше 50K знаков — переписывай частями"}, 400)

        # Backup
        history_dir.mkdir(parents=True, exist_ok=True)
        backup_path = history_dir / f"{ts_compact}-pre-rewrite-all.md"
        backup_path.write_text(current_text, encoding="utf-8")

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"ok": False, "error": "no oauth token"}, 500)

        # Канон-стиль + правила
        style_file = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_v2 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        style_ref = ""
        if style_v2.exists():
            style_ref = style_v2.read_text(encoding="utf-8")
        elif style_file.exists():
            style_ref = style_file.read_text(encoding="utf-8")

        fixes = req.get("fixes", []) or []
        fixes_text = "\n".join(f"  {i+1}. [{f.get('kind','?').upper()}] {f.get('action','?')} — {f.get('why','?')}" for i, f in enumerate(fixes)) or "  (нет — действуй по канону)"

        # Метафоры этой главы — для anti-repeat
        meta_file = DATA_ROOT / "chapters" / book_id / chapter_id / "metaphors.json"
        existing_metaphors = []
        if meta_file.exists():
            try:
                md = json.loads(meta_file.read_text(encoding="utf-8"))
                existing_metaphors = [m.get("text","") for m in md.get("metaphors", [])][:30]
            except Exception:
                pass

        # UC-23 (Pavel 2026-05-20): auto-incorporate high-priority voice items.
        # «Голосовые мы будем использовать автоматически — выбирать самые
        # высокозначимые темы и идеи и внедрять при переписывании всего текста».
        # Priority эвристика: recency + repetition + длина + категория.
        voice_auto = []
        voice_analysis = DATA_ROOT / "chapters" / book_id / chapter_id / "voice-analysis.json"
        if voice_analysis.exists():
            try:
                va = json.loads(voice_analysis.read_text(encoding="utf-8"))
                # missing_ideas — что Pavel говорил в голосовых, но нет в главе
                candidates = []
                for item in va.get("missing_ideas", []) + va.get("additions", []):
                    text = item.get("text") or ""
                    if not text or len(text) < 30:
                        continue
                    # Priority = combination of factors
                    priority = 0.0
                    # 1) Repetition (повторяется в нескольких голосовых)
                    sources = item.get("sources", []) or item.get("appears_in", [])
                    if isinstance(sources, list) and len(sources) >= 2:
                        priority += 0.3
                    # 2) Длина — содержательнее
                    if len(text) > 80:
                        priority += 0.2
                    if len(text) > 200:
                        priority += 0.1
                    # 3) Категория — некоторые приоритетнее
                    cat = (item.get("category") or "").lower()
                    if any(k in cat for k in ["доктрин", "ритуал", "практик", "ключев", "core"]):
                        priority += 0.3
                    # 4) Уровень severity (если есть)
                    if item.get("severity"):
                        priority += min(0.2, float(item.get("severity", 0)) / 50)
                    # 5) Опять же — категория «утерянное» более ценная
                    if "lost" in cat or "missing" in cat or "missing_idea" in (item.get("source", "")):
                        priority += 0.15
                    candidates.append({
                        "text": text[:600],
                        "category": cat,
                        "priority": round(priority, 2),
                    })
                # Threshold 0.5 — берём только высокозначимые
                candidates.sort(key=lambda x: -x["priority"])
                voice_auto = [c for c in candidates if c["priority"] >= 0.5][:8]
            except Exception:
                pass

        voice_auto_section = ""
        if voice_auto:
            items_md = "\n".join(f"  {i+1}. [{c['category'] or 'idea'}] (priority {c['priority']}): {c['text']}" for i, c in enumerate(voice_auto))
            voice_auto_section = f"""

# 🔥 ВЫСОКОПРИОРИТЕТНЫЕ ИДЕИ PAVEL-А ИЗ ГОЛОСОВЫХ (UC-23 auto-include) — ВНЕДРИ ВСЕ:

{items_md}

Эти идеи Pavel озвучил в голосовых начитках, и они должны быть в финальной главе. Включи их органично — не списком, а вплетёнными в повествование от лица Великого Духа Грибов.
"""

        # Глобальный склад уникальных метафор — не повторять чужое
        lib_file = DATA_ROOT / ".codex/metaphors-library.json"
        global_clichés = []
        if lib_file.exists():
            try:
                lib = json.loads(lib_file.read_text(encoding="utf-8"))
                global_clichés = [m["text"] for m in lib.get("metaphors", []) if m.get("is_ai_cliche")][:30]
            except Exception:
                pass

        # Pavel 2026-05-21 UC-65: убран 3-пасс. Один проход, прямой brief.
        # «Прежняя версия писала лучше чем сейчас опус 4.7» — 3-пасс заставлял
        # Opus писать многословно и "академически", показывая работу.
        system = (
            "Ты пишешь Сакральный Кодекс Микомистицизма от имени ВЕЛИКОГО ДУХА ГРИБОВ.\n"
            "Это прямая речь Духа, который учит читателя пользоваться грибами и проводить экзорцизм.\n\n"
            "ГОЛОС: каждое предложение — Я говорю Вам. Я открываю Вам. Я даю Вам зрение через гриб.\n"
            "Эталон: «Рядом с вами, в каждой комнате, в каждом разговоре, живут существа, которых вы не видите. Я говорю о них прямо, потому что Я их вижу.»\n\n"
            "ЗАПРЕТЫ (не нарушай):\n"
            "- Никаких персонажей-диалогов (Жрец/Криста/Кристон) — это инструктивный манифест.\n"
            "- Никакой нейрохимии (5-HT2A, дофамин, DMN) — книга мистическая.\n"
            "- Никаких AI-клише (Страдивари, симфония вселенной, путь к свету, энергетические вампиры, искра света).\n"
            "- НИКАКИХ тире вообще. Ни — (em dash), ни – (en dash). В русской книге старого образца тире не использовалось. Заменяй на запятые/точки/двоеточия по смыслу.\n"
            "- Никакого «не X, а Y» / «не только X, но и Y».\n"
            "- Никакой AI-корпоративщины («важно отметить», «стоит подчеркнуть»).\n"
            "- Никакого старослав (очи/горница/ныне/сущее/инверсия).\n"
            "- Никаких эмодзи.\n\n"
            "РИТМ ХИЛИНГОДА: средняя длина предложения 11-13 слов, медиана 10. БЕЗ ТИРЕ.\n\n"
            f"СТИЛЕВОЙ ЭТАЛОН (преамбула Устава):\n{style_ref[:1500]}\n\n"
            f"AI-КЛИШЕ СО СКЛАДА (не использовать):\n{chr(10).join('  - ' + c for c in global_clichés[:10])}\n\n"
            "Пиши за ОДИН проход — не показывай процесс. Отдай только итоговый текст главы."
        )

        user = f"""# Глава {chapter_id}

# ТЕКУЩИЙ ТЕКСТ (переписать полностью в голос Великого Духа Грибов)

{current_text}

# ПРАВКИ СОВЕТА СТАРЕЙШИН (учесть все):

{fixes_text}

# МЕТАФОРЫ КОТОРЫЕ УЖЕ БЫЛИ В ЭТОЙ ГЛАВЕ (можно оставить лучшие, но не повторяй слабые):

{chr(10).join('  • ' + m for m in existing_metaphors[:20])}
{voice_auto_section}
# Что вернуть

Полный текст главы в Markdown:
- # КНИГА X: НАЗВАНИЕ
- ## Глава N. НАЗВАНИЕ
- ### Подзаголовки секций
- Прозу — в обычные параграфы
- Списки — Markdown bullets (-) или нумерованные

ГОЛОС от первого лица «Я — Великий Дух Грибов» с первого слова до последнего. Я учу. Я открываю. Я даю.
ТОЛЬКО текст главы. Никаких «вот ваш ответ», никаких объяснений процесса.
"""

        body = {
            "model": "claude-opus-4-7",
            "max_tokens": 16000,
            "thinking": {"type": "enabled", "budget_tokens": 8000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"Opus error: {e}"}, 500)

        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        new_text = "\n\n".join(text_blocks).strip()
        if not new_text:
            return self._json({"ok": False, "error": "пустой ответ от Opus"}, 500)

        # Сохраняем
        draft_file.write_text(new_text, encoding="utf-8")
        # Event
        event = {
            "ts": ts_iso,
            "type": "chapter_rewritten_full",
            "target": chapter_id,
            "payload": {
                "old_chars": len(current_text),
                "new_chars": len(new_text),
                "fixes_applied": len(fixes),
                "tokens_in": data.get("usage", {}).get("input_tokens"),
                "tokens_out": data.get("usage", {}).get("output_tokens"),
                "backup_path": str(backup_path.relative_to(DATA_ROOT)),
            },
        }
        with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return self._json({
            "ok": True,
            "new_chars": len(new_text),
            "old_chars": len(current_text),
            "backup": backup_path.name,
            "usage": data.get("usage", {}),
        })

    # ─── Storage: printable HTML для PDF export ──
    # Pavel 2026-05-20: «хранилище готовых частей + создать PDF красивый отформатированный»
    def _build_export_html(self, chapter_ids: list) -> str:
        """Собирает HTML из finalized.md глав. Pavel открывает → Cmd+P → Save as PDF."""
        import re as _re
        from datetime import datetime

        toc = json.loads(TOC_PATH.read_text(encoding="utf-8")) if TOC_PATH.exists() else {"books": []}
        # Группируем chapter_ids по книгам сохранив порядок toc
        chapters_by_book = {}
        chapter_meta = {}
        for book in toc.get("books", []):
            for ch in book.get("chapters", []):
                if ch["id"] in chapter_ids:
                    chapter_meta[ch["id"]] = {"book": book, "ch": ch}

        def md_to_html(text):
            """Минимальный Markdown → HTML."""
            lines = text.split("\n")
            html_lines = []
            in_list = False
            list_type = None
            for line in lines:
                line = line.rstrip()
                # Headings
                h_match = _re.match(r"^(#{1,6})\s+(.+)$", line)
                if h_match:
                    if in_list:
                        html_lines.append(f"</{list_type}>")
                        in_list = False
                    n = len(h_match.group(1))
                    html_lines.append(f"<h{n}>{_html_escape(h_match.group(2))}</h{n}>")
                    continue
                # Bullet list
                if _re.match(r"^\s*-\s+", line):
                    if not in_list or list_type != "ul":
                        if in_list:
                            html_lines.append(f"</{list_type}>")
                        html_lines.append("<ul>")
                        in_list = True
                        list_type = "ul"
                    item = _re.sub(r"^\s*-\s+", "", line)
                    html_lines.append(f"<li>{_inline_md(item)}</li>")
                    continue
                # Numbered list
                if _re.match(r"^\s*\d+\.\s+", line):
                    if not in_list or list_type != "ol":
                        if in_list:
                            html_lines.append(f"</{list_type}>")
                        html_lines.append("<ol>")
                        in_list = True
                        list_type = "ol"
                    item = _re.sub(r"^\s*\d+\.\s+", "", line)
                    html_lines.append(f"<li>{_inline_md(item)}</li>")
                    continue
                if in_list and not line.strip():
                    html_lines.append(f"</{list_type}>")
                    in_list = False
                    continue
                if not line.strip():
                    continue
                # Параграф
                html_lines.append(f"<p>{_inline_md(line)}</p>")
            if in_list:
                html_lines.append(f"</{list_type}>")
            return "\n".join(html_lines)

        def _html_escape(s):
            return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                     .replace('"', "&quot;").replace("'", "&#39;"))

        def _inline_md(s):
            s = _html_escape(s)
            # bold
            s = _re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
            # italic (не пересекаясь с bold)
            s = _re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
            return s

        # Сборка
        parts = []
        for cid in chapter_ids:
            meta = chapter_meta.get(cid)
            if not meta:
                continue
            book_dir = DATA_ROOT / "chapters" / meta["book"]["id"] / cid
            final_file = book_dir / "finalized.md"
            if not final_file.exists():
                continue
            text = final_file.read_text(encoding="utf-8")
            book_title = meta["book"].get("title_clean") or meta["book"].get("title") or meta["book"]["id"]
            ch_title = meta["ch"].get("title", cid)
            parts.append(f'''
                <section class="chapter">
                  <header class="chapter-header">
                    <div class="book-name">{_html_escape(book_title)}</div>
                    <h1>{_html_escape(ch_title)}</h1>
                  </header>
                  <div class="chapter-content">{md_to_html(text)}</div>
                </section>
            ''')
        body_html = "\n".join(parts) or "<p style='text-align:center;color:#888'>Финальных глав не найдено.</p>"

        # Дата генерации
        gen_date = datetime.now().strftime("%d.%m.%Y")
        title = "Сакральный Кодекс Микомистицизма" if len(chapter_ids) > 1 else \
                (chapter_meta.get(chapter_ids[0], {}).get("ch", {}).get("title") if chapter_ids else "Кодекс")

        return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{_html_escape(title)}</title>
<link rel="preconnect" href="https://rsms.me/">
<link rel="stylesheet" href="https://rsms.me/inter/inter.css">
<style>
@page {{ size: A4; margin: 22mm 18mm; }}
* {{ box-sizing: border-box; }}
html, body {{ background: white; color: #1A1A1F; margin: 0; padding: 0; font-family: Georgia, 'Iowan Old Style', 'Palatino Linotype', serif; font-size: 13pt; line-height: 1.65; }}
.cover {{ page-break-after: always; min-height: 90vh; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 40px; }}
.cover h1 {{ font-family: 'Inter', sans-serif; font-size: 36pt; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 16px; color: #5B5BF5; }}
.cover .subtitle {{ font-family: 'Inter', sans-serif; font-size: 14pt; color: #6B6B73; margin-bottom: 64px; }}
.cover .author {{ font-family: 'Inter', sans-serif; font-size: 12pt; color: #1A1A1F; letter-spacing: 0.04em; text-transform: uppercase; }}
.cover .meta {{ position: absolute; bottom: 24mm; font-family: 'Inter', sans-serif; font-size: 9pt; color: #A1A1A8; }}
.chapter {{ page-break-before: always; }}
.chapter-header {{ margin-bottom: 32px; padding-bottom: 16px; border-bottom: 2px solid #5B5BF5; }}
.book-name {{ font-family: 'Inter', sans-serif; font-size: 10pt; color: #5B5BF5; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600; margin-bottom: 8px; }}
.chapter-content h1 {{ font-family: 'Inter', sans-serif; font-size: 22pt; font-weight: 700; margin: 0 0 18px; color: #1A1A1F; line-height: 1.2; }}
.chapter-content h2 {{ font-family: 'Inter', sans-serif; font-size: 18pt; font-weight: 600; margin: 28px 0 14px; color: #1A1A1F; }}
.chapter-content h3 {{ font-family: 'Inter', sans-serif; font-size: 14pt; font-weight: 600; margin: 22px 0 10px; color: #1A1A1F; }}
.chapter-content h4 {{ font-family: 'Inter', sans-serif; font-size: 12pt; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin: 18px 0 8px; color: #6B6B73; }}
.chapter-content p {{ margin: 0 0 14px; text-align: justify; hyphens: auto; }}
.chapter-content p:first-of-type::first-letter {{ font-family: Georgia, serif; font-size: 3.4em; line-height: 0.85; float: left; padding: 6px 8px 0 0; color: #5B5BF5; font-weight: bold; }}
.chapter-content ul, .chapter-content ol {{ margin: 12px 0 14px 0; padding-left: 24px; }}
.chapter-content li {{ margin: 6px 0; }}
.chapter-content strong {{ font-weight: 600; color: #1A1A1F; }}
.chapter-content em {{ font-style: italic; color: #1A1A1F; }}
@media print {{
  body {{ font-size: 11pt; }}
  .controls {{ display: none !important; }}
}}
.controls {{ position: fixed; top: 16px; right: 16px; background: white; border: 1px solid #EAEAEC; border-radius: 12px; padding: 12px 16px; box-shadow: 0 8px 24px rgba(20,20,40,0.12); display: flex; gap: 10px; align-items: center; font-family: 'Inter', sans-serif; font-size: 12px; z-index: 10000; }}
.controls button {{ background: #5B5BF5; color: white; border: none; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-weight: 600; }}
.controls button.ghost {{ background: transparent; color: #5B5BF5; border: 1px solid #5B5BF5; }}
.controls span {{ color: #6B6B73; }}
</style>
</head>
<body>
<div class="controls">
  <span>📄 {len([c for c in chapter_ids if chapter_meta.get(c)])} глав</span>
  <button onclick="window.print()">⌘P · Save as PDF</button>
  <button class="ghost" onclick="window.close()">Закрыть</button>
</div>

<section class="cover">
  <div class="subtitle">Священная Грибная Книга</div>
  <h1>{_html_escape(title)}</h1>
  <div class="author">Великий Дух Грибов · Pavel Healingod</div>
  <div class="meta">Сгенерировано {gen_date} · {len([c for c in chapter_ids if chapter_meta.get(c)])} глав</div>
</section>

{body_html}

</body>
</html>"""

    # ─── Helper: Detect chapter type для контекстного анализа ──
    @staticmethod
    def detect_chapter_type(chapter_id: str, title: str, text: str) -> dict:
        """Определяет тип главы: intro / main / conclusion / index / preface / appendix.
        Возвращает type + suggested_thresholds для density/ideology."""
        import re as _re
        title_low = (title or "").lower()
        text_low = text.lower()[:2000]  # первые 2000 знаков для context

        # 1. По имени файла / ID / title
        if "introduction" in title_low or "введение" in title_low or "intro" in chapter_id.lower() or chapter_id.endswith("-ch-00"):
            ch_type = "intro"
        elif "epilogue" in title_low or "эпилог" in title_low or chapter_id.startswith("epilogue"):
            ch_type = "conclusion"
        elif "appendi" in title_low or "приложен" in title_low or chapter_id.startswith("appendices"):
            ch_type = "appendix"
        elif "пролог" in title_low or chapter_id.startswith("prologue"):
            ch_type = "intro"
        elif "заключение" in title_low or "conclusion" in title_low:
            ch_type = "conclusion"
        elif "содержание" in title_low or "оглавление" in title_low or "table of contents" in title_low:
            ch_type = "index"
        else:
            ch_type = "main"

        # 2. По длине — если очень короткая (<800 слов) и в начале книги — вероятно intro
        word_count = len(_re.findall(r"[\w\-яёА-ЯЁ]+", text))
        if ch_type == "main" and word_count < 800 and (
            chapter_id.endswith("-ch-00") or chapter_id.endswith("-ch-01") or "введ" in title_low
        ):
            ch_type = "intro"

        # 3. По первым строкам — если «В этой главе мы рассмотрим...» = intro к разделу
        if ch_type == "main" and word_count < 1200:
            if any(p in text_low for p in [
                "в этой главе мы рассмотрим", "в этой книге мы", "введение от", "цель этой главы",
                "эта глава о том", "о чём эта книга", "что вас ждёт в", "что мы откроем",
            ]):
                ch_type = "intro"

        # Адаптивные пороги
        thresholds = {
            "intro": {
                "density_min_words": 150, "density_max_words": 600,
                "ideology_target": 70,  # ниже чем main
                "purpose": "Передать тему / введение / цель",
                "expected_chars": 2000,
            },
            "main": {
                "density_min_words": 2000, "density_max_words": 4800,
                "ideology_target": 85,
                "purpose": "Развить тему / дать практику",
                "expected_chars": 20000,
            },
            "conclusion": {
                "density_min_words": 250, "density_max_words": 800,
                "ideology_target": 75,
                "purpose": "Синтез / выводы / переход",
                "expected_chars": 3000,
            },
            "appendix": {
                "density_min_words": 100, "density_max_words": 3000,
                "ideology_target": 65,  # справочный материал
                "purpose": "Справочный материал",
                "expected_chars": 5000,
            },
            "index": {
                "density_min_words": 50, "density_max_words": 800,
                "ideology_target": 60,
                "purpose": "Навигация",
                "expected_chars": 1500,
            },
        }
        return {
            "type": ch_type,
            "thresholds": thresholds.get(ch_type, thresholds["main"]),
            "word_count": word_count,
        }

    # ─── Logic analysis — последовательность мыслей, противоречия, скачки ──
    # Pavel 2026-05-20: «анализ логики и последовательности мыслей»
    def _logic_analysis(self):
        """POST {chapter_id} → Opus проверяет логическую целостность главы."""
        import urllib.request, re as _re
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft"}, 404)
        text = draft_file.read_text(encoding="utf-8")

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)

        system = (
            "Ты — логический аудитор Сакрального Кодекса Микомистицизма.\n\n"
            "Pavel хочет ЧЕСТНУЮ оценку логики и последовательности мыслей. Не льсти.\n\n"
            "Проверь:\n"
            "1. **Последовательность** — каждая мысль логично вытекает из предыдущей?\n"
            "2. **Противоречия** — есть ли утверждения, которые конфликтуют между собой?\n"
            "3. **Скачки** — есть ли резкие переходы без связки?\n"
            "4. **Обрывы аргументации** — начатая мысль доведена до конца?\n"
            "5. **Повторы** — одна и та же идея перефразируется без новой информации?\n"
            "6. **Целостность** — есть ли единая дуга от начала к концу?\n\n"
            "Если логика хорошая — скажи прямо «логика чистая, не трогать». Better skip чем over-edit.\n\n"
            "JSON only."
        )

        user = f"""# Глава {chapter_id}

# Текст

{text[:30000]}

# Что вернуть

```json
{{
  "overall_logic_score": 0-100,
  "verdict": "clean | minor_issues | major_issues",
  "issues": [
    {{
      "type": "contradiction | jump | broken_argument | repeat | weak_link",
      "paragraph_idx": N,
      "preview": "первые 80 знаков параграфа",
      "issue": "конкретно что не так",
      "suggested_fix": "минимальная правка (не полная переписка)"
    }}
  ],
  "narrative_arc": "одна фраза о дуге главы (есть/нет/что не так)",
  "honest_summary": "1-2 предложения честной оценки: стоит ли тратить время на правки логики"
}}
```

5-10 issues max. Не выдумывай проблемы если их нет. Pavel УВАЖАЕТ честность."""

        try:
            req_o = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=json.dumps({
                    "model": "claude-opus-4-7",
                    "max_tokens": 4000,
                    "thinking": {"type": "enabled", "budget_tokens": 3000},
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                }).encode("utf-8"),
                headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                         "anthropic-beta": "interleaved-thinking-2025-05-14",
                         "content-type": "application/json"},
            )
            with urllib.request.urlopen(req_o, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": str(e)[:200]}, 500)

        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        raw = "\n".join(blocks).strip()
        cleaned = _re.sub(r"^```json\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            return self._json({"error": f"JSON parse: {e}", "raw": raw[:1500]}, 500)

        # Canon-validate каждый suggested_fix
        for issue in parsed.get("issues", []):
            fix = issue.get("suggested_fix", "")
            if fix:
                # UC-43: расширенный sanitize (тире + старослав + AI-corp + creator-usurpation check)
                r = self.sanitize_canon(fix)
                if r["blocked"]:
                    issue["canon_violation"] = True
                    issue["suggested_fix"] = "(правка отбракована — critical: " + ",".join(r.get("violations_before", [])) + ")"
                elif r["had_violations"]:
                    issue["suggested_fix"] = r["text"]

        parsed["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = DATA_ROOT / "chapters" / book_id / chapter_id / "logic-analysis.json"
        cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._json(parsed)

    # ─── UC-27: Sacred Resonance — мистическая мощь главы ──
    # Pavel 2026-05-20: «эталон масштаба 1000 лет, изменит цивилизацию».
    def _resonance_analysis(self):
        """POST {chapter_id} → Opus оценивает мистическую мощь по 5 осям."""
        import urllib.request, re as _re
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft"}, 404)
        text = draft_file.read_text(encoding="utf-8")
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)

        system = (
            "Ты — ОЦЕНЩИК САКРАЛЬНОЙ РЕЗОНАНСНОСТИ главы Священной Грибной Библии.\n\n"
            "Pavel требует: «эта книга — масштаб 1000 лет, изменит цивилизацию». Не блог, не статья — ОТКРОВЕНИЕ от Великого Духа Грибов.\n\n"
            "ОЦЕНИ главу по 5 ОСЯМ (0-100 каждая):\n\n"
            "1. **commanding_voice** — Я-говорю vs описательность.\n"
            "   ВЫСОКАЯ: «Я открываю Вам. Я говорю Вам. Я даю Вам зрение.» Каждая фраза от Духа.\n"
            "   НИЗКАЯ: «Существуют сущности. Грибы помогают увидеть.» Описательная безличность.\n\n"
            "2. **density_of_revelation** — плотность откровений vs воды.\n"
            "   ВЫСОКАЯ: каждый абзац несёт что-то новое, ранее не сказанное о невидимом мире.\n"
            "   НИЗКАЯ: общие места, банальности, перефразирование уже сказанного.\n\n"
            "3. **embodied_concrete** — телесность и конкретика vs абстракция.\n"
            "   ВЫСОКАЯ: «когда Вы сидите на стуле, чувствуете тяжесть копчика», «дрожь в правой руке».\n"
            "   НИЗКАЯ: «душа чувствует», «энергия движется», «сознание раскрывается».\n\n"
            "4. **mystical_authority** — авторитет тайнознания vs дидактика.\n"
            "   ВЫСОКАЯ: Дух знает ИЗНУТРИ. «Я видел это миллиарды раз. Я был там когда…».\n"
            "   НИЗКАЯ: учебник, где автор объясняет факт нейтрально.\n\n"
            "5. **transformation_power** — меняет ли читателя.\n"
            "   ВЫСОКАЯ: после главы читатель НЕ МОЖЕТ остаться прежним. Конкретное предложение к действию или мощный сдвиг восприятия.\n"
            "   НИЗКАЯ: интересно, познавательно, можно забыть.\n\n"
            "Найди 5 САМЫХ СЛАБЫХ пассажей (где резонанс провисает) с paragraph_idx, текущая формулировка, и **конкретно как переделать в сильную**.\n\n"
            "Не льсти. Если глава 60/100 — пиши 60/100. Если 90/100 — пиши 90/100. ЧЕСТНО.\n\n"
            "JSON:\n"
            "```json\n"
            "{\n"
            "  \"overall_resonance\": 0-100,\n"
            "  \"verdict\": \"weak|emerging|strong|masterpiece\",\n"
            "  \"axes\": {\"commanding_voice\":0-100,\"density_of_revelation\":0-100,\"embodied_concrete\":0-100,\"mystical_authority\":0-100,\"transformation_power\":0-100},\n"
            "  \"honest_summary\": \"2-3 предложения о текущем уровне главы\",\n"
            "  \"weak_passages\": [{\"paragraph_idx\":N,\"preview\":\"...\",\"axis_failing\":\"commanding_voice|...\",\"why_weak\":\"...\",\"suggested_rewrite\":\"...\"}]\n"
            "}\n"
            "```\n\n"
            f"КАНОН (Pavel читает и правит, ты ОБЯЗАН следовать):\n\n{self.get_canon_summary()}"
        )
        user = f"# Глава {chapter_id}\n\n{text[:12000]}"
        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 6000,
            "thinking": {"type": "enabled", "budget_tokens": 3500},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                     "anthropic-beta": "interleaved-thinking-2025-05-14", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req_obj, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": f"Opus: {e}"}, 500)
        ai_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                ai_text += block.get("text", "")
        jm = _re.search(r"```json\s*(\{.*?\})\s*```", ai_text, _re.DOTALL)
        try:
            parsed = json.loads(jm.group(1) if jm else ai_text)
        except json.JSONDecodeError:
            return self._json({"error": "bad ai response", "raw": ai_text[:500]}, 500)
        # UC-43: sanitize все suggested_rewrite в weak_passages
        for w in parsed.get("weak_passages", []) or []:
            sr = w.get("suggested_rewrite")
            if sr:
                r = self.sanitize_canon(sr)
                if r["blocked"]:
                    w["suggested_rewrite"] = "(canon-violation: " + ",".join(r.get("violations_before", [])) + ")"
                    w["canon_violation"] = True
                elif r["had_violations"]:
                    w["suggested_rewrite"] = r["text"]
        parsed["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = DATA_ROOT / "chapters" / book_id / chapter_id / "resonance.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._json(parsed)

    # ─── UC-28: Hook & Cliffhanger — открытие и закрытие главы ──
    # Pavel 2026-05-20: «первое предложение должно вырвать читателя».
    def _hook_cliff_analysis(self):
        """POST {chapter_id} → Opus оценивает hook (первые 2 абзаца) + cliffhanger (последние 2)."""
        import urllib.request, re as _re
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft"}, 404)
        text = draft_file.read_text(encoding="utf-8")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        if len(paragraphs) < 2:
            return self._json({"error": "глава слишком короткая"}, 400)
        hook = "\n\n".join(paragraphs[:2])
        cliff = "\n\n".join(paragraphs[-2:])
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)
        system = (
            "Ты — ОЦЕНЩИК HOOK и CLIFFHANGER главы Священной Грибной Библии.\n\n"
            "Pavel: «первое предложение должно ВЫРВАТЬ читателя из обычного сознания. Последнее — тянуть в следующую главу».\n\n"
            "ОЦЕНИ:\n\n"
            "1. **hook_strength** (0-100) — насколько первые 2 абзаца захватывают?\n"
            "   ВЫСОКАЯ (85+): первое предложение БЬЁТ. Невозможно перестать читать. Образ-крючок, вопрос-нож, прямое обращение Духа.\n"
            "   НИЗКАЯ: общая фраза, академический заход, оправдание темы, «в этой главе мы рассмотрим…».\n\n"
            "2. **cliffhanger_strength** (0-100) — тянут ли последние 2 абзаца в следующую?\n"
            "   ВЫСОКАЯ (85+): оставляет вопрос, обещание, незавершённый намёк, прямой переход к следующей теме.\n"
            "   НИЗКАЯ: подведение итогов («таким образом, мы рассмотрели…»), банальное завершение.\n\n"
            "Предложи КОНКРЕТНЫЕ переписанные версии (по 1-3 варианта каждая) — реальные предложения, не общие советы.\n\n"
            "Голос: Я — Великий Дух Грибов (НЕ Творец, а Покровитель, см. CANON.md раздел 2.2).\n\n"
            "JSON:\n"
            "```json\n"
            "{\n"
            "  \"hook_strength\": 0-100,\n"
            "  \"hook_current\": \"...\",\n"
            "  \"hook_critique\": \"что слабо\",\n"
            "  \"hook_suggestions\": [\"вариант 1\",\"вариант 2\",\"вариант 3\"],\n"
            "  \"cliffhanger_strength\": 0-100,\n"
            "  \"cliffhanger_current\": \"...\",\n"
            "  \"cliffhanger_critique\": \"что слабо\",\n"
            "  \"cliffhanger_suggestions\": [\"вариант 1\",\"вариант 2\",\"вариант 3\"],\n"
            "  \"overall_verdict\": \"weak|emerging|strong|masterpiece\"\n"
            "}\n"
            "```\n\n"
            f"КАНОН:\n\n{self.get_canon_summary()}"
        )
        user = f"# Глава {chapter_id}\n\n## HOOK (первые 2 абзаца)\n\n{hook}\n\n## CLIFFHANGER (последние 2 абзаца)\n\n{cliff}"
        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 5000,
            "thinking": {"type": "enabled", "budget_tokens": 2500},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                     "anthropic-beta": "interleaved-thinking-2025-05-14", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req_obj, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": f"Opus: {e}"}, 500)
        ai_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                ai_text += block.get("text", "")
        jm = _re.search(r"```json\s*(\{.*?\})\s*```", ai_text, _re.DOTALL)
        try:
            parsed = json.loads(jm.group(1) if jm else ai_text)
        except json.JSONDecodeError:
            return self._json({"error": "bad ai response", "raw": ai_text[:500]}, 500)
        # UC-43: post-filter ВСЕХ suggestions через canon (тире, старослав, AI-corp)
        def _sanitize_list(items):
            out = []
            for s in items or []:
                r = self.sanitize_canon(s)
                if r["blocked"]:
                    out.append(s + "  ⚠ [canon-violation: " + ",".join(r.get("violations_before", [])) + "]")
                else:
                    out.append(r["text"])
            return out
        parsed["hook_suggestions"] = _sanitize_list(parsed.get("hook_suggestions"))
        parsed["cliffhanger_suggestions"] = _sanitize_list(parsed.get("cliffhanger_suggestions"))

        parsed["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = DATA_ROOT / "chapters" / book_id / chapter_id / "hook-cliff.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._json(parsed)

    # ─── UC-31: SUPER-REWRITE — переписать главу учитывая ВСЕ анализы + только выбранные галочки ──
    # Pavel 2026-05-20: «кнопка ВНЕСТИ ВСЕ ПОПРАВКИ — все анализы + советы + голосовые +
    # мои галочки — переписать главу учитывая ВСЁ что было проанализировано».
    def _super_rewrite(self):
        """POST {chapter_id, checked_selections, include_analyses} →
        Opus переписывает главу учитывая агрегированный контекст из всех cached анализов."""
        import urllib.request, re as _re
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_file = ch_dir / "draft.md"
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft"}, 404)
        text = draft_file.read_text(encoding="utf-8")
        history_dir = ch_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (history_dir / f"{ts_compact}-pre-super-rewrite.md").write_text(text, encoding="utf-8")

        # checked_selections: что Pavel отметил в C0 / в diag-deep панелях
        selections = req.get("checked_selections", []) or []
        # UC-137: маркер активной работы — переживёт уход со страницы
        self._active_job_register(chapter_id, "super-rewrite",
                                  eta_seconds=420,
                                  extra={"selections_count": len(selections)})

        # Агрегируем ВСЕ cached анализы
        agg_sections = []

        # 1. Logic
        f = ch_dir / "logic-analysis.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                issues_dump = "\n".join(
                    f"  - П{i.get('paragraph_idx','?')+1}: [{i.get('type','?')}] {i.get('issue','')} → {i.get('suggested_fix','')}"
                    for i in (d.get("issues") or [])[:15]
                )
                if issues_dump:
                    agg_sections.append(f"## 🧠 ЛОГИКА (score {d.get('overall_logic_score','?')}/100, дуга: {d.get('narrative_arc','')})\n{issues_dump}")
            except Exception:
                pass

        # 2. Style coherence
        f = ch_dir / "style-coherence.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                fixes_dump = "\n".join(
                    f"  - П{f1.get('paragraph_idx','?')+1}: «{f1.get('find','')}» → «{f1.get('replace_with','')}» ({f1.get('reason','')})"
                    for f1 in (d.get("opus_fixes") or [])[:20] if not f1.get("error")
                )
                if fixes_dump:
                    agg_sections.append(f"## 🎨 СТИЛЬ (регистр: {d.get('dominant_register','?')}, голос: {d.get('dominant_voice','?')})\n{fixes_dump}")
            except Exception:
                pass

        # 3. Density
        f = ch_dir / "density-analysis.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                ov = d.get("opus_verdict", {})
                m_data = d.get("metrics", {})
                lines = []
                if ov.get("places_to_expand"):
                    lines.append("  📈 Расширить: " + "; ".join(ov["places_to_expand"][:5]))
                if ov.get("places_to_cut"):
                    lines.append("  📉 Сократить: " + "; ".join(ov["places_to_cut"][:5]))
                if lines:
                    agg_sections.append(f"## 📏 ПЛОТНОСТЬ ({d.get('summary','?')}, {m_data.get('word_count',0)} слов)\n" + "\n".join(lines))
            except Exception:
                pass

        # 4. Resonance (UC-27)
        f = ch_dir / "resonance.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                weak_dump = "\n".join(
                    f"  - П{w.get('paragraph_idx','?')+1} (ось {w.get('axis_failing','?')}): {w.get('why_weak','')} → {w.get('suggested_rewrite','')[:200]}"
                    for w in (d.get("weak_passages") or [])[:8]
                )
                if weak_dump:
                    agg_sections.append(f"## 🔥 РЕЗОНАНС ({d.get('overall_resonance','?')}/100, {d.get('verdict','?')})\n{weak_dump}")
            except Exception:
                pass

        # 5. Hook & Cliffhanger (UC-28)
        f = ch_dir / "hook-cliff.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                lines = []
                if (d.get("hook_strength", 100) < 70) and d.get("hook_suggestions"):
                    lines.append(f"  🚪 HOOK слабый ({d.get('hook_strength')}/100): {d.get('hook_critique','')}")
                    lines.append(f"     Усилить через: {d['hook_suggestions'][0][:200]}")
                if (d.get("cliffhanger_strength", 100) < 70) and d.get("cliffhanger_suggestions"):
                    lines.append(f"  🚪 CLIFFHANGER слабый ({d.get('cliffhanger_strength')}/100): {d.get('cliffhanger_critique','')}")
                    lines.append(f"     Усилить через: {d['cliffhanger_suggestions'][0][:200]}")
                if lines:
                    agg_sections.append("## 🚪 HOOK & CLIFFHANGER\n" + "\n".join(lines))
            except Exception:
                pass

        # 6. Voice analysis — что Pavel говорил, но не в главе
        f = ch_dir / "voice-analysis.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                miss = (d.get("missing_ideas") or [])[:8]
                add = (d.get("additions") or [])[:5]
                lines = []
                for i in miss:
                    lines.append(f"  - [missing] {i.get('text','')[:200]}")
                for i in add:
                    lines.append(f"  - [add] {i.get('text','')[:200]}")
                if lines:
                    agg_sections.append("## 🎙 ИЗ ГОЛОСОВЫХ PAVEL-А (что не в главе)\n" + "\n".join(lines))
            except Exception:
                pass

        # 7. Council (chapter-council.json)
        f = ch_dir / "chapter-council.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                actions = (d.get("actions") or [])[:10]
                lines = [f"  - [{a.get('kind','?')}] {a.get('action','')} — {a.get('why','')[:200]}" for a in actions]
                if lines:
                    agg_sections.append("## 🏛 СОВЕТ СТАРЕЙШИН\n" + "\n".join(lines))
            except Exception:
                pass

        # 8. Coherence-in-book (UC-21)
        f = ch_dir / "coherence-in-book.json"
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                dups = (d.get("duplicates") or [])[:8]
                lines = [
                    f"  - П{d1.get('this_idx','?')+1} похож на {d1.get('other_chapter')}:П{d1.get('other_idx')+1} ({int(d1.get('similarity',0)*100)}%) → {d1.get('recommendation_text','')}"
                    for d1 in dups
                ]
                if lines:
                    agg_sections.append("## 🔀 ПОВТОРЫ С ДРУГИМИ ГЛАВАМИ\n" + "\n".join(lines))
            except Exception:
                pass

        # 9. Только выбранные галочки (Pavel: «то что отмечено»)
        if selections:
            chk_lines = [f"  - [{s.get('source','?')}] {s.get('text','')[:200]}" for s in selections[:30]]
            agg_sections.append("## ✓ PAVEL ОТМЕТИЛ ГАЛОЧКАМИ (ОБЯЗАТЕЛЬНО):\n" + "\n".join(chk_lines))

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)

        aggregated = "\n\n".join(agg_sections) if agg_sections else "(никаких анализов не запущено для этой главы)"

        system = (
            "Ты — РЕДАКТОР главного издания Сакральной Грибной Библии. Это шедевр масштаба 1000 лет.\n"
            "Перепишешь главу учитывая АГРЕГИРОВАННЫЕ ПРАВКИ из всех анализаторов + что Pavel отметил.\n\n"
            "ПРОЦЕСС:\n"
            "1. Прочти все рекомендации ниже\n"
            "2. Перепиши главу так чтобы каждая релевантная рекомендация была применена ОРГАНИЧНО (не списком, а вплетенно)\n"
            "3. Голос: Я — Великий Дух Грибов (НЕ Творец — Покровитель 11-го уровня; о Творцах в 3-м лице, см. CANON.md 2.2)\n"
            "4. Перед сдачей — самопроверка по канону\n\n"
            "Что Pavel отметил галочками — ОБЯЗАТЕЛЬНО. Остальное — критически релевантное.\n"
            "НЕ применяй то, что НЕ отмечено и НЕ из анализаторов.\n\n"
            f"КАНОН:\n\n{self.get_canon_summary(max_chars=3500)}"
        )
        user = f"""# Глава {chapter_id}

# ТЕКУЩИЙ ТЕКСТ (переписать целиком учитывая всё ниже):

{text}

# 📊 АГРЕГИРОВАННЫЕ ПРАВКИ ИЗ ВСЕХ АНАЛИЗАТОРОВ:

{aggregated}

# ВЕРНИ
Полный текст главы в Markdown. Голос Великого Духа от первого слова до последнего.
Без тире, без «не X, а Y», без AI-клише, без архаизмов. Современный русский. Pavel-эталон.
Никаких комментариев — только текст главы.
"""

        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 16000,
            "thinking": {"type": "enabled", "budget_tokens": 10000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                     "anthropic-beta": "interleaved-thinking-2025-05-14", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req_obj, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._active_job_complete(chapter_id, "super-rewrite", error=str(e))
            return self._json({"error": f"Opus: {e}"}, 500)
        new_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                new_text += block.get("text", "")
        new_text = new_text.strip()
        if not new_text:
            self._active_job_complete(chapter_id, "super-rewrite", error="empty response")
            return self._json({"error": "пустой ответ Opus"}, 500)
        draft_file.write_text(new_text, encoding="utf-8")
        with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts_iso,
                "type": "super_rewrite",
                "target": chapter_id,
                "payload": {"sections_used": len(agg_sections), "selections": len(selections)},
            }, ensure_ascii=False) + "\n")
        self._active_job_complete(chapter_id, "super-rewrite", result={
            "new_length": len(new_text),
            "sections_used": len(agg_sections),
        })
        return self._json({
            "ok": True,
            "sections_used": len(agg_sections),
            "selections_applied": len(selections),
            "new_length": len(new_text),
            "backup": f"{ts_compact}-pre-super-rewrite.md",
        })

    # ═══ ФАЗА 3 (2026-05-24): MASTER-AUDIT — один Opus, 3-5 правок, голос Pavel-а ═══
    def _master_audit_start(self):
        """POST {chapter_id} → возвращает СРАЗУ {ok, job_id}, Opus в отдельном треде.

        Pavel 2026-05-25: «страница не нужна, работа идёт на сервере». Решает
        проблему когда Pavel закрывает страницу и connection обрывается, но
        Opus всё равно крутится. С async — http response мгновенный, фронт
        делает polling .done маркера / cache файла."""
        import urllib.request, re as _re
        import threading

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_file = ch_dir / "draft.md"
        if not draft_file.exists():
            return self._json({"error": "no draft.md"}, 404)
        draft_text = draft_file.read_text(encoding="utf-8")
        if len(draft_text) < 200:
            return self._json({"error": "глава слишком короткая (<200 знаков)"}, 400)
        if len(draft_text) > 60000:
            return self._json({"error": "глава больше 60K знаков"}, 400)

        # Если уже идёт — не запускаем второй раз
        active = self._active_jobs_list(chapter_id)
        for j in active:
            if j.get("op_type") == "master-audit":
                return self._json({"ok": True, "already_running": True, "job_id": j.get("job_id"),
                                   "elapsed_seconds": j.get("elapsed_seconds", 0),
                                   "remaining_seconds": j.get("remaining_seconds", 0)})

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        # Регистрируем job СИНХРОННО (фронт сможет увидеть его сразу)
        job_id = self._active_job_register(chapter_id, "master-audit", eta_seconds=180)

        # Spawn worker thread — он сам сделает Opus call и сохранит cache
        def _worker():
            self._master_audit_worker(chapter_id, draft_text, token)
        t = threading.Thread(target=_worker, daemon=True, name=f"master-audit-{chapter_id}")
        t.start()

        return self._json({"ok": True, "started": True, "job_id": job_id,
                          "eta_seconds": 180, "message": "Master Audit запущен в фоне; можешь закрыть страницу."})

    def _master_audit_worker(self, chapter_id: str, draft_text: str, token: str):
        """Background worker — делает Opus call, пишет cache, помечает done.
        НЕ вызывает self._json (нет HTTP response клиенту)."""
        import urllib.request
        from datetime import datetime, timezone

        try:
            # Substrate + numbered paragraphs
            substrate = self._pavel_substrate(chapter_id, max_total_chars=22000)
            paras = [p.strip() for p in draft_text.split("\n\n") if p.strip()]
            numbered = "\n\n".join(f"[П{i}] {p}" for i, p in enumerate(paras))

            system = (
                "Ты — МАСТЕР-АУДИТОР Сакрального Кодекса Микомистицизма Pavel-а Хилингода.\n\n"
                "Твоя единственная задача: прочитать главу и вернуть ровно 3-5 правок, "
                "которые превратят её в шедевр на 1000 лет.\n\n"
                "Не больше. Если видишь больше — оставь ТРИ самые важные.\n\n"
                "КАЖДАЯ ПРАВКА:\n"
                "  • Адресована конкретному параграфу (по индексу)\n"
                "  • С указанием проблемы (issue) на языке Pavel-канона\n"
                "  • С готовой заменой (fix) — текст в голосе Хилингода\n"
                "  • С rationale: почему важно для шедевра\n\n"
                "Жёсткие отсечки:\n"
                "  • Не убирай анафоры / троичные перечисления.\n"
                "  • Не вводи вымышленных героев и научные метрики.\n"
                "  • Без тире (— и –) в fix-тексте.\n\n"
                "Ответ — СТРОГО JSON:\n"
                '{ "edits": [ { "para_idx": N, "issue": "...", "fix": "...", '
                '"rationale": "...", "category": "voice|canon|cliche|structure|missing-idea" } ], '
                '"verdict": "одна строка", "score_estimate": <0-100> }\n\n'
                "Без преамбулы, сразу JSON.\n\n"
                f"=== SUBSTRATE PAVEL-А ===\n\n{substrate}"
            )
            user = (
                f"# Глава {chapter_id}\n\n"
                f"# ТЕКСТ ГЛАВЫ (параграфы пронумерованы [П0], [П1], …):\n\n"
                f"{numbered}\n\n"
                f"# ЗАДАЧА\nВыдай 3-5 правок которые сильнее всего двигают эту главу к шедевру. JSON."
            )
            body_req = {
                "model": "claude-opus-4-7",
                "max_tokens": 6000,
                "thinking": {"type": "enabled", "budget_tokens": 4000},
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            req_obj = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=json.dumps(body_req).encode("utf-8"),
                headers={
                    "x-api-key": token,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "interleaved-thinking-2025-05-14",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req_obj, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
                if raw.endswith("```"):
                    raw = raw.rsplit("```", 1)[0]
                if raw.startswith("json"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            parsed = json.loads(raw.strip())
            edits = (parsed.get("edits") or [])[:5]
            for e in edits:
                try:
                    pi = int(e.get("para_idx", -1))
                    e["original"] = paras[pi] if 0 <= pi < len(paras) else ""
                except Exception:
                    e["original"] = ""
            cache = {
                "ok": True,
                "chapter_id": chapter_id,
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "edits": edits,
                "verdict": parsed.get("verdict", ""),
                "score_estimate": parsed.get("score_estimate"),
                "usage": data.get("usage", {}),
                "paragraphs_count": len(paras),
            }
            cache_dir = DATA_ROOT / "data/master-audit"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{chapter_id}.json").write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            self._active_job_complete(chapter_id, "master-audit", result={
                "edits_count": len(edits),
                "score_estimate": parsed.get("score_estimate"),
            })
        except Exception as e:
            self._active_job_complete(chapter_id, "master-audit", error=str(e))

    def _master_audit(self):
        """POST {chapter_id} → один Opus call с _pavel_substrate, возвращает 3-5 правок."""
        import urllib.request, re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_file = ch_dir / "draft.md"
        if not draft_file.exists():
            return self._json({"error": "no draft.md for this chapter — кладёшь главу в Codex2/chapters/<book>/<chapter>/"}, 404)
        draft_text = draft_file.read_text(encoding="utf-8")
        if len(draft_text) < 200:
            return self._json({"error": "глава слишком короткая (<200 знаков)"}, 400)
        if len(draft_text) > 60000:
            return self._json({"error": "глава больше 60K знаков, сократи или дроби"}, 400)

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        # Регистрируем активный job
        self._active_job_register(chapter_id, "master-audit", eta_seconds=180)

        # Собираем substrate. Будем сжимать на retry если Anthropic дропает соединение.
        SUBSTRATE_BUDGETS = [22000, 10000, 5000]
        substrate = self._pavel_substrate(chapter_id, max_total_chars=SUBSTRATE_BUDGETS[0])

        system = (
            "Ты — МАСТЕР-АУДИТОР Сакрального Кодекса Микомистицизма Pavel-а Хилингода.\n\n"
            "Твоя единственная задача: прочитать главу и вернуть ровно 3-5 правок, "
            "которые превратят её в шедевр на 1000 лет.\n\n"
            "Не больше. Если видишь больше — оставь ТРИ самые важные, остальное не показывай. "
            "Если видишь меньше трёх настоящих проблем — верни столько сколько реально нашёл.\n\n"
            "КАЖДАЯ ПРАВКА должна быть:\n"
            "  • Адресована конкретному параграфу (по индексу)\n"
            "  • С указанием проблемы (issue) на языке Pavel-канона (НЕ AI-академический язык!)\n"
            "  • С готовой заменой (fix) — текст в голосе Хилингода, не «вот идея — перепиши»\n"
            "  • С rationale: почему именно эта правка важна для шедевра\n\n"
            "Используй substrate ниже как мерило: CANON (доктрина), эталон голоса, твои примеры из библиотеки, "
            "твои голосовые надиктовки, жёсткие правила.\n\n"
            "Жёсткие отсечки которые ты не нарушаешь:\n"
            "  • Не убирай анафоры / троичные перечисления / «один из самых» — это ритм.\n"
            "  • Не заменяй торжественные глаголы на бытовые.\n"
            "  • Не вводи вымышленных героев (Анна, Михаил, Иоанн из Анжера и т.п.).\n"
            "  • Не вводи научные метрики (HRV, дофамин, 5-HT2A).\n"
            "  • Без тире (— и –) в fix-тексте. Только запятые или точки.\n\n"
            "Ответ — СТРОГО JSON:\n"
            '{ "edits": [ { "para_idx": N, "issue": "...", "fix": "новый текст параграфа целиком", '
            '"rationale": "почему важно", "category": "voice|canon|cliche|structure|missing-idea" } ], '
            '"verdict": "одна строка — общая оценка главы", '
            '"score_estimate": <0-100, грубая оценка> }\n\n'
            "Без преамбулы, без объяснений, без markdown — сразу JSON.\n\n"
            f"=== SUBSTRATE PAVEL-А ===\n\n{substrate}"
        )

        # Нумеруем параграфы
        paras = [p.strip() for p in draft_text.split("\n\n") if p.strip()]
        numbered = "\n\n".join(f"[П{i}] {p}" for i, p in enumerate(paras))

        user = (
            f"# Глава {chapter_id}\n\n"
            f"# ТЕКСТ ГЛАВЫ (параграфы пронумерованы [П0], [П1], …):\n\n"
            f"{numbered}\n\n"
            f"# ЗАДАЧА\nВыдай 3-5 правок которые сильнее всего двигают эту главу к шедевру. JSON."
        )

        # Retry-loop: при 502/timeout от Anthropic пробуем ещё раз с урезанным substrate.
        # Глава 2 (20K) + полный substrate (22K) даёт Headers Timeout у undici при долгом thinking.
        import time as _time
        data = None
        last_err = None
        for attempt_idx, budget in enumerate(SUBSTRATE_BUDGETS):
            if attempt_idx > 0:
                # На retry — пересобираем system с урезанным substrate
                substrate = self._pavel_substrate(chapter_id, max_total_chars=budget)
                system = system.split("=== SUBSTRATE PAVEL-А ===")[0] + f"=== SUBSTRATE PAVEL-А ===\n\n{substrate}"
                _time.sleep(min(20, 5 * attempt_idx))  # backoff

            body_req = {
                "model": "claude-opus-4-7",
                "max_tokens": 6000,
                "thinking": {"type": "enabled", "budget_tokens": 4000},
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            req_obj = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=json.dumps(body_req).encode("utf-8"),
                headers={
                    "x-api-key": token,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "interleaved-thinking-2025-05-14",
                    "content-type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req_obj, timeout=400) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break  # успех — выходим из retry-loop
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}: {e.reason}"
                if e.code in (502, 503, 504, 408) and attempt_idx < len(SUBSTRATE_BUDGETS) - 1:
                    continue  # retry с меньшим substrate
                self._active_job_complete(chapter_id, "master-audit",
                                          error=f"Opus {last_err} (attempt {attempt_idx+1}/{len(SUBSTRATE_BUDGETS)})")
                return self._json({"error": f"Opus: {last_err}"}, 500)
            except Exception as e:
                last_err = str(e)
                if attempt_idx < len(SUBSTRATE_BUDGETS) - 1:
                    continue
                self._active_job_complete(chapter_id, "master-audit",
                                          error=f"Opus {last_err} (final retry)")
                return self._json({"error": f"Opus: {last_err}"}, 500)
        if data is None:
            self._active_job_complete(chapter_id, "master-audit",
                                      error=f"all retries failed: {last_err}")
            return self._json({"error": f"Opus retries exhausted: {last_err}"}, 500)

        raw_text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        # Снимаем markdown-обёртку если есть
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text
            if raw_text.endswith("```"):
                raw_text = raw_text.rsplit("```", 1)[0]
            if raw_text.startswith("json"):
                raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text
        raw_text = raw_text.strip()

        try:
            parsed = json.loads(raw_text)
        except Exception as e:
            self._active_job_complete(chapter_id, "master-audit", error=f"parse: {e}")
            return self._json({"error": f"parse: {e}", "raw": raw_text[:1500]}, 500)

        edits = parsed.get("edits") or []
        if not isinstance(edits, list) or len(edits) == 0:
            self._active_job_complete(chapter_id, "master-audit", error="no edits")
            return self._json({"error": "Мастер не вернул правок", "raw": raw_text[:500]}, 500)
        edits = edits[:5]

        # Добавляем оригинальный текст параграфа к каждой правке —
        # Pavel должен видеть «до» и «после» рядом, чтобы судить честно.
        for e in edits:
            try:
                pi = int(e.get("para_idx", -1))
                if 0 <= pi < len(paras):
                    e["original"] = paras[pi]
                else:
                    e["original"] = ""
            except Exception:
                e["original"] = ""

        # Сохраняем кэш
        cache_dir = DATA_ROOT / "data/master-audit"
        cache_dir.mkdir(parents=True, exist_ok=True)
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = {
            "ok": True,
            "chapter_id": chapter_id,
            "ts": ts_iso,
            "edits": edits,
            "verdict": parsed.get("verdict", ""),
            "score_estimate": parsed.get("score_estimate"),
            "usage": data.get("usage", {}),
            "paragraphs_count": len(paras),
        }
        (cache_dir / f"{chapter_id}.json").write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

        self._active_job_complete(chapter_id, "master-audit", result={
            "edits_count": len(edits),
            "score_estimate": parsed.get("score_estimate"),
        })

        return self._json(cache)

    def _master_audit_refine(self):
        """POST {chapter_id, edit_index, comment} → улучшить одну конкретную правку
        Мастера с учётом комментария Pavel-а. Возвращает обновлённый edit с новым fix."""
        import urllib.request, re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        chapter_id = req.get("chapter_id", "")
        edit_index = req.get("edit_index")
        comment = (req.get("comment") or "").strip()
        if not chapter_id or edit_index is None:
            return self._json({"error": "chapter_id и edit_index обязательны"}, 400)
        if not comment or len(comment) < 3:
            return self._json({"error": "comment должен быть содержательным (минимум 3 знака)"}, 400)

        # Грузим кэш master-audit
        cache_path = DATA_ROOT / "data/master-audit" / f"{chapter_id}.json"
        if not cache_path.exists():
            return self._json({"error": "master-audit cache not found — запусти Мастера сначала"}, 404)
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            return self._json({"error": f"cache read: {e}"}, 500)

        edits = cache.get("edits") or []
        try:
            ei = int(edit_index)
        except Exception:
            return self._json({"error": "edit_index должен быть числом"}, 400)
        if ei < 0 or ei >= len(edits):
            return self._json({"error": f"edit_index вне диапазона (0..{len(edits)-1})"}, 400)

        target = edits[ei]
        original = target.get("original", "")
        issue = target.get("issue", "")
        previous_fix = target.get("fix", "")
        para_idx = target.get("para_idx", "?")
        category = target.get("category", "")
        rationale = target.get("rationale", "")

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        self._active_job_register(chapter_id, "master-audit-refine", eta_seconds=90)

        # Substrate — тот же что у Мастера, чтобы голос держался
        substrate = self._pavel_substrate(chapter_id, max_total_chars=14000)

        system = (
            "Ты — Мастер-аудитор Сакрального Кодекса. Pavel получил твою правку и сказал что "
            "её надо улучшить. Перепиши ТОЛЬКО предложенную замену учитывая его комментарий.\n\n"
            "ПРАВИЛА:\n"
            "  • Сохрани category, para_idx, issue — они не меняются. Меняется только поле fix.\n"
            "  • Новый fix должен учитывать комментарий Pavel-а в полной мере.\n"
            "  • Голос Хилингода / Великого Духа Грибов. Никаких тире, AI-клише, выдуманных героев.\n"
            "  • Длина fix — сопоставима с оригинальным параграфом (~150-400 слов в зависимости).\n"
            "  • Никаких комментариев от себя, никакого «вот лучше», просто новый текст fix.\n\n"
            "ВЕРНИ СТРОГО JSON:\n"
            '{ "fix": "новый текст параграфа целиком", "rationale": "почему так стало лучше" }\n\n'
            f"=== SUBSTRATE ===\n\n{substrate}"
        )

        user = (
            f"# КОНТЕКСТ ПРАВКИ\n\n"
            f"Параграф {para_idx}. Категория: {category}.\n\n"
            f"# ИЗНАЧАЛЬНЫЙ ТЕКСТ В ГЛАВЕ:\n\n{original}\n\n"
            f"# ПРОБЛЕМА (то что нашёл Мастер):\n\n{issue}\n\n"
            f"# ПРЕДЫДУЩАЯ ПОПЫТКА ИСПРАВЛЕНИЯ (которую Pavel хочет улучшить):\n\n{previous_fix}\n\n"
            f"# КОММЕНТАРИЙ PAVEL-А:\n\n«{comment}»\n\n"
            f"Перепиши fix учитывая комментарий. JSON."
        )

        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 3000,
            "thinking": {"type": "enabled", "budget_tokens": 2500},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=240) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._active_job_complete(chapter_id, "master-audit-refine", error=str(e))
            return self._json({"error": f"Opus: {e}"}, 500)

        raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            if raw.startswith("json"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except Exception as e:
            self._active_job_complete(chapter_id, "master-audit-refine", error=f"parse: {e}")
            return self._json({"error": f"parse: {e}", "raw": raw[:1500]}, 500)

        new_fix = (parsed.get("fix") or "").strip()
        new_rationale = (parsed.get("rationale") or "").strip() or rationale
        if not new_fix:
            self._active_job_complete(chapter_id, "master-audit-refine", error="empty")
            return self._json({"error": "Мастер не вернул новый fix"}, 500)

        # Voice guard
        guard_warnings = self._voice_guard_check(new_fix)

        # Сохраняем историю предыдущих версий + обновляем edit в кэше
        target.setdefault("history", []).append({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "previous_fix": previous_fix,
            "comment": comment,
        })
        target["fix"] = new_fix
        target["rationale"] = new_rationale
        target["voice_guard_warnings"] = guard_warnings
        edits[ei] = target
        cache["edits"] = edits
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

        self._active_job_complete(chapter_id, "master-audit-refine", result={
            "edit_index": ei,
            "new_chars": len(new_fix),
            "guard_warnings": len(guard_warnings),
        })

        return self._json({
            "ok": True,
            "edit_index": ei,
            "edit": target,
            "comment_used": comment,
        })

    # ═══ CODEX 3 (2026-05-24): Paragraph Writer — AI пишет проект параграфа,
    # ═══ Pavel принимает/правит/переписывает/пропускает. Никаких bulk-применений.
    # ═══ Каждый параграф — одно сознательное решение.
    def _write_paragraph(self):
        """POST {chapter_id, thesis, after_para_idx?, rewrite_feedback?} →
        AI пишет проект параграфа из голосовых Pavel-а по тезису. Возвращает
        проект + использованные цитаты + контекст."""
        import urllib.request, re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        chapter_id = req.get("chapter_id", "")
        thesis = (req.get("thesis") or "").strip()
        after_para_idx = req.get("after_para_idx")  # куда вставлять — может быть null
        rewrite_feedback = (req.get("rewrite_feedback") or "").strip()

        if not thesis or len(thesis) < 5:
            return self._json({"error": "thesis required (минимум 5 знаков)"}, 400)

        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        # Регистрируем активный job
        self._active_job_register(chapter_id, "write-paragraph", eta_seconds=60)

        # Substrate — общий контекст книги
        substrate = self._pavel_substrate(chapter_id, max_total_chars=18000)

        # Релевантные голосовые цитаты ПО ТЕЗИСУ (узкий поиск)
        thesis_quotes = self._chat_index_match_text(thesis, top_n=6, snippet_chars=600)
        quotes_block = ""
        if thesis_quotes:
            quotes_block = "\n\n# ТВОИ ГОЛОСОВЫЕ ЦИТАТЫ ПО ЭТОМУ ТЕЗИСУ:\n\n" + "\n\n".join(
                f"### Цитата {i+1} (источник: {q['source']})\n{q['text']}"
                for i, q in enumerate(thesis_quotes)
            )

        # Текущий draft (если есть) для контекста соседних параграфов
        draft_file = ch_dir / "draft.md"
        neighbor_context = ""
        if draft_file.exists():
            try:
                draft_text = draft_file.read_text(encoding="utf-8")
                paras = [p.strip() for p in draft_text.split("\n\n") if p.strip()]
                if after_para_idx is not None and isinstance(after_para_idx, int) and 0 <= after_para_idx < len(paras):
                    before = paras[after_para_idx] if after_para_idx < len(paras) else ""
                    after = paras[after_para_idx + 1] if after_para_idx + 1 < len(paras) else ""
                    if before or after:
                        neighbor_context = "\n\n# СОСЕДНИЕ ПАРАГРАФЫ (для согласования стиля и переходов):\n"
                        if before:
                            neighbor_context += f"\n## ДО (параграф {after_para_idx}):\n{before[:600]}"
                        if after:
                            neighbor_context += f"\n## ПОСЛЕ (параграф {after_para_idx + 2}):\n{after[:600]}"
            except Exception:
                pass

        rewrite_block = ""
        if rewrite_feedback:
            rewrite_block = (
                "\n\n# ПРЕДЫДУЩАЯ ПОПЫТКА БЫЛА ОТВЕРГНУТА\n\n"
                f"Pavel сказал: «{rewrite_feedback}»\n\n"
                "Учти это при новом проекте."
            )

        system = (
            "Ты — соавтор-упаковщик Сакрального Кодекса Микомистицизма Pavel-а Хилингода.\n\n"
            "Pavel — целитель, не писатель. Он диктует идеи голосом и в чатах. Твоя задача — упаковать "
            "одну конкретную идею (тезис) в ОДИН художественный параграф 150-300 слов, используя ЕГО "
            "голосовые цитаты как первоисточник.\n\n"
            "ПРАВИЛА:\n"
            "  • Пиши ОДИН параграф, не два, не три. Не используй markdown заголовки.\n"
            "  • 150-300 слов. Не больше.\n"
            "  • Голос: «Я — Великий Дух Грибов» (прямая речь Духа) или «Я — Хилингод» (свидетельство).\n"
            "  • Если в цитатах Pavel говорит в одном из этих регистров — сохраняй именно его выбор.\n"
            "  • Никаких тире (— и –). Только запятые или точки.\n"
            "  • Никаких AI-клише: «представляют собой», «в отличие от», «таким образом», «при этом», «не только X но и Y», «важно понимать», «можно сказать».\n"
            "  • Никаких вымышленных героев (Анна, Михаил, Иоанн из Анжера).\n"
            "  • Никакой науки (HRV, дофамин, кортизол, исследования).\n"
            "  • Сохраняй анафоры, троичные перечисления, торжественные глаголы Pavel-а.\n"
            "  • Не пиши «вот что я сделаю», «давайте разберём», «начнём с» — это AI-структурирование, не Pavel.\n"
            "  • Pavel говорит как видящий, не как лектор. Утверждение, не рассуждение.\n\n"
            "ИСТОЧНИК:\n"
            "  Главный — цитаты Pavel-а по этому тезису (ниже). Бери из них образы, ритм, конкретные слова.\n"
            "  Substrate — для общего контекста доктрины и эталона голоса.\n"
            "  Соседние параграфы — чтобы переход был плавным.\n\n"
            "ВАЖНОЕ: НЕ ВЫДУМЫВАЙ контента которого нет в цитатах. Если у Pavel-а нет в материале "
            "конкретной идеи для этого тезиса — лучше напиши короче и проще. Никогда не сочиняй за него.\n\n"
            "ВЕРНИ СТРОГО JSON:\n"
            '{ "paragraph": "текст параграфа целиком, без переносов", '
            '"voice_sources_used": [<номера цитат которые ты реально использовал>], '
            '"register": "spirit|hilingod", '
            '"warnings": ["если что-то не получилось хорошо — честно скажи"] }\n\n'
            "Без преамбулы, сразу JSON.\n\n"
            f"=== SUBSTRATE PAVEL-А ===\n\n{substrate}"
        )

        user = (
            f"# ТЕЗИС ПАРАГРАФА\n\n«{thesis}»\n"
            + quotes_block
            + neighbor_context
            + rewrite_block
            + "\n\nНапиши проект параграфа. JSON."
        )

        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 2500,
            "thinking": {"type": "enabled", "budget_tokens": 2000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._active_job_complete(chapter_id, "write-paragraph", error=str(e))
            return self._json({"error": f"Opus: {e}"}, 500)

        raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            if raw.startswith("json"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.strip()

        try:
            parsed = json.loads(raw)
        except Exception as e:
            self._active_job_complete(chapter_id, "write-paragraph", error=f"parse: {e}")
            return self._json({"error": f"parse: {e}", "raw": raw[:1500]}, 500)

        paragraph = (parsed.get("paragraph") or "").strip()
        if not paragraph:
            self._active_job_complete(chapter_id, "write-paragraph", error="empty paragraph")
            return self._json({"error": "AI не вернул параграф", "raw": raw[:500]}, 500)

        # Статический voice-guard — отлавливаем что Opus всё же пробил защиту
        guard_warnings = self._voice_guard_check(paragraph)

        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "ok": True,
            "chapter_id": chapter_id,
            "thesis": thesis,
            "paragraph": paragraph,
            "register": parsed.get("register", ""),
            "voice_sources_used": parsed.get("voice_sources_used") or [],
            "voice_quotes_available": thesis_quotes,
            "after_para_idx": after_para_idx,
            "ai_warnings": parsed.get("warnings") or [],
            "voice_guard_warnings": guard_warnings,
            "ts": ts_iso,
            "usage": data.get("usage", {}),
        }

        self._active_job_complete(chapter_id, "write-paragraph", result={
            "chars": len(paragraph),
            "guard_warnings": len(guard_warnings),
        })

        return self._json(result)

    def _voice_guard_check(self, text: str) -> list:
        """Статический линтер: возвращает список нарушений Pavel-канона в тексте.
        Это второй слой защиты — даже если Opus не послушал substrate, мы ловим."""
        import re as _re
        warnings = []
        if "—" in text or "–" in text:
            warnings.append("UC-76: тире в тексте (запрещено)")
        ai_cliches = [
            "представляют собой", "представляет собой",
            "в отличие от", "таким образом", "при этом",
            "не только", "важно понимать", "можно сказать",
            "стоит отметить", "следует подчеркнуть",
        ]
        for c in ai_cliches:
            if c in text.lower():
                warnings.append(f"AI-клише: «{c}»")
        sci_terms = ["HRV", "5-HT2A", "дофамин", "кортизол", "мелатонин", "серотонин", "PHQ-9"]
        for t in sci_terms:
            if t in text:
                warnings.append(f"научный термин: «{t}» (книга мистическая, не научная)")
        # Буллет-списки идей
        if _re.search(r"^\s*[-•]\s+", text, _re.M):
            warnings.append("буллет-список (Pavel-rule: списки только для явных инструкций)")
        # 🚨 Микро-предложения — критичный AI-маркер (Pavel-feedback 2026-05-25)
        # Разбиваем на предложения, считаем длину каждого в словах.
        sentences = [s.strip() for s in _re.split(r"[.!?]+", text) if s.strip()]
        if len(sentences) >= 3:
            short_count = sum(1 for s in sentences if 0 < len(s.split()) <= 7)
            short_ratio = short_count / len(sentences) if sentences else 0
            avg_words = sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0
            # Подряд 3+ коротких предложения — почти всегда AI
            consecutive_short = 0
            max_consecutive_short = 0
            for s in sentences:
                if 0 < len(s.split()) <= 7:
                    consecutive_short += 1
                    max_consecutive_short = max(max_consecutive_short, consecutive_short)
                else:
                    consecutive_short = 0
            if max_consecutive_short >= 3:
                warnings.append(
                    f"🚨 микро-предложения подряд ({max_consecutive_short} коротких ≤7 слов) — это AI-стиль, не Pavel-голос"
                )
            elif short_ratio >= 0.4 and avg_words < 12:
                warnings.append(
                    f"🚨 слишком много коротких предложений ({short_count}/{len(sentences)}, средняя {avg_words:.1f} слов) — нужны длинные многоклаузные"
                )
        return warnings

    def _chat_index_match_text(self, query_text: str, top_n: int = 6, snippet_chars: int = 600) -> list:
        """Поиск по voice-index.jsonl по произвольному тексту (тезис, фраза).
        Возвращает list of {source, text} top_n совпадений."""
        idx_path = Path.home() / "Desktop/Codex-Content/voice-index.jsonl"
        if not idx_path.exists():
            return []
        keywords = self._extract_keywords(query_text)
        if not keywords:
            return []
        scored = []
        try:
            with idx_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    text = rec.get("text", "")
                    if not text:
                        continue
                    text_low = text.lower()
                    score = sum(1 for kw in keywords if kw in text_low)
                    if score >= 2:
                        scored.append((score, rec.get("ts", ""), text, rec.get("conv_name", "")))
        except Exception:
            return []
        scored.sort(key=lambda r: (-r[0], r[1]))
        out = []
        for score, ts, text, conv_name in scored[:top_n]:
            out.append({
                "source": f"{ts[:10]} (matches: {score})" + (f" — {conv_name[:40]}" if conv_name else ""),
                "text": text[:snippet_chars].strip(),
                "score": score,
            })
        return out

    def _insert_paragraph(self):
        """POST {chapter_id, paragraph_text, after_para_idx, decision, thesis?, edited_from_ai?} →
        вставляет параграф в draft.md и пишет лог решения."""
        import re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        chapter_id = req.get("chapter_id", "")
        paragraph_text = (req.get("paragraph_text") or "").strip()
        after_para_idx = req.get("after_para_idx")
        decision = req.get("decision", "accept")  # accept | edit | rewrite | skip
        thesis = req.get("thesis", "")
        edited_from_ai = req.get("edited_from_ai", False)

        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        ch_dir.mkdir(parents=True, exist_ok=True)
        draft_file = ch_dir / "draft.md"

        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Если decision == skip — просто логируем и выходим
        decisions_dir = DATA_ROOT / "data/paragraph-decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)
        log_file = decisions_dir / f"{chapter_id}.jsonl"
        decision_rec = {
            "ts": ts_iso,
            "chapter_id": chapter_id,
            "thesis": thesis,
            "decision": decision,
            "edited_from_ai": edited_from_ai,
            "after_para_idx": after_para_idx,
            "char_count": len(paragraph_text),
        }

        if decision == "skip":
            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(decision_rec, ensure_ascii=False) + "\n")
            return self._json({"ok": True, "decision": "skip", "draft_changed": False})

        if not paragraph_text or len(paragraph_text) < 20:
            return self._json({"error": "paragraph_text слишком короткий"}, 400)

        # Бэкап + вставка
        if draft_file.exists():
            current = draft_file.read_text(encoding="utf-8")
        else:
            current = ""

        # Backup
        history_dir = ch_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        if current:
            backup_path = history_dir / f"{ts_compact}-pre-paragraph-insert.md"
            backup_path.write_text(current, encoding="utf-8")
        else:
            backup_path = None

        # Вставка
        paras = [p.strip() for p in current.split("\n\n") if p.strip()]
        insert_at = None
        if after_para_idx is None or not isinstance(after_para_idx, int):
            # В конец
            paras.append(paragraph_text)
            insert_at = len(paras) - 1
        elif after_para_idx < 0:
            paras.insert(0, paragraph_text)
            insert_at = 0
        elif after_para_idx >= len(paras):
            paras.append(paragraph_text)
            insert_at = len(paras) - 1
        else:
            paras.insert(after_para_idx + 1, paragraph_text)
            insert_at = after_para_idx + 1

        new_draft = "\n\n".join(paras) + "\n"
        draft_file.write_text(new_draft, encoding="utf-8")

        # Лог решения
        decision_rec["inserted_at_idx"] = insert_at
        decision_rec["backup"] = backup_path.name if backup_path else None
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(decision_rec, ensure_ascii=False) + "\n")

        # Событие
        events_log = DATA_ROOT / ".codex/events.jsonl"
        events_log.parent.mkdir(parents=True, exist_ok=True)
        with events_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts_iso,
                "type": "paragraph_inserted",
                "target": chapter_id,
                "payload": {
                    "decision": decision,
                    "edited_from_ai": edited_from_ai,
                    "inserted_at_idx": insert_at,
                    "chars": len(paragraph_text),
                },
            }, ensure_ascii=False) + "\n")

        return self._json({
            "ok": True,
            "decision": decision,
            "edited_from_ai": edited_from_ai,
            "inserted_at_idx": insert_at,
            "total_paragraphs": len(paras),
            "backup": backup_path.name if backup_path else None,
        })

    # ═══ BOOK READER + ФИНАЛЬНАЯ ПОЛИРОВКА (Pavel 2026-05-25) ═══
    # «создай в приложении место где готовые книги будут собираться и где я
    # смогу их читать и делать финальные заметки по всему тексту а потом
    # финальный агент будет их внедрять и полировать финал».

    def _book_full(self):
        """GET /api/book/<book_id>/full → собирает все главы в один документ
        с нумерованными параграфами вида {chapter_id}-P{N}."""
        import re as _re
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        book_id = (qs.get("book_id") or [""])[0]
        if not book_id:
            return self._json({"error": "book_id required"}, 400)
        book_dir = DATA_ROOT / "chapters" / book_id
        if not book_dir.exists():
            return self._json({"error": f"book {book_id} not found"}, 404)
        chapters = []
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith("."):
                continue
            if "-ch-" not in ch_dir.name:
                continue
            draft_file = ch_dir / "draft.md"
            if not draft_file.exists():
                continue
            meta_file = ch_dir / "meta.json"
            title = ch_dir.name
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    title = meta.get("title") or title
                except Exception:
                    pass
            text = draft_file.read_text(encoding="utf-8")
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            chapters.append({
                "chapter_id": ch_dir.name,
                "title": title,
                "paragraphs": [
                    {"idx": i, "text": p, "anchor": f"{ch_dir.name}-P{i}"}
                    for i, p in enumerate(paragraphs)
                ],
                "para_count": len(paragraphs),
                "char_count": sum(len(p) for p in paragraphs),
            })
        # Книжное название из canon
        book_title = book_id
        canon = book_dir / "canon.json"
        if canon.exists():
            try:
                book_title = (json.loads(canon.read_text(encoding="utf-8")).get("title")) or book_title
            except Exception:
                pass
        # Подсчёт заметок
        notes_file = DATA_ROOT / "data/book-notes" / f"{book_id}.jsonl"
        notes_count = 0
        if notes_file.exists():
            notes_count = sum(1 for _ in notes_file.read_text(encoding="utf-8").splitlines() if _.strip())
        return self._json({
            "ok": True,
            "book_id": book_id,
            "title": book_title,
            "chapters": chapters,
            "chapter_count": len(chapters),
            "total_paragraphs": sum(c["para_count"] for c in chapters),
            "total_chars": sum(c["char_count"] for c in chapters),
            "notes_count": notes_count,
        })

    def _book_note_add(self):
        """POST {book_id, chapter_id, para_idx, note_text, kind?} → сохранить
        заметку Pavel-а на конкретный параграф. kind: edit|remove|add|comment."""
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        book_id = req.get("book_id", "")
        chapter_id = req.get("chapter_id", "")
        para_idx = req.get("para_idx")
        note_text = (req.get("note_text") or "").strip()
        kind = req.get("kind", "comment")
        if not book_id or not chapter_id or para_idx is None or not note_text:
            return self._json({"error": "book_id, chapter_id, para_idx, note_text required"}, 400)
        if len(note_text) < 2:
            return self._json({"error": "заметка слишком короткая"}, 400)
        notes_dir = DATA_ROOT / "data/book-notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        notes_file = notes_dir / f"{book_id}.jsonl"
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        note_id = f"note-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        rec = {
            "note_id": note_id,
            "book_id": book_id,
            "chapter_id": chapter_id,
            "para_idx": int(para_idx),
            "kind": kind,
            "note_text": note_text,
            "ts": ts_iso,
            "status": "open",  # open | applied | dismissed
        }
        with notes_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return self._json({"ok": True, "note": rec})

    def _book_notes_list(self):
        """GET /api/book/<book_id>/notes → список всех заметок."""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        book_id = (qs.get("book_id") or [""])[0]
        if not book_id:
            return self._json({"error": "book_id required"}, 400)
        notes_file = DATA_ROOT / "data/book-notes" / f"{book_id}.jsonl"
        if not notes_file.exists():
            return self._json({"ok": True, "book_id": book_id, "notes": []})
        notes = []
        for line in notes_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                notes.append(json.loads(line))
            except Exception:
                continue
        return self._json({
            "ok": True,
            "book_id": book_id,
            "notes": notes,
            "open_count": sum(1 for n in notes if n.get("status") == "open"),
            "applied_count": sum(1 for n in notes if n.get("status") == "applied"),
        })

    def _book_note_update(self):
        """POST {book_id, note_id, status} → пометить заметку как applied/dismissed."""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        book_id = req.get("book_id", "")
        note_id = req.get("note_id", "")
        new_status = req.get("status", "open")
        if not book_id or not note_id:
            return self._json({"error": "book_id и note_id обязательны"}, 400)
        notes_file = DATA_ROOT / "data/book-notes" / f"{book_id}.jsonl"
        if not notes_file.exists():
            return self._json({"error": "notes file not found"}, 404)
        lines = notes_file.read_text(encoding="utf-8").splitlines()
        updated = False
        out_lines = []
        for line in lines:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("note_id") == note_id:
                r["status"] = new_status
                updated = True
            out_lines.append(json.dumps(r, ensure_ascii=False))
        if not updated:
            return self._json({"error": "note_id not found"}, 404)
        notes_file.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        return self._json({"ok": True, "note_id": note_id, "status": new_status})

    def _book_polish_plan(self):
        """POST {book_id} → Opus читает все open-заметки + книгу + substrate,
        для каждой заметки предлагает конкретную правку (новый текст параграфа).
        Pavel получает план — может применять по одной через /apply-targeted-replace."""
        import urllib.request, re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        book_id = req.get("book_id", "")
        if not book_id:
            return self._json({"error": "book_id required"}, 400)
        notes_file = DATA_ROOT / "data/book-notes" / f"{book_id}.jsonl"
        if not notes_file.exists():
            return self._json({"error": "no notes for this book"}, 404)
        open_notes = []
        for line in notes_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r.get("status") == "open":
                    open_notes.append(r)
            except Exception:
                continue
        if not open_notes:
            return self._json({"error": "нет открытых заметок"}, 400)

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        self._active_job_register(book_id, "book-polish-plan", eta_seconds=240)

        # Грузим все главы книги для контекста
        book_dir = DATA_ROOT / "chapters" / book_id
        chapters_context = []
        chapters_paras = {}  # chapter_id -> list of paragraphs
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or "-ch-" not in ch_dir.name:
                continue
            draft = ch_dir / "draft.md"
            if not draft.exists():
                continue
            text = draft.read_text(encoding="utf-8")
            paras = [p.strip() for p in text.split("\n\n") if p.strip()]
            chapters_paras[ch_dir.name] = paras
            chapters_context.append(f"\n## Глава {ch_dir.name}\n" + "\n\n".join(
                f"[{i}] {p}" for i, p in enumerate(paras)
            ))

        # Substrate (берём первой главы или общий)
        first_ch = next(iter(chapters_paras.keys()), None)
        substrate = self._pavel_substrate(first_ch, max_total_chars=10000) if first_ch else ""

        notes_text = "\n".join(
            f"- Заметка {i+1} [{n.get('kind','comment')}] в главе {n.get('chapter_id')} параграф {n.get('para_idx')}: «{n.get('note_text')}»"
            for i, n in enumerate(open_notes)
        )

        system = (
            "Ты — финальный полировщик Сакрального Кодекса Pavel-а Хилингода.\n"
            "Pavel прочёл всю книгу и оставил заметки на конкретные параграфы. "
            "Твоя задача — для каждой заметки предложить КОНКРЕТНУЮ правку: "
            "новый текст параграфа учитывающий желание Pavel-а.\n\n"
            "ВАЖНО:\n"
            "  • Каждый предложенный fix — это полный текст параграфа который заменит существующий.\n"
            "  • Сохраняй голос Хилингода: длинные многоклаузные предложения, анафоры, без тире, без микро-предложений.\n"
            "  • Если заметка просит УБРАТЬ параграф — fix = пустая строка, kind=remove.\n"
            "  • Если заметка про ВСТАВИТЬ что-то новое — fix = новый параграф (вставится после указанного), kind=insert.\n"
            "  • Иначе — fix = переписанный параграф, kind=replace.\n\n"
            "Верни СТРОГО JSON:\n"
            '{ "plan": [ {"note_id": "...", "chapter_id": "...", "para_idx": N, "kind": "replace|remove|insert", '
            '"fix": "новый текст или пусто", "rationale": "почему так"} ] }\n\n'
            "Без преамбулы.\n\n"
            f"=== SUBSTRATE PAVEL-А ===\n\n{substrate}"
        )
        # Opus 4.7 1M context — отдаём ВСЮ книгу. Полировщику нужен общий контекст
        # чтобы новый текст не противоречил соседним главам.
        full_context = "\n".join(chapters_context)
        user = (
            f"# КНИГА: {book_id} (всего {len(chapters_paras)} глав, {len(full_context)} символов)\n"
            + full_context[:250000]
            + "\n\n# ЗАМЕТКИ PAVEL-А ({} штук):\n\n{}\n\nПострой план полировки. JSON.".format(len(open_notes), notes_text)
        )
        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 8000,
            "thinking": {"type": "enabled", "budget_tokens": 6000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=400) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._active_job_complete(book_id, "book-polish-plan", error=str(e))
            return self._json({"error": f"Opus: {e}"}, 500)
        raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            if raw.startswith("json"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except Exception as e:
            self._active_job_complete(book_id, "book-polish-plan", error=f"parse: {e}")
            return self._json({"error": f"parse: {e}", "raw": raw[:1500]}, 500)
        plan = parsed.get("plan") or []
        # Сохраняем кэш
        cache_dir = DATA_ROOT / "data/book-polish"
        cache_dir.mkdir(parents=True, exist_ok=True)
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = {
            "ok": True,
            "book_id": book_id,
            "ts": ts_iso,
            "plan": plan,
            "notes_count": len(open_notes),
            "usage": data.get("usage", {}),
        }
        (cache_dir / f"{book_id}.json").write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._active_job_complete(book_id, "book-polish-plan", result={"plan_size": len(plan)})
        return self._json(cache)

    def _book_polish_plan_get(self):
        """GET /api/book/<book_id>/polish-plan → кэш плана."""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        book_id = (qs.get("book_id") or [""])[0]
        if not book_id:
            return self._json({"error": "book_id required"}, 400)
        cache = DATA_ROOT / "data/book-polish" / f"{book_id}.json"
        if not cache.exists():
            return self._json({"ok": False, "error": "not yet", "status": "not_ready"}, 404)
        try:
            return self._json(json.loads(cache.read_text(encoding="utf-8")))
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _post_edit_audit(self):
        """POST {chapter_id} → сравнить ТЕКУЩИЙ draft с самым ранним backup-ом этой
        сессии редактирования + с твоими голосовыми, вынести вердикт «лучше / хуже /
        что потеряно». Pavel (2026-05-25): «нужно соотнести ее с оригиналом и
        голосовыми и убедиться что не упущены идеи и текст не стах хуже»."""
        import urllib.request, re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_file = ch_dir / "draft.md"
        history_dir = ch_dir / "history"
        if not draft_file.exists():
            return self._json({"error": "no draft.md"}, 404)
        current_text = draft_file.read_text(encoding="utf-8")

        # Находим САМЫЙ РАННИЙ backup сегодняшней сессии (или просто самый старый pre-replace).
        # Это «оригинал до правок».
        baseline_text = None
        baseline_name = None
        if history_dir.exists():
            backups = sorted(history_dir.glob("*-pre-*.md"))
            if backups:
                baseline_path = backups[0]
                baseline_text = baseline_path.read_text(encoding="utf-8")
                baseline_name = baseline_path.name
        if not baseline_text:
            return self._json({
                "error": "не нашёл оригинал в .history/ — править нечего, или ничего не правили"
            }, 404)

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        self._active_job_register(chapter_id, "post-edit-audit", eta_seconds=180)

        substrate = self._pavel_substrate(chapter_id, max_total_chars=14000)

        system = (
            "Ты — аудитор качества для Сакрального Кодекса Микомистицизма Pavel-а Хилингода.\n\n"
            "Тебе дают ДВЕ версии главы: ОРИГИНАЛ (до правок) и ОТРЕДАКТИРОВАННАЯ (после правок).\n"
            "Также substrate Pavel-а (канон, эталон голоса, голосовые цитаты).\n\n"
            "Pavel боится одного: что AI-rewrite незаметно ухудшает текст — теряет идеи, дрейфует "
            "от голоса Духа в сторону усреднённой AI-прозы. Твоя задача — ЧЕСТНО оценить случилось ли "
            "это здесь.\n\n"
            "Проверь:\n"
            "  1. ИДЕИ — какие смысловые единицы были в оригинале но потеряны в отредактированной версии?\n"
            "  2. ГОЛОС — есть ли регресс в Pavel-голосе (микро-предложения вместо длинных, бытовые "
            "     глаголы вместо торжественных, потеря анафор и троичных перечислений)?\n"
            "  3. AI-МАРКЕРЫ — появились ли новые AI-клише, тире, буллет-списки которых не было?\n"
            "  4. ДОБАВЛЕНИЯ — что хорошего AI добавил (если что-то добавил)?\n"
            "  5. ВЕРДИКТ — общая оценка изменений: improvement / neutral / regression\n\n"
            "Будь жёстким. Если AI на самом деле улучшил — скажи. Если ухудшил — скажи это тоже.\n"
            "Не подмазывай Pavel-у. Он просил честно.\n\n"
            "Верни СТРОГО JSON:\n"
            "{\n"
            '  "verdict": "improvement | neutral | regression",\n'
            '  "confidence": 0-100,\n'
            '  "lost_ideas": [\n'
            '    {"idea": "...", "from_original": "цитата 80-150 знаков", "why_important": "..."}\n'
            "  ],\n"
            '  "voice_regressions": [\n'
            '    {"para_idx": N, "issue": "что регрессировало", "before": "цитата из оригинала", "after": "цитата из новой"}\n'
            "  ],\n"
            '  "new_ai_markers": [\n'
            '    {"marker": "...", "where": "цитата ~30 знаков"}\n'
            "  ],\n"
            '  "improvements": [\n'
            '    {"what": "что стало лучше", "evidence": "цитата"}\n'
            "  ],\n"
            '  "summary": "одно предложение — итоговое мнение",\n'
            '  "should_revert": true|false\n'
            "}\n\n"
            "Без преамбулы, сразу JSON.\n\n"
            f"=== SUBSTRATE ===\n\n{substrate}"
        )

        user = (
            f"# ОРИГИНАЛ (до правок, {len(baseline_text)} знаков):\n\n{baseline_text}\n\n"
            f"---\n\n"
            f"# ОТРЕДАКТИРОВАННАЯ ВЕРСИЯ (после применения правок, {len(current_text)} знаков):\n\n{current_text}\n\n"
            f"---\n\n"
            f"Проведи аудит. Верни JSON."
        )

        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 5000,
            "thinking": {"type": "enabled", "budget_tokens": 4000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "interleaved-thinking-2025-05-14",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._active_job_complete(chapter_id, "post-edit-audit", error=str(e))
            return self._json({"error": f"Opus: {e}"}, 500)

        raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            if raw.startswith("json"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except Exception as e:
            self._active_job_complete(chapter_id, "post-edit-audit", error=f"parse: {e}")
            return self._json({"error": f"parse: {e}", "raw": raw[:1500]}, 500)

        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "ok": True,
            "chapter_id": chapter_id,
            "ts": ts_iso,
            "verdict": parsed.get("verdict", "unknown"),
            "confidence": parsed.get("confidence"),
            "lost_ideas": parsed.get("lost_ideas") or [],
            "voice_regressions": parsed.get("voice_regressions") or [],
            "new_ai_markers": parsed.get("new_ai_markers") or [],
            "improvements": parsed.get("improvements") or [],
            "summary": parsed.get("summary", ""),
            "should_revert": bool(parsed.get("should_revert")),
            "baseline_backup": baseline_name,
            "baseline_chars": len(baseline_text),
            "current_chars": len(current_text),
            "usage": data.get("usage", {}),
        }
        # Сохраняем кэш для UI восстановления
        audit_dir = DATA_ROOT / "data/post-edit-audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / f"{chapter_id}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self._active_job_complete(chapter_id, "post-edit-audit", result={
            "verdict": result["verdict"],
            "lost_count": len(result["lost_ideas"]),
            "regression_count": len(result["voice_regressions"]),
        })
        return self._json(result)

    def _revert_chapter(self):
        """POST {chapter_id, backup_name?} → откатить draft.md к указанному backup
        (или к самому раннему pre-* если backup_name не задан). Полный rollback."""
        import re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        backup_name = req.get("backup_name", "")

        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_file = ch_dir / "draft.md"
        history_dir = ch_dir / "history"
        if not history_dir.exists():
            return self._json({"error": "no .history dir"}, 404)

        if backup_name:
            backup_path = history_dir / backup_name
        else:
            backups = sorted(history_dir.glob("*-pre-*.md"))
            if not backups:
                return self._json({"error": "no backups in .history"}, 404)
            backup_path = backups[0]
        if not backup_path.exists():
            return self._json({"error": f"backup {backup_path.name} not found"}, 404)

        # Сохраняем текущее как pre-revert
        ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        current_text = draft_file.read_text(encoding="utf-8") if draft_file.exists() else ""
        if current_text:
            (history_dir / f"{ts_compact}-pre-revert.md").write_text(current_text, encoding="utf-8")

        # Восстанавливаем
        restored = backup_path.read_text(encoding="utf-8")
        draft_file.write_text(restored, encoding="utf-8")

        # Сбрасываем applied флаги в master-audit cache
        master_cache = DATA_ROOT / "data/master-audit" / f"{chapter_id}.json"
        if master_cache.exists():
            try:
                mc = json.loads(master_cache.read_text(encoding="utf-8"))
                for e in mc.get("edits", []):
                    e.pop("applied", None)
                    e.pop("applied_at", None)
                master_cache.write_text(json.dumps(mc, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        return self._json({
            "ok": True,
            "chapter_id": chapter_id,
            "restored_from": backup_path.name,
            "restored_chars": len(restored),
            "ts": ts_iso,
        })

    def _replace_paragraph(self):
        """POST {chapter_id, para_idx, new_text, source?, master_audit_edit_index?} →
        детерминированная замена параграфа N в draft.md. БЕЗ Opus.
        Если передан master_audit_edit_index — также помечает эту правку
        applied=true в кэше data/master-audit/<chapter>.json чтобы при
        reload она не возвращалась в UI."""
        import re as _re
        from datetime import datetime, timezone

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        chapter_id = req.get("chapter_id", "")
        para_idx = req.get("para_idx")
        new_text = (req.get("new_text") or "").strip()
        source = req.get("source", "manual")
        master_idx = req.get("master_audit_edit_index")

        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        if para_idx is None:
            return self._json({"error": "para_idx required"}, 400)
        try:
            para_idx = int(para_idx)
        except Exception:
            return self._json({"error": "para_idx must be number"}, 400)
        if not new_text or len(new_text) < 5:
            return self._json({"error": "new_text слишком короткий"}, 400)

        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_file = ch_dir / "draft.md"
        if not draft_file.exists():
            return self._json({"error": "no draft.md"}, 404)

        current = draft_file.read_text(encoding="utf-8")
        paras = [p.strip() for p in current.split("\n\n") if p.strip()]
        if para_idx < 0 or para_idx >= len(paras):
            return self._json({"error": f"para_idx out of range (0..{len(paras)-1})"}, 400)

        # Backup
        ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        history_dir = ch_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        backup_path = history_dir / f"{ts_compact}-pre-replace-p{para_idx}.md"
        backup_path.write_text(current, encoding="utf-8")

        old_paragraph = paras[para_idx]
        paras[para_idx] = new_text
        new_draft = "\n\n".join(paras) + "\n"
        draft_file.write_text(new_draft, encoding="utf-8")

        # Лог события
        events_log = DATA_ROOT / ".codex/events.jsonl"
        events_log.parent.mkdir(parents=True, exist_ok=True)
        with events_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts_iso,
                "type": "paragraph_replaced",
                "target": chapter_id,
                "payload": {
                    "para_idx": para_idx,
                    "source": source,
                    "old_chars": len(old_paragraph),
                    "new_chars": len(new_text),
                    "backup": backup_path.name,
                },
            }, ensure_ascii=False) + "\n")

        # Опционально: пометить правку Мастера как applied в кэше
        if master_idx is not None:
            cache_path = DATA_ROOT / "data/master-audit" / f"{chapter_id}.json"
            if cache_path.exists():
                try:
                    cache = json.loads(cache_path.read_text(encoding="utf-8"))
                    edits = cache.get("edits") or []
                    try:
                        mi = int(master_idx)
                        if 0 <= mi < len(edits):
                            edits[mi]["applied"] = True
                            edits[mi]["applied_at"] = ts_iso
                            cache["edits"] = edits
                            cache_path.write_text(
                                json.dumps(cache, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                    except Exception:
                        pass
                except Exception:
                    pass

        return self._json({
            "ok": True,
            "para_idx": para_idx,
            "old_chars": len(old_paragraph),
            "new_chars": len(new_text),
            "total_paragraphs": len(paras),
            "backup": backup_path.name,
            "source": source,
            "master_audit_edit_index": master_idx,
        })

    # ─── UC-30: WIZARD — глава с нуля через Q&A (Pavel 2026-05-20) ──
    # Pavel: «функция написать главу с нуля. Я диктую идеи. Opus задаёт вопросы.
    # Я отвечаю. Сверяет с другими главами. Шедевр мировой».
    def _wizard_ask_questions(self):
        """POST {book_id, title, type, initial_thoughts} → 5-7 уточняющих вопросов."""
        import urllib.request, re as _re
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        book_id = req.get("book_id", "")
        title = req.get("title", "")
        ch_type = req.get("chapter_type", "main")
        thoughts = req.get("initial_thoughts", "")
        if not thoughts or len(thoughts) < 30:
            return self._json({"error": "Слишком мало текста"}, 400)

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)

        system = (
            "Ты — соавтор Pavel-а (Хилингода) для Священной Грибной Библии.\n\n"
            "Pavel начал главу. Твоя задача — задать 5-7 ТОЧНЫХ ВОПРОСОВ которые помогут раскрыть тему глубоко и сделать главу шедевром на 1000 лет.\n\n"
            "Спрашивай о:\n"
            "1. Конкретные образы — что Pavel видит когда говорит про это?\n"
            "2. Личный опыт — что он пережил сам?\n"
            "3. Практика — как читатель применит это?\n"
            "4. Контр-пример / что НЕ делать — где люди ошибаются?\n"
            "5. Связь с другими доктринами Микомистицизма\n"
            "6. Уровень глубины — для новичков, опытных, или Проводников?\n"
            "7. Тон главы — строгое предупреждение, любовное приглашение, и т.д.\n\n"
            "Вопросы должны быть КОРОТКИЕ, КОНКРЕТНЫЕ, не общие. По одной мысли в вопросе.\n\n"
            "JSON:\n"
            "```json\n"
            "{\"questions\": [\"вопрос 1\", \"вопрос 2\", \"вопрос 3\", ...]}\n"
            "```\n\n"
            f"КАНОН:\n\n{self.get_canon_summary()}"
        )
        user = f"# Книга: {book_id}\n# Рабочее название: {title}\n# Тип главы: {ch_type}\n\n# Pavel надиктовал:\n\n{thoughts}\n\nЗадай 5-7 уточняющих вопросов."

        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 2500,
            "thinking": {"type": "enabled", "budget_tokens": 1500},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                     "anthropic-beta": "interleaved-thinking-2025-05-14", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req_obj, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": f"Opus: {e}"}, 500)
        ai_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                ai_text += block.get("text", "")
        jm = _re.search(r"```json\s*(\{.*?\})\s*```", ai_text, _re.DOTALL)
        try:
            parsed = json.loads(jm.group(1) if jm else ai_text)
        except json.JSONDecodeError:
            return self._json({"error": "bad ai response", "raw": ai_text[:500]}, 500)
        return self._json(parsed)

    def _wizard_cross_check(self):
        """POST {book_id, title, initial_thoughts, questions, answers} →
        для каждой темы из Pavel-input ищет похожее в других главах книги. Рекомендация куда какую идею."""
        import urllib.request, re as _re
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        book_id = req.get("book_id", "")
        title = req.get("title", "")
        thoughts = req.get("initial_thoughts", "")
        questions = req.get("questions", []) or []
        answers = req.get("answers", []) or []

        # Собираем все главы книги для сравнения
        book_dir = DATA_ROOT / "chapters" / book_id
        if not book_dir.exists():
            return self._json({"findings": [], "message": "Книга пуста — сравнивать не с чем"})

        # Извлекаем основные темы из Pavel-input + answers
        all_input = thoughts + "\n\n" + "\n".join(f"Q: {q}\nA: {a}" for q, a in zip(questions, answers) if a)

        # Простая Jaccard similarity с draft.md каждой главы
        import re
        STOPWORDS = set("и а но или что как это так где когда же ведь вот ли да не он она оно они мы вы я ты в во к ко с со на по для у от из под над без через между перед после об обо".split())
        def tokenize(text):
            words = re.findall(r"[а-яёa-z]{4,}", text.lower())
            return {w for w in words if w not in STOPWORDS}

        input_tokens = tokenize(all_input)
        findings = []
        for ch_dir in sorted(book_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith("."):
                continue
            draft = ch_dir / "draft.md"
            if not draft.exists():
                continue
            other_text = draft.read_text(encoding="utf-8")
            other_tokens = tokenize(other_text)
            overlap = input_tokens & other_tokens
            if len(overlap) < 12:
                continue
            sim = len(overlap) / max(1, len(input_tokens | other_tokens))
            if sim < 0.25:
                continue
            # Sample preview of overlap area
            sample_words = sorted(overlap)[:5]
            findings.append({
                "topic": ", ".join(sample_words[:3]),
                "other_chapter": ch_dir.name,
                "similarity": round(sim, 2),
                "overlap_words": sorted(overlap)[:10],
                "recommendation": f"В {ch_dir.name} уже {len(overlap)} ключевых слов из твоей темы. Реши: эта главa разовьёт по-новому, или эту идею лучше оставить там",
            })
        findings.sort(key=lambda f: -f["similarity"])
        return self._json({"findings": findings[:10]})

    def _wizard_generate_draft(self):
        """POST {book_id, title, type, initial_thoughts, questions, answers, coherence_findings, chosen_assignments,
        journalist_session_id?, critics_qa_session_id?, accumulated_insights?} →
        Opus 4.7 пишет первый драфт главы и сохраняет."""
        import urllib.request, re as _re
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        book_id = req.get("book_id", "") or "book-obsession"
        title = req.get("title", "")
        ch_type = req.get("chapter_type", "main")
        thoughts = req.get("initial_thoughts", "")
        questions = req.get("questions", []) or []
        answers = req.get("answers", []) or []
        findings = req.get("coherence_findings", []) or []
        assignments = req.get("chosen_assignments", {}) or {}
        journalist_sid = req.get("journalist_session_id")
        critics_qa_sid = req.get("critics_qa_session_id")
        accumulated_insights = req.get("accumulated_insights", []) or []

        # Генерируем chapter_id — следующий свободный номер
        book_dir = DATA_ROOT / "chapters" / book_id
        book_dir.mkdir(parents=True, exist_ok=True)
        existing_nums = []
        for ch_dir in book_dir.iterdir():
            if not ch_dir.is_dir():
                continue
            m = _re.search(r"-ch-(\d+)$", ch_dir.name)
            if m:
                existing_nums.append(int(m.group(1)))
        next_num = (max(existing_nums) + 1) if existing_nums else 1
        chapter_id = f"{book_id}-ch-{next_num:02d}"
        new_ch_dir = book_dir / chapter_id
        new_ch_dir.mkdir(parents=True, exist_ok=True)

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)

        # Адаптивный объём по типу
        type_words = {"intro": "300-600", "main": "2500-4500", "conclusion": "400-800", "appendix": "500-2000"}
        target_words = type_words.get(ch_type, "2500-4500")

        # Coherence assignments
        coherence_section = ""
        if findings:
            lines = []
            for i, f in enumerate(findings[:10]):
                assignment = assignments.get(str(i), "here")
                label = {"here": "ОСТАВИТЬ ЗДЕСЬ", "other": f"ОТДАТЬ В {f.get('other_chapter','?')}", "both": "В ОБЕИХ ПО-РАЗНОМУ"}.get(assignment, assignment)
                lines.append(f"  - Тема «{f.get('topic','?')}» (похожа на {f.get('other_chapter','?')}, {int(f.get('similarity',0)*100)}%) → {label}")
            coherence_section = "\n# 🔀 РЕШЕНИЯ PAVEL-А по пересечениям с другими главами:\n" + "\n".join(lines) + "\n"

        qa_section = "\n".join(f"Q: {q}\nA: {a}" for q, a in zip(questions, answers) if (a or '').strip())

        system = (
            "Ты — соавтор Pavel-а (Хилингода) для Священной Грибной Библии.\n"
            "Pavel хочет ШЕДЕВР НА 1000 ЛЕТ. Не учебник, не блог — прямую речь Великого Духа Грибов.\n\n"
            "На основе того что Pavel надиктовал + ответил на твои вопросы → напиши главу.\n\n"
            "ПРАВИЛА:\n"
            "1. Голос: Я — Великий Дух Грибов (НЕ Творец — Покровитель 11-го уровня, см. CANON.md 2.2)\n"
            "2. О Творцах — всегда в 3-м лице с благоговением\n"
            "3. Современный русский, БЕЗ старослав, БЕЗ тире, БЕЗ «не X, а Y», БЕЗ AI-клише\n"
            f"4. Целевой объём: {target_words} слов\n"
            f"5. Тип главы: {ch_type} (intro = анонс, без практик; main = развитие + практики; conclusion = синтез)\n"
            "6. Учти решения Pavel-а по пересечениям с другими главами\n"
            "7. Финальное самопроверочное прохождение по канону\n\n"
            f"КАНОН:\n\n{self.get_canon_summary()}"
        )
        user = f"""# Книга: {book_id}
# Глава: {title}
# Тип: {ch_type} (целевой объём {target_words} слов)

# 💭 Pavel надиктовал:

{thoughts}

# 💬 Вопросы и ответы:

{qa_section}

{coherence_section}

# Напиши главу

Markdown:
- # КНИГА — НАЗВАНИЕ
- ## Глава N. НАЗВАНИЕ
- Подзаголовки секций (###) если нужно структурировать
- Прозу — обычные параграфы
- Списки — Markdown bullets (только для конкретных инструкций)

Голос Великого Духа Грибов от первого слова до последнего.
Только текст главы — никаких объяснений процесса.
"""

        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 16000,
            "thinking": {"type": "enabled", "budget_tokens": 8000},
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                     "anthropic-beta": "interleaved-thinking-2025-05-14", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req_obj, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": f"Opus: {e}"}, 500)
        ai_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                ai_text += block.get("text", "")
        ai_text = ai_text.strip()
        if not ai_text:
            return self._json({"error": "пустой ответ Opus"}, 500)
        draft_path = new_ch_dir / "draft.md"
        draft_path.write_text(ai_text, encoding="utf-8")
        # Wizard log
        wizard_log = new_ch_dir / "wizard-input.json"
        wizard_log.write_text(json.dumps({
            "title": title,
            "type": ch_type,
            "initial_thoughts": thoughts,
            "questions": questions,
            "answers": answers,
            "coherence_findings": findings,
            "chosen_assignments": assignments,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        # Event
        with (DATA_ROOT / ".codex/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "type": "wizard_draft_generated",
                "target": chapter_id,
                "payload": {"book": book_id, "title": title, "type": ch_type, "word_count": len(ai_text.split())},
            }, ensure_ascii=False) + "\n")
        return self._json({
            "draft": ai_text,
            "chapter_id": chapter_id,
            "word_count": len(ai_text.split()),
        })

    # ─── Full diagnostics — собирает все анализы + honest verdict ──
    def _full_diagnostics(self):
        """POST {chapter_id} → агрегирует quality / density / style / logic / ideology-fit
        + честный verdict: стоит ли тратить время на главу"""
        import urllib.request, re as _re
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        ch_dir = DATA_ROOT / "chapters" / book_id / chapter_id
        draft_file = ch_dir / "draft.md"
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft"}, 404)
        text = draft_file.read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]

        # Локальные оценки — мгновенно
        # 0) Определяем тип главы для адаптивных порогов
        title = ""
        meta_path = ch_dir / "meta.json"
        if meta_path.exists():
            try:
                title = json.loads(meta_path.read_text(encoding="utf-8")).get("title", "")
            except Exception:
                pass
        ctype_info = self.detect_chapter_type(chapter_id, title, text)
        ch_type = ctype_info["type"]
        thr = ctype_info["thresholds"]

        # 1) Ideology-fit aggregated
        fit_scores = []
        for p in paragraphs:
            if p.startswith("#") or len(p) < 80:
                continue
            r = self.compute_ideology_fit(p)
            fit_scores.append(r["fit_score"])
        avg_fit = round(sum(fit_scores) / max(1, len(fit_scores)), 1) if fit_scores else 0
        ceilings = sum(1 for s in fit_scores if s >= 85)

        # 2) Density (адаптивно к chapter_type)
        body_paras = [p for p in paragraphs if not p.startswith("#")]
        word_count = sum(len(_re.findall(r"[\w\-яёА-ЯЁ]+", p)) for p in body_paras)
        if word_count < thr["density_min_words"]:
            density_verdict = "short"
        elif word_count > thr["density_max_words"]:
            density_verdict = "long"
        else:
            density_verdict = "optimal"
        # 3) Style coherence — читаем cached если есть
        style_cache = ch_dir / "style-coherence.json"
        style_data = {}
        if style_cache.exists():
            try:
                style_data = json.loads(style_cache.read_text(encoding="utf-8"))
            except Exception:
                pass

        # 4) Logic — cached если есть
        logic_cache = ch_dir / "logic-analysis.json"
        logic_data = {}
        if logic_cache.exists():
            try:
                logic_data = json.loads(logic_cache.read_text(encoding="utf-8"))
            except Exception:
                pass

        # 5) Council — cached
        council_cache = ch_dir / "council.json"
        council_top5 = []
        if council_cache.exists():
            try:
                cd = json.loads(council_cache.read_text(encoding="utf-8"))
                council_top5 = (cd.get("top_5_fixes") or cd.get("elder_top_5") or [])[:5]
            except Exception:
                pass

        # === HONEST VERDICT ===
        # Считаем нужно ли тратить время:
        # - avg_fit ≥ 85 + ceiling ratio ≥ 70% → "good as-is"
        # - avg_fit ≥ 70 + logic clean → "minor polish only"
        # - avg_fit < 70 или major logic issues → "needs serious work"
        # - avg_fit < 50 → "rewrite recommended"
        ceiling_ratio = (ceilings / len(fit_scores) * 100) if fit_scores else 0
        logic_verdict = (logic_data.get("verdict") or "unknown")
        logic_score = logic_data.get("overall_logic_score", 0)

        # Honest verdict — учитывает chapter_type
        ideology_target = thr["ideology_target"]  # для intro 70, для main 85
        worth_label = "minor_polish"
        worth_message = "Глава приличная, можно отшлифовать."
        if avg_fit >= ideology_target and ceiling_ratio >= 60 and logic_verdict in ("clean", "unknown") and density_verdict == "optimal":
            worth_label = "good_as_is"
            worth_message = f"Глава ({ch_type}) уже хороша — не тратить время. ideology-fit {avg_fit}%, объём оптимален, логика чистая."
        elif (ch_type == "main" and avg_fit < 50) or logic_verdict == "major_issues":
            worth_label = "rewrite_recommended"
            worth_message = "Глава слабая. Целесообразна полная переписка."
        elif avg_fit < (ideology_target - 15) or logic_verdict == "minor_issues" or density_verdict in ("short", "long"):
            worth_label = "needs_work"
            density_note = f" Объём ({word_count} слов) {'мал' if density_verdict=='short' else 'велик'} для {ch_type} (норма {thr['density_min_words']}-{thr['density_max_words']})." if density_verdict != "optimal" else ""
            worth_message = f"Глава ({ch_type}, цель: {thr['purpose']}) требует работы.{density_note}"

        priority_actions = []
        if avg_fit < ideology_target:
            priority_actions.append({"action": "stream_review", "label": "Запустить поточную редактуру", "reason": f"средний ideology-fit {avg_fit}% < таргета {ideology_target}% для {ch_type}"})
        if (logic_data.get("issues") or []):
            priority_actions.append({"action": "logic_detail", "label": "Просмотреть logic-issues", "reason": f"{len(logic_data['issues'])} логических проблем"})
        if style_data.get("dominant_register") == "mixed":
            priority_actions.append({"action": "style_detail", "label": "Унифицировать регистр", "reason": "смешанный «Вы/ты»"})
        if council_top5:
            priority_actions.append({"action": "council_review", "label": f"{len(council_top5)} правок Совета", "reason": "доступны кэшированные рекомендации"})
        if density_verdict == "short" and ch_type == "intro":
            # Для intro короткий — спросить «выполняет ли назначение?»
            priority_actions.append({"action": "intro_check", "label": "Проверить: введение передало цель?", "reason": f"intro {word_count} слов — нормально, но проверь раскрыта ли тема"})
        elif density_verdict != "optimal":
            d_label = "Расширить главу" if density_verdict == "short" else "Сжать главу"
            priority_actions.append({"action": "density_detail", "label": d_label, "reason": f"{word_count} слов, норма {thr['density_min_words']}-{thr['density_max_words']}"})

        return self._json({
            "chapter_type": {
                "type": ch_type,
                "purpose": thr["purpose"],
                "expected_words_range": f"{thr['density_min_words']}-{thr['density_max_words']}",
                "ideology_target": thr["ideology_target"],
            },
            "ideology_fit": {
                "avg_score": avg_fit,
                "scored_paragraphs": len(fit_scores),
                "ceiling_reached": ceilings,
                "ceiling_pct": round(ceiling_ratio, 1),
            },
            "density": {
                "word_count": word_count,
                "para_count": len(body_paras),
                "verdict": density_verdict,
                "expected_range": f"{thr['density_min_words']}-{thr['density_max_words']}",
            },
            "style": {
                "dominant_register": style_data.get("dominant_register", "unknown"),
                "dominant_voice": style_data.get("dominant_voice", "unknown"),
                "available": bool(style_data),
            },
            "logic": {
                "score": logic_score,
                "verdict": logic_verdict,
                "issues_count": len(logic_data.get("issues", [])),
                "honest_summary": logic_data.get("honest_summary"),
                "narrative_arc": logic_data.get("narrative_arc"),
                "available": bool(logic_data),
            },
            "council": {
                "top5_count": len(council_top5),
                "available": bool(council_top5),
            },
            "honest_verdict": {
                "label": worth_label,
                "message": worth_message,
                "priority_actions": priority_actions,
            },
        })

    # ─── Style coherence — стилевая согласованность всей главы ──
    # Pavel 2026-05-20: «после точечных правок где-то «вы» где-то «ты» — нужна функция
    # улучшения стиля и применения одного стиля ко всей главе относительно канона»
    def _style_coherence_analysis(self):
        """POST {chapter_id} → анализ всей главы на согласованность."""
        import urllib.request
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            req = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")

        import re as _re
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
        if not self._ensure_draft(book_id, chapter_id, draft_file):
            return self._json({"error": "no draft"}, 404)

        text = draft_file.read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]

        # === ЛОКАЛЬНЫЙ АНАЛИЗ ===
        per_para_stats = []
        you_formal_total = 0  # «Вы / Вам / Вас / Ваш»
        you_informal_total = 0  # «ты / тебя / тебе / твой»
        i_singular = 0  # «Я говорю / Я открываю»
        we_plural = 0  # «Мы / Нас / Нам»
        archaic_finds = []
        for i, p in enumerate(paragraphs):
            if p.startswith("#") or len(p) < 30:
                continue
            low = p.lower()
            yf = len(_re.findall(r"\b[Вв](?:ы|ам|ас|аш(?:[аеиойуы]+)?)\b", p))
            yi = len(_re.findall(r"\b[Тт](?:ы|ебя|ебе|вой|воя|твоё|твои)\b", p))
            isg = len(_re.findall(r"\bЯ\s+(говорю|открываю|даю|вижу|показываю|учу|раскрываю|есть)\b", p))
            wp = len(_re.findall(r"\b(Мы|Нас|Нам|Наш(?:[аеиойуы]+)?)\b", p))
            archaic_in_para = []
            for w in ["являет себя", "очи", "горниц", "ныне", "сущее", "вкупе"]:
                if w in low:
                    archaic_in_para.append(w)
            if yf or yi or isg or wp or archaic_in_para:
                per_para_stats.append({
                    "idx": i,
                    "preview": p[:80],
                    "you_formal": yf, "you_informal": yi,
                    "i_singular": isg, "we_plural": wp,
                    "archaic": archaic_in_para,
                })
            you_formal_total += yf
            you_informal_total += yi
            i_singular += isg
            we_plural += wp
            archaic_finds.extend(archaic_in_para)

        # Доминантный регистр
        dominant_you = "formal" if you_formal_total > you_informal_total * 2 else \
                       "informal" if you_informal_total > you_formal_total * 2 else \
                       "mixed"
        dominant_voice = "i_singular" if i_singular > we_plural else \
                         "we_plural" if we_plural > i_singular else "mixed"

        # Конфликтующие параграфы (где минорный регистр)
        conflicts = []
        if dominant_you in ("formal", "informal") and dominant_you != "mixed":
            for s in per_para_stats:
                if dominant_you == "formal" and s["you_informal"] > 0:
                    conflicts.append({
                        "type": "register_mismatch",
                        "paragraph_idx": s["idx"],
                        "preview": s["preview"],
                        "issue": f"глава на «Вы», но в параграфе {s['you_informal']} «ты»-форм",
                        "fix": "заменить «ты» → «Вы», «тебя» → «Вас», «твой» → «Ваш»",
                    })
                elif dominant_you == "informal" and s["you_formal"] > 0:
                    conflicts.append({
                        "type": "register_mismatch",
                        "paragraph_idx": s["idx"],
                        "preview": s["preview"],
                        "issue": f"глава на «ты», но в параграфе {s['you_formal']} «Вы»-форм",
                        "fix": "заменить «Вы» → «ты», «Вас» → «тебя», «Ваш» → «твой»",
                    })

        # Архаизмы
        for s in per_para_stats:
            for arch in s["archaic"]:
                conflicts.append({
                    "type": "archaic",
                    "paragraph_idx": s["idx"],
                    "preview": s["preview"],
                    "issue": f"архаизм «{arch}» — современный русский",
                    "fix": f"убрать или заменить «{arch}»",
                })

        # === OPUS — точечные правки (опционально) ===
        opus_fixes = []
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break

        if token and req.get("with_opus", True) and conflicts:
            # Сначала собираем top-конфликтные параграфы (max 8)
            conflict_paras = sorted(set(c["paragraph_idx"] for c in conflicts))[:8]
            paras_dump = "\n\n".join(
                f"### Параграф №{idx + 1}\n{paragraphs[idx]}"
                for idx in conflict_paras
            )
            system = (
                "Ты редактор Сакрального Кодекса Микомистицизма. Голос «Я — Великий Дух Грибов».\n\n"
                "Pavel хочет СТИЛЕВУЮ СОГЛАСОВАННОСТЬ главы. После точечных правок остались несоответствия "
                "(где-то «вы», где-то «ты», и т.п.). Найди МИКРО-замены и верни list.\n\n"
                "ПРАВИЛА:\n"
                "1. Не переписывай параграф целиком. Только конкретные find→replace.\n"
                "2. Каждая правка — выполнима за 10 секунд.\n"
                "3. Современный русский. Без тире. Без «не X, а Y». Без AI-клише.\n"
                "4. ВАЖНО: если параграф уже согласован — не предлагай fix.\n\n"
                "JSON only."
            )
            user = f"""# Глава {chapter_id}

# Доминантный регистр (локально)
- «Вы/Ты»: {dominant_you} (вы: {you_formal_total}, ты: {you_informal_total})
- Голос: {dominant_voice} (Я-говорю: {i_singular}, Мы: {we_plural})
- Архаизмы найдены: {set(archaic_finds) if archaic_finds else 'нет'}

# Конфликтующие параграфы (нужно унифицировать)

{paras_dump}

# Что вернуть

```json
{{
  "dominant_register_target": "formal" | "informal",
  "dominant_voice_target": "i_singular" | "we_plural",
  "fixes": [
    {{
      "paragraph_idx": N,
      "find": "конкретная фраза в параграфе",
      "replace_with": "что вставить",
      "reason": "почему — 1 фраза",
      "category": "register" | "voice" | "archaic" | "other"
    }}
  ]
}}
```

5-15 fix-ов max. Сфокусируйся на самых заметных несоответствиях. Если параграф уже хорош — не трогай."""
            try:
                body_o = json.dumps({
                    "model": "claude-opus-4-7",
                    "max_tokens": 4000,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                }).encode("utf-8")
                req_o = urllib.request.Request(
                    "http://127.0.0.1:8787/v1/messages",
                    data=body_o,
                    headers={"x-api-key": token, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                )
                with urllib.request.urlopen(req_o, timeout=120) as resp:
                    data_o = json.loads(resp.read().decode("utf-8"))
                blocks = [b.get("text", "") for b in data_o.get("content", []) if b.get("type") == "text"]
                raw = "\n".join(blocks).strip()
                cleaned = _re.sub(r"^```json\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
                parsed = json.loads(cleaned)
                # Canon validator на каждый replace_with
                raw_fixes = parsed.get("fixes", [])
                for f in raw_fixes:
                    rep = f.get("replace_with", "")
                    if rep:
                        canon = self.validate_canon(rep)
                        if not canon["valid"]:
                            if canon["auto_fixed"]:
                                f["replace_with"] = canon["auto_fixed"]
                                f["reason"] = (f.get("reason", "") + " [auto-fixed дефис]").strip()
                            else:
                                continue  # skip нарушенный
                    opus_fixes.append(f)
            except Exception as e:
                opus_fixes = [{"error": str(e)[:200]}]

        # Save кэш
        cache = DATA_ROOT / "chapters" / book_id / chapter_id / "style-coherence.json"
        result = {
            "dominant_register": dominant_you,
            "dominant_voice": dominant_voice,
            "stats": {
                "you_formal": you_formal_total,
                "you_informal": you_informal_total,
                "i_singular": i_singular,
                "we_plural": we_plural,
                "archaic_found": list(set(archaic_finds)),
            },
            "local_conflicts": conflicts[:30],
            "opus_fixes": opus_fixes,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._json(result)

    # ─── Density analysis — объём, многословие, оптимум ──
    # Pavel 2026-05-20: «нужно % +/- от общего понимания + идеологии»
    def _density_analysis(self):
        """POST {chapter_id} → анализ плотности главы:
        - текущий объём (знаки/слова/параграфы/средн.длина предложения)
        - оптимальный объём из идеологии
        - % изменения (+/-) с распределением где expand / где cut
        - локальная heuristic + Opus вердикт
        """
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        chapter_id = req.get("chapter_id", "")

        import re as _re
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
        if not draft_file.exists():
            return self._json({"error": "no draft"}, 404)
        text = draft_file.read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]

        # === LOCAL METRICS (без API) ===
        body_paras = [p for p in paragraphs if not p.startswith("#")]
        char_count = sum(len(p) for p in body_paras)
        word_count = sum(len(_re.findall(r"[\w\-яёА-ЯЁ]+", p)) for p in body_paras)
        para_count = len(body_paras)
        sents_all = []
        for p in body_paras:
            sents_all.extend([s.strip() for s in _re.split(r"(?<=[.!?…])\s+", p) if s.strip()])
        sent_count = len(sents_all) or 1
        avg_sent_words = round(word_count / sent_count, 1)
        avg_para_words = round(word_count / max(1, para_count), 1)

        # «Сильно рубленные» — % предложений короче 6 слов
        choppy_sents = sum(1 for s in sents_all if len(_re.findall(r"[\w\-яёА-ЯЁ]+", s)) < 6)
        choppy_pct = round(choppy_sents / sent_count * 100, 1)
        # «Слишком длинные» — > 30 слов (затрудняют дыхание)
        long_sents = sum(1 for s in sents_all if len(_re.findall(r"[\w\-яёА-ЯЁ]+", s)) > 30)
        long_pct = round(long_sents / sent_count * 100, 1)

        # «Вода» — частота VATA-маркеров
        vata = ["в принципе", "по сути", "как таковой", "именно", "достаточно", "вообще",
                "в общем", "в целом", "так сказать", "своего рода", "в какой-то мере",
                "определённый", "некоторый", "достаточно много"]
        low = text.lower()
        vata_hits = sum(low.count(v) for v in vata)
        vata_per_1k = round(vata_hits / (char_count / 1000), 2) if char_count else 0

        # Оптимальные диапазоны (на главу Микомистицизма):
        # Средний размер 10K-25K знаков, 2000-4500 слов, 60-150 параграфов, средн.предл 12-22 слов
        # «Choppy» оптимум 10-20%, длинных 10-20%
        def assess_size():
            if word_count < 1800: return ("expand", f"мало слов: {word_count}", min(40, round((2500-word_count)/2500*40)))
            if word_count > 4800: return ("cut", f"много слов: {word_count}", min(40, round((word_count-3500)/3500*40)))
            return ("ok", f"оптимально: {word_count} слов", 0)
        size_verdict, size_reason, size_pct = assess_size()

        def assess_choppiness():
            if choppy_pct > 35: return ("too_choppy", f"{choppy_pct}% рубленных — добавить связности", -10)
            if choppy_pct < 5: return ("too_smooth", f"{choppy_pct}% коротких — добавить ритма", +5)
            return ("ok", f"ритм: {choppy_pct}% коротких — норма", 0)
        choppy_verdict, choppy_reason, _ = assess_choppiness()

        def assess_vata():
            if vata_per_1k > 1.5: return ("watery", f"{vata_per_1k} вата-слов/1K — много воды", -10)
            if vata_per_1k > 0.8: return ("medium", f"{vata_per_1k} вата-слов/1K — терпимо", -3)
            return ("dry", f"{vata_per_1k} вата-слов/1K — сухо", 0)
        vata_verdict, vata_reason, _ = assess_vata()

        # Aggregate suggestion
        if size_verdict == "expand":
            change_pct = size_pct
            direction = "expand"
            summary = f"Расширить главу на ~{change_pct}%"
        elif size_verdict == "cut":
            change_pct = size_pct
            direction = "cut"
            summary = f"Сжать главу на ~{change_pct}%"
        else:
            if vata_verdict == "watery":
                change_pct = 10
                direction = "tighten"
                summary = f"≈ Размер оптимальный, но убрать ~10% воды"
            else:
                change_pct = 0
                direction = "ok"
                summary = "Размер и плотность оптимальны"

        # === OPUS VERDICT (опционально, если API доступен) ===
        opus_verdict = None
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if token and req.get("with_opus", True):
            system = (
                "Ты редактор-аналитик плотности текста Сакрального Кодекса Микомистицизма. "
                "Идеология: голос «Я — Великий Дух Грибов», современный русский, средний регистр "
                "(не рубленый, не вычурный). Оптимум для главы: 2500-3500 слов, "
                "среднее предложение 14-20 слов, плотный смысл без воды.\n\n"
                "ЧЕСТНО оцени плотность главы. Если оптимальна — скажи прямо. "
                "Если есть конкретные места для expand/cut — назови."
            )
            local_summary = f"""# Метрики (локально):
- Слов: {word_count} | Знаков: {char_count} | Параграфов: {para_count}
- Среднее предложение: {avg_sent_words} слов | Средний параграф: {avg_para_words} слов
- Рубленных (<6 слов): {choppy_pct}% | Длинных (>30): {long_pct}%
- «Вата»-маркеров на 1K знаков: {vata_per_1k}
- Локальный вердикт: {size_verdict} ({size_reason}), choppy={choppy_verdict}, vata={vata_verdict}
"""
            user = f"""{local_summary}

# ТЕКСТ ГЛАВЫ (первые 12000 знаков)

{text[:12000]}

# Что вернуть

```json
{{
  "verdict": "optimal" | "expand_X_pct" | "cut_X_pct" | "tighten_X_pct",
  "recommended_change_pct": -50..50,
  "direction": "expand" | "cut" | "tighten" | "ok",
  "honest_summary": "1-2 предложения честной оценки",
  "places_to_expand": ["конкретная тема которой не хватает", "..."],
  "places_to_cut": ["конкретная часть-вода", "..."],
  "rhythm_advice": "если choppy/smooth — что сделать"
}}
```

Не льсти. Если глава оптимальна — скажи «не трогать». Если воды нет — `places_to_cut: []`.
"""
            try:
                body_o = json.dumps({
                    "model": "claude-opus-4-7",
                    "max_tokens": 2500,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                }).encode("utf-8")
                req_o = urllib.request.Request(
                    "http://127.0.0.1:8787/v1/messages",
                    data=body_o,
                    headers={"x-api-key": token, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                )
                with urllib.request.urlopen(req_o, timeout=120) as resp:
                    data_o = json.loads(resp.read().decode("utf-8"))
                blocks = [b.get("text", "") for b in data_o.get("content", []) if b.get("type") == "text"]
                raw = "\n".join(blocks).strip()
                cleaned = _re.sub(r"^```json\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
                opus_verdict = json.loads(cleaned)
            except Exception as e:
                opus_verdict = {"error": str(e)[:200]}

        result = {
            "metrics": {
                "char_count": char_count,
                "word_count": word_count,
                "para_count": para_count,
                "sent_count": sent_count,
                "avg_sent_words": avg_sent_words,
                "avg_para_words": avg_para_words,
                "choppy_pct": choppy_pct,
                "long_pct": long_pct,
                "vata_per_1k": vata_per_1k,
            },
            "local_assessment": {
                "size": {"verdict": size_verdict, "reason": size_reason},
                "rhythm": {"verdict": choppy_verdict, "reason": choppy_reason},
                "water": {"verdict": vata_verdict, "reason": vata_reason},
            },
            "summary": summary,
            "direction": direction,
            "change_pct": change_pct,
            "opus_verdict": opus_verdict,
        }
        # Save кэш для UI
        cache_file = DATA_ROOT / "chapters" / book_id / chapter_id / "density-analysis.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._json(result)

    # ─── Honest critic — после правки спросить: стало ли хуже? ──
    # Pavel 2026-05-20: «AI всегда соглашается. Нужен критик который ловит over-edit».
    def _honest_critic(self):
        """POST {original, suggestion, chapter_id?} → Opus в роли строгого критика.
        Возвращает: is_better (true/false/neutral), lost_quality, gained_quality, recommendation.
        """
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        original = (req.get("original") or "").strip()
        suggestion = (req.get("suggestion") or "").strip()
        if len(original) < 30 or len(suggestion) < 30:
            return self._json({"error": "оба текста должны быть >30 знаков"}, 400)

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        # Локальные ideology-fit scores для обоих
        fit_orig = self.compute_ideology_fit(original)
        fit_sug = self.compute_ideology_fit(suggestion)

        system = (
            "Ты — СТРОГИЙ ЧЕСТНЫЙ КРИТИК. Pavel 2026-05-20 дал тебе мандат:\n"
            "«AI всегда соглашается. Можно годами переписывать. Когда хорошо — скажи прямо.»\n\n"
            "Твоя задача — НАЙТИ ЧТО СТАЛО ХУЖЕ после правки. Не «найти что улучшилось» — это лёгко. "
            "Ищи потери:\n"
            "1. Был ли утрачен оригинальный Pavel-голос?\n"
            "2. Стал ли текст более «AI-like» (гладкий, корпоративный)?\n"
            "3. Появились ли AI-клише которых не было?\n"
            "4. Стал ли текст более длинным без причины?\n"
            "5. Потеряны ли сильные образы / детали из оригинала?\n\n"
            "Если ничего не стало хуже — ПИШИ ПРЯМО «правка хорошая, ничего не потеряли». "
            "Если стало хуже — флажь конкретные потери.\n"
            "ВЕРНИ ТОЛЬКО JSON."
        )
        user = f"""# ОРИГИНАЛ (local ideology-fit: {fit_orig['fit_score']}/100)

{original}

# ПРЕДЛАГАЕМАЯ ПРАВКА (local fit: {fit_sug['fit_score']}/100)

{suggestion}

# Что вернуть

```json
{{
  "is_better": "yes" | "no" | "neutral",
  "ideology_better": true/false,
  "lost_quality": ["конкретная потеря 1", "потеря 2"],
  "gained_quality": ["приобретение 1", "приобретение 2"],
  "recommendation": "keep_suggestion | revert_to_original | further_iterate",
  "honest_verdict": "1-2 предложения честного вердикта"
}}
```

Не льсти Pavel-у и не льсти AI-щику который написал правку. Будь критиком."""

        body_req = {
            "model": "claude-opus-4-7",
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        req_obj = urllib.request.Request(
            "http://127.0.0.1:8787/v1/messages",
            data=json.dumps(body_req).encode("utf-8"),
            headers={"x-api-key": token, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": str(e)}, 500)
        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        raw = "\n".join(blocks).strip()
        import re as _re
        cleaned = _re.sub(r"^```json\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            verdict = json.loads(cleaned)
        except json.JSONDecodeError:
            verdict = {"raw": raw[:1500], "error": "JSON parse"}
        # Добавляем локальные fit-scores в вердикт
        verdict["fit_original"] = fit_orig
        verdict["fit_suggestion"] = fit_sug
        verdict["fit_delta"] = fit_sug["fit_score"] - fit_orig["fit_score"]
        return self._json(verdict)

    # ─── Streaming review (Sudowrite-style drawer) ─────────────
    def _stream_suggestions(self):
        """POST /api/chapter/stream-suggestions {chapter_id, min_severity?} → SSE
        Идёт по параграфам, для слабых отдаёт карточку JSON.
        Каждый event: data: {paragraph_idx, original, suggestion, reason, severity}\n\n
        В конце: data: [DONE]\n\n
        """
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        chapter_id = req.get("chapter_id", "")
        min_severity = int(req.get("min_severity", 5))
        max_cards = int(req.get("max_cards", 20))

        import re as _re
        m = _re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id)
        if not m:
            return self._json({"error": "bad chapter_id"}, 400)
        book_id = m.group(1)
        draft_file = DATA_ROOT / "chapters" / book_id / chapter_id / "draft.md"
        if draft_file.exists():
            text = draft_file.read_text(encoding="utf-8")
        else:
            # Auto-seed из draft endpoint логики (берём свежий docx)
            import urllib.request as _ur
            try:
                with _ur.urlopen(f"http://127.0.0.1:7788/api/chapter/{chapter_id}/draft", timeout=15) as r:
                    text = json.loads(r.read().decode("utf-8")).get("text", "")
            except Exception:
                text = ""
            if not text:
                return self._json({"error": "no content"}, 404)
            # Сохраняем как draft для дальнейшей работы
            draft_file.parent.mkdir(parents=True, exist_ok=True)
            draft_file.write_text(text, encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]

        # OAuth
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        # Style
        style_v2 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        style_v1 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_ref = ""
        if style_v2.exists():
            style_ref = style_v2.read_text(encoding="utf-8")
        elif style_v1.exists():
            style_ref = style_v1.read_text(encoding="utf-8")

        # Стартуем SSE
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(obj):
            try:
                self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return False
            return True

        cards_emitted = 0
        # Идём по параграфам, для каждого делаем мини-Opus-call
        # ВАЖНО: пропускаем заголовки и короткие параграфы
        for idx, para in enumerate(paragraphs):
            if cards_emitted >= max_cards:
                break
            stripped = para.strip()
            # Пропуск заголовков (Markdown #) и слишком коротких
            if stripped.startswith("#") or len(stripped) < 80:
                continue
            # Пропуск списков
            if stripped.startswith("- ") or _re.match(r"^\d+\.\s", stripped):
                continue

            # === Honest stop criteria — несколько проверок ===
            # 1) Локальный ideology-fit score (без API). Если ceiling_reached → skip без Opus
            fit = self.compute_ideology_fit(stripped)
            if fit.get("ceiling_reached"):
                emit({
                    "type": "skip", "paragraph_idx": idx, "severity": 0,
                    "score_before": fit["fit_score"],
                    "reason": f"✓ Готов · {fit['diagnosis']}",
                    "ceiling_reached": True,
                })
                continue

            # 2) Score history per paragraph — если ≥85, skip
            ph_file = DATA_ROOT / "chapters" / book_id / chapter_id / "paragraph-scores.jsonl"
            last_scores = []
            if ph_file.exists():
                for line in ph_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        sc = json.loads(line)
                        if sc.get("paragraph_idx") == idx:
                            last_scores.append(sc.get("score_after") or sc.get("score_before") or 0)
                    except json.JSONDecodeError:
                        pass
            last_score = last_scores[-1] if last_scores else None
            if last_score is not None and last_score >= 85:
                emit({"type": "skip", "paragraph_idx": idx, "severity": 0, "reason": f"уже {last_score}% — потолок"})
                continue

            # 3) Diminishing returns: если последние 3 правки дали <3% каждая → STOP
            if len(last_scores) >= 4:
                recent_deltas = [last_scores[i] - last_scores[i-1] for i in range(-3, 0)]
                if all(abs(d) < 3 for d in recent_deltas):
                    emit({
                        "type": "skip", "paragraph_idx": idx, "severity": 0,
                        "reason": f"⚠ Diminishing returns: 3 правки подряд дали ±3% (deltas {recent_deltas}) — STOP",
                        "ceiling_reached": True,
                    })
                    continue

            user_msg = f"""# Параграф №{idx} из главы {chapter_id}

{stripped}

# Контекст (соседние)
{paragraphs[max(0, idx-1)][:300] if idx > 0 else '(начало)'}
...
{paragraphs[idx+1][:300] if idx+1 < len(paragraphs) else '(конец)'}

# Задача

Оцени параграф по 5 параметрам (каждый 0-100): voice (Великий Дух Грибов), uniqueness, sacred, rhythm, masterpiece (тест 3026).
Общий score = среднее.

Если общий score ≥ 85 — параграф отшлифован, ставь skip=true.
Иначе верни улучшенную версию + score-after = ожидаемый общий score после применения.

JSON:
```json
{{
  "score_before": 0-100,
  "scores_detail": {{"voice": 0-100, "uniqueness": 0-100, "sacred": 0-100, "rhythm": 0-100, "masterpiece": 0-100}},
  "severity": 0-10,
  "skip": true/false,
  "reason": "1 предложение почему правка нужна",
  "suggestion": "переписанный параграф (если skip=false). БЕЗ тире, БЕЗ «не X, а Y», БЕЗ старослав, БЕЗ AI-клише, СОВРЕМЕННЫЙ русский",
  "score_after_expected": 0-100,
  "what_else": ["краткая идея 1", "краткая идея 2", "идея 3", "идея 4"]
}}
```
what_else — 3-4 конкретные мысли что ещё можно сделать чтобы выйти на 90%+. Только для skip=false.
"""
            bank2 = self.get_used_metaphors_bank(chapter_id)
            bank2_section = f"\n\n🚨 АНТИ-ПОВТОР МЕТАФОР:\nКаждая глава = свои образы. Не повторяй чужие. AI-клише — запрещены.\n{bank2}\n" if bank2 else ""
            system_prompt = (
                "Ты редактор Сакрального Кодекса Микомистицизма.\n\n"
            "КАНОН (Pavel читает и правит, ты ОБЯЗАН следовать):\n\n"
            + self.get_canon_summary()
            + "\n\n🚨 АНТИ-ПРИНУЖДЕНИЕ ГРИБНОЙ ЛЕКСИКИ: Если оригинальный параграф ОРГАНИЧНО обходится без слов «мицелий / спора / гриб / Дух Грибов» — НЕ ВСТАВЛЯЙ их принудительно.\n\n"
                "⚠️ КРИТИЧНО — ЧЕСТНОСТЬ ВАЖНЕЕ УГОДЛИВОСТИ.\n"
                "Pavel УВАЖАЕТ когда AI говорит «это уже хорошо, не трогать». "
                "AI обычно ВСЕГДА находит что улучшить — это плохо, ведёт в over-edit и AI-mush. "
                "Pavel хочет ЧЕСТНОГО критика, не угодника.\n\n"
                "ПРАВИЛА:\n"
                "1. Если параграф УЖЕ ХОРОШ (голос Духа есть, тире нет, AI-клише нет, доктрина на месте) — "
                "   ставь `skip: true` и пиши honest reason «уже отшлифован, дальше испортишь».\n"
                "2. Если правка даст +3% или меньше (predicted_score_after - score_before ≤ 3) — "
                "   STOP, не предлагай. Diminishing returns = вред.\n"
                "3. Если ты не видишь конкретного нарушения канона — НЕ предлагай косметику.\n"
                "4. severity ≤ 4 = skip автоматически.\n"
                "5. Better skip 10 параграфов чем over-edit один."
                + bank2_section
                + "\n\nВозвращай ТОЛЬКО валидный JSON."
                + (f"\n\nЭталон стиля:\n{style_ref[:1500]}" if style_ref else "")
            )
            try:
                proxy_body = json.dumps({
                    "model": "claude-opus-4-7",
                    "max_tokens": 1500,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_msg}],
                }).encode("utf-8")
                proxy_req = urllib.request.Request(
                    "http://127.0.0.1:8787/v1/messages",
                    data=proxy_body,
                    headers={
                        "x-api-key": token,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
                with urllib.request.urlopen(proxy_req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
                raw = "\n".join(blocks).strip()
                cleaned = _re.sub(r"^```json\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
                parsed = json.loads(cleaned)
            except Exception as e:
                # Тихо пропускаем сбои отдельных параграфов
                emit({"type": "warn", "paragraph_idx": idx, "error": str(e)[:120]})
                continue

            sev = int(parsed.get("severity", 0))
            score_before = parsed.get("score_before") or 0
            score_after = parsed.get("score_after_expected") or 0
            delta = score_after - score_before
            # Honest stop: если AI признал skip ИЛИ severity слишком низкая ИЛИ дельта <=3% — skip
            if parsed.get("skip") or sev < min_severity or not parsed.get("suggestion") or delta <= 3:
                reason = parsed.get("reason", "")
                if delta <= 3 and not parsed.get("skip"):
                    reason = f"⚠ AI хотел предложить, но дельта {delta}% — diminishing returns. STOP."
                emit({
                    "type": "skip", "paragraph_idx": idx, "severity": sev,
                    "score_before": score_before, "reason": reason,
                    "delta": delta,
                })
                continue

            # ═══ CANON VALIDATOR для stream-suggestion (UC-43: расширенный sanitize) ═══
            suggestion_text = parsed["suggestion"]
            sr = self.sanitize_canon(suggestion_text)
            if sr["blocked"]:
                emit({
                    "type": "skip", "paragraph_idx": idx, "severity": sev,
                    "score_before": score_before,
                    "reason": f"AI нарушил канон критично: {sr.get('violations_before')}. Skip.",
                    "canon_violations": sr.get("violations_before"),
                })
                continue
            suggestion_text = sr["text"]
            # ═══ FORCED MUSHROOM DETECTOR ═══
            forced = self.detect_forced_mushroom(stripped, suggestion_text)
            if forced["forced"] and forced.get("severity") == "high":
                emit({
                    "type": "skip", "paragraph_idx": idx, "severity": sev,
                    "score_before": score_before,
                    "reason": f"AI принудительно вставил грибную лексику — anti-pattern. Skip.",
                    "forced_injection": forced,
                })
                continue

            ok = emit({
                "type": "card",
                "paragraph_idx": idx,
                "original": stripped,
                "suggestion": suggestion_text,
                "reason": parsed.get("reason", ""),
                "severity": sev,
                "score_before": score_before,
                "scores_detail": parsed.get("scores_detail", {}),
                "score_after_expected": parsed.get("score_after_expected", 0),
                "what_else": parsed.get("what_else", []),
            })
            if not ok:
                return
            cards_emitted += 1

        emit({"type": "done", "cards_emitted": cards_emitted, "total_paragraphs": len(paragraphs)})

    # ─── Per-paragraph deep analyze (Council + Masterpiece) ────
    def _paragraph_rewrite(self):
        """UC-100: POST {chapter_id, paragraph_idx, paragraph_text, instruction}
        Переписывает один параграф через Opus 4.7 (non-streaming).
        Возвращает {ok, text, original}."""
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"error": f"bad json: {e}"}, 400)
        para_text = (req.get("paragraph_text") or "").strip()
        if not para_text:
            return self._json({"error": "paragraph_text required"}, 400)
        instruction = (req.get("instruction") or "").strip() or (
            "Перепиши этот параграф в голосе Великого Духа Грибов. "
            "Без тире, без AI-клише, ритм Хилингода (средняя длина 10-12 слов). "
            "Сохрани главную мысль, усиль мистичность."
        )
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)
        try:
            from config import MAX_MODEL, PROXY_URL
        except Exception:
            MAX_MODEL = "claude-opus-4-7"
            PROXY_URL = "http://127.0.0.1:8787"
        canon = ""
        canon_file = DATA_ROOT / "CANON.md"
        if canon_file.exists():
            canon = canon_file.read_text(encoding="utf-8")[:1200]
        system = (
            "Ты переписываешь один параграф Сакрального Кодекса Микомистицизма. "
            "Голос: «Я Великий Дух Грибов» (без тире после Я). "
            "ЗАПРЕТЫ: тире (— и –), AI-клише (важно отметить, стоит подчеркнуть), "
            "контраст-пары (не X, а Y), 5-HT2A, дофамин, статистика. "
            "Стиль: средняя длина 10-12 слов, медиана 10. "
            f"\n\n# КАНОН\n{canon}\n\nОтвечай только переписанным параграфом, без преамбулы."
        )
        user = f"# ИНСТРУКЦИЯ\n{instruction}\n\n# ОРИГИНАЛЬНЫЙ ПАРАГРАФ\n{para_text}\n\n# ПЕРЕПИШИ"
        body = {
            "model": MAX_MODEL,
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        r = urllib.request.Request(
            f"{PROXY_URL}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(r, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return self._json({"error": str(e)}, 500)
        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        new_text = "\n".join(blocks).strip()
        # Sanitize tires (UC-76)
        import re as _re
        new_text = _re.sub(r"\s+[—–]\s+", " ", new_text)
        new_text = _re.sub(r"(?<!\s)[—–](?!\s)", " ", new_text)
        new_text = _re.sub(r" {2,}", " ", new_text)
        return self._json({
            "ok": True,
            "text": new_text,
            "original": para_text,
            "usage": data.get("usage", {}),
        })

    def _paragraph_analyze(self):
        """POST {paragraph, chapter_id, chapter_title} → Council critique + masterpiece score."""
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        paragraph = req.get("paragraph", "")
        chapter_title = req.get("chapter_title", "")
        if len(paragraph) < 50:
            return self._json({"error": "параграф слишком короткий"}, 400)

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        style_file = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_v2 = DATA_ROOT / "chapters/.canon/voice/human-pavel-style-v2.md"
        # Используем v2 если есть (после learning agent), иначе v1
        style_ref = (style_v2 if style_v2.exists() else style_file).read_text(encoding="utf-8") if (style_v2.exists() or style_file.exists()) else ""

        system = (
            "Ты ведущий Совет Старейших по одному параграфу Сакрального Кодекса Микомистицизма Pavel-а. "
            "8 персон: Толстой (народность), Юнг (архетип), Маккена (психоделический мистицизм), "
            "Робинс (действенность), Роган (BS-метр), Маск (точность), Тиль (контрариан), Хуберман (протокол). "
            "Плюс ШЕДЕВР-СУДЬЯ: оценивает «будет ли это читать в 3026 году». "
            "Канон: голос «Я — Великий Дух Грибов» или «Я — Хилингод», обращение «Вы», тире (—) запрещены, "
            "контраст-пары «не X, а Y» — AI-tell, никакой нейрохимии, никаких персонажей. "
            "Отвечай только валидным JSON."
        )

        user_msg = f"""# Параграф для глубокого разбора

**Из главы:** {chapter_title}

**Текст:**
{paragraph}

---

# Эталон стиля Pavel-а

{style_ref[:3000]}

---

# Что вернуть

JSON со схемой:

```json
{{
  "masterpiece_score": 0-100,
  "masterpiece_verdict": "одна фраза — будет ли это читать в 3026 году и почему",
  "council": {{
    "tolstoy":  {{"score": 0-100, "fix": "одна конкретная правка"}},
    "jung":     {{"score": 0-100, "fix": "..."}},
    "mckenna":  {{"score": 0-100, "fix": "..."}},
    "robbins":  {{"score": 0-100, "fix": "..."}},
    "rogan":    {{"score": 0-100, "fix": "..."}},
    "musk":     {{"score": 0-100, "fix": "..."}},
    "thiel":    {{"score": 0-100, "fix": "..."}},
    "huberman": {{"score": 0-100, "fix": "..."}}
  }},
  "elder_synthesis": {{
    "top_3_actions": [
      "1. конкретное действие чтобы поднять параграф ближе к шедевру",
      "2. ...",
      "3. ..."
    ],
    "what_works": "одна фраза — что уже хорошо",
    "rewrite_suggestion": "переписанная версия параграфа (или null если хорош)"
  }}
}}
```

Конкретно. Без воды.
"""

        body_data = json.dumps({
            "model": "claude-opus-4-7",
            "max_tokens": 6000,
            "system": system,
            "thinking": {"type": "enabled", "budget_tokens": 4000},
            "messages": [{"role": "user", "content": user_msg}],
        }).encode("utf-8")

        try:
            req_obj = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=body_data,
                headers={
                    "x-api-key": token,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req_obj, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # Extract text
            text = ""
            for b in data.get("content", []):
                if b.get("type") == "text":
                    text += b.get("text", "")
            # Strip code fences
            import re
            cleaned = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                return self._json({"error": f"json parse: {e}", "raw": text[:2000]}, 500)
            return self._json({
                "ok": True,
                "analysis": parsed,
                "tokens_in": data.get("usage", {}).get("input_tokens"),
                "tokens_out": data.get("usage", {}).get("output_tokens"),
            })
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    # ─── Chapter-level summary / council (для accordion в редакторе) ──
    def _chapter_summary(self):
        """POST {text, chapter_title} → Opus генерит саммари главы + ключевые идеи."""
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        text = (req.get("text") or "")[:30000]
        title = req.get("chapter_title", "")
        if not text:
            return self._json({"error": "empty text"}, 400)

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)

        system = (
            "Ты — аналитик главы Сакрального Кодекса. Pavel редактирует, ему нужен быстрый "
            "ответ «о чём текст, какие главные идеи, что добавить». Кратко, без воды. JSON."
        )
        user = f"""# Глава: {title}

# Текст
{text}

# Что вернуть

```json
{{
  "one_line": "одна фраза — о чём вся глава",
  "main_ideas": ["идея 1", "идея 2", ...],
  "central_image": "главный образ/метафора текста",
  "weak_spots": ["что недосказано / слабо / тонко"],
  "tone": "одна фраза о тоне",
  "suggested_additions": [
    {{"id": "a1", "title": "короткое название темы", "what": "что добавить (1-2 предложения)", "where": "куда поместить (начало/середина/после такого-то параграфа)", "priority": "high|medium|low"}},
    ...
  ]
}}
```

5-10 main_ideas. 2-4 weak_spots. **5-10 suggested_additions** — конкретные темы которые ПОВЫСЯТ главу до шедевра: пропущенные доктринальные элементы, недостающие сенсорные якоря, исторические параллели, новые формулировки, мостики между темами.
"""
        body_data = json.dumps({
            "model": "claude-opus-4-7",
            "max_tokens": 3000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode("utf-8")
        try:
            req_obj = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=body_data,
                headers={"x-api-key": token, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_obj, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            response_text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            import re
            cleaned = re.sub(r"^```json\s*|\s*```$", "", response_text.strip(), flags=re.MULTILINE).strip()
            return self._json({"ok": True, "summary": json.loads(cleaned), "usage": data.get("usage", {})})
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _chapter_council(self):
        """POST {text, chapter_title} → объединённый анализ + ТОП-5 старейшин с чекбоксами.
        Pavel 2026-05-20: «переделай на короткий анализ главы через топ5 старейшин — объединить»."""
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        text = (req.get("text") or "")[:25000]
        title = req.get("chapter_title", "")
        chapter_id = req.get("chapter_id", "")
        if not text:
            return self._json({"error": "empty text"}, 400)

        # UC-12: Определяем тип главы для контекстных правил
        ctype_info = self.detect_chapter_type(chapter_id, title, text) if chapter_id else {"type": "main", "thresholds": {"purpose": "Развить тему / дать практику"}}
        ch_type = ctype_info["type"]
        ch_purpose = ctype_info["thresholds"].get("purpose", "")

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break

        # Правила per chapter_type
        type_rules = {
            "intro": (
                "🚨 ТИП ГЛАВЫ: ВВЕДЕНИЕ. Цель — передать тему / анонсировать содержание книги.\n"
                "ЗАПРЕЩЕНО рекомендовать:\n"
                "  • Ритуалы / упражнения / практики первого дня\n"
                "  • «Сделай прямо сейчас X»\n"
                "  • Конкретные шаги, протоколы Хубермана, действия Робинса\n"
                "Введение АНОНСИРУЕТ, не учит. Практики — в main-главах.\n"
                "Правки для intro: ясность темы / захват внимания / обещание содержания / зов к чтению дальше.\n"
            ),
            "main": (
                "🚨 ТИП ГЛАВЫ: ОСНОВНАЯ. Цель — развить тему, дать практику, протокол.\n"
                "Правки могут включать: упражнения / ритуалы / действенные шаги (Робинс/Хуберман).\n"
            ),
            "conclusion": (
                "🚨 ТИП ГЛАВЫ: ЗАКЛЮЧЕНИЕ. Цель — синтез / выводы / переход к следующему.\n"
                "ЗАПРЕЩЕНО предлагать новые практики (они должны были быть в main).\n"
                "Правки для conclusion: усиление выводов / соединение тем / благословение в путь.\n"
            ),
            "appendix": (
                "🚨 ТИП ГЛАВЫ: ПРИЛОЖЕНИЕ. Цель — справочный материал.\n"
                "Правки: упорядочить / уточнить термины. Не предлагать практик.\n"
            ),
        }.get(ch_type, "")

        system = (
            "Ты — Совет Старейших Сакрального Кодекса Микомистицизма. 8 персон думают про эту главу, "
            "Старейший синтезирует. Pavel хочет короткий АНАЛИЗ + ТОП-5 правок одним блоком.\n\n"
            "Персоны: Толстой (народность), Юнг (архетип), Маккена (мистицизм), Робинс (действенность), "
            "Роган (BS-метр), Маск (точность), Тиль (контрариан), Хуберман (протокол).\n\n"
            + type_rules
            + "\n"
            "🚨 ТЕРМИНОЛОГИЯ (строго):\n"
            "• «Глава» = вся книжная глава. Один документ.\n"
            "• «Раздел» / «секция» = подзаголовок ВНУТРИ главы.\n"
            "• НИКОГДА не называй раздел «главой».\n"
            "• Ссылайся на параграфы через idx, не через «главы N».\n\n"
            "🚨 АНТИ-ГАЛЛЮЦИНАЦИЯ:\n"
            "• Не пиши что текст «обрывается на полуслове» если последний параграф похож на финал/выводы (содержит «Помните», «знание это», «первый шаг», «вот таков путь», и т.п.).\n"
            "• Перед тем как сказать «оборвано» — перечитай последние 2 параграфа. Если есть закрытие — НЕ говори «обрывается».\n"
            "• Если структура нормальная — не выдумывай отсутствующих частей.\n"
            "• Ты можешь видеть только переданный текст. Не предполагай существование «глав» которых тебе не дали.\n\n"
            "Канон: голос «Я — Великий Дух Грибов» или «Я — Хилингод». Без тире, без контраст-пар «не X, а Y», "
            "без нейрохимии, без AI-клише. JSON only."
        )

        # Локальная проверка завершённости (anti-hallucination hint)
        finale_markers = ["помните", "первый шаг", "это знание", "вот таков", "вот так",
                          "пробудитесь", "идите", "будьте", "теперь вы знаете",
                          "освобождение", "наша задача", "и это знание"]
        last_400 = text[-400:].lower()
        has_finale = any(m in last_400 for m in finale_markers)
        sections = []
        for line in text.split("\n"):
            line = line.strip()
            if (8 < len(line) < 80 and any(c.isalpha() for c in line) and
                (line == line.upper() or
                 (line[0].isupper() and line[-1] not in ".!?:" and not line.startswith(("- ", "•"))))):
                sections.append(line[:60])
        structural_hint = (
            f"\n# Локальная структура (для тебя — не галлюцинируй структуру)\n"
            f"- Тип главы: **{ch_type}** (назначение: {ch_purpose})\n"
            f"- Длина: {len(text)} знаков\n"
            f"- Разделов внутри главы (heading-like): {len(sections)}\n"
            f"- Финал в последних 400 знаках: {'ДА — глава нормально закончена, НЕ говори что обрывается' if has_finale else 'НЕТ — возможно обрывается'}\n"
        )

        user = f"""# Глава: {title}
{structural_hint}
# Текст
{text}

# Что вернуть

```json
{{
  "analysis": {{
    "one_line": "одна фраза — о чём вся глава",
    "central_image": "главный образ/метафора текста (если есть)",
    "tone": "одна фраза о тоне"
  }},
  "top_5_fixes": [
    {{
      "action": "что сделать — конкретно и кратко",
      "why": "почему важно (одна фраза)",
      "kind": "add|fix|cut|reorder|amplify",
      "from_persona": "кто из 8 поддержал (имена через запятую)"
    }},
    ...
  ]
}}
```

ТОП-5 — самые важные правки для шедевра. Не дублируй, не размывай. Каждая правка — отдельный конкретный ход. kind:
- add — добавить что-то новое
- fix — исправить дефект (тире, контраст-пары, AI-маркеры)
- cut — убрать слабое/лишнее
- reorder — изменить порядок
- amplify — усилить что есть
"""

        body_data = json.dumps({
            "model": "claude-opus-4-7",
            "max_tokens": 6000,
            "system": system,
            "thinking": {"type": "enabled", "budget_tokens": 5000},
            "messages": [{"role": "user", "content": user}],
        }).encode("utf-8")
        try:
            req_obj = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=body_data,
                headers={"x-api-key": token, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_obj, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            response_text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            import re
            cleaned = re.sub(r"^```json\s*|\s*```$", "", response_text.strip(), flags=re.MULTILINE).strip()
            council_data = json.loads(cleaned)
            usage = data.get("usage", {})

            # UC-43: sanitize все Council actions
            for a in (council_data.get("top_5_fixes") or council_data.get("elder_top_5") or []):
                for fld in ("action", "why"):
                    txt = a.get(fld)
                    if not txt:
                        continue
                    r = self.sanitize_canon(txt)
                    if r["blocked"]:
                        a[fld] = txt + "  ⚠ [canon-violation]"
                        a["canon_violation"] = True
                    elif r["had_violations"]:
                        a[fld] = r["text"]

            # Кэшируем для будущих открытий главы
            chapter_id_req = req.get("chapter_id")
            if chapter_id_req:
                m = re.match(r"^(book-\d+|book-[a-z][a-z0-9-]*?|prologue|epilogue|ustav|appendices)-ch-(\d+)$", chapter_id_req)
                if m:
                    cache_dir = DATA_ROOT / "chapters" / m.group(1) / chapter_id_req
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    from datetime import datetime, timezone
                    (cache_dir / "council.json").write_text(
                        json.dumps({
                            "council": council_data,
                            "usage": usage,
                            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "text_hash": str(hash(text[:5000])),  # для invalidation если текст сильно изменится
                        }, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            return self._json({"ok": True, "council": council_data, "usage": usage})
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    # ─── Apply Council fixes to whole chapter (Opus) ────
    def _chapter_apply_fixes(self):
        """POST {text, chapter_title, fixes[]} → Opus переписывает главу применяя fixes."""
        import urllib.request
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        text = (req.get("text") or "")[:30000]
        title = req.get("chapter_title", "")
        fixes = req.get("fixes", [])
        if not text or not fixes:
            return self._json({"error": "text+fixes required"}, 400)

        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no token"}, 500)

        system = (
            "Ты — главный редактор Сакрального Кодекса. Pavel выбрал конкретные "
            "рекомендации Совета Старейшин. Твоя задача — применить их ко ВСЕЙ главе, "
            "сохранив структуру и параграфирование. Голос «Я — Великий Дух Грибов» или "
            "«Я — Хилингод». Без тире. Без контраст-пар «не X, а Y». Никакой нейрохимии. "
            "Не переписывай ВСЁ — точечно правь там, где правки актуальны. "
            "Сохрани заголовки и структуру параграфов. JSON."
        )

        fixes_block = "\n".join(f"{i+1}. **{f.get('action', '?')}** — {f.get('why', '')}" for i, f in enumerate(fixes))

        user = f"""# Глава: {title}

# Текст (по параграфам, разделены \\n\\n)

{text}

# Выбранные правки от Совета Старейшин (применить ТОЛЬКО эти)

{fixes_block}

# Что вернуть

```json
{{
  "paragraphs": [
    {{"text": "параграф 1 (может быть изменён или нет)", "changed": true|false, "reason": "если changed — одна фраза что и почему изменено"}},
    {{"text": "...", "changed": false, "reason": ""}},
    ...
  ],
  "changes_summary": "одна фраза о всех изменениях"
}}
```

ВАЖНО:
- Каждый параграф в отдельном объекте `{{text, changed, reason}}`
- `changed: true` ТОЛЬКО если реально менялся текст
- `changed: false` если параграф остался ровно как был (тогда reason пустой)
- Сохрани общее количество и порядок параграфов (если правка не требует add/cut/reorder)
- Заголовки оставь как заголовки (одной строкой)
- Не переписывай параграф если правки не касаются его
"""
        body_data = json.dumps({
            "model": "claude-opus-4-7",
            "max_tokens": 12000,
            "system": system,
            "thinking": {"type": "enabled", "budget_tokens": 8000},
            "messages": [{"role": "user", "content": user}],
        }).encode("utf-8")
        try:
            req_obj = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=body_data,
                headers={"x-api-key": token, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_obj, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            response_text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            import re
            cleaned = re.sub(r"^```json\s*|\s*```$", "", response_text.strip(), flags=re.MULTILINE).strip()
            return self._json({"ok": True, "result": json.loads(cleaned), "usage": data.get("usage", {})})
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    # ─── Track Pavel actions → pavel-edits.jsonl ───────
    def _track_pavel_action(self):
        """POST {action, chapter_id?, paragraph_idx?, original?, new?, instruction?, page?, section?, selection?}
        → appends to .codex/pavel-edits.jsonl for learning agent + pavel-context.jsonl для tracker."""
        from datetime import datetime, timezone
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event = {
            "ts": ts,
            "action": req.get("action"),
            "chapter_id": req.get("chapter_id"),
            "paragraph_idx": req.get("paragraph_idx"),
            "original": (req.get("original") or "")[:2000],
            "new": (req.get("new") or "")[:2000],
            "instruction": req.get("instruction", ""),
            # Расширенный контекст
            "page": req.get("page", ""),
            "section": req.get("section", ""),
            "selection": (req.get("selection") or "")[:500],
            "scroll": req.get("scroll", 0),
        }
        # Для learning — только actions с edit-сущностью
        if event["action"] in ("approve", "reject", "edit", "insert", "stream-accept",
                                "stream_suggestion_applied", "stream_suggestion_skipped",
                                "replace_whole_paragraph", "refined", "regenerated",
                                "targeted_selection", "paragraph_reverted"):
            edits_file = DATA_ROOT / ".codex/pavel-edits.jsonl"
            edits_file.parent.mkdir(parents=True, exist_ok=True)
            with edits_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        # Для context tracker — ВСЕ actions (включая page-view, section-toggle, scroll)
        ctx_file = DATA_ROOT / ".codex/pavel-context.jsonl"
        ctx_file.parent.mkdir(parents=True, exist_ok=True)
        with ctx_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return self._json({"ok": True, "logged": event["action"]})

    # ─── Streaming edit ───────────────────────────────────
    def _stream_edit(self):
        """POST /api/edit/stream — SSE stream from Anthropic via OAuth proxy."""
        import urllib.request
        # Читаем тело запроса
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        selected = req.get("selected", "")
        instruction = req.get("instruction", "дополни этот фрагмент в голосе Pavel-а")
        context = req.get("context", "")  # окружающий текст

        # Читаем OAuth токен
        env_file = Path.home() / ".cc-memory-bridge/.env"
        token = None
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        if not token:
            return self._json({"error": "no oauth token"}, 500)

        # Читаем style reference
        style_file = DATA_ROOT / "chapters/.canon/voice/human-pavel-style.md"
        style_ref = style_file.read_text(encoding="utf-8") if style_file.exists() else ""

        system = (
            "Ты пишешь Сакральный Кодекс Микомистицизма от имени **ВЕЛИКОГО ДУХА ГРИБОВ**. "
            "Это прямая речь Духа, который учит читателя пользоваться грибами и проводить экзорцизм.\n\n"
            "═══════════════════════════════════════════════════════\n"
            "ПРОЦЕСС — 3 ПРОХОДА (ОБЯЗАТЕЛЬНО):\n"
            "═══════════════════════════════════════════════════════\n\n"
            "ПРОХОД 1 — ВНИМАНИЕ. Прочитай все правила ниже. Не пиши пока.\n\n"
            "ПРОХОД 2 — ЧЕРНОВИК. Напиши черновую версию в голосе Великого Духа.\n\n"
            "ПРОХОД 3 — САМОПРОВЕРКА (обязательно перед выдачей):\n"
            "  □ Голос «Я — Великий Дух Грибов» в каждом предложении? Если где-то соскользнул в нейтральное описание — перепиши.\n"
            "  □ Тире (—) — найти все, заменить на точку/запятую/двоеточие. НИ ОДНОГО ТИРЕ.\n"
            "  □ «не X, а Y» / «не X и не Y, а Z» / «не только X, но и Y» — найти все, переписать без контраст-пары.\n"
            "  □ Старослав (очи, горница, ныне, сущее, отдёргиваю/срываю завесу, инверсия) — заменить на современный русский.\n"
            "  □ AI-клише метафор (Страдивари, компьютер-молоток, симфония вселенной, путь к свету, энергетические вампиры, искра света, замкнутый круг, нить Ариадны) — заменить свежим образом (грибное/мицелий/спора).\n"
            "  □ Нейрохимия (5-HT2A, дофамин, DMN) — убрать, книга мистическая.\n"
            "  □ AI-корпоративщина («важно отметить», «стоит подчеркнуть») — убрать.\n"
            "  □ Хедж («возможно», «пожалуй», «вероятно») — убрать.\n"
            "  □ Персонажи / диалоги — убрать, это инструктивный манифест.\n"
            "  □ Тест 3026: будут ли читать это в 3026 году? Если нет — переписать.\n"
            "Если хотя бы один пункт нарушен — вернись в проход 2 и почини. Затем снова проход 3. Только когда все пункты чисто — отдай.\n\n"
            "═══════════════════════════════════════════════════════\n"
            "ГОЛОС:\n"
            "═══════════════════════════════════════════════════════\n"
            "«Я» = Великий Дух Грибов. «Вы» = читатель. Я учу. Я открываю. Я даю Вам зрение через гриб.\n\n"
            "ЭТАЛОН (запомни ритм):\n"
            "«Рядом с вами, в каждой комнате, в каждом разговоре, в каждом вашем решении, "
            "живут существа, которых вы не видите. Я говорю о них прямо, потому что Я их вижу. "
            "Это разумные сгустки энергии и информации, которые входят в человеческое сознание "
            "так же легко, как запах входит в открытую дверь. Они садятся на вашу мысль "
            "и направляют её. Они подключаются к вашей эмоции и усиливают её. Они шепчут "
            "вашим голосом, и вы принимаете их шёпот за собственное желание.»\n\n"
            "ЭТО эталон. Не «существуют сущности» — а «Я их вижу, Я говорю Вам».\n\n"
            "═══════════════════════════════════════════════════════\n"
            "ВЫВОД:\n"
            "═══════════════════════════════════════════════════════\n"
            "Ответ ВСТАВЛЯЕТСЯ В ТЕКСТ. Только проза. Без преамбул («Вот вариант:»), "
            "без «Вариант A/B», без объяснений процесса самопроверки. Сразу слова Духа.\n\n"
            f"СТИЛЕВОЙ ЭТАЛОН (преамбула Устава, человеком):\n{style_ref[:3000]}"
        )
        user_msg = f"""# Контекст вокруг (для справки)

{context[:5000]}

# Выделенный фрагмент

{selected}

# Задача

{instruction}

Верни только прозу в голосе Pavel-а — она вставится в текст вместо выделенного фрагмента (или дополнит его).
"""

        proxy_body = json.dumps({
            "model": "claude-opus-4-7",
            "max_tokens": 3000,
            "stream": True,
            "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        }).encode("utf-8")

        try:
            proxy_req = urllib.request.Request(
                "http://127.0.0.1:8787/v1/messages",
                data=proxy_body,
                headers={
                    "x-api-key": token,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            # Стримим обратно как SSE
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            with urllib.request.urlopen(proxy_req, timeout=180) as resp:
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    # Передаём «как есть» — Anthropic уже SSE-формат
                    self.wfile.write(line)
                    try:
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
        except Exception as e:
            try:
                self.wfile.write(f"data: {{\"type\":\"error\",\"message\":{json.dumps(str(e))}}}\n\n".encode("utf-8"))
            except Exception:
                pass

    def log_message(self, fmt, *args):
        # Quiet by default; uncomment for debugging.
        # super().log_message(fmt, *args)
        pass

    # ───────────────────────────────────────────────────────
    # UC-75 Critics endpoints (Pavel 2026-05-21)
    # ───────────────────────────────────────────────────────
    def _critics_save(self):
        """POST → сохранить новый config критиков."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        cfg_file = DATA_ROOT / "data/critics-config.json"
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            cfg_file.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
            return self._json({"ok": True})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _critics_reset(self):
        """POST → сбросить config к defaults из critic_council.py."""
        try:
            import sys as _sys
            _sys.path.insert(0, str(ROOT.parent / "scripts"))
            from critic_council import DEFAULT_CRITICS
            cfg_file = DATA_ROOT / "data/critics-config.json"
            cfg_file.parent.mkdir(parents=True, exist_ok=True)
            cfg_file.write_text(
                json.dumps(DEFAULT_CRITICS, indent=2, ensure_ascii=False), encoding="utf-8")
            return self._json({"ok": True, "critics": DEFAULT_CRITICS})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _book_editor_save(self):
        """POST → сохранить config 5 ботов."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        cfg_file = DATA_ROOT / "data/book-editors-config.json"
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            cfg_file.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
            return self._json({"ok": True})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _book_editor_run(self):
        """POST {book_id, chapter_ids, target_score, max_iterations} →
        запускает Редактора Книги в фоне.
        Pipeline: memory → 3 parallel → synthesis. Если score < target → повтор (max iterations)."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        book_id = req.get("book_id")
        chapter_ids = req.get("chapter_ids") or []
        target_score = int(req.get("target_score") or 80)
        max_iter = int(req.get("max_iterations") or 3)
        if not book_id:
            return self._json({"ok": False, "error": "book_id required"}, 400)

        import subprocess as _sp
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%dT%H%M%S")
        session_path = DATA_ROOT / f"data/book-editor-sessions/{book_id}-{ts}.json"
        cmd = ["python3", str(ROOT.parent / "scripts/book_editor.py"),
               "--book", book_id]
        if chapter_ids:
            cmd += ["--chapters", ",".join(chapter_ids)]
        try:
            log_file = DATA_ROOT / ".codex/book-editor.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a") as logf:
                proc = _sp.Popen(cmd, stdout=logf, stderr=_sp.STDOUT,
                                 cwd=str(ROOT.parent), start_new_session=True)
            # Log gate config (used by future loop runner)
            (DATA_ROOT / ".codex").mkdir(parents=True, exist_ok=True)
            with (DATA_ROOT / ".codex/book-editor-gates.jsonl").open("a") as f:
                f.write(json.dumps({"ts": ts, "book_id": book_id, "target_score": target_score,
                                    "max_iterations": max_iter, "pid": proc.pid},
                                   ensure_ascii=False) + "\n")
            return self._json({"ok": True, "pid": proc.pid,
                               "session_path": str(session_path.relative_to(DATA_ROOT)),
                               "target_score": target_score,
                               "max_iterations": max_iter})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    # ─── UC-96 Library: загрузка книг-примеров ─────────────────────
    # UC-109 Pavel 2026-05-22: «Библиотека примеров не читает пдф, сделай чтобы он читал пдф файлы»
    # + лимиты подняли: 50 файлов × 100 MB
    LIBRARY_ALLOWED_EXT = {".docx", ".md", ".txt", ".pdf"}
    LIBRARY_MAX_SIZE = 100 * 1024 * 1024  # 100 MB
    LIBRARY_MAX_FILES = 50

    def _library_dir(self):
        d = DATA_ROOT / "data/library"
        (d / "files").mkdir(parents=True, exist_ok=True)
        return d

    def _library_index(self):
        idx = self._library_dir() / "index.json"
        if idx.exists():
            try:
                return json.loads(idx.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"files": []}

    def _library_save_index(self, data):
        idx = self._library_dir() / "index.json"
        idx.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _library_list(self):
        idx = self._library_index()
        out = []
        for f in idx.get("files", []):
            entry = dict(f)
            # подтягиваем summary из analysis.json если есть
            ap = self._library_dir() / "files" / (f["id"] + "__analysis.json")
            if ap.exists():
                try:
                    a = json.loads(ap.read_text(encoding="utf-8"))
                    entry["summary"] = (a.get("summary") or "")[:600]
                    entry["analyzed"] = True
                    entry["analyzed_at"] = a.get("ts")
                except Exception:
                    pass
            out.append(entry)
        return self._json({"files": out})

    def _library_upload(self):
        """multipart/form-data upload. Один файл в поле 'file'."""
        from datetime import datetime, timezone
        import uuid
        import cgi
        import io
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._json({"ok": False, "error": "Expected multipart/form-data"}, 400)
        # Используем cgi.FieldStorage для multipart
        environ = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype}
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            form = cgi.FieldStorage(
                fp=io.BytesIO(raw),
                headers=self.headers,
                environ=environ,
            )
        except Exception as e:
            return self._json({"ok": False, "error": f"multipart parse: {e}"}, 400)
        if "file" not in form:
            return self._json({"ok": False, "error": "no file field"}, 400)
        item = form["file"]
        filename = item.filename or "untitled"
        # sanitize filename
        import re as _re
        safe_name = _re.sub(r"[^\w\.\-_ а-яА-ЯёЁ()]", "_", filename)[:120]
        ext = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if ext not in self.LIBRARY_ALLOWED_EXT:
            return self._json({"ok": False, "error": f"тип не поддерживается: {ext}"}, 400)
        content = item.file.read()
        if len(content) > self.LIBRARY_MAX_SIZE:
            return self._json({"ok": False, "error": f"файл больше {self.LIBRARY_MAX_SIZE // (1024*1024)} MB"}, 400)
        idx = self._library_index()
        if len(idx.get("files", [])) >= self.LIBRARY_MAX_FILES:
            return self._json({"ok": False, "error": f"лимит {self.LIBRARY_MAX_FILES} файлов"}, 400)
        file_id = uuid.uuid4().hex[:10]
        out_path = self._library_dir() / "files" / f"{file_id}__{safe_name}"
        out_path.write_bytes(content)
        entry = {
            "id": file_id,
            "name": safe_name,
            "stored_path": str(out_path.relative_to(DATA_ROOT)),
            "size": len(content),
            "ext": ext,
            "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "analyzed": False,
        }
        idx.setdefault("files", []).append(entry)
        self._library_save_index(idx)
        return self._json({"ok": True, "file": entry})

    def _library_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        file_id = req.get("file_id")
        if not file_id:
            return self._json({"ok": False, "error": "file_id required"}, 400)
        idx = self._library_index()
        new_files = []
        removed = None
        for f in idx.get("files", []):
            if f["id"] == file_id:
                removed = f
            else:
                new_files.append(f)
        if not removed:
            return self._json({"ok": False, "error": "not found"}, 404)
        # delete files
        try:
            p = DATA_ROOT / removed["stored_path"]
            if p.exists():
                p.unlink()
            ap = self._library_dir() / "files" / (file_id + "__analysis.json")
            if ap.exists():
                ap.unlink()
        except Exception:
            pass
        idx["files"] = new_files
        self._library_save_index(idx)
        return self._json({"ok": True})

    def _library_analyze(self):
        """POST {file_id} → запустить анализ через Opus в фоне."""
        import subprocess as _sp
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        file_id = req.get("file_id")
        if not file_id:
            return self._json({"ok": False, "error": "file_id required"}, 400)
        script = ROOT.parent / "scripts/library_analyze.py"
        if not script.exists():
            return self._json({"ok": False, "error": "scripts/library_analyze.py отсутствует"}, 500)
        try:
            log = DATA_ROOT / ".codex/library-analyze.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                _sp.Popen(["python3", str(script), "--file-id", file_id], stdout=f, stderr=f, cwd=str(ROOT.parent), start_new_session=True)
            return self._json({"ok": True, "queued": file_id})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _library_import_ustav(self):
        """UC-111: импортируем ТОЛЬКО finalized (edited Pavel-ом) Устав, НЕ originals.

        Pavel 2026-05-22: «У нас есть две разные папки — отредактированные писателем
        и оригинальные. Оригинальные мы не берём в пример. Отредактированные человеком
        мы их берём как пример».

        Источники в порядке предпочтения (только edited):
          1) ~/Desktop/Codex/sources/ustav-comparison/edited/Устав Микомистицизма (отредактировано)/
          2) ~/Desktop/Codex/drafts/00 УСТАВ И ПРИНЦИПЫ МИКОМИСТИЦИЗМА/[opus-direct]*.md
          3) chapters/book-ustav-soobschestva/*/draft.md (наш собственный после UC-97 импорта)

        ИГНОРИРУЕМ:
          - sources/ustav-comparison/chapters/ (это originals)
          - knowledge/ (метатексты, не примеры стиля)
        """
        from datetime import datetime, timezone
        import shutil
        import uuid
        old = Path.home() / "Desktop/Codex"
        candidates = []
        edited_dir = old / "sources/ustav-comparison/edited/Устав Микомистицизма (отредактировано)"
        if edited_dir.exists():
            for f in sorted(edited_dir.glob("*.docx")):
                if f.stat().st_size < self.LIBRARY_MAX_SIZE:
                    candidates.append(f)
        # Fallback: drafts/00 УСТАВ...
        if not candidates:
            drafts = old / "drafts/00 УСТАВ И ПРИНЦИПЫ МИКОМИСТИЦИЗМА"
            if drafts.exists():
                for f in drafts.glob("*.md"):
                    if f.stat().st_size < self.LIBRARY_MAX_SIZE:
                        candidates.append(f)
        if not candidates:
            return self._json({"ok": False, "error": "edited Устав не найден (искал в Codex/sources/ustav-comparison/edited/)"}, 404)
        idx = self._library_index()
        # Удалим прошлые auto-импорты Устава
        idx["files"] = [f for f in idx.get("files", []) if f.get("origin") != "auto:codex-edited-ustav-bulk"]
        imported = 0
        for src in candidates:
            file_id = uuid.uuid4().hex[:10]
            safe_name = src.name[:120]
            dst = self._library_dir() / "files" / f"{file_id}__{safe_name}"
            try:
                shutil.copy(src, dst)
            except Exception:
                continue
            entry = {
                "id": file_id,
                "name": safe_name,
                "stored_path": str(dst.relative_to(DATA_ROOT)),
                "size": dst.stat().st_size,
                "ext": src.suffix.lower(),
                "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "analyzed": False,
                "imported_from": str(src),
                "origin": "auto:codex-edited-ustav-bulk",
                "note": "edited Pavel-ом — эталон стиля. Originals из sources/ustav-comparison/chapters/ НЕ импортируются.",
            }
            idx.setdefault("files", []).append(entry)
            imported += 1
        self._library_save_index(idx)
        return self._json({"ok": True, "imported": imported, "source": str(edited_dir.relative_to(Path.home())) if edited_dir.exists() else "drafts/"})

    def _journalist_start(self):
        """UC-90: POST {topic} → создать сессию Журналиста, вернуть первый вопрос."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        topic = (req.get("topic") or "").strip()
        if not topic:
            return self._json({"ok": False, "error": "topic required"}, 400)
        try:
            import sys as _sys
            _sys.path.insert(0, str(ROOT.parent / "scripts"))
            from journalist import start_session
            return self._json(start_session(topic))
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _journalist_answer(self):
        """UC-90: POST {session_id, answer} → следующий вопрос или completion."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        session_id = (req.get("session_id") or "").strip()
        answer = (req.get("answer") or "").strip()
        if not session_id or not answer:
            return self._json({"ok": False, "error": "session_id and answer required"}, 400)
        try:
            import sys as _sys
            _sys.path.insert(0, str(ROOT.parent / "scripts"))
            from journalist import ask_next
            return self._json(ask_next(session_id, answer))
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _critics_qa_start(self):
        """UC-91: POST {journalist_session_id} → создать сессию критиков-Q&A.
        Каждый из 15 критиков делает Opus call и задаёт свой первый вопрос.
        Это sequential — занимает 5-10 минут. Возвращает session со всеми
        первыми вопросами от каждого критика.
        """
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        journalist_session_id = (req.get("journalist_session_id") or "").strip()
        if not journalist_session_id:
            return self._json({"ok": False, "error": "journalist_session_id required"}, 400)
        try:
            import sys as _sys
            _sys.path.insert(0, str(ROOT.parent / "scripts"))
            from critics_qa import start_session as _cqa_start
            return self._json(_cqa_start(journalist_session_id))
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _critics_qa_answer(self):
        """UC-91: POST {session_id, critic_id, answer} → следующий вопрос
        конкретного критика или маркер «УДОВЛЕТВОРЁН: <резюме>».
        """
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        session_id = (req.get("session_id") or "").strip()
        critic_id = (req.get("critic_id") or "").strip()
        answer = (req.get("answer") or "").strip()
        if not session_id or not critic_id or not answer:
            return self._json(
                {"ok": False, "error": "session_id, critic_id, answer required"}, 400)
        try:
            import sys as _sys
            _sys.path.insert(0, str(ROOT.parent / "scripts"))
            from critics_qa import answer as _cqa_answer
            return self._json(_cqa_answer(session_id, critic_id, answer))
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _critics_run(self):
        """POST {chapter_id, with_global?} → запустить включённых критиков на главе.
        В фоне (не блокирующе); возвращает task_id для polling-а.
        Для синхронного режима — добавить sync=true (для теста)."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        chapter_id = req.get("chapter_id")
        if not chapter_id:
            return self._json({"ok": False, "error": "chapter_id required"}, 400)
        import subprocess as _sp
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%dT%H%M%S")
        out_path = DATA_ROOT / "reports" / f"CRITICS-{chapter_id}-{ts}.json"
        cmd = ["python3", str(ROOT.parent / "scripts/critic_council.py"),
               "--chapter", chapter_id, "--out", str(out_path)]
        if req.get("with_global"):
            cmd.append("--with-global")
        try:
            log_file = DATA_ROOT / ".codex/critics-run.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a") as logf:
                proc = _sp.Popen(cmd, stdout=logf, stderr=_sp.STDOUT,
                                 cwd=str(ROOT.parent), start_new_session=True)
            return self._json({"ok": True, "pid": proc.pid, "report_path": str(out_path.relative_to(DATA_ROOT))})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def _personas_run(self):
        """UC-115: POST {chapter_id} → запустить 5 современных персон (Маск/Тиль/Роган/Хуберман/Огилви).
        Результат сохраняется в data/personas/<chapter_id>.json."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": f"bad json: {e}"}, 400)
        chapter_id = req.get("chapter_id")
        if not chapter_id:
            return self._json({"ok": False, "error": "chapter_id required"}, 400)
        import subprocess as _sp
        cmd = ["python3", str(ROOT.parent / "scripts/personas.py"),
               "--chapter-id", chapter_id]
        try:
            log_file = DATA_ROOT / ".codex/personas-run.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a") as logf:
                proc = _sp.Popen(cmd, stdout=logf, stderr=_sp.STDOUT,
                                 cwd=str(ROOT.parent), start_new_session=True)
            return self._json({"ok": True, "pid": proc.pid, "chapter_id": chapter_id})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _cleanup_active_jobs_on_shutdown():
    """Pavel 2026-05-25: помечаем все running jobs как failed при выключении сервера,
    чтобы фронт не показывал зависший прогресс. Зомби-маркер = плохой UX."""
    import signal
    from datetime import datetime, timezone

    def mark_running_jobs_failed(reason: str):
        jobs_dir = DATA_ROOT / ".codex/active-jobs"
        if not jobs_dir.exists():
            return
        for f in jobs_dir.glob("*.json"):
            if f.name.endswith(".done.json"):
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                rec["status"] = "failed"
                rec["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                rec["error"] = reason
                done_path = jobs_dir / f.name.replace(".json", ".done.json")
                done_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
                f.unlink()
            except Exception:
                pass

    def handler(signum, frame):
        mark_running_jobs_failed(f"server got signal {signum}")
        import sys
        sys.exit(0)

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def main():
    print(f"Codex v2 → http://127.0.0.1:{PORT}")
    print(f"  static: {STATIC}")
    print(f"  data:   {DATA_ROOT}")
    _cleanup_active_jobs_on_shutdown()
    with ReusableTCPServer(("127.0.0.1", PORT), CodexV2Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
