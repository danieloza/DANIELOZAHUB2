# -*- coding: utf-8 -*-
import json
import logging
import time
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from config import DATA_DIR, ENV_DRIVE, ENV_SA, ENV_SHEET_ID, ENV_SHEET_NAME, SA_JSON_DEFAULT, env, must
from domain.metrics import record_metric

_ws = None
_drive = None
log = logging.getLogger("danex.sheets")


def _with_retry(fn, what: str, attempts: int = 3, base_delay: float = 0.6):
    last_exc = None
    for i in range(1, attempts + 1):
        t0 = time.perf_counter()
        try:
            out = fn()
            record_metric("gsheets_call", ok=True, latency_ms=int((time.perf_counter() - t0) * 1000), operation=what)
            return out
        except Exception as exc:
            record_metric("gsheets_call", ok=False, latency_ms=int((time.perf_counter() - t0) * 1000), operation=what)
            last_exc = exc
            if i >= attempts:
                break
            delay = base_delay * (2 ** (i - 1))
            log.warning("Retry %s failed (%s/%s): %s", what, i, attempts, exc)
            time.sleep(delay)
    raise last_exc


def sa_path() -> str:
    raw = env(ENV_SA, str(SA_JSON_DEFAULT)).strip()
    if raw.startswith("{"):
        # Support secret manager payload that stores full SA JSON content.
        target = DATA_DIR / "service_account.runtime.json"
        try:
            parsed = json.loads(raw)
            target.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            target.write_text(raw, encoding="utf-8")
        return str(target)
    return raw


def ws():
    global _ws
    if _ws:
        return _ws

    def _init_ws():
        creds = Credentials.from_service_account_file(sa_path(), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        return gc.open_by_key(must(ENV_SHEET_ID)).worksheet(env(ENV_SHEET_NAME, "Arkusz1"))

    _ws = _with_retry(_init_ws, "ws_init")
    return _ws


def drive():
    global _drive
    if _drive:
        return _drive

    def _init_drive():
        creds = Credentials.from_service_account_file(sa_path(), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    _drive = _with_retry(_init_drive, "drive_init")
    return _drive


def ensure_drive_root():
    folder_id = must(ENV_DRIVE)
    _with_retry(lambda: drive().files().get(fileId=folder_id, fields="id,name").execute(), "drive_root_check")
    return folder_id


def get_all_values():
    return _with_retry(lambda: ws().get_all_values(), "get_all_values")


def get_row(row_no: int):
    return _with_retry(lambda: ws().row_values(row_no), "get_row")


def update_cell(row_no: int, col: int, value):
    return _with_retry(lambda: ws().update_cell(row_no, col, value), "update_cell")


def append_row(values, value_input_option="USER_ENTERED"):
    return _with_retry(lambda: ws().append_row(values, value_input_option=value_input_option), "append_row")


def next_row():
    return len(get_all_values()) + 1
