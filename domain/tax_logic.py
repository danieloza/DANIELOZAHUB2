# -*- coding: utf-8 -*-
from datetime import datetime
from domain.utils import parse_amount
from config import COL_TYPE, COL_VAT, COL_NET, TYPE_VAT

def analyze_tax_efficiency(rows: list[list]) -> dict:
    """
    Senior IT: Pro Tax Assistant.
    Calculates real tax savings and provides strategic financial advice.
    """
    total_gross = 0.0
    total_net = 0.0
    total_vat = 0.0
    
    vat_invoices_count = 0
    total_invoices_count = 0
    
    for r in rows:
        if len(r) < COL_TYPE: continue
        gross = parse_amount(r[3]) # COL_GROSS is 4
        if gross <= 0: continue
        
        total_gross += gross
        total_invoices_count += 1
        
        if (r[COL_TYPE-1] or "").upper() == TYPE_VAT:
            total_vat += parse_amount(r[5] if len(r) >= 6 else "0")
            total_net += parse_amount(r[6] if len(r) >= 7 else "0")
            vat_invoices_count += 1
        else:
            # For non-VAT, Net equals Gross
            total_net += gross

    # --- Calculations ---
    # Assuming standard 19% PIT (Linear) or 12% (Scale) - let's use 19% for business demo
    pit_rate = 0.19 
    pit_savings = total_net * pit_rate
    total_savings = pit_savings + total_vat
    
    efficiency = (vat_invoices_count / total_invoices_count * 100) if total_invoices_count > 0 else 0
    
    # --- Deadlines ---
    now = datetime.now()
    next_month = now.month + 1 if now.month < 12 else 1
    deadline_year = now.year if now.month < 12 else now.year + 1
    deadline_date = f"25.{next_month:02d}.{deadline_year}"

    # --- Message Construction (HTML) ---
    msg = (
        f"💰 <b>STRATEGIA PODATKOWA salondanex.pl</b> 💰\n\n"
        f"📊 <b>Statystyki:</b>\n"
        f"• Suma Brutto: <b>{total_gross:.2f} PLN</b>\n"
        f"• Odliczony VAT: <b>{total_vat:.2f} PLN</b>\n"
        f"• Oszczędność na PIT: <b>{pit_savings:.2f} PLN</b>\n\n"
        f"🔥 <b>RAZEM ZOSTAJE W KIESZENI: {total_savings:.2f} PLN</b>\n\n"
        f"📈 <b>Efektywność: {efficiency:.1f}%</b>\n"
    )
    
    if efficiency < 70:
        msg += (
            f"⚠️ <b>ALARM:</b> Masz tylko {vat_invoices_count} faktur VAT na {total_invoices_count} zakupów. "
            f"Tracisz możliwość odliczenia VAT z pozostałych transakcji!\n\n"
        )
    else:
        msg += "✅ <b>Świetnie!</b> Optymalnie dobierasz dokumenty kosztowe.\n\n"

    msg += (
        f"📅 <b>NAJBLIŻSZE TERMINY:</b>\n"
        f"• Podatek VAT/PIT: <b>{deadline_date}</b>\n"
        f"• Pamiętaj o wysłaniu paczki ZIP przed 25-tym!"
    )
        
    return {
        "vat_total": total_vat,
        "efficiency": efficiency,
        "savings": total_savings,
        "msg": msg
    }
