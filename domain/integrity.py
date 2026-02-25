# -*- coding: utf-8 -*-
from datetime import datetime
from config import COL_DATE, COL_GROSS, COL_NET, COL_VAT, COL_TYPE, COL_NO, TYPE_VAT
from ocr_service import parse_amount

def check_business_integrity(rows: list[list]) -> list[str]:
    """
    Performs a deep scan of the invoice registry to find logical inconsistencies.
    Returns a list of warnings.
    """
    warnings = []
    
    # 1. Check for Duplicate Invoice Numbers (across the whole history)
    # We map "InvoiceNo" -> [row_ids]
    seen_numbers = {}
    
    # 2. Check for Math Errors (Gross vs Net+VAT)
    # 3. Check for Future Dates
    
    today = datetime.now().date()
    
    for idx, r in enumerate(rows, start=2):
        if len(r) < COL_TYPE: continue
        
        # --- Duplicates ---
        inv_no = (r[COL_NO-1] or "").strip().upper()
        # Ignore extremely short/generic numbers to avoid false positives on "1", "FV", etc.
        if len(inv_no) > 3:
            if inv_no in seen_numbers:
                prev_row = seen_numbers[inv_no]
                warnings.append(f"⚠️ Duplikat numeru '{inv_no}': wiersz {idx} i {prev_row}.")
            else:
                seen_numbers[inv_no] = idx
                
        # --- Math Logic ---
        gross = parse_amount(r[COL_GROSS-1])
        net = parse_amount(r[COL_NET-1] if len(r) >= COL_NET else "")
        vat = parse_amount(r[COL_VAT-1] if len(r) >= COL_VAT else "")
        inv_type = (r[COL_TYPE-1] or "").upper()
        
        if inv_type == TYPE_VAT and gross > 0 and net > 0:
            # Check if Net + Vat ~= Gross (allow 0.05 tolerance)
            if abs(gross - (net + vat)) > 0.05:
                warnings.append(f"🧮 Blad matematyczny (wiersz {idx}): {net} + {vat} != {gross}")
                
        # --- Future Dates ---
        date_str = (r[COL_DATE-1] or "").strip()
        if date_str:
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                if dt > today:
                    warnings.append(f"📅 Data z przyszlosci (wiersz {idx}): {date_str}")
            except:
                pass # Invalid date format handled elsewhere

    return warnings

def get_system_health_checklist() -> list[tuple[str, bool, str]]:
    """
    Returns a checklist of system health status.
    Format: (Name, IsOK, Details)
    """
    import os
    from pathlib import Path
    from config import INV_DIR, BACKUPS_DIR, ENV_SHEET_ID
    
    checks = []
    
    # 1. Directories
    checks.append(("Folder Faktur", INV_DIR.exists(), str(INV_DIR)))
    checks.append(("Folder Backup", BACKUPS_DIR.exists(), str(BACKUPS_DIR)))
    
    # 2. Config
    checks.append(("Google Sheet ID", bool(ENV_SHEET_ID), "Skonfigurowano"))
    
    # 3. Disk Space (Simple check if writable)
    try:
        test_file = INV_DIR / ".write_test"
        test_file.touch()
        test_file.unlink()
        checks.append(("Zapis na dysk", True, "OK"))
    except Exception as e:
        checks.append(("Zapis na dysk", False, str(e)))
        
    return checks
