# -*- coding: utf-8 -*-
from config import COL_DATE, COL_NO, COL_COMP, COL_GROSS

def preview_fields_map(row: list) -> dict:
    return {
        "date": row[COL_DATE-1],
        "no": row[COL_NO-1],
        "company": row[COL_COMP-1],
        "gross": row[COL_GROSS-1]
    }
