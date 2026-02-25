# -*- coding: utf-8 -*-
import re
from datetime import datetime
from collections import Counter
from config import COL_DATE, COL_GROSS, COL_CAT, COL_COMP
from domain.utils import parse_amount

def parse_month_arg(args: list[str]) -> str:
    if not args:
        return datetime.now().strftime("%Y-%m")
    m = (args[0] or "").strip()
    if re.match(r"^\d{4}-\d{2}$", m):
        return m
    return datetime.now().strftime("%Y-%m")

def get_monthly_insights(rows: list[list], month: str) -> dict:
    """
    Analyzes rows for a specific month and returns 'gems' of information.
    """
    total_gross = 0.0
    cat_summary = Counter()
    top_vendors = Counter()
    biggest_expense = {"amount": 0.0, "company": "-"}
    
    count = 0
    for r in rows:
        if len(r) < COL_CAT: continue
        r_date = (r[COL_DATE-1] or "").strip()
        if not r_date.startswith(month): continue
        
        gross = parse_amount(r[COL_GROSS-1])
        company = (r[COL_COMP-1] or "Nieznana").strip()
        category = (r[COL_CAT-1] or "inne").strip()
        
        total_gross += gross
        cat_summary[category] += gross
        top_vendors[company] += 1
        count += 1
        
        if gross > biggest_expense["amount"]:
            biggest_expense = {"amount": gross, "company": company}

    if count == 0:
        return None

    return {
        "total": total_gross,
        "count": count,
        "categories": cat_summary.most_common(3),
        "top_vendor": top_vendors.most_common(1)[0] if top_vendors else ("-", 0),
        "biggest": biggest_expense
    }

