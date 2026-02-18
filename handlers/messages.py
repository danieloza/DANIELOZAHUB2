# -*- coding: utf-8 -*-
import asyncio
import time
from collections import Counter
from datetime import datetime
from statistics import median

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from config import (
    COL_COMP,
    COL_DATE,
    COL_FILE,
    COL_GROSS,
    COL_NET,
    COL_NO,
    COL_STATUS,
    COL_TYPE,
    COL_VAT,
    ENV_OPENAI_API_KEY,
    INV_DIR,
    MAMA_FAVORITE_SHOPS,
    MAMA_VOICE_ENABLED,
    STATE,
    STATUS_OK,
    STATUS_TODO,
    TYPE_NO_VAT,
    TYPE_VAT,
    admin_ids,
    env,
    is_allowed,
    is_mama,
    is_operator,
)
from domain.audit import log_event
from domain.invoices import missing_fields
from handlers.callbacks import build_month_zip, today_ym
from keyboards import (
    kb_mama_company_suggestions,
    kb_mama_daily_one_button,
    kb_mama_next_only,
    kb_mama_pick_type,
    kb_mama_review_tiles,
    kb_mama_sos_safe,
    kb_mama_tiles,
    kb_mama_ultra_amount,
    kb_invoice,
    kb_page,
)
from ocr_service import parse_amount
from storage_router import get_all_values, get_row, update_cell


def _rows_for_month(update: Update, month: str):
    allv = get_all_values(update)
    rows = allv[1:] if len(allv) > 1 else []
    out = []
    for idx, r in enumerate(rows, start=2):
        if len(r) >= COL_DATE and (r[COL_DATE - 1] or "").startswith(month):
            out.append((idx, r))
    return out


def _calc_net_vat_from_type(type_raw: str, gross: float):
    t = (type_raw or "").strip().lower().replace("%", "")
    no_vat_tokens = ("zw", "np", "nie podlega", "bez vat", "no vat", "vat0")
    if any(tok in t for tok in no_vat_tokens) or t.strip() == "0":
        return gross, 0.0

    rate = None
    for cand in ("23", "8", "5"):
        if cand in t:
            rate = int(cand)
            break
    if rate is None and "vat" in t:
        rate = 23
    if rate is None or rate <= 0:
        return gross, 0.0

    net = gross / (1.0 + rate / 100.0)
    vat = gross - net
    return net, vat


def _find_next_missing_amount(update: Update, month: str):
    for row_no, r in _rows_for_month(update, month):
        r = r + [""] * (max(COL_GROSS, COL_STATUS, COL_FILE) - len(r))
        st = (r[COL_STATUS - 1] or "").strip()
        gross = parse_amount(r[COL_GROSS - 1] or "")
        if st == STATUS_TODO and gross <= 0:
            return row_no
    return None


def _find_next_todo(update: Update, month: str):
    for row_no, r in _rows_for_month(update, month):
        r = r + [""] * (max(COL_GROSS, COL_STATUS, COL_FILE) - len(r))
        if (r[COL_STATUS - 1] or "").strip() == STATUS_TODO:
            return row_no
    return None


def _month_from_row(update: Update, row_no: int) -> str:
    r = get_row(update, row_no)
    d = (r[COL_DATE - 1] if len(r) >= COL_DATE else "") or ""
    return d[:7] if len(d) >= 7 else ""


def _pick_next_row(update: Update, month: str):
    nxt = _find_next_missing_amount(update, month) if month else None
    if not nxt and month:
        nxt = _find_next_todo(update, month)
    return nxt

_POLISH_MONTH_NAMES = {
    1: "stycznia",
    2: "lutego",
    3: "marca",
    4: "kwietnia",
    5: "maja",
    6: "czerwca",
    7: "lipca",
    8: "sierpnia",
    9: "wrzesnia",
    10: "pazdziernika",
    11: "listopada",
    12: "grudnia",
}

MAMA_UNDO = {}
MAMA_PROGRESS = {}


def _mama_large_font(state: dict | None) -> bool:
    return bool((state or {}).get("large_font", False))


def _mama_tiles_for(uid: int):
    st = dict(STATE.get(uid, {}) or {})
    return kb_mama_tiles(large_font=_mama_large_font(st))


def _mama_review_tiles_for(uid: int):
    st = dict(STATE.get(uid, {}) or {})
    return kb_mama_review_tiles(large_font=_mama_large_font(st))


def _mama_type_tiles_for(uid: int):
    st = dict(STATE.get(uid, {}) or {})
    return kb_mama_pick_type(large_font=_mama_large_font(st))


def _set_mama_progress(uid: int, **kwargs) -> dict:
    cur = dict(MAMA_PROGRESS.get(uid, {}) or {})
    cur.update(kwargs)
    MAMA_PROGRESS[uid] = cur
    return cur


def _register_mama_amount_failure(uid: int) -> int:
    cur = _set_mama_progress(uid, wrong_amount_streak=int((MAMA_PROGRESS.get(uid, {}) or {}).get("wrong_amount_streak", 0)) + 1)
    return int(cur.get("wrong_amount_streak", 0))


def _reset_mama_amount_failure(uid: int) -> None:
    _set_mama_progress(uid, wrong_amount_streak=0)


def _today_mama_ok_count(update: Update, month: str) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    cnt = 0
    try:
        rows = _rows_for_month(update, month)
    except Exception:
        return 0
    for _, r in rows:
        r = r + [""] * (max(COL_DATE, COL_STATUS) - len(r))
        if (r[COL_DATE - 1] or "").strip()[:10] == today and (r[COL_STATUS - 1] or "").strip() == STATUS_OK:
            cnt += 1
    return cnt


