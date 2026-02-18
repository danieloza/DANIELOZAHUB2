# -*- coding: utf-8 -*-
import csv
import io
import zipfile
from datetime import datetime
from pathlib import Path

from config import COL_DATE, COL_GROSS, COL_STATUS, STATUS_SENT
from domain.invoices import missing_fields
from ocr_service import parse_amount
from sheets_service import get_all_values, update_cell


def _rows_for_month(month: str):
    allv = get_all_values()
    header = allv[0] if allv else []
    rows = allv[1:] if len(allv) > 1 else []
    out = []
    for idx, r in enumerate(rows, start=2):
        r = r + [""] * (max(COL_GROSS, COL_STATUS, COL_DATE) - len(r))
        if (r[COL_DATE - 1] or "").startswith(month):
            out.append((idx, r))
    return header, out


def build_month_zip_bytes(month: str):
    header, month_rows = _rows_for_month(month)

    csv_buf = io.StringIO()
    w = csv.writer(csv_buf)
    if header:
        w.writerow(header)
    for _, r in month_rows:
        w.writerow(r)

    csv_bytes = csv_buf.getvalue().encode("utf-8")

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"export_{month}.csv", csv_bytes)

    zip_name = f"danex_export_{month}.zip"
    return zip_buf.getvalue(), zip_name


def build_backup_zip(save_local: bool = False, month: str | None = None, mark_sent: bool = False):
    if month is None:
        month = datetime.now().strftime("%Y-%m")

    zip_bytes, zip_name = build_month_zip_bytes(month)

    if mark_sent:
        _, month_rows = _rows_for_month(month)
        for row_no, r in month_rows:
            gross = parse_amount(r[COL_GROSS - 1] or "")
            miss = missing_fields(r)
            if gross > 0 and not miss:
                update_cell(row_no, COL_STATUS, STATUS_SENT)

    if save_local:
        backups = Path(__file__).resolve().parent.parent / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        out_path = backups / zip_name
        out_path.write_bytes(zip_bytes)

    return zip_bytes, zip_name


def restore_test_zip(zip_bytes: bytes) -> dict:
    info = {"ok": False, "csv_files": 0, "rows": 0, "error": ""}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            info["csv_files"] = len(csv_names)
            if not csv_names:
                info["error"] = "No CSV inside backup zip"
                return info
            total_rows = 0
            for name in csv_names:
                payload = zf.read(name).decode("utf-8", errors="ignore")
                reader = csv.reader(io.StringIO(payload))
                for _ in reader:
                    total_rows += 1
            info["rows"] = total_rows
            info["ok"] = total_rows > 0
            if not info["ok"]:
                info["error"] = "CSV parsed but empty"
            return info
    except Exception as exc:
        info["error"] = str(exc)
        return info


def restore_test_latest_backup() -> dict:
    backups = Path(__file__).resolve().parent.parent / "backups"
    files = sorted(backups.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"ok": False, "error": "No backup zip files found", "path": ""}
    latest = files[0]
    res = restore_test_zip(latest.read_bytes())
    res["path"] = str(latest)
    return res
