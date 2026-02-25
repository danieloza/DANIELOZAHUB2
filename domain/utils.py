# -*- coding: utf-8 -*-
import re

def parse_amount(txt: str) -> float:
    """
    Robust amount parser that handles:
    - 1 234,56 (spaces, comma)
    - 1.234,56 (dot thousands, comma decimal)
    - 1,234.56 (comma thousands, dot decimal)
    - currency symbols (PLN, zł, etc.)
    - mixed unicode spaces (NBSP, etc.)
    """
    if txt is None:
        return 0.0

    s = str(txt).strip().lower()
    if not s:
        return 0.0

    # Remove common currency/unit tokens and weird characters
    replacements = {
        "pln": "", "zł": "", "zl": "", "z?": "", "zlt": "",
        "brutto": "", "netto": "", "suma": "", "razem": "",
        " ": "", "\u00a0": "", "\t": "", "\n": ""
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    
    # Remove any non-numeric except , . -
    s = re.sub(r"[^0-9,.-]", "", s)
    if not s:
        return 0.0

    # Handle mixed separators logic
    # Heuristic: if both exist, the rightmost one is likely the decimal separator
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # Format 1.234,56 -> remove dots, replace comma with dot
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            # Format 1,234.56 -> remove commas
            s = s.replace(",", "")
    else:
        # Only one separator type present
        # If it's a comma, treat as decimal separator (standard PL/EU)
        s = s.replace(",", ".")

    try:
        return float(s)
    except ValueError:
        # Fallback: find the first sequence that looks like a float
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else 0.0

def normalize_text(text: str) -> str:
    """Sanitizes text from mojibake and excessive whitespace."""
    if not text:
        return ""
    
    repl = {
        "dost??pu": "dostępu",
        "faktur??": "fakturę",
        "miesi??ca": "miesiąca",
        "miesi??c": "miesiąc",
        "Miesi??ce": "Miesiące",
        "Podgl??d": "Podgląd",
        "Wys??ane": "Wysłane",
        "Wys??ana": "Wysłana",
        "Wys??any": "Wysłany",
        "Wy??lij": "Wyślij",
        "zdj??cie": "zdjęcie",
        "ksi??gowej": "księgowej",
        "Brak dostepu": "Brak dostępu",
        "Brak dost??pu": "Brak dostępu",
    }
    
    out = str(text)
    for bad, good in repl.items():
        out = out.replace(bad, good)
        
    return re.sub(r"\s+", " ", out).strip()

def escape_markdown(text: str) -> str:
    """Escapes special characters for Telegram Markdown (legacy)."""
    if not text: return ""
    # In legacy Markdown, we mainly worry about _, *, `
    # and [ if it looks like a link.
    # We escape by prefixing with \ or just replacing if it's simpler.
    # For now, let's just make it safe for bold/italics.
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
