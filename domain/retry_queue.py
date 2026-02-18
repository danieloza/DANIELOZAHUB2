# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from config import DATA_DIR

_QUEUE_FILE = DATA_DIR / "retry_queue.json"
_DLQ_FILE = DATA_DIR / "dead_letter_queue.json"


def _now() -> datetime:
    return datetime.now()


def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _fmt_dt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def queue_size() -> int:
    return len(_load(_QUEUE_FILE))


def dead_letter_size() -> int:
    return len(_load(_DLQ_FILE))


def enqueue(operation: str, payload: dict, error: str, max_attempts: int = 6, delay_sec: int = 30) -> str:
    rows = _load(_QUEUE_FILE)
    rid = uuid4().hex
    rows.append(
        {
            "id": rid,
            "operation": operation,
            "payload": payload,
            "attempts": 0,
            "max_attempts": max(1, int(max_attempts)),
            "error": str(error),
            "created_at": _fmt_dt(_now()),
            "next_try_at": _fmt_dt(_now() + timedelta(seconds=max(0, int(delay_sec)))),
        }
    )
    _save(_QUEUE_FILE, rows)
    return rid


def process_queue(executor, limit: int = 20) -> dict:
    rows = _load(_QUEUE_FILE)
    dlq = _load(_DLQ_FILE)
    if not rows:
        return {"processed": 0, "ok": 0, "failed": 0, "moved_to_dlq": 0}

    now = _now()
    processed = 0
    ok = 0
    failed = 0
    moved = 0
    kept: list[dict] = []

    for rec in rows:
        if processed >= max(1, limit):
            kept.append(rec)
            continue

        try:
            due = _parse_dt(rec.get("next_try_at", "1970-01-01 00:00:00")) <= now
        except Exception:
            due = True

        if not due:
            kept.append(rec)
            continue

        processed += 1
        try:
            executor(rec)
            ok += 1
        except Exception as exc:
            failed += 1
            rec["attempts"] = int(rec.get("attempts", 0)) + 1
            rec["error"] = str(exc)
            backoff = min(3600, 30 * (2 ** min(6, rec["attempts"] - 1)))
            rec["next_try_at"] = _fmt_dt(_now() + timedelta(seconds=backoff))
            if rec["attempts"] >= int(rec.get("max_attempts", 6)):
                rec["dlq_at"] = _fmt_dt(_now())
                dlq.append(rec)
                moved += 1
            else:
                kept.append(rec)

    _save(_QUEUE_FILE, kept)
    _save(_DLQ_FILE, dlq)
    return {"processed": processed, "ok": ok, "failed": failed, "moved_to_dlq": moved}
