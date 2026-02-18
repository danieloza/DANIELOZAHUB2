# backup.py
# -*- coding: utf-8 -*-

import io
import csv
import zipfile
from datetime import datetime
from typing import List


def _now():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_backup_zip(
    month: str,
    header: List[str],
    rows: List[List[str]],
) -> tuple[bytes, str]:
    """
    Buduje paczkę ZIP do księgowej (CSV + info).
    Zwraca: (zip_bytes, filename)
    """

    stamp = _now()
    zip_name = f"danex_backup_{month}_{stamp}.zip"

    # CSV
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)

    csv_bytes = csv_buf.getvalue().encode("utf-8-sig")

    # INFO
    info_txt = (
        f"Danex Faktury – backup\n"
        f"Miesiąc: {month}\n"
        f"Ilość faktur: {len(rows)}\n"
        f"Utworzono: {datetime.now().isoformat(timespec='seconds')}\n"
    ).encode("utf-8")

    # ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{month}/faktury_{month}.csv", csv_bytes)
        z.writestr(f"{month}/INFO.txt", info_txt)

    return buf.getvalue(), zip_name
