#!/usr/bin/env python3
"""Pre-warm master-audit cache for all chapters of a book.

Runs sequentially (one chapter at a time) via the async endpoint —
each call returns immediately, then we wait for the .done marker to
appear before triggering the next one. This keeps proxy load low.

Usage:
    python3 scripts/prewarm_master_audit.py --book book-12

Pavel rule: "не экономь токены". Each chapter ~10K input + 1.5K output,
$0.15-0.20. 17 chapters ≈ $3.

Pavel rule: "работаю всю ночь и думай над оптимизацией". This script
runs in the background while Pavel sleeps so EVERY chapter has fresh
cache when he wakes up.
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = "http://127.0.0.1:7788"


def list_chapters(book_id: str) -> list:
    """Все главы книги, сортированы по номеру."""
    book_dir = ROOT / "chapters" / book_id
    if not book_dir.exists():
        return []
    chapters = []
    for d in sorted(book_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith("."):
            continue
        if not (d / "draft.md").exists():
            continue
        # Skip short / empty drafts
        size = (d / "draft.md").stat().st_size
        if size < 200:
            continue
        chapters.append({"chapter_id": d.name, "size": size})
    return chapters


def has_fresh_cache(chapter_id: str, max_age_hours: int = 24) -> bool:
    """Есть ли свежий master-audit cache для главы?"""
    cache_file = ROOT / "data" / "master-audit" / f"{chapter_id}.json"
    if not cache_file.exists():
        return False
    age_seconds = time.time() - cache_file.stat().st_mtime
    return age_seconds < max_age_hours * 3600


def start_audit(chapter_id: str) -> dict:
    req = urllib.request.Request(
        f"{SERVER}/api/chapter/master-audit-start",
        data=json.dumps({"chapter_id": chapter_id}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def wait_for_done(chapter_id: str, max_seconds: int = 360) -> bool:
    """Poll until .done.json appears or cache file is fresh."""
    deadline = time.time() + max_seconds
    cache_file = ROOT / "data" / "master-audit" / f"{chapter_id}.json"
    start_ts = time.time()

    while time.time() < deadline:
        if cache_file.exists() and cache_file.stat().st_mtime > start_ts - 5:
            return True
        time.sleep(5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True, help="book_id, e.g. book-12")
    ap.add_argument("--force", action="store_true", help="re-audit even if cache exists")
    ap.add_argument("--max-age-hours", type=int, default=24,
                    help="skip chapters with cache newer than this (default 24h)")
    args = ap.parse_args()

    chapters = list_chapters(args.book)
    if not chapters:
        print(f"ERROR: no chapters with drafts in {args.book}", file=sys.stderr)
        return 1

    print(f"=== Pre-warming master-audit for {args.book} ===")
    print(f"Total chapters: {len(chapters)}")
    if not args.force:
        with_cache = [c for c in chapters if has_fresh_cache(c["chapter_id"], args.max_age_hours)]
        print(f"Already cached (skipping): {len(with_cache)}")
        chapters = [c for c in chapters if not has_fresh_cache(c["chapter_id"], args.max_age_hours)]
    print(f"To audit now: {len(chapters)}")
    print()

    results = []
    for i, ch in enumerate(chapters, 1):
        print(f"[{i}/{len(chapters)}] {ch['chapter_id']} ({ch['size']/1024:.1f} KB)…", flush=True)
        ts_start = time.time()
        r = start_audit(ch["chapter_id"])
        if r.get("error"):
            print(f"   ERROR start: {r['error']}")
            results.append({"chapter_id": ch["chapter_id"], "status": "start_error", "error": r["error"]})
            continue
        if r.get("already_running"):
            print(f"   already running, waiting…")
        # Wait for cache to appear
        ok = wait_for_done(ch["chapter_id"], max_seconds=360)
        elapsed = int(time.time() - ts_start)
        if ok:
            # Read score
            try:
                d = json.loads((ROOT / "data" / "master-audit" / f"{ch['chapter_id']}.json").read_text())
                edits_n = len(d.get("edits", []))
                score = d.get("score_estimate")
                print(f"   ✓ done in {elapsed}s · {edits_n} правок · score {score}")
                results.append({"chapter_id": ch["chapter_id"], "status": "ok",
                                "elapsed": elapsed, "edits": edits_n, "score": score})
            except Exception as e:
                results.append({"chapter_id": ch["chapter_id"], "status": "parse_error", "error": str(e)})
        else:
            print(f"   ✗ timeout after {elapsed}s")
            results.append({"chapter_id": ch["chapter_id"], "status": "timeout", "elapsed": elapsed})

    # Save run log
    out_dir = ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = out_dir / f"PREWARM-{args.book}-{ts}.json"
    log_file.write_text(json.dumps({
        "book_id": args.book,
        "ts": ts,
        "results": results,
        "ok_count": sum(1 for r in results if r["status"] == "ok"),
        "fail_count": sum(1 for r in results if r["status"] != "ok"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"=== Done ===")
    print(f"OK: {sum(1 for r in results if r['status']=='ok')} · FAIL: {sum(1 for r in results if r['status']!='ok')}")
    print(f"Log: {log_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