def _mama_company_suggestions(update: Update, limit: int = 8) -> list[str]:
    hist = Counter()
    allv = get_all_values(update)
    rows = allv[1:] if len(allv) > 1 else []
    for r in rows:
        if len(r) < COL_COMP:
            continue
        c = (r[COL_COMP - 1] or "").strip()
        if len(c) < 2:
            continue
        hist[c] += 1
    popular = [name for name, _ in hist.most_common(max(0, limit - len(MAMA_FAVORITE_SHOPS)))]
    out = []
    for v in list(MAMA_FAVORITE_SHOPS) + popular:
        if v not in out:
            out.append(v)
    return out[:limit]


def _mama_company_keyboard(update: Update, uid: int):
    st = dict(STATE.get(uid, {}) or {})
    return kb_mama_company_suggestions(_mama_company_suggestions(update), large_font=_mama_large_font(st))


def _mama_active_mode(mode: str) -> bool:
    return mode in {
        "mama_review",
        "mama_wait_amount",
        "mama_set_price",
        "mama_ultra_amount",
        "mama_pick_company",
        "mama_set_company",
        "mama_confirm_amount",
        "add_wait_type",
        "add_wait_file",
    }


def _mama_remaining_todo(update: Update, month: str) -> int:
    cnt = 0
    for _, r in _rows_for_month(update, month):
        r = r + [""] * (max(COL_GROSS, COL_STATUS) - len(r))
        st = (r[COL_STATUS - 1] or "").strip()
        gross = parse_amount(r[COL_GROSS - 1] or "")
        if st == STATUS_TODO or gross <= 0:
            cnt += 1
    return cnt


def _mama_next_step_hint(update: Update, row_no: int) -> str:
    r = _row_with_padding(update, row_no)
    gross = parse_amount((r[COL_GROSS - 1] if len(r) >= COL_GROSS else "") or "")
    if gross <= 0:
        return "wpisz kwote"
    miss = missing_fields(r)
    if miss:
        return "uzupelnij brakujace pola"
    return "potwierdz Kwota OK"


def _mama_progress_text(update: Update, month: str, row_no: int) -> str:
    left = _mama_remaining_todo(update, month)
    return f"Zostalo: {left}. Teraz: {_mama_next_step_hint(update, row_no)}."


def _company_amount_history(update: Update, company: str, limit: int = 60) -> list[float]:
    comp_norm = (company or "").strip().lower()
    if not comp_norm:
        return []
    allv = get_all_values(update)
    rows = allv[1:] if len(allv) > 1 else []
    vals: list[float] = []
    for r in rows:
        r = r + [""] * (max(COL_COMP, COL_GROSS) - len(r))
        c = (r[COL_COMP - 1] or "").strip().lower()
        if c != comp_norm:
            continue
        v = parse_amount(r[COL_GROSS - 1] or "")
        if v > 0:
            vals.append(v)
    return vals[-limit:]


def _is_suspicious_amount(update: Update, company: str, value: float) -> tuple[bool, float, int]:
    vals = _company_amount_history(update, company)
    if len(vals) < 5 or value <= 0:
        return False, 0.0, len(vals)
    med = float(median(vals))
    if med <= 0:
        return False, 0.0, len(vals)
    ratio = value / med
    suspicious = (ratio >= 2.5 or ratio <= 0.4) and abs(value - med) >= 50.0
    return suspicious, med, len(vals)


def _clear_pending_amount_state(uid: int) -> None:
    st = dict(STATE.get(uid, {}) or {})
    for k in ("pending_amount_raw", "pending_amount_value", "amount_confirmed", "amount_confirm_row"):
        st.pop(k, None)
    STATE[uid] = st

def _row_with_padding(update: Update, row_no: int):
    r = get_row(update, row_no)
    return r + [""] * (max(COL_GROSS, COL_STATUS, COL_NET, COL_VAT, COL_FILE) - len(r))


def _remember_mama_undo(uid: int, row_no: int, row_before: list, month: str, action: str):
    MAMA_UNDO[uid] = {
        "row": int(row_no),
        "month": month or "",
        "action": action,
        "gross": (row_before[COL_GROSS - 1] if len(row_before) >= COL_GROSS else "") or "",
        "net": (row_before[COL_NET - 1] if len(row_before) >= COL_NET else "") or "",
        "vat": (row_before[COL_VAT - 1] if len(row_before) >= COL_VAT else "") or "",
        "status": (row_before[COL_STATUS - 1] if len(row_before) >= COL_STATUS else "") or "",
    }


def _human_date(date_raw: str) -> str:
    d = (date_raw or "").strip()
    if len(d) >= 10:
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d")
            return f"{dt.day} {_POLISH_MONTH_NAMES.get(dt.month, dt.strftime('%m'))}"
        except Exception:
            return d[:10]
    return d or "bez daty"


def _human_todo_reason(r: list) -> str:
    gross = parse_amount((r[COL_GROSS - 1] if len(r) >= COL_GROSS else "") or "")
    if gross <= 0:
        return "brak kwoty"
    miss = missing_fields(r)
    if miss:
        return f"brak: {', '.join(miss)}"
    return "wymaga sprawdzenia"


def _human_todo_rows(update: Update, month: str, limit: int = 5):
    ranked = []
    for row_no, r in _rows_for_month(update, month):
        r = r + [""] * (max(COL_GROSS, COL_STATUS, COL_COMP, COL_DATE) - len(r))
        st = (r[COL_STATUS - 1] or "").strip()
        gross = parse_amount(r[COL_GROSS - 1] or "")
        if st != STATUS_TODO and gross > 0:
            continue
        comp = (r[COL_COMP - 1] or "").strip() or "nieznana firma"
        date_h = _human_date((r[COL_DATE - 1] if len(r) >= COL_DATE else "") or "")
        reason = _human_todo_reason(r)
        priority = 0 if gross <= 0 else 1
        ranked.append((priority, row_no, f"Faktura z {comp}, {date_h}, {reason}."))
    ranked.sort(key=lambda x: (x[0], x[1]))
    return [(row_no, text) for _, row_no, text in ranked[:limit]]


