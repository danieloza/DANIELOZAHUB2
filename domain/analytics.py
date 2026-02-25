# -*- coding: utf-8 -*-
from statistics import mean, stdev

def analyze_expense_anomaly(current_amount: float, vendor: str, history_rows: list[list]) -> tuple[bool, str]:
    """
    Analyzes if the current expense is significantly higher than usual for this vendor.
    Returns (is_anomaly, message).
    """
    from config import COL_COMP, COL_GROSS
    from domain.utils import parse_amount
    
    vendor_amounts = []
    normalized_vendor = vendor.lower().strip()
    
    for r in history_rows:
        if len(r) < COL_GROSS: continue
        row_comp = (r[COL_COMP-1] or "").lower().strip()
        
        # Simple fuzzy contains match
        if normalized_vendor in row_comp or row_comp in normalized_vendor:
            val = parse_amount(r[COL_GROSS-1])
            if val > 0:
                vendor_amounts.append(val)
    
    if len(vendor_amounts) < 3:
        return False, "" # Not enough data
        
    avg = mean(vendor_amounts)
    
    # Threshold: 50% higher than average or > 2 standard deviations
    if current_amount > avg * 1.5:
        percent_diff = int(((current_amount - avg) / avg) * 100)
        return True, f"💸 *Wykryto anomalię:* Ta faktura jest o *{percent_diff}%* droższa niż średnia dla {vendor} ({avg:.2f} zł)."
        
    return False, ""
