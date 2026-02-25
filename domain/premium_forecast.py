# -*- coding: utf-8 -*-
import logging
from statistics import mean
from datetime import datetime
from domain.utils import parse_amount
from config import COL_DATE, COL_GROSS

def predict_next_month_spending(history_rows: list[list]) -> dict:
    """
    Senior IT: Cashflow Forecasting.
    Analyzes historical data to predict next month's liability.
    """
    monthly_totals = {}
    
    for r in history_rows:
        if len(r) < COL_GROSS: continue
        date_str = (r[COL_DATE-1] or "").strip()
        if len(date_str) < 7: continue
        
        month = date_str[:7]
        amount = parse_amount(r[COL_GROSS-1])
        if amount > 0:
            monthly_totals[month] = monthly_totals.get(month, 0.0) + amount
            
    # Sort months
    sorted_months = sorted(monthly_totals.keys())
    if len(sorted_months) < 2:
        return {"prediction": 0.0, "confidence": "low", "msg": "Za mało danych do prognozy."}
        
    values = [monthly_totals[m] for m in sorted_months]
    avg_spend = mean(values)
    
    # Calculate simple trend (last month vs average)
    last_val = values[-1]
    trend = (last_val - avg_spend) / avg_spend if avg_spend > 0 else 0
    
    prediction = last_val * (1 + trend)
    
    return {
        "prediction": round(prediction, 2),
        "avg": round(avg_spend, 2),
        "confidence": "medium" if len(values) >= 3 else "low",
        "msg": f"Na podstawie trendów ({int(trend*100)}%), przewidywane wydatki na przyszły miesiąc to ok. {prediction:.2f} PLN."
    }
