# -*- coding: utf-8 -*-
import hashlib
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitz
from PIL import Image, ImageStat
from googleapiclient.http import MediaFileUpload
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from config import (
    COL_CAT,
    COL_COMP,
    COL_DATE,
    COL_FILE,
    COL_GROSS,
    COL_NET,
    COL_NO,
    COL_STATUS,
    COL_TYPE,
    COL_USER,
    COL_VAT,
    DEFAULT_CATEGORY,
    INV_DIR,
    MAX_OCR_PDF_PAGES,
    MAX_UPLOAD_BYTES,
    MAMA_FAVORITE_SHOPS,
    STATE,
    STATUS_NEW,
    STATUS_OK,
    STATUS_TODO,
    TYPE_NO_VAT,
    TYPE_VAT,
    is_allowed,
    is_mama,
    is_operator,
)
from domain.audit import begin_request, log_event
from domain.idempotency import find_duplicate, find_duplicate_content, register_content_hash, register_file_hash
from domain.invoices import missing_fields, today_ymd, user_label, vat_net_from_gross
from domain.metrics import record_metric
from keyboards import kb_invoice, kb_mama_company_suggestions, kb_mama_next_only, kb_mama_review_tiles, kb_mama_tiles, kb_page
from ocr_service import extract_fields, ocr_image, ocr_pdf, parse_amount, setup_tesseract
from sheets_service import drive, ensure_drive_root
from storage_router import append_row, get_all_values, next_row

