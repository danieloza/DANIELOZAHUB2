# -*- coding: utf-8 -*-
from types import SimpleNamespace
from typing import Any

from telegram import Update

from domain.metrics import record_metric
from domain.retry_queue import dead_letter_size, enqueue, process_queue, queue_size
from storage_api import ApiStorage
from storage_sheets import SheetsStorage

_sheets = SheetsStorage()
_api = ApiStorage()


def _beta_user_ids() -> set[int]:
    from config import env

    raw = env("BETA_API_USER_IDS", "").strip()
    if not raw:
        return set()
    out = set()
    for x in raw.split(","):
        x = x.strip()
        if x.isdigit():
            out.add(int(x))
    return out


def _storage_by_name(name: str):
    if name == "ApiStorage":
        return _api
    return _sheets


def get_storage(update: Update):
    uid = update.effective_user.id if update and update.effective_user else None
    if uid and uid in _beta_user_ids():
        return _api
    return _sheets


def _exec_retry(rec: dict) -> None:
    payload = rec.get("payload", {})
    op = rec.get("operation", "")
    backend = payload.get("backend", "SheetsStorage")
    uid = int(payload.get("user_id") or 0)
    st = _storage_by_name(backend)
    fake = SimpleNamespace(effective_user=SimpleNamespace(id=uid))

    if op == "append_row":
        st.append_row(fake, payload.get("values", []), value_input_option=payload.get("value_input_option", "USER_ENTERED"))
        return
    if op == "update_cell":
        st.update_cell(fake, int(payload.get("row_no", 0)), int(payload.get("col", 0)), payload.get("value"))
        return
    raise RuntimeError(f"Unknown queue operation: {op}")


def process_retry_backlog(limit: int = 20) -> dict:
    return process_queue(_exec_retry, limit=limit)


def retry_stats() -> dict:
    return {"queue": queue_size(), "dlq": dead_letter_size()}


def ws(update: Update):
    return get_storage(update).ws(update)


def get_all_values(update: Update):
    return get_storage(update).get_all_values(update)


def get_row(update: Update, row_no: int):
    return get_storage(update).get_row(update, row_no)


def update_cell(update: Update, row_no: int, col: int, value: Any):
    storage = get_storage(update)
    try:
        process_retry_backlog(limit=5)
        out = storage.update_cell(update, row_no, col, value)
        record_metric("storage_write", ok=True, backend=type(storage).__name__, operation="update_cell")
        return out
    except Exception as exc:
        payload = {
            "backend": type(storage).__name__,
            "user_id": update.effective_user.id if update and update.effective_user else None,
            "row_no": row_no,
            "col": col,
            "value": value,
        }
        enqueue("update_cell", payload, error=str(exc))
        record_metric("storage_write", ok=False, backend=type(storage).__name__, operation="update_cell")
        raise


def append_row(update: Update, values, value_input_option: str = "USER_ENTERED"):
    storage = get_storage(update)
    try:
        process_retry_backlog(limit=5)
        out = storage.append_row(update, values, value_input_option=value_input_option)
        record_metric("storage_write", ok=True, backend=type(storage).__name__, operation="append_row")
        return out
    except Exception as exc:
        payload = {
            "backend": type(storage).__name__,
            "user_id": update.effective_user.id if update and update.effective_user else None,
            "values": list(values),
            "value_input_option": value_input_option,
        }
        qid = enqueue("append_row", payload, error=str(exc))
        record_metric("storage_write", ok=False, backend=type(storage).__name__, operation="append_row")
        raise RuntimeError(f"append_row failed, queued as {qid}") from exc


def next_row(update: Update):
    return get_storage(update).next_row(update)