def _find_next_after(update: Update, month: str, after_row: int | None):
    rows = _rows_for_month(update, month)
    for row_no, r in rows:
        if after_row is not None and row_no <= after_row:
            continue
        r = r + [""] * (max(COL_GROSS, COL_STATUS) - len(r))
        st = (r[COL_STATUS - 1] or "").strip()
        gross = parse_amount(r[COL_GROSS - 1] or "")
        if st == STATUS_TODO or gross <= 0:
            return row_no
    return None


def _mama_review_text(update: Update, row_no: int) -> str:
    r = _row_with_padding(update, row_no)
    comp = (r[COL_COMP - 1] if len(r) >= COL_COMP else "") or "nieznana firma"
    gross = (r[COL_GROSS - 1] if len(r) >= COL_GROSS else "") or "-"
    reason = _human_todo_reason(r)
    return (
        f"Do poprawy: {comp}\n"
        f"Kwota: {gross}\n"
        f"Problem: {reason}\n"
        f"Kliknij: Kwota OK albo Popraw kwote."
    )




def _merge_mama_state(uid: int, **kwargs):
    st = dict(STATE.get(uid, {}) or {})
    st.update(kwargs)
    st["last_step_ts"] = float(time.time())
    STATE[uid] = st
    return st

def _parse_words_int_pl(tokens: list[str]):
    units = {
        "zero": 0,
        "jeden": 1,
        "jedna": 1,
        "dwa": 2,
        "dwie": 2,
        "trzy": 3,
        "cztery": 4,
        "piec": 5,
        "szesc": 6,
        "siedem": 7,
        "osiem": 8,
        "dziewiec": 9,
        "dziesiec": 10,
        "jedenascie": 11,
        "dwanascie": 12,
        "trzynascie": 13,
        "czternascie": 14,
        "pietnascie": 15,
        "szesnascie": 16,
        "siedemnascie": 17,
        "osiemnascie": 18,
        "dziewietnascie": 19,
    }
    tens = {
        "dwadziescia": 20,
        "trzydziesci": 30,
        "czterdziesci": 40,
        "piecdziesiat": 50,
        "szescdziesiat": 60,
        "siedemdziesiat": 70,
        "osiemdziesiat": 80,
        "dziewiecdziesiat": 90,
    }
    hundreds = {
        "sto": 100,
        "dwiescie": 200,
        "trzysta": 300,
        "czterysta": 400,
        "piecset": 500,
        "szescset": 600,
        "siedemset": 700,
        "osiemset": 800,
        "dziewiecset": 900,
    }

    total = 0
    cur = 0
    used = False
    for t in tokens:
        if t in hundreds:
            cur += hundreds[t]
            used = True
            continue
        if t in tens:
            cur += tens[t]
            used = True
            continue
        if t in units:
            cur += units[t]
            used = True
            continue
        if t in {"tysiac", "tysiace", "tysiecy"}:
            if cur <= 0:
                cur = 1
            total += cur * 1000
            cur = 0
            used = True
            continue
        return None
    if not used:
        return None
    return total + cur


def _try_parse_spoken_amount(txt_raw: str):
    raw = (txt_raw or "").strip().lower()
    if not raw or any(ch.isdigit() for ch in raw):
        return 0.0

    repl = {
        "ą": "a",
        "ć": "c",
        "ę": "e",
        "ł": "l",
        "ń": "n",
        "ó": "o",
        "ś": "s",
        "ż": "z",
        "ź": "z",
        "-": " ",
        ",": " ",
        ".": " ",
    }
    for a, b in repl.items():
        raw = raw.replace(a, b)
    tokens = [t for t in raw.split() if t]
    if not tokens:
        return 0.0

    sep_tokens = {"przecinek", "kropka", "po"}
    for sep in sep_tokens:
        if sep in tokens:
            i = tokens.index(sep)
            left = _parse_words_int_pl(tokens[:i])
            right = _parse_words_int_pl(tokens[i + 1 :])
            if left is not None and right is not None:
                return float(f"{left}.{int(right):02d}")

    # Prefer split where decimal tail is 2 words (e.g. "czterdziesci piec") and in 10..99.
    for i in range(len(tokens) - 1, 0, -1):
        right_tokens = tokens[i:]
        if len(right_tokens) > 2:
            continue
        left = _parse_words_int_pl(tokens[:i])
        right = _parse_words_int_pl(right_tokens)
        if left is None or right is None:
            continue
        if 10 <= right <= 99:
            return float(f"{left}.{int(right):02d}")

    for i in range(1, len(tokens)):
        left = _parse_words_int_pl(tokens[:i])
        right = _parse_words_int_pl(tokens[i:])
        if left is None or right is None:
            continue
        if 0 <= right <= 99:
            return float(f"{left}.{int(right):02d}")

    whole = _parse_words_int_pl(tokens)
    return float(whole) if whole is not None else 0.0