_ALLOWED_DOC_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_int(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _normalize_field(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "")


def content_hash_from_fields(fields: dict, inv_type: str) -> str:
    payload = "|".join(
        [
            _normalize_field(fields.get("date", "")),
            _normalize_field(fields.get("no", "")),
            _normalize_field(fields.get("company", "")),
            _normalize_field(fields.get("gross", "")),
            _normalize_field(inv_type),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def month_now() -> str:
    return datetime.now().strftime("%Y-%m")


def menu_kb(update: Update):
    return kb_mama_tiles() if is_mama(update) else kb_page(1)


def _mama_top_companies(update: Update, limit: int = 8) -> list[str]:
    counts = Counter()
    allv = get_all_values(update)
    rows = allv[1:] if len(allv) > 1 else []
    for r in rows:
        if len(r) < COL_COMP:
            continue
        comp = (r[COL_COMP - 1] or "").strip()
        if len(comp) < 2:
            continue
        counts[comp] += 1
    return [name for name, _ in counts.most_common(limit)]


async def _mama_missing_amount_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    data = dict(getattr(ctx.job, "data", {}) or {})
    uid = int(data.get("uid", 0) or 0)
    row_no = int(data.get("row_no", 0) or 0)
    if uid <= 0 or row_no <= 0:
        return
    st = dict(STATE.get(uid, {}) or {})
    if str(st.get("row", "")) != str(row_no):
        return
    if st.get("mode") not in {"mama_wait_amount", "mama_set_price", "mama_ultra_amount", "mama_pick_company", "mama_set_company"}:
        return
    try:
        await ctx.bot.send_message(chat_id=uid, text="Wpisz tylko kwote, np. 123,45.", reply_markup=kb_mama_review_tiles())
    except Exception:
        return


def ensure_month_folder(parent_id: str, month: str) -> str:
    svc = drive()
    q = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{month}' and '{parent_id}' in parents and trashed=false"
    )
    res = svc.files().list(q=q, fields="files(id,name)", pageSize=10).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": month, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    created = svc.files().create(body=meta, fields="id").execute()
    return created["id"]


def upload_to_drive(filepath: Path, month: str) -> str:
    parent = ensure_drive_root()
    folder = ensure_month_folder(parent, month)
    media = MediaFileUpload(str(filepath), resumable=True)
    meta = {"name": filepath.name, "parents": [folder]}
    created = drive().files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    fid = created["id"]
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{fid}/view?usp=sharing"


def normalize_inv_type(v: str) -> str:
    s = (v or "").strip().lower().replace(" ", "").replace("-", "_")
    if s in ("vat", "fakturavat", "type_vat"):
        return TYPE_VAT
    if s in ("novat", "no_vat", "bezvat", "bez_vat", "type_no_vat"):
        return TYPE_NO_VAT
    return v



def _check_image_quality(local: Path) -> tuple[bool, str]:
    try:
        with Image.open(local) as img:
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            mean = float(stat.mean[0]) if stat.mean else 0.0
            std = float(stat.stddev[0]) if stat.stddev else 0.0

        reasons = []
        if mean < 55:
            reasons.append("ciemne")
        if std < 18:
            reasons.append("niewyrazne")

        try:
            import pytesseract

            osd = pytesseract.image_to_osd(str(local))
            m = re.search(r"Rotate:\s*(\d+)", osd)
            if m:
                angle = int(m.group(1)) % 360
                if angle in (90, 180, 270):
                    reasons.append("krzywe")
        except Exception:
            pass

        if reasons:
            return False, f"Zdjecie wyglada na {'/'.join(reasons)}. Zrob jeszcze raz - jasniej i prosto nad faktura."
        return True, ""
    except Exception:
        return True, ""


def _validate_saved_file(local: Path, is_pdf: bool) -> tuple[bool, str]:
    size = _safe_int(local.stat().st_size if local.exists() else 0)
    if size <= 0:
        return False, "Plik jest pusty albo nie zostal poprawnie pobrany."
    if size > MAX_UPLOAD_BYTES:
        return False, f"Plik jest za duzy (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)."

    if is_pdf:
        try:
            with fitz.open(local) as doc:
                pages = len(doc)
            if pages > MAX_OCR_PDF_PAGES:
                return False, f"PDF ma za duzo stron do OCR (max {MAX_OCR_PDF_PAGES})."
        except Exception:
            return False, "Nie udalo sie odczytac PDF."

    return True, ""


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await update.message.reply_text("Brak dostepu.", reply_markup=menu_kb(update))
    if not (is_operator(update) or is_mama(update)):
        return await update.message.reply_text("Tylko operator lub admin moze dodawac faktury.", reply_markup=menu_kb(update))

    uid = update.effective_user.id
    request_id = begin_request(f"f{uid}_{datetime.now():%Y%m%d%H%M%S}")
    st = STATE.get(uid, {})
    mode = st.get("mode", "")
    inv_type = normalize_inv_type(st.get("inv_type", ""))

    if inv_type in (TYPE_VAT, TYPE_NO_VAT) and mode != "add_wait_file":
        mode = "add_wait_file"
        STATE[uid] = {"mode": mode, "inv_type": inv_type}

    if mode != "add_wait_file" or inv_type not in (TYPE_VAT, TYPE_NO_VAT):
        if is_mama(update):
            return await update.message.reply_text(
                "Najpierw kliknij Dodaj fakture, potem Typ VAT albo Typ Bez VAT.",
                reply_markup=menu_kb(update),
            )
        return await update.message.reply_text(
            "Najpierw kliknij Dodaj fakture i wybierz typ (VAT/Bez VAT).",
            reply_markup=menu_kb(update),
        )

    setup_tesseract()
    is_pdf = False

    if update.message.document:
        doc = update.message.document
        mime = (getattr(doc, "mime_type", "") or "").lower()
        size = _safe_int(getattr(doc, "file_size", 0))

        if mime and mime not in _ALLOWED_DOC_MIME:
            return await update.message.reply_text("Nieobslugiwany typ pliku. Wyslij PDF/JPG/PNG.", reply_markup=menu_kb(update))
        if size > MAX_UPLOAD_BYTES:
            return await update.message.reply_text(
                f"Plik jest za duzy (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
                reply_markup=menu_kb(update),
            )

        tg = await context.bot.get_file(doc.file_id)
        name = doc.file_name or "faktura"
        local = INV_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{name}"
        await tg.download_to_drive(local)
        is_pdf = local.suffix.lower() == ".pdf" or mime == "application/pdf"
    else:
        photo = update.message.photo[-1]
        size = _safe_int(getattr(photo, "file_size", 0))
        if size > MAX_UPLOAD_BYTES:
            return await update.message.reply_text(
                f"Plik jest za duzy (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
                reply_markup=menu_kb(update),
            )
        tg = await context.bot.get_file(photo.file_id)
        local = INV_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_photo.jpg"
        await tg.download_to_drive(local)

    ok, reason = _validate_saved_file(local, is_pdf=is_pdf)
    if not ok:
        STATE.pop(uid, None)
        log_event("invoice_rejected_validation", user_id=uid, request_id=request_id, reason=reason)
        return await update.message.reply_text(reason, reply_markup=menu_kb(update))

    if not is_pdf:
        if is_mama(update):
            try:
                with local.open("rb") as img_f:
                    await update.message.reply_photo(photo=img_f, caption="Podglad zdjecia. Sprawdzam jakosc...")
            except Exception:
                pass

        q_ok, q_msg = _check_image_quality(local)
        if not q_ok:
            if is_mama(update):
                voice_mode = bool(st.get("voice_mode", False))
                STATE[uid] = {"mode": "add_wait_file", "inv_type": inv_type, "voice_mode": voice_mode, "last_step": "add:quality_failed"}
            else:
                STATE.pop(uid, None)
            log_event("invoice_rejected_quality", user_id=uid, request_id=request_id, reason=q_msg)
            return await update.message.reply_text(q_msg, reply_markup=menu_kb(update))

    t0 = time.perf_counter()
    try:
        text = ocr_pdf(local) if is_pdf else ocr_image(local)
        record_metric("ocr_process", ok=True, latency_ms=int((time.perf_counter() - t0) * 1000), source=("pdf" if is_pdf else "image"))
    except Exception as exc:
        record_metric("ocr_process", ok=False, latency_ms=int((time.perf_counter() - t0) * 1000), source=("pdf" if is_pdf else "image"))
        log_event("ocr_failed", user_id=uid, request_id=request_id, error=str(exc))
        STATE.pop(uid, None)
        return await update.message.reply_text("OCR nie powiodl sie. Sprobuj ponownie.", reply_markup=menu_kb(update))

    file_hash = sha256_file(local)
    dup = find_duplicate(file_hash)
    if dup:
        STATE.pop(uid, None)
        log_event("invoice_duplicate_rejected", user_id=uid, file_hash=file_hash, duplicate_of=dup, request_id=request_id)
        row_ref = dup.get("row_no", "?")
        return await update.message.reply_text(
            f"Duplikat pliku. Ta faktura byla juz dodana (wiersz {row_ref}).",
            reply_markup=menu_kb(update),
        )

    fields = extract_fields(text)
    content_hash = content_hash_from_fields(fields, inv_type)
    dup_content = find_duplicate_content(content_hash)
    if dup_content:
        STATE.pop(uid, None)
        log_event(
            "invoice_duplicate_content_rejected",
            user_id=uid,
            request_id=request_id,
            content_hash=content_hash,
            duplicate_of=dup_content,
        )
        row_ref = dup_content.get("row_no", "?")
        return await update.message.reply_text(
            f"Mozliwy duplikat po tresci OCR (wiersz {row_ref}). Sprawdz przed dodaniem.",
            reply_markup=menu_kb(update),
        )

    up_m = month_now()
    try:
        link = upload_to_drive(local, up_m)
    except Exception:
        link = local.name

    gross_f = parse_amount(fields.get("gross", ""))
    vat_s = ""
    net_s = ""
    if inv_type == TYPE_VAT and gross_f > 0:
        vat, net = vat_net_from_gross(gross_f)
        vat_s = f"{vat:.2f}"
        net_s = f"{net:.2f}"

    preview = [""] * COL_FILE
    preview[COL_DATE - 1] = fields.get("date") or today_ymd()
    preview[COL_NO - 1] = fields.get("no", "")
    preview[COL_COMP - 1] = fields.get("company", "")
    preview[COL_GROSS - 1] = fields.get("gross", "")
    preview[COL_TYPE - 1] = inv_type
    preview[COL_VAT - 1] = vat_s
    preview[COL_NET - 1] = net_s
    preview[COL_CAT - 1] = DEFAULT_CATEGORY
    preview[COL_USER - 1] = user_label(update)
    preview[COL_STATUS - 1] = STATUS_NEW
    preview[COL_FILE - 1] = link

    miss = missing_fields(preview)
    status = STATUS_OK if not miss else STATUS_TODO
    preview[COL_STATUS - 1] = status

    row_no = next_row(update)
    try:
        append_row(update, preview)
    except Exception as exc:
        log_event("invoice_queue_fallback", user_id=uid, request_id=request_id, error=str(exc))
        STATE.pop(uid, None)
        return await update.message.reply_text(
            "Backend chwilowo niedostepny. Zapis trafil do retry queue i zostanie ponowiony automatycznie.",
            reply_markup=menu_kb(update),
        )

    register_file_hash(file_hash, row_no=row_no, file_link=link, user_id=uid)
    register_content_hash(content_hash, row_no=row_no, file_link=link, user_id=uid)

    log_event(
        "invoice_added",
        user_id=uid,
        row_no=row_no,
        status=status,
        inv_type=inv_type,
        file_hash=file_hash,
        content_hash=content_hash,
        request_id=request_id,
    )

    if is_mama(update):
        month = (preview[COL_DATE - 1] or "")[:7]
        voice_mode = bool(st.get("voice_mode", False))
        large_font = bool(st.get("large_font", False))

        companies = list(MAMA_FAVORITE_SHOPS)
        ocr_company = (preview[COL_COMP - 1] or "").strip()
        if ocr_company:
            companies.append(ocr_company)
        companies.extend(_mama_top_companies(update, limit=8))
        uniq_companies = []
        for c in companies:
            if c and c not in uniq_companies:
                uniq_companies.append(c)

        if parse_amount(preview[COL_GROSS - 1] or "") <= 0:
            STATE[uid] = {
                "mode": "mama_pick_company",
                "row": str(row_no),
                "month": month,
                "voice_mode": voice_mode,
                "large_font": large_font,
                "last_step": f"add:no_amount:{row_no}",
            }
            if context.job_queue is not None:
                context.job_queue.run_once(
                    _mama_missing_amount_reminder,
                    when=120,
                    data={"uid": uid, "row_no": row_no},
                    name=f"mama_amount_reminder_{uid}_{row_no}",
                )
            await update.message.reply_text(
                "Dodane. Za chwile poprosze o kwote, jesli bedzie brak.",
                reply_markup=kb_mama_company_suggestions(uniq_companies, large_font=large_font),
            )
            return

        STATE[uid] = {
            "mode": "mama_pick_company",
            "row": str(row_no),
            "month": month,
            "next_row": str(row_no),
            "voice_mode": voice_mode,
            "large_font": large_font,
            "last_step": f"add:ok:{row_no}",
        }
        await update.message.reply_text(
            "Zapisane. Potwierdz firme albo zostaw OCR.",
            reply_markup=kb_mama_company_suggestions(uniq_companies, large_font=large_font),
        )
        return

    STATE.pop(uid, None)
    await update.message.reply_text(
        f"Dodano fakture | wiersz {row_no}\nTyp: {inv_type}\nStatus: {status}",
        reply_markup=kb_invoice(row_no, link),
    )


def register(app):
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))


