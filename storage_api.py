# -*- coding: utf-8 -*-
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from telegram import Update

from config import (
    COL_DATE,
    COL_NO,
    COL_COMP,
    COL_GROSS,
    COL_TYPE,
    COL_VAT,
    COL_NET,
    COL_CAT,
    COL_USER,
    COL_STATUS,
    COL_FILE,
    STATUS_NEW,
    STATUS_TODO,
    STATUS_OK,
    STATUS_SENT,
    env,
)
from domain.metrics import record_metric

_DATA_DIR = Path(__file__).resolve().parent / "data"
_DATA_DIR.mkdir(exist_ok=True)


def _map_path(user_id: int) -> Path:
    return _DATA_DIR / f"api_rowmap_{user_id}.json"


def _load_map(user_id: int) -> Dict[str, Any]:
    p = _map_path(user_id)
    if not p.exists():
        return {"next_row": 2, "row_to_invoice": {}, "meta_by_invoice": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"next_row": 2, "row_to_invoice": {}, "meta_by_invoice": {}}


def _save_map(user_id: int, data: Dict[str, Any]) -> None:
    _map_path(user_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _bot_status_to_api_status(bot_status: str) -> str:
    s = (bot_status or "").strip().upper()
    if s == STATUS_SENT:
        return "sent"
    if s == STATUS_OK:
        return "sent"
    return "draft"


def _api_status_to_bot_status(api_status: str) -> str:
    s = (api_status or "").strip().lower()
    if s == "sent":
        return STATUS_SENT
    if s == "paid":
        return STATUS_OK
    return STATUS_TODO


class ApiStorage:
    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_exp: float = 0.0
        self._http: Optional[httpx.Client] = None
        self._last_base_url: str = ""

    def _client(self) -> httpx.Client:
        base_url = env("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        if self._http is None or self._last_base_url != base_url:
            self._http = httpx.Client(base_url=base_url, timeout=30.0)
            self._last_base_url = base_url
        return self._http

    def _request_with_retry(self, method: str, path: str, **kwargs):
        last_exc = None
        for attempt in range(1, 4):
            t0 = time.perf_counter()
            try:
                resp = self._client().request(method, path, **kwargs)
                elapsed = int((time.perf_counter() - t0) * 1000)
                record_metric("api_request", ok=resp.status_code < 500, latency_ms=elapsed, method=method, path=path)
                return resp
            except Exception as exc:
                elapsed = int((time.perf_counter() - t0) * 1000)
                record_metric("api_request", ok=False, latency_ms=elapsed, method=method, path=path)
                last_exc = exc
                if attempt >= 3:
                    break
                time.sleep(0.5 * attempt)
        raise last_exc

    def _login(self) -> None:
        email = env("BOT_API_EMAIL", "")
        password = env("BOT_API_PASSWORD", "")
        if not email or not password:
            raise RuntimeError("Brak BOT_API_EMAIL/BOT_API_PASSWORD w .env/Secret Manager")
        r = self._request_with_retry("POST", "/api/v1/auth/login", data={"username": email, "password": password})
        r.raise_for_status()
        data = r.json()
        tok = data.get("access_token") or data.get("token")
        if not tok:
            raise RuntimeError(f"Brak access_token w odpowiedzi: {data}")
        self._token = tok
        exp = data.get("expires_in")
        self._token_exp = time.time() + (int(exp) if exp else 25 * 60)

    def _ensure(self) -> None:
        if (not self._token) or (time.time() > (self._token_exp - 30)):
            self._login()

    def _req(self, method: str, path: str, json_body=None, params=None):
        self._ensure()
        headers = {"Authorization": f"Bearer {self._token}"}
        r = self._request_with_retry(method, path, json=json_body, params=params, headers=headers)
        r.raise_for_status()
        return r.json() if r.content else None

    def _find_or_create_client(self, name: str) -> int:
        name = (name or "").strip() or "Nieznany klient"
        res = self._req("GET", "/api/v1/clients", params={"q": name, "skip": 0, "limit": 20})
        if isinstance(res, list):
            for c in res:
                if (c.get("name") or "").strip().lower() == name.lower():
                    return int(c["id"])
        created = self._req("POST", "/api/v1/clients", json_body={"name": name})
        return int(created["id"])

    def ws(self, update: Update):
        return self

    def next_row(self, update: Update) -> int:
        m = _load_map(update.effective_user.id)
        return int(m.get("next_row", 2))

    def append_row(self, update: Update, values: List[Any], value_input_option: str = "USER_ENTERED") -> int:
        uid = update.effective_user.id
        m = _load_map(uid)
        row_no = int(m.get("next_row", 2))
        m["next_row"] = row_no + 1

        vals = list(values)
        if len(vals) < COL_FILE:
            vals += [""] * (COL_FILE - len(vals))

        no_s = str(vals[COL_NO - 1] or "").strip() or "BRAK_NUMERU"
        comp_s = str(vals[COL_COMP - 1] or "").strip() or "Nieznany klient"
        gross_s = str(vals[COL_GROSS - 1] or "").strip()
        status_s = str(vals[COL_STATUS - 1] or "").strip() or STATUS_NEW

        try:
            gross = float(gross_s.replace(" ", "").replace(",", "."))
        except Exception:
            gross = 0.0

        client_id = self._find_or_create_client(comp_s)
        if gross <= 0:
            gross_api = 0.01
            status_s = STATUS_TODO
        else:
            gross_api = gross

        inv = self._req(
            "POST",
            "/api/v1/invoices",
            json_body={
                "client_id": client_id,
                "number": no_s,
                "total_gross": gross_api,
                "status": _bot_status_to_api_status(status_s),
            },
        )
        inv_id = int(inv["id"])

        m.setdefault("row_to_invoice", {})[str(row_no)] = inv_id
        m.setdefault("meta_by_invoice", {})[str(inv_id)] = {
            "company": comp_s,
            "date": str(vals[COL_DATE - 1] or ""),
            "type": str(vals[COL_TYPE - 1] or ""),
            "vat": str(vals[COL_VAT - 1] or ""),
            "net": str(vals[COL_NET - 1] or ""),
            "cat": str(vals[COL_CAT - 1] or ""),
            "user": str(vals[COL_USER - 1] or ""),
            "file": str(vals[COL_FILE - 1] or ""),
        }
        _save_map(uid, m)
        return row_no

    def update_cell(self, update: Update, row_no: int, col: int, value: Any):
        uid = update.effective_user.id
        m = _load_map(uid)
        inv_id = m.get("row_to_invoice", {}).get(str(int(row_no)))
        if not inv_id:
            return
        inv_id = int(inv_id)
        v = "" if value is None else str(value)

        if col == COL_GROSS:
            try:
                gross = float(v.replace(" ", "").replace(",", "."))
                if gross > 0:
                    self._req("PATCH", f"/api/v1/invoices/{inv_id}", json_body={"total_gross": gross})
            except Exception:
                pass
        elif col == COL_NO and v.strip():
            self._req("PATCH", f"/api/v1/invoices/{inv_id}", json_body={"number": v.strip()})
        elif col == COL_STATUS:
            self._req("PATCH", f"/api/v1/invoices/{inv_id}", json_body={"status": _bot_status_to_api_status(v)})

        meta = m.setdefault("meta_by_invoice", {}).setdefault(str(inv_id), {})
        if col == COL_DATE:
            meta["date"] = v
        if col == COL_COMP:
            meta["company"] = v
        if col == COL_TYPE:
            meta["type"] = v
        if col == COL_VAT:
            meta["vat"] = v
        if col == COL_NET:
            meta["net"] = v
        if col == COL_CAT:
            meta["cat"] = v
        if col == COL_USER:
            meta["user"] = v
        if col == COL_FILE:
            meta["file"] = v
        _save_map(uid, m)

    def get_all_values(self, update: Update):
        uid = update.effective_user.id
        m = _load_map(uid)
        out = [[""] * COL_FILE]
        for row_no in sorted((int(k) for k in m.get("row_to_invoice", {}).keys())):
            inv_id = int(m["row_to_invoice"][str(row_no)])
            inv = self._req("GET", f"/api/v1/invoices/{inv_id}")
            meta = m.get("meta_by_invoice", {}).get(str(inv_id), {})
            r = [""] * COL_FILE
            r[COL_DATE - 1] = meta.get("date", "")
            r[COL_NO - 1] = inv.get("number", "")
            r[COL_COMP - 1] = meta.get("company", "")
            r[COL_GROSS - 1] = str(inv.get("total_gross", ""))
            r[COL_TYPE - 1] = meta.get("type", "")
            r[COL_VAT - 1] = meta.get("vat", "")
            r[COL_NET - 1] = meta.get("net", "")
            r[COL_CAT - 1] = meta.get("cat", "")
            r[COL_USER - 1] = meta.get("user", "")
            r[COL_STATUS - 1] = _api_status_to_bot_status(inv.get("status", ""))
            r[COL_FILE - 1] = meta.get("file", "")
            out.append(r)
        return out

    def get_row(self, update: Update, row_no: int):
        allv = self.get_all_values(update)
        if row_no < 1 or row_no > len(allv):
            return []
        return allv[row_no - 1]
