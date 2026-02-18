# -*- coding: utf-8 -*-
from datetime import datetime
from config import (
    COL_DATE, COL_NO, COL_GROSS, COL_STATUS, COL_TYPE,
    STATUS_TODO, STATUS_OK, TYPE_VAT
)
from ocr_service import parse_amount

def today_ymd() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def user_label(update) -> str:
    u = update.effective_user
    return u.username or u.full_name or str(u.id)

def missing_fields(row: list) -> list[str]:
    miss = []

    # data – jeśli u Ciebie jest wymagana, zostaw
    if not (row[COL_DATE - 1] or "").strip():
        miss.append("data")

    # ❌ numer NIE jest wymagany – usunięty warunek

    # ✅ kwota JEST wymagana
    gross = row[COL_GROSS - 1] if len(row) >= COL_GROSS else ""
    if parse_amount(gross) <= 0:
        miss.append("kwota")

    return miss
    

def auto_status(row: list) -> str:
    miss = missing_fields(row)
    return STATUS_OK if not miss else STATUS_TODO

def vat_net_from_gross(gross: float) -> tuple[float, float]:
    # VAT 23% w brutto: vat = brutto * 0.23/1.23
    vat = round(gross * 0.23 / 1.23, 2)
    net = round(gross - vat, 2)
    return vat, net

def should_recalc(row: list, smart: bool = True) -> bool:
    # smart: tylko gdy VAT i gdy vat/netto puste lub 0
    if len(row) < COL_TYPE:
        return False
    if (row[COL_TYPE-1] or "").strip() != TYPE_VAT:
        return False
    if len(row) < 7:
        return True
    # vat col = 6, net col = 7
    vat_v = parse_amount(row[5] if len(row) >= 6 else "")
    net_v = parse_amount(row[6] if len(row) >= 7 else "")
    if not smart:
        return True
    return (vat_v <= 0) or (net_v <= 0)
