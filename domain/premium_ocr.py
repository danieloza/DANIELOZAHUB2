# -*- coding: utf-8 -*-
import re
from domain.utils import parse_amount

def extract_currency(text: str) -> str:
    """Detects currency in text."""
    t = text.upper()
    if "EUR" in t or "€" in t: return "EUR"
    if "USD" in t or "$" in t: return "USD"
    if "GBP" in t or "£" in t: return "GBP"
    return "PLN"

def extract_nip(text: str) -> str:
    """Finds NIP number."""
    m = re.search(r"(?:NIP|VAT\s*ID)[:\s]*([0-9-]{10,13})", text, re.IGNORECASE)
    if m:
        return "".join(filter(str.isdigit, m.group(1)))
    return ""
