# -*- coding: utf-8 -*-
import re
from pathlib import Path
import fitz
import pytesseract
from PIL import Image

from config import env, ENV_TESS

from domain.utils import parse_amount, normalize_text

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
    # OCR max 3 pages for invoices
    for i in range(min(3, len(doc))):
        pix = doc.load_page(i).get_pixmap(dpi=250) # Higher DPI for better OCR
        img = path.with_suffix(f".p{i}.png")
        pix.save(img)
        out.append(ocr_image(img))
        try:
            img.unlink(missing_ok=True)
        except Exception:
            pass
    doc.close()
    return "\n\n".join(out)

def normalize_date(s: str) -> str:
    s = (s or "").strip()
    patterns = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y")
    for f in patterns:
        try:
            from datetime import datetime
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""

async def ai_refine_ocr(text: str) -> dict | None:
    """
    Senior IT: RAG-Augmented Extraction.
    Uses context from the LangChain project to help AI understand the document.
    """
    from config import env, ENV_OPENAI_API_KEY
    from domain.rag_bridge import get_smart_context_for_invoice
    
    api_key = env(ENV_OPENAI_API_KEY, "")
    if not api_key: return None
    
    # 1. Retrieve Context using RAG Bridge (Now Async)
    rag_context = await get_smart_context_for_invoice(text)
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        system_prompt = (
            "You are a professional accounting assistant. "
            "Extract invoice data from the OCR text into JSON. "
            "Fields: date (YYYY-MM-DD), no (invoice number), company (seller name), gross (total amount as number). "
        )
        
        user_content = f"OCR TEXT:\n{text[:2000]}"
        if rag_context:
            user_content = f"CONTEXT FROM KNOWLEDGE BASE:\n{rag_context}\n\n" + user_content
            system_prompt += "Use the provided CONTEXT to fix any OCR errors (like misread company names or digits)."

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        import json
        return json.loads(response.choices[0].message.content)
    except:
        return None

async def extract_fields(text: str) -> dict:
    t = text or ""
    
    # Try Standard Regex first
    res = _extract_fields_regex(t)
    
    # Senior IT: If Regex missed gross or company, and AI is available, use it!
    if not res.get("gross") or not res.get("company"):
        ai_res = await ai_refine_ocr(t)
        if ai_res:
            # Merge: Keep what regex got, fill gaps with AI
            for k in ("date", "no", "company", "gross"):
                if not res.get(k) and ai_res.get(k):
                    res[k] = str(ai_res[k])
    
    return res

def _extract_fields_regex(text: str) -> dict:
    t = text or ""
    
    # --- DATE ---
    # Look for common date patterns YYYY-MM-DD or DD-MM-YYYY near keywords
    m_date = re.search(r"(?:data|dnia|wystawienia|sprzedaży).*?(\d{4}[-./]\d{2}[-./]\d{2}|\d{2}[-./]\d{2}[-./]\d{4})", t, re.IGNORECASE | re.DOTALL)
    if not m_date:
         m_date = re.search(r"\b(\d{4}[-./]\d{2}[-./]\d{2})\b", t)
    
    inv_date = normalize_date(m_date.group(1)) if m_date else ""

    # --- INVOICE NO ---
    # Look for 'Faktura nr', 'FV nr', etc.
    m_no = re.search(r"(?:Faktura|FV|Nr)\s*(?:VAT|nr)?\s*[:.]?\s*([A-Z0-9/.-]{4,})", t, re.IGNORECASE)
    inv_no = m_no.group(1).strip() if m_no else ""
    # Cleanup trailing dots/punctuation from invoice number
    inv_no = re.sub(r"[.,]$", "", inv_no)

    # --- AMOUNT ---
    # Heuristics: look for 'Razem', 'Do zapłaty', 'Suma', 'Total'
    # We try to find the largest amount near these keywords.
    candidates = []
    
    amount_patterns = [
        r"(?:do\s+zapłaty|razem|suma|total|kwota\s+do\s+zapłaty)\s*:?\s*([0-9\s.,]+(?:PLN|zł|zlt)?)",
        r"([0-9\s.,]+)\s*(?:PLN|zł|zlt)",  # Amount followed by currency
    ]
    
    for pat in amount_patterns:
        for match in re.finditer(pat, t, re.IGNORECASE):
            val = parse_amount(match.group(1))
            if val > 0 and val < 1000000: # Sanity check < 1M
                candidates.append(val)
    
    # If candidates found, pick the largest (usually the Total Gross)
    gross = max(candidates) if candidates else 0.0

    # --- SELLER ---
    # Look for 'Sprzedawca', 'Wystawca'
    m_seller = re.search(r"(?:Sprzedawca|Wystawca|Dostawca)[:\s]*\n?(.+)", t, re.IGNORECASE)
    seller = normalize_text(m_seller.group(1)[:80]) if m_seller else ""

    return {
        "date": inv_date,
        "no": inv_no,
        "company": seller,
        "gross": f"{gross:.2f}" if gross else ""
    }
