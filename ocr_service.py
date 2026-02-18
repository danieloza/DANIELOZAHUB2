# -*- coding: utf-8 -*-
import re
from pathlib import Path
import fitz
import pytesseract
from PIL import Image

from config import env, ENV_TESS

def setup_tesseract():
    t = env(ENV_TESS, "")
    if t:
        pytesseract.pytesseract.tesseract_cmd = t

def ocr_image(path: Path) -> str:
    try:
        return pytesseract.image_to_string(Image.open(path), lang="pol")
    except Exception:
        return pytesseract.image_to_string(Image.open(path))

def ocr_pdf(path: Path) -> str:
    doc = fitz.open(path)
    out = []
    for i in range(min(2, len(doc))):
        pix = doc.load_page(i).get_pixmap(dpi=220)
        img = path.with_suffix(f".p{i}.png")
        pix.save(img)
        out.append(ocr_image(img))
        try:
            img.unlink(missing_ok=True)
        except Exception:
            pass
    doc.close()
    return "\n".join(out)

def parse_amount(v: str) -> float:
    if not v:
        return 0.0
    s = str(v).replace("zł", "").replace("PLN", "")
    s = s.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def normalize_date(s: str) -> str:
    s = (s or "").strip()
    for f in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d.%m.%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""

def extract_fields(text: str) -> dict:
    t = text or ""

    m_date = re.search(r"\b(20\d{2}[-./]\d{2}[-./]\d{2})\b", t)
    inv_date = normalize_date(m_date.group(1)) if m_date else ""

    m_no = re.search(r"Faktura(?:\s+VAT)?\s*([A-Z0-9/.-]{5,})", t, re.IGNORECASE)
    inv_no = m_no.group(1).strip() if m_no else ""

    m_total = re.search(r"Razem\s+do\s+zapłaty[:\s]*([0-9\s.,]{3,})", t, re.IGNORECASE)
    if not m_total:
        m_total = re.search(r"Razem[:\s]*([0-9\s.,]{3,})\s*PLN", t, re.IGNORECASE)
    gross = parse_amount(m_total.group(1)) if m_total else 0.0

    m_seller = re.search(r"Sprzedawca[:\s]*\n?(.+)", t)
    seller = m_seller.group(1).strip()[:80] if m_seller else ""

    return {
        "date": inv_date,
        "no": inv_no,
        "company": seller,
        "gross": f"{gross:.2f}" if gross else ""
    }
