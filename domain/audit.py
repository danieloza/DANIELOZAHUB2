# -*- coding: utf-8 -*-
import json
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timedelta
from uuid import uuid4

from config import LOGS_DIR, STATUS_SENT, STATUS_TODO

_AUDIT_FILE = LOGS_DIR / "audit.jsonl"
_REQUEST_ID: ContextVar[str] = ContextVar("audit_request_id", default="")


def begin_request(request_id: str | None = None) -> str:
    rid = (request_id or "").strip() or uuid4().hex[:12]
    _REQUEST_ID.set(rid)
    return rid


def current_request_id() -> str:
    return _REQUEST_ID.get("")


def log_event(event_type: str, user_id: int | None = None, **payload) -> None:
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event_type,
        "user_id": user_id,
        **payload,
    }
    rid = current_request_id()
    if rid and "request_id" not in rec:
        rec["request_id"] = rid
    with _AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_recent(limit: int = 50):
    if not _AUDIT_FILE.exists():
        return []
    lines = _AUDIT_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    out = []
    for ln in lines[-max(1, limit):]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def count_last_hours(hours: int = 24) -> int:
    if not _AUDIT_FILE.exists():
        return 0
    cut = datetime.now() - timedelta(hours=hours)
    cnt = 0
    for rec in read_recent(5000):
        ts = rec.get("ts")
        if not ts:
            continue
        try:
            d = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if d >= cut:
            cnt += 1
    return cnt


def mama_activity_last_24h(mama_user_ids: set[int]) -> dict:
    if not _AUDIT_FILE.exists() or not mama_user_ids:
        return {"added": 0, "status_changes": 0, "total_events": 0}
    cut = datetime.now() - timedelta(hours=24)
    out = {"added": 0, "status_changes": 0, "total_events": 0}
    for rec in read_recent(8000):
        uid = rec.get("user_id")
        if uid not in mama_user_ids:
            continue
        ts = rec.get("ts")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if dt < cut:
            continue
        out["total_events"] += 1
        ev = rec.get("event", "")
        if ev == "invoice_added":
            out["added"] += 1
        if ev == "status_change":
            out["status_changes"] += 1
    return out


def mama_weekly_summary(mama_user_ids: set[int], days: int = 7) -> dict:
    if not _AUDIT_FILE.exists() or not mama_user_ids:
        return {"added": 0, "waiting": 0, "sent": 0, "top_fixed": []}

    cut = datetime.now() - timedelta(days=max(1, days))
    added = 0
    waiting = 0
    sent = 0
    fixed_counter: Counter[int] = Counter()

    for rec in read_recent(30000):
        uid = rec.get("user_id")
        if uid not in mama_user_ids:
            continue
        ts = rec.get("ts")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if dt < cut:
            continue

        ev = rec.get("event", "")
        row_no = rec.get("row_no")
        if ev == "invoice_added":
            added += 1
        elif ev == "status_change":
            new_status = rec.get("new_status", "")
            if new_status == STATUS_SENT:
                sent += 1
            if new_status == STATUS_TODO:
                waiting += 1
                if isinstance(row_no, int):
                    fixed_counter[row_no] += 1
        elif ev == "ocr_fix" and isinstance(row_no, int):
            fixed_counter[row_no] += 1

    top_fixed = [{"row": row_no, "count": cnt} for row_no, cnt in fixed_counter.most_common(3)]
    return {"added": added, "waiting": waiting, "sent": sent, "top_fixed": top_fixed}
