# -*- coding: utf-8 -*-
import difflib
import re
from datetime import datetime

# --- SMART CONFIG ---
CATEGORY_RULES = {
    "paliwo": ["orlen", "lotos", "bp", "shell", "circle", "stacja", "paliwa", "moya"],
    "biuro": ["papier", "druk", "xero", "toner", "artykuly biurowe", "ikea", "castorama"],
    "spozywcze": ["biedronka", "lidl", "auchan", "carrefour", "kaufland", "zabka", "dino", "delikatesy"],
    "uslugi": ["usluga", "serwis", "naprawa", "konsulting", "transport"],
    "media": ["orange", "t-mobile", "play", "plus", "netia", "upc", "vectra", "tauron", "pge", "enea", "energa"],
    "auto": ["auto", "moto", "czesci", "warsztat", "opony", "myjnia"],
}

def predict_category(company: str) -> str:
    """
    Inteligentnie zgaduje kategorie na podstawie nazwy firmy.
    """
    c = (company or "").lower()
    for cat, keywords in CATEGORY_RULES.items():
        if any(k in c for k in keywords):
            return cat
    return "inne"

def fuzzy_match_company(input_name: str, known_companies: list[str]) -> str | None:
    """
    Znajduje najbardziej podobna nazwe firmy w bazie (poprawia literowki).
    Np. 'Biedronk' -> 'Biedronka'.
    """
    if not input_name or not known_companies:
        return None
    
    # 1. Exact match (case insensitive)
    norm_input = input_name.strip().lower()
    for k in known_companies:
        if k.strip().lower() == norm_input:
            return k

    # 2. Fuzzy match
    matches = difflib.get_close_matches(input_name, known_companies, n=1, cutoff=0.7)
    if matches:
        return matches[0]
    
    return None

def is_soft_duplicate(new_row: dict, existing_rows: list[list]) -> tuple[bool, str]:
    """
    Sprawdza, czy faktura nie dubluje sie logicznie (ta sama firma, data i kwota),
    nawet jesli plik jest inny (inne zdjecie tego samego dokumentu).
    """
    # new_row expected keys: date, company, gross
    new_date = new_row.get("date", "")
    new_gross = new_row.get("gross", "")
    new_comp = (new_row.get("company", "") or "").lower().strip()[:10] # compare start of name

    if not new_date or not new_gross:
        return False, ""

    from config import COL_DATE, COL_GROSS, COL_COMP, COL_STATUS, STATUS_OK, STATUS_TODO

    for r in existing_rows:
        if len(r) < COL_GROSS: continue
        
        # Check amount (exact match)
        ex_gross = (r[COL_GROSS-1] or "").replace(",", ".").strip()
        if ex_gross != new_gross:
            continue
            
        # Check date (exact match)
        ex_date = (r[COL_DATE-1] or "").strip()
        if ex_date != new_date:
            continue

        # Check company (fuzzy start)
        ex_comp = (r[COL_COMP-1] or "").lower().strip()[:10]
        if new_comp in ex_comp or ex_comp in new_comp:
            row_no = existing_rows.index(r) + 1 # simplistic row finding
            return True, f"Znaleziono identyczna fakture (Data: {new_date}, Kwota: {new_gross}) juz w systemie."

    return False, ""

def sanitize_company_name(ocr_name: str) -> str:
    """
    Czysci smieci z nazwy firmy po OCR.
    """
    if not ocr_name: return ""
    s = ocr_name.strip()
    # Remove "Sprzedawca:" prefixes
    s = re.sub(r"^(sprzedawca|wystawca|dostawca)[:\s]*", "", s, flags=re.IGNORECASE)
    # Remove common Poland prefixes like "PL", "NIP" if at start
    s = re.sub(r"^(pl|nip)\s*[\d-]+\s*", "", s, flags=re.IGNORECASE)
    return s.strip()