async def _send_mama_sos(ctx: ContextTypes.DEFAULT_TYPE, update: Update, state: dict):
    ids = sorted(admin_ids())
    if not ids:
        return
    uid = update.effective_user.id if update and update.effective_user else 0
    name = (update.effective_user.full_name if update and update.effective_user else "") or "-"
    msg = (
        "SOS MAMA\n"
        f"user_id: {uid}\n"
        f"name: {name}\n"
        f"mode: {state.get('mode', '-') }\n"
        f"row: {state.get('row', '-') }\n"
        f"month: {state.get('month', '-') }\n"
        f"last_step: {state.get('last_step', '-') }\n"
        f"ts: {datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    for aid in ids:
        try:
            await ctx.bot.send_message(chat_id=aid, text=msg)
        except Exception:
            continue



async def _send_mama_soft_alert(ctx: ContextTypes.DEFAULT_TYPE, update: Update, reason: str, state: dict):
    ids = sorted(admin_ids())
    if not ids:
        return
    uid = update.effective_user.id if update and update.effective_user else 0
    name = (update.effective_user.full_name if update and update.effective_user else "") or "-"
    msg = (
        "MAMA SOFT ALERT\n"
        f"reason: {reason}\n"
        f"user_id: {uid}\n"
        f"name: {name}\n"
        f"mode: {state.get('mode', '-') }\n"
        f"row: {state.get('row', '-') }\n"
        f"last_step: {state.get('last_step', '-') }\n"
        f"ts: {datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    for aid in ids:
        try:
            await ctx.bot.send_message(chat_id=aid, text=msg)
        except Exception:
            continue
def _voice_integration_ready() -> tuple[bool, str]:
    if not MAMA_VOICE_ENABLED:
        return False, "Tryb glosowy jest wylaczony (MAMA_VOICE_ENABLED=0)."
    if not env(ENV_OPENAI_API_KEY, ""):
        return False, "Brak OPENAI_API_KEY."
    try:
        import openai  # noqa: F401
    except Exception:
        return False, "Brak biblioteki openai. Zainstaluj requirements i sprobuj ponownie."
    return True, ""


def _transcribe_voice_sync(local_path: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=env(ENV_OPENAI_API_KEY, ""))
    with open(local_path, "rb") as f:
        out = client.audio.transcriptions.create(model="whisper-1", file=f, language="pl")
    txt = getattr(out, "text", None)
    if txt is None and isinstance(out, dict):
        txt = out.get("text")
    return (txt or "").strip()


async def _transcribe_voice_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> str:
    if not update.message or not update.message.voice:
        return ""
    tg_file = await ctx.bot.get_file(update.message.voice.file_id)
    local = INV_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_voice.ogg"
    await tg_file.download_to_drive(local)
    try:
        return await asyncio.to_thread(_transcribe_voice_sync, str(local))
    finally:
        try:
            local.unlink(missing_ok=True)
        except Exception:
            pass


async def _handle_mama_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, txt_raw: str) -> bool:
    uid = update.effective_user.id
    txt = (txt_raw or "").strip().lower()
    state = dict(STATE.get(uid, {}) or {})
    mode = state.get("mode", "")

    if txt in ("stop", "cancel", "anuluj", "koniec") and _mama_active_mode(mode):
        streak = int(state.get("cancel_streak", 0) or 0) + 1
        _merge_mama_state(uid, cancel_streak=streak, mode="", row="", month="", next_row="", last_step="cancel")
        if streak >= max(1, MAMA_CANCEL_ALERT_STREAK):
            await _send_mama_soft_alert(ctx, update, f"cancel_streak={streak}", STATE.get(uid, {}))
            _merge_mama_state(uid, cancel_streak=0, last_step="cancel_alert_sent")
        await update.message.reply_text("Anulowano. Wrocilam do menu.", reply_markup=_mama_tiles_for(uid))
        return True

    if txt in ("pomoc",):
        await update.message.reply_text(
            "Tryb prosty: 1) Dodaj  2) Popraw  3) Wyslij. Gdy cos nie idzie: Cofnij albo SOS.",
            reply_markup=_mama_tiles_for(uid),
        )
        return True

    if txt in ("duza czcionka on", "duza czcionka", "duza czcionka off"):
        to_on = txt != "duza czcionka off"
        _merge_mama_state(uid, large_font=to_on, last_step="toggle_large_font")
        await update.message.reply_text(
            f"Duza czcionka: {'ON' if to_on else 'OFF'}.",
            reply_markup=_mama_tiles_for(uid),
        )
        return True

    if txt in ("tryb glosowy", "glosowy"):
        voice_mode = not bool(state.get("voice_mode", False))
        _merge_mama_state(uid, voice_mode=voice_mode, last_step="toggle_voice")
        status = "ON" if voice_mode else "OFF"
        await update.message.reply_text(
            f"Tryb glosowy: {status}.",
            reply_markup=_mama_tiles_for(uid),
        )
        return True

    if txt in ("potrzebuje pomocy", "sos"):
        _merge_mama_state(uid, last_step="sos")
        await _send_mama_sos(ctx, update, STATE.get(uid, {}))
        await update.message.reply_text(
            "Wyslalam alert do opiekuna.",
            reply_markup=kb_mama_sos_safe(),
        )
        return True

    if txt in ("wroc do menu",):
        _merge_mama_state(uid, mode="", row="", month="", next_row="", last_step="safe_menu")
        await update.message.reply_text("Wrocilam do menu.", reply_markup=_mama_tiles_for(uid))
        return True

    if txt in ("poczekaj",):
        await update.message.reply_text("Opiekun dostal alert. Poczekaj spokojnie.", reply_markup=kb_mama_sos_safe())
        return True

    if txt in ("cofnij", "cofnij ostatnia akcje", "undo"):
        undo = MAMA_UNDO.get(uid)
        if not undo:
            await update.message.reply_text("Nie mam nic do cofniecia.", reply_markup=_mama_tiles_for(uid))
            return True

        row_no = int(undo.get("row", 0) or 0)
        if row_no <= 0:
            MAMA_UNDO.pop(uid, None)
            await update.message.reply_text("Nie moge cofnac tej akcji.", reply_markup=_mama_tiles_for(uid))
            return True

        update_cell(update, row_no, COL_GROSS, undo.get("gross", ""))
        update_cell(update, row_no, COL_NET, undo.get("net", ""))
        update_cell(update, row_no, COL_VAT, undo.get("vat", ""))
        update_cell(update, row_no, COL_STATUS, undo.get("status", ""))

        month = (undo.get("month") or _month_from_row(update, row_no) or today_ym()).strip()
        _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=month, next_row="", last_step=f"undo:{row_no}")
        MAMA_UNDO.pop(uid, None)
        await update.message.reply_text(
            f"Cofnelam ostatnia akcje. Wrocilam do faktury #{row_no}.",
            reply_markup=_mama_review_tiles_for(uid),
        )
        await update.message.reply_text(_mama_review_text(update, row_no), reply_markup=_mama_review_tiles_for(uid))
        return True

    if txt in ("dodaj fakture", "dzisiaj dodaj fakture"):
        _merge_mama_state(uid, mode="add_wait_type", last_step="add:start")
        await update.message.reply_text("Krok 1/2: wybierz Typ VAT albo Typ Bez VAT.", reply_markup=_mama_type_tiles_for(uid))
        return True

    if txt in ("typ vat", "vat"):
        _merge_mama_state(uid, mode="add_wait_file", inv_type=TYPE_VAT, last_step="add:type_vat")
        await update.message.reply_text("Krok 2/2: wyslij jedno zdjecie albo PDF.", reply_markup=_mama_tiles_for(uid))
        return True

    if txt in ("typ bez vat", "bez vat", "novat"):
        _merge_mama_state(uid, mode="add_wait_file", inv_type=TYPE_NO_VAT, last_step="add:type_novat")
        await update.message.reply_text("Krok 2/2: wyslij jedno zdjecie albo PDF.", reply_markup=_mama_tiles_for(uid))
        return True

    if txt in ("co mam poprawic",):
        m = today_ym()
        items = _human_todo_rows(update, m, limit=7)
        if not items:
            await update.message.reply_text(f"W {m} wszystko jest juz gotowe.", reply_markup=_mama_tiles_for(uid))
            return True

        row_no = int(items[0][0])
        _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=m, next_row="", last_step=f"todo:list:{m}")
        lines = "\n".join(f"- {desc}" for _, desc in items)
        await update.message.reply_text(f"Do poprawy w {m}:\n{lines}", reply_markup=_mama_review_tiles_for(uid))
        await update.message.reply_text(_mama_progress_text(update, m, row_no), reply_markup=_mama_review_tiles_for(uid))
        await update.message.reply_text(_mama_review_text(update, row_no), reply_markup=_mama_review_tiles_for(uid))
        return True

    if txt in ("wyslij do ksiegowej",):
        m = today_ym()
        zip_bytes, filename = build_month_zip(update, m)
        await update.message.reply_document(document=zip_bytes, filename=filename, caption=f"Paczka {m}")
        _merge_mama_state(uid, mode="mama_after_send", month=m, last_step=f"export:{m}")
        await update.message.reply_text("Wyslane do ksiegowej.", reply_markup=kb_mama_next_only(_mama_large_font(state)))
        return True

    if mode == "mama_pick_company":
        row_s = str(state.get("row", ""))
        if row_s.isdigit():
            row_no = int(row_s)
            if txt in ("zostaw ocr",):
                _merge_mama_state(uid, mode="mama_wait_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="company:skip")
                await update.message.reply_text("Zostawiam firme z OCR.", reply_markup=_mama_review_tiles_for(uid))
                return True
            if txt in ("popraw recznie",):
                _merge_mama_state(uid, mode="mama_set_company", row=str(row_no), month=state.get("month", today_ym()), last_step="company:manual")
                await update.message.reply_text("Wpisz nazwe firmy.", reply_markup=_mama_tiles_for(uid))
                return True
            update_cell(update, row_no, COL_COMP, txt_raw.strip())
            _merge_mama_state(uid, mode="mama_wait_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="company:set")
            await update.message.reply_text("Firma zapisana.", reply_markup=_mama_review_tiles_for(uid))
            return True

    if mode == "mama_set_company":
        row_s = str(state.get("row", ""))
        if row_s.isdigit() and (txt_raw or "").strip():
            row_no = int(row_s)
            update_cell(update, row_no, COL_COMP, txt_raw.strip())
            _merge_mama_state(uid, mode="mama_wait_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="company:manual_set")
            await update.message.reply_text("Firma zapisana.", reply_markup=_mama_review_tiles_for(uid))
            return True

    if mode == "mama_confirm_amount":
        if txt in ("tak",):
            pending = str(state.get("pending_amount_raw", "")).strip()
            row_s = str(state.get("amount_confirm_row", state.get("row", "")))
            _merge_mama_state(
                uid,
                mode="mama_set_price",
                row=row_s,
                month=state.get("month", today_ym()),
                amount_confirmed=True,
                last_step="amount:confirmed",
            )
            if pending:
                return await _handle_mama_text(update, ctx, pending)
            await update.message.reply_text("Wpisz kwote jeszcze raz.", reply_markup=_mama_review_tiles_for(uid))
            return True
        if txt in ("popraw kwote",):
            _merge_mama_state(uid, mode="mama_set_price", amount_confirmed=False, last_step="amount:edit")
            await update.message.reply_text("Popraw kwote, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
            return True
    if txt in ("dalej",):
        state = dict(STATE.get(uid, {}) or {})
        mode = state.get("mode", "")
        if mode == "mama_after_send":
            _merge_mama_state(uid, mode="", row="", month="", next_row="", last_step="after_send_next")
            await update.message.reply_text("Co dalej?", reply_markup=_mama_tiles_for(uid))
            return True

        month = (state.get("month") or today_ym()).strip()
        nxt_s = str(state.get("next_row", "")).strip()
        if nxt_s.isdigit():
            nxt = int(nxt_s)
        else:
            cur = int(state.get("row")) if str(state.get("row", "")).isdigit() else None
            nxt = _find_next_after(update, month, after_row=cur)
            if not nxt and cur is not None:
                nxt = _find_next_after(update, month, after_row=None)
                if nxt == cur:
                    nxt = None

        if not nxt:
            _merge_mama_state(uid, mode="", row="", month="", next_row="", last_step="next:none")
            await update.message.reply_text("Brak kolejnych faktur do poprawy.", reply_markup=_mama_tiles_for(uid))
            return True

        _merge_mama_state(uid, mode="mama_review", row=str(nxt), month=month, next_row="", last_step=f"next:{nxt}")
        await update.message.reply_text(_mama_review_text(update, nxt), reply_markup=_mama_review_tiles_for(uid))
        return True

    if txt in ("nagraj kwote",) and mode == "mama_ultra_amount":
        _merge_mama_state(uid, voice_mode=True, last_step="ultra:voice")
        await update.message.reply_text("Nagraj teraz tylko kwote.", reply_markup=kb_mama_ultra_amount())
        return True

    if txt in ("wpisz kwote",) and mode == "mama_ultra_amount":
        row_s = state.get("row", "")
        _merge_mama_state(uid, mode="mama_set_price", row=str(row_s), month=state.get("month", today_ym()), last_step="ultra:type")
        await update.message.reply_text("Wpisz tylko kwote, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
        return True

    if mode in {"mama_wait_amount", "mama_set_price", "mama_ultra_amount"} and txt in ("popraw kwote",):
        row_s = state.get("row", "")
        if str(row_s).isdigit():
            row_no = int(row_s)
            month = state.get("month") or _month_from_row(update, row_no) or today_ym()
            _merge_mama_state(uid, mode="mama_set_price", row=str(row_no), month=month, last_step=f"price:ask:{row_no}")
            await update.message.reply_text("Wpisz tylko kwote, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
            return True

    if mode == "mama_review" and txt in ("kwota ok", "ok"):
        row_s = state.get("row", "")
        if row_s.isdigit():
            row_no = int(row_s)
            month = (state.get("month") or _month_from_row(update, row_no) or today_ym()).strip()
            r_before = _row_with_padding(update, row_no)
            _remember_mama_undo(uid, row_no, r_before, month, "mama_ok")

            old_status = (r_before[COL_STATUS - 1] if len(r_before) >= COL_STATUS else "") or ""
            miss = missing_fields(r_before)
            new_status = STATUS_TODO if miss else STATUS_OK
            update_cell(update, row_no, COL_STATUS, new_status)
            log_event("status_change", user_id=uid, row_no=row_no, old_status=old_status, new_status=new_status, source="messages:mama:ok")

            if miss:
                _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=month, last_step=f"ok:missing:{row_no}")
                await update.message.reply_text("Brakuje danych. Kliknij Popraw kwote.", reply_markup=_mama_review_tiles_for(uid))
                return True

            done_today = _today_mama_ok_count(update, month)
            if done_today and done_today % 3 == 0:
                await update.message.reply_text(f"Super, {done_today}/3 gotowe dzisiaj.", reply_markup=_mama_review_tiles_for(uid))

            nxt = _find_next_after(update, month, after_row=row_no)
            if nxt:
                _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=month, next_row=str(nxt), last_step=f"ok:{row_no}")
                await update.message.reply_text("Zapisane.", reply_markup=kb_mama_next_only(_mama_large_font(state)))
                return True

            _merge_mama_state(uid, mode="", row="", month=month, next_row="", last_step=f"ok:last:{row_no}")
            await update.message.reply_text("Zapisane. Nie ma juz nic do poprawy.", reply_markup=_mama_tiles_for(uid))
            return True

    if mode in {"mama_set_price", "mama_wait_amount", "mama_ultra_amount"}:
        row_s = state.get("row", "")
        if not str(row_s).isdigit():
            STATE.pop(uid, None)
            await update.message.reply_text("Cos poszlo nie tak. Kliknij Co mam poprawic.", reply_markup=_mama_tiles_for(uid))
            return True

        row_no = int(row_s)
        val = parse_amount(txt_raw)
        if val <= 0:
            val = _try_parse_spoken_amount(txt_raw)
        if val <= 0:
            bad = _register_mama_amount_failure(uid)
            if bad >= 2:
                _merge_mama_state(uid, mode="mama_ultra_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="price:ultra")
                await update.message.reply_text("Przechodze na ultra-prosty tryb.", reply_markup=kb_mama_ultra_amount())
                return True
            await update.message.reply_text("Nie widze kwoty. Wpisz np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
            return True

        _reset_mama_amount_failure(uid)
        month = (state.get("month") or _month_from_row(update, row_no) or today_ym()).strip()
        row_before = _row_with_padding(update, row_no)
        company = (row_before[COL_COMP - 1] if len(row_before) >= COL_COMP else "") or ""

        suspicious, med, hist_n = _is_suspicious_amount(update, company, val)
        if suspicious and not bool(state.get("amount_confirmed", False)):
            _merge_mama_state(
                uid,
                mode="mama_confirm_amount",
                row=str(row_no),
                month=month,
                pending_amount_raw=txt_raw,
                pending_amount_value=f"{val:.2f}",
                amount_confirm_row=str(row_no),
                amount_confirmed=False,
                last_step=f"amount:confirm:{row_no}",
            )
            await update.message.reply_text(
                f"Kwota {val:.2f} mocno odstaje od historii firmy ({med:.2f}, n={hist_n}). Na pewno?",
                reply_markup=kb_mama_amount_confirm(),
            )
            return True

        _remember_mama_undo(uid, row_no, row_before, month, "mama_set_price")

        update_cell(update, row_no, COL_GROSS, f"{val:.2f}")
        row_after = _row_with_padding(update, row_no)
        type_v = (row_after[COL_TYPE - 1] if len(row_after) >= COL_TYPE else "") or ""
        net, vat = _calc_net_vat_from_type(type_v, val)
        update_cell(update, row_no, COL_NET, f"{net:.2f}")
        update_cell(update, row_no, COL_VAT, f"{vat:.2f}")

        row_after = _row_with_padding(update, row_no)
        old_status = (row_after[COL_STATUS - 1] if len(row_after) >= COL_STATUS else "") or ""
        miss = missing_fields(row_after)
        new_status = STATUS_TODO if miss else STATUS_OK
        update_cell(update, row_no, COL_STATUS, new_status)
        log_event("status_change", user_id=uid, row_no=row_no, old_status=old_status, new_status=new_status, source="messages:mama:set_price")

        if new_status == STATUS_OK:
            done_today = _today_mama_ok_count(update, month)
            if done_today and done_today % 3 == 0:
                await update.message.reply_text(f"Super, {done_today}/3 gotowe dzisiaj.", reply_markup=_mama_review_tiles_for(uid))

        nxt = _find_next_after(update, month, after_row=row_no)
        if nxt:
            _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=month, next_row=str(nxt), last_step=f"price:set:{row_no}")
            await update.message.reply_text("Zapisane.", reply_markup=kb_mama_next_only(_mama_large_font(state)))
            return True

        _merge_mama_state(uid, mode="", row="", month=month, next_row="", last_step=f"price:last:{row_no}")
        await update.message.reply_text("Zapisane. Nie ma juz nic do poprawy.", reply_markup=_mama_tiles_for(uid))
        return True

    return False


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not is_mama(update):
        return
    if not update.message or not update.message.voice:
        return

    uid = update.effective_user.id
    st = STATE.get(uid, {})
    mode = st.get("mode", "")
    if mode not in {"mama_set_price", "mama_ultra_amount", "mama_wait_amount"}:
        return await update.message.reply_text(
            "Nagranie glosowe dziala w kroku wpisywania kwoty. Kliknij Popraw kwote.",
            reply_markup=_mama_review_tiles_for(uid),
        )

    if not bool(st.get("voice_mode", False)):
        return await update.message.reply_text(
            "Wlacz najpierw Tryb glosowy, potem nagraj kwote.",
            reply_markup=_mama_review_tiles_for(uid),
        )

    ok, reason = _voice_integration_ready()
    if not ok:
        return await update.message.reply_text(reason, reply_markup=_mama_review_tiles_for(uid))

    try:
        txt = await _transcribe_voice_note(update, ctx)
    except Exception:
        return await update.message.reply_text(
            "Nie udalo sie rozpoznac nagrania. Powiedz kwote wolniej albo wpisz ja recznie.",
            reply_markup=_mama_review_tiles_for(uid),
        )

    if not txt:
        return await update.message.reply_text(
            "Nie uslyszalam kwoty. Powiedz jeszcze raz albo wpisz recznie.",
            reply_markup=_mama_review_tiles_for(uid),
        )

    await update.message.reply_text(f"Rozpoznalam: {txt}", reply_markup=_mama_review_tiles_for(uid))
    handled = await _handle_mama_text(update, ctx, txt)
    if handled:
        return
    await update.message.reply_text("Nie rozpoznalam kwoty. Wpisz liczbe, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await update.message.reply_text(" Brak dostepu.", reply_markup=kb_page(1))

    uid = update.effective_user.id
    txt_raw = (update.message.text or "").strip()
    txt = txt_raw.lower()
    mode = STATE.get(uid, {}).get("mode", "")

    if is_mama(update):
        handled = await _handle_mama_text(update, ctx, txt_raw)
        if handled:
            return

    if mode in {"set_vat", "set_price", "edit_field"} and not is_operator(update):
        STATE.pop(uid, None)
        return await update.message.reply_text("Tylko operator lub admin moze zmieniac dane.", reply_markup=kb_page(1))

    if mode == "edit_field":
        row_s = STATE.get(uid, {}).get("row", "")
        field = STATE.get(uid, {}).get("field", "")
        if not str(row_s).isdigit():
            STATE.pop(uid, None)
            return await update.message.reply_text("Blad stanu. Kliknij /start.", reply_markup=kb_page(1))
        if txt in ("stop", "/stop", "cancel", "anuluj", "koniec"):
            STATE.pop(uid, None)
            return await update.message.reply_text("Anulowano poprawke OCR.", reply_markup=kb_page(1))

        row_no = int(row_s)
        field_to_col = {
            "no": COL_NO,
            "comp": COL_COMP,
            "date": COL_DATE,
            "gross": COL_GROSS,
        }
        col = field_to_col.get(field)
        if not col:
            STATE.pop(uid, None)
            return await update.message.reply_text("Nieznane pole OCR.", reply_markup=kb_page(1))

        value = txt_raw
        if field == "gross":
            val = parse_amount(txt_raw)
            if val <= 0:
                return await update.message.reply_text("Podaj poprawna kwote, np. 123,45", reply_markup=kb_page(1))
            value = f"{val:.2f}"

        update_cell(update, row_no, col, value)

        if field == "gross":
            r = get_row(update, row_no)
            gross = parse_amount((r[COL_GROSS - 1] if len(r) >= COL_GROSS else "") or "")
            inv_type = (r[COL_TYPE - 1] if len(r) >= COL_TYPE else "") or ""
            net, vat = _calc_net_vat_from_type(inv_type, gross)
            update_cell(update, row_no, COL_NET, f"{net:.2f}")
            update_cell(update, row_no, COL_VAT, f"{vat:.2f}")

        r = get_row(update, row_no)
        old_status = (r[COL_STATUS - 1] if len(r) >= COL_STATUS else "") or ""
        miss = missing_fields(r)
        new_status = STATUS_OK if not miss else STATUS_TODO
        update_cell(update, row_no, COL_STATUS, new_status)
        log_event("status_change", user_id=uid, row_no=row_no, old_status=old_status, new_status=new_status, source=f"messages:edit_field:{field}")
        log_event("ocr_fix", user_id=uid, row_no=row_no, field=field, value=value)

        STATE.pop(uid, None)
        return await update.message.reply_text(f"Poprawiono pole `{field}` w wierszu {row_no}.", reply_markup=kb_page(1))

    if mode == "set_vat":
        row_s = STATE.get(uid, {}).get("row", "")
        if not str(row_s).isdigit():
            STATE.pop(uid, None)
            return await update.message.reply_text(" Blad. Kliknij /start.", reply_markup=kb_page(1))

        row_no = int(row_s)
        if txt in ("stop", "/stop", "cancel", "anuluj", "koniec"):
            STATE.pop(uid, None)
            return await update.message.reply_text(" Anulowano ustawianie VAT.", reply_markup=kb_page(1))

        vat_type_raw = txt_raw.strip()
        update_cell(update, row_no, COL_TYPE, vat_type_raw)

        r = get_row(update, row_no)
        gross = parse_amount((r[COL_GROSS - 1] if len(r) >= COL_GROSS else "") or "")
        if gross <= 0:
            STATE.pop(uid, None)
            return await update.message.reply_text(
                "Nie moge przeliczyc: brak kwoty brutto.\nNajpierw wpisz brutto, potem ustaw VAT.",
                reply_markup=kb_page(1),
            )

        net, vat = _calc_net_vat_from_type(vat_type_raw, gross)
        update_cell(update, row_no, COL_NET, f"{net:.2f}")
        update_cell(update, row_no, COL_VAT, f"{vat:.2f}")

        STATE.pop(uid, None)
        return await update.message.reply_text(
            f"VAT ustawiony: {vat_type_raw}\nBrutto: {gross:.2f} | Netto: {net:.2f} | VAT: {vat:.2f}",
            reply_markup=kb_page(1),
        )

    if mode == "set_price":
        row_s = STATE.get(uid, {}).get("row", "")
        month = STATE.get(uid, {}).get("month", "")

        if not str(row_s).isdigit():
            STATE.pop(uid, None)
            return await update.message.reply_text(" Blad. Kliknij /start.", reply_markup=kb_page(1))

        row_no = int(row_s)
        if not month:
            month = _month_from_row(update, row_no)

        if txt in ("stop", "/stop", "cancel", "anuluj", "koniec"):
            STATE.pop(uid, None)
            return await update.message.reply_text(" Tryb kontynuuj zakonczony.", reply_markup=kb_page(1))

        val = parse_amount(txt_raw)
        if val <= 0:
            return await update.message.reply_text("Podaj poprawna kwote, np. 123,45 (albo `stop`)", reply_markup=kb_page(1))

        update_cell(update, row_no, COL_GROSS, f"{val:.2f}")

        r = get_row(update, row_no)
        type_v = (r[COL_TYPE - 1] if len(r) >= COL_TYPE else "") or ""
        net, vat = _calc_net_vat_from_type(type_v, val)
        update_cell(update, row_no, COL_NET, f"{net:.2f}")
        update_cell(update, row_no, COL_VAT, f"{vat:.2f}")

        r = get_row(update, row_no)
        old_status = (r[COL_STATUS - 1] if len(r) >= COL_STATUS else "") or ""
        miss = missing_fields(r)

        if miss:
            update_cell(update, row_no, COL_STATUS, STATUS_TODO)
            log_event("status_change", user_id=uid, row_no=row_no, old_status=old_status, new_status=STATUS_TODO, source="messages:set_price:missing")
            STATE.pop(uid, None)
            return await update.message.reply_text(
                f"Kwota ustawiona ({val:.2f}), ale brakuje jeszcze: {', '.join(miss)}.\nWiersz {row_no} zostaje: {STATUS_TODO}",
                reply_markup=kb_page(1),
            )

        update_cell(update, row_no, COL_STATUS, STATUS_OK)
        log_event("status_change", user_id=uid, row_no=row_no, old_status=old_status, new_status=STATUS_OK, source="messages:set_price:ok")

        STATE.pop(uid, None)
        return await update.message.reply_text(
            f"Kwota ustawiona: {val:.2f} PLN\nWiersz {row_no} -> {STATUS_OK}",
            reply_markup=kb_page(1),
        )

    if txt_raw.isdigit() and len(txt_raw) == 4:
        year = int(txt_raw)
        from keyboards import kb_months_of_year

        return await update.message.reply_text(
            f"Miesiace {year} (kliknij):",
            reply_markup=kb_months_of_year("snap", year),
        )

    await update.message.reply_text("Kliknij /start", reply_markup=(kb_mama_tiles() if is_mama(update) else kb_page(1)))


def register(app):
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))













































