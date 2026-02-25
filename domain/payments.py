# -*- coding: utf-8 -*-
import re

def extract_iban(text: str) -> str:
    """
    Extracts Polish IBAN or standard account number from OCR text.
    """
    # Remove spaces to make regex easier
    clean_text = text.replace(" ", "").replace("-", "")
    
    # Look for PL... (28 digits) or just 26 digits
    # PL check
    m_pl = re.search(r"PL[0-9]{26}", clean_text, re.IGNORECASE)
    if m_pl:
        return m_pl.group(0).upper()
        
    # Standard 26 digit check (often OCR misses PL)
    m_std = re.search(r"[0-9]{26}", clean_text)
    if m_std:
        return "PL" + m_std.group(0)
        
    return ""

def generate_payment_qr_url(iban: str, amount: float, title: str, receiver: str) -> str:
    """
    Generates a URL to a QR code image that allows 'Scan & Pay' in banking apps.
    Uses a standard QR generator API for the demo.
    Format: |PL|IBAN|Amount|Name|Title||
    """
    if not iban: return ""
    
    # Standard Polish Payment QR Format string
    # We use a simplified version compatible with most apps
    # Format: |PL|IBAN|AM|NAME|TITLE||
    # Note: Real banking apps use a specific binary format, but text-based formatting works for many scanners.
    # For demo visualization, we simply encode the data.
    
    amount_str = f"{int(amount*100)}" # Amount in grosze
    qr_data = f"|PL|{iban}|{amount_str}|{receiver}|{title}||"
    
    # Using Google Chart API (reliable, free) for visualization
    import urllib.parse
    encoded_data = urllib.parse.quote(qr_data)
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded_data}"
