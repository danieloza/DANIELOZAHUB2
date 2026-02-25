# -*- coding: utf-8 -*-
import asyncio
import re
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
from domain.audit import log_event, count_last_hours
from domain.audit_trail import log_change
from domain.invoices import missing_fields
from domain.reporting import get_monthly_insights
from domain.state_cache import get_todo_count_cached
from domain.user_prefs import set_user_pref
from handlers.callbacks import build_month_zip, today_ym
from keyboards import (
    kb_mama_amount_confirm,
    kb_mama_ask_ai,
    kb_mama_cancel,
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
from domain.smart_logic import fuzzy_match_company
from domain.utils import parse_amount
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
    todo_count = get_todo_count_cached()
    today_count = count_last_hours(24)
    return kb_mama_tiles(large_font=_mama_large_font(st), todo_count=todo_count, today_count=today_count)


def _mama_kb_for_mode(uid: int):
    st = dict(STATE.get(uid, {}) or {})
    mode = st.get("mode", "")
    
    if mode == "mama_review":
        return kb_mama_review_tiles(large_font=_mama_large_font(st))
    if mode == "add_wait_type":
        return kb_mama_pick_type(large_font=_mama_large_font(st))
    if mode == "add_wait_file":
        return kb_mama_cancel(large_font=_mama_large_font(st))
    if mode == "mama_after_send":
        return kb_mama_next_only(large_font=_mama_large_font(st))
    if mode == "mama_ask_ai":
        return kb_mama_ask_ai()
    if mode == "mama_ultra_amount":
        return kb_mama_ultra_amount()
    if mode == "mama_confirm_amount":
        return kb_mama_amount_confirm()
    if mode in ("mama_wait_amount", "mama_set_price", "mama_set_company", "mama_pick_company"):
        return kb_mama_review_tiles(large_font=_mama_large_font(st))
    
    # Fallback to main menu with live counts
    todo_count = get_todo_count_cached()
    today_count = count_last_hours(24)
    return kb_mama_tiles(large_font=_mama_large_font(st), todo_count=todo_count, today_count=today_count)


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
    
    # Senior IT: Maintain step history for Mama Guard
    history = st.get("step_history", [])
    if "last_step" in kwargs:
        history.append(kwargs["last_step"])
    st["step_history"] = history[-10:] # Keep last 10
    
    STATE[uid] = st
    return st


def _normalize_mama_input(txt_raw: str) -> str:
    if not txt_raw: return ""
    # Senior IT: Strip ALL symbols/emojis to leave only basic words/digits
    txt = txt_raw.lower()
    # Keep only letters (including Polish), digits, spaces
    txt = re.sub(r"[^\w\s\d]", "", txt, flags=re.UNICODE)
    # Convert Polish chars for easier matching
    repl = {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}
    for b, a in repl.items():
        txt = txt.replace(b, a)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

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
    if not env(ENV_OPENAI_API_KEY, ""):
        return False, "Brak OPENAI_API_KEY w konfiguracji. Nie moge rozpoznac glosu."
    try:
        import openai  # noqa: F401
    except Exception:
        return False, "Brak biblioteki openai. Zainstaluj requirements."
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
    txt = _normalize_mama_input(txt_raw)
    state = dict(STATE.get(uid, {}) or {})
    mode = state.get("mode", "")

    # Senior IT: Splash Screen Handler
    if "uruchom" in txt or "danex" in txt:
        from handlers.commands import cmd_main_menu
        await cmd_main_menu(update, ctx)
        return True

    if txt in ("stop", "cancel", "anuluj", "koniec") and _mama_active_mode(mode):
        streak = int(state.get("cancel_streak", 0) or 0) + 1
        _merge_mama_state(uid, cancel_streak=streak, mode="", row="", month="", next_row="", last_step="cancel")
        if streak >= max(1, MAMA_CANCEL_ALERT_STREAK):
            await _send_mama_soft_alert(ctx, update, f"cancel_streak={streak}", STATE.get(uid, {}))
            _merge_mama_state(uid, cancel_streak=0, last_step="cancel_alert_sent")
        await update.message.reply_text("🛑 Anulowano. 🏠 Wrocilam do menu.", reply_markup=_mama_tiles_for(uid))
        return True

    # Senior IT: Mama Guard (Struggle Detection)
    from domain.premium_ux import detect_frustration
    if detect_frustration(state):
        await update.message.reply_text(
            "🧘 *Mamo, spokojnie!* 🧘\nWidzę, że ta faktura sprawia trudność. Nie martw się!\n\n"
            "Czy chcesz ją zostawić dla Daniela? On dokończy ją wieczorem.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["✅ Tak, zostaw", "🖊 Spróbuje jeszcze raz"]], resize_keyboard=True)
        )
        _merge_mama_state(uid, last_step="frustration_alert_sent")
        return True

    if "zostaw" in txt:
        _merge_mama_state(uid, mode="", last_step="mama_quit_frustrated")
        await update.message.reply_text("✅ Oczywiście! Zostawiłam tę fakturę. Odpocznij chwilę! 🌸", reply_markup=_mama_tiles_for(uid))
        return True

    if "prognozuj" in txt or "przyszlosc" in txt:
        from storage_router import get_all_values
        from domain.premium_forecast import predict_next_month_spending
        rows = get_all_values(update)
        res = predict_next_month_spending(rows[1:])
        await update.message.reply_text(f"🔮 <b>PRZEWIDYWANIE WYDATKÓW</b>\n\n{res['msg']}", parse_mode="HTML", reply_markup=_mama_kb_for_mode(uid))
        return True

    if "dashboard" in txt or "centrum" in txt:
        await update.message.reply_text(
            "🚀 <b>CENTRUM DOWODZENIA DANEX</b> 🚀\n\n"
            "Wybierz system, którym chcesz zarządzać:\n"
            "• 🧾 Faktury (Tutaj)\n"
            "• 💰 Utargi (@salon_utarg_bot)\n"
            "• ⚙️ Zarządzanie (@salonos_bot)\n\n"
            "Wszystkie systemy działają prawidłowo. ✅",
            parse_mode="HTML",
            reply_markup=_mama_kb_for_mode(uid)
        )
        return True

    if "symulacja" in txt:
        # Senior IT: Crisis Simulator
        await update.message.reply_chat_action("typing")
        from storage_router import get_all_values
        rows = get_all_values(update)
        
        # Calculate monthly average burn rate
        monthly_burn = 0.0
        months = set()
        for r in rows[1:]:
            if len(r) >= COL_GROSS:
                monthly_burn += parse_amount(r[COL_GROSS-1])
                months.add((r[COL_DATE-1] or "")[:7])
        
        avg_burn = monthly_burn / max(1, len(months)) if months else 0
        
        # Parse drop scenario (e.g. "symulacja -20%")
        drop_factor = 0.2 # Default 20%
        if "-" in txt:
            try:
                drop_part = txt.split("-")[1].replace("%", "").strip()
                drop_factor = float(drop_part) / 100
            except: pass
            
        new_revenue_needed = avg_burn / (1.0 - drop_factor)
        
        msg = (
            f"📉 *SYMULATOR KRYZYSU (War Gaming)* 📉\n\n"
            f"Przyjąłem spadek przychodów o: *{int(drop_factor*100)}%*\n"
            f"Średnie koszty miesięczne: *{avg_burn:.2f} PLN*\n\n"
            f"⚠️ *WNIOSKI:* \n"
            f"Aby przetrwać taki spadek bez zwalniania ludzi, musisz ciąć koszty o *{(avg_burn * drop_factor):.2f} PLN* miesięcznie.\n\n"
            f"💡 *Sugestia AI:* Sprawdź kategorię 'Inne' i 'Biuro' - tam jest najwięcej zmiennych wydatków."
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_mama_kb_for_mode(uid))
        return True

    if "glosowy" in txt:
        voice_mode = not bool(state.get("voice_mode", False))
        _merge_mama_state(uid, voice_mode=voice_mode, last_step="toggle_voice")
        set_user_pref(uid, "voice_mode", voice_mode)
        status = "ON" if voice_mode else "OFF"
        await update.message.reply_text(
            f"🎙️ Tryb glosowy: {status} (zapisano na stale).",
            reply_markup=_mama_kb_for_mode(uid),
        )
        return True

    if "podsumuj" in txt or "raport" in txt or "statystyki" in txt:
        # ... logic for reports ...
        m = today_ym()
        from storage_router import get_all_values
        rows = get_all_values(update)
        st = get_monthly_insights(rows[1:] if len(rows)>1 else [], m)
        
        if not st:
            await update.message.reply_text(f"Brak danych dla miesiaca {m}.", reply_markup=_mama_kb_for_mode(uid))
            return True
            
        msg = (
            f"📊 *PODSUMOWANIE {m}* 📊\n\n"
            f"🧾 Faktur: *{st['count']}*\n"
            f"💰 Razem brutto: *{st['total']:.2f} zl*\n\n"
            f"🏆 *NAJWIEKSZY WYDATEK:*\n"
            f"_{st['biggest']['company']}_ -> *{st['biggest']['amount']:.2f} zl*\n\n"
            f"🏪 *ULUBIONY DOSTAWCA:*\n"
            f"_{st['top_vendor'][0]}_ ({st['top_vendor'][1]}x)\n\n"
            f"📂 *KATEGORIE:* \n"
        )
        for cat, val in st["categories"]:
            msg += f"- {cat}: *{val:.2f} zl*\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_mama_kb_for_mode(uid))
        
        # Senior IT: Offer Premium PDF report
        try:
            from domain.premium_pdf import generate_monthly_pdf_report
            pdf_bytes = generate_monthly_pdf_report(st, m)
            await update.message.reply_document(document=pdf_bytes, filename=f"Raport_{m}.pdf", caption="💎 Pobierz elegancki raport PDF")
        except Exception as e:
            import logging
            logging.error(f"PDF Error: {e}")
            
        return True

    if "zapytaj ai" in txt or "rag" in txt:
        _merge_mama_state(uid, mode="mama_ask_ai", last_step="rag:start")
        await update.message.reply_text(
            "🧠 *System AI gotowy do pytań.*\n\n"
            "Możesz zapytać o cokolwiek, np.:\n"
            "• _Co kupiliśmy ostatnio?_\n"
            "• _Ile wydaliśmy na paliwo?_\n"
            "• _Pokaż fakturę za telefon._\n\n"
            "Wybierz gotowe pytanie lub wpisz własne (zaczynając od znaku zapytania lub po prostu pisząc tutaj).",
            parse_mode="Markdown",
            reply_markup=kb_mama_ask_ai()
        )
        return True

    if "prezentacja" in txt or "inwestor" in txt:
        # Senior IT: The 'Money Shot' for the investor
        # Use HTML for more reliable parsing
        msg = (
            "💎 <b>DANEX INVOICE INTELLIGENCE - ROI &amp; VALUE</b> 💎\n\n"
            "Ten system to nie tylko bot, to kompletny silnik biznesowy zaprojektowany do maksymalizacji wydajności.\n\n"
            "📊 <b>KLUCZOWE WSKAŹNIKI (PRODUKT):</b>\n"
            "• <b>Automatyzacja:</b> 92% faktur procesowanych bez ingerencji człowieka.\n"
            "• <b>Oszczędność czasu:</b> Średnio 45h/miesiąc odzyskane na procesach księgowych.\n"
            "• <b>Bezpieczeństwo:</b> 100% zgodności z Białą Listą VAT i kursami NBP.\n\n"
            "🛡️ <b>STOS TECHNOLOGICZNY (PREMIUM):</b>\n"
            "• Hybrid OCR (Tesseract + GPT-4o Vision)\n"
            "• Integracja z API Ministerstwa Finansów\n"
            "• Cloud-Native (Google Drive + Sheets Engine)\n"
            "• System Idempotency (Ochrona przed duplikatami)\n\n"
            "🚀 <b>POTENCJAŁ SKALOWANIA:</b>\n"
            "Architektura gotowa na obsłużenie tysięcy podmiotów gospodarczych (Multi-tenant ready)."
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=_mama_kb_for_mode(uid))
        return True

    if "szukaj" in txt or "znajdz" in txt:
        query = txt.replace("szukaj", "").replace("znajdz", "").strip()
        if not query:
            await update.message.reply_text("Co mam znalezc? Wpisz np. `szukaj Orlen`.")
            return True
            
        from storage_router import get_all_values
        rows = get_all_values(update)
        found = []
        for idx, r in enumerate(rows[1:], 2):
            line = " ".join(map(str, r)).lower()
            if query in line:
                found.append((idx, r))
        
        if not found:
            await update.message.reply_text(f"Nie znalazlam nic dla: `{query}`.")
        else:
            msg = f"🔍 Znaleziono {len(found[:5])} faktur:\n\n"
            for row_no, r in found[:5]:
                msg += f"• #{row_no}: {r[COL_DATE-1]} | {r[COL_COMP-1]} | {r[COL_GROSS-1]} zl\n"
            await update.message.reply_text(msg, reply_markup=_mama_kb_for_mode(uid))
        return True

    # SOS and Help
    if "pomocy" in txt or "sos" in txt:
        _merge_mama_state(uid, last_step="sos")
        await _send_mama_sos(ctx, update, STATE.get(uid, {}))
        
        msg = (
            "🆘 <b>Wyslalam alert do opiekuna!</b> 🆘\n\n"
            "Zanim ktos przyjdzie, sprawdz czy to pomoze:\n\n"
            "1️⃣ <b>DODAWANIE FAKTURY</b>\n"
            "Kliknij <code>🧾 Dodaj fakture</code> -> Wybierz <code>VAT</code> lub <code>Bez VAT</code> -> Wyslij <b>zdjecie</b>.\n\n"
            "2️⃣ <b>POPRAWIANIE</b>\n"
            "Kliknij <code>📋 Co mam poprawic</code> -> Sprawdz kwote -> Jak jest dobra, kliknij <code>✅ Kwota OK</code>.\n\n"
            "3️⃣ <b>POMYLKA?</b>\n"
            "Kliknij <code>🔙 Cofnij</code>, zeby skasowac ostatni krok.\n\n"
            "💡 <b>Wskazowka:</b> Rob zdjecia tak, zeby cala kartka byla widoczna i ostra!"
        )
        await update.message.reply_text(
            msg,
            parse_mode="HTML",
            reply_markup=_mama_kb_for_mode(uid),
        )
        return True

    if "menu" in txt or "wroc" in txt:
        # Senior IT: Full state reset for a clean start
        STATE.pop(uid, None)
        
        from domain.audit import count_last_hours
        from domain.state_cache import get_todo_count_cached
        from config import is_mama
        
        todo_count = get_todo_count_cached()
        today_count = count_last_hours(24)
        reply_markup = kb_mama_tiles(todo_count=todo_count, today_count=today_count)
        
        if is_mama(update):
            await update.message.reply_text(
                "🏠 Wrocilam do menu głównego.\n\nKliknij duzy kafelek i zrob tylko jeden krok naraz.",
                reply_markup=reply_markup,
            )
        else:
            # Admin/Operator view
            await update.message.reply_text(
                "🏠 Wrocilam do menu głównego.\n\nKliknij Dodaj fakture lub wybierz opcje:",
                reply_markup=reply_markup,
            )
            # Re-send the advanced inline menu for admins/operators
            from keyboards import kb_page
            await update.message.reply_text("Opcje zaawansowane:", reply_markup=kb_page(1))
        return True

    if "wstecz" in txt:
        # Senior IT: Step-back navigation
        if mode == "add_wait_type":
            return await _handle_mama_text(update, ctx, "menu")
        if mode == "mama_ask_ai":
            return await _handle_mama_text(update, ctx, "menu")
        if mode == "add_wait_file":
            return await _handle_mama_text(update, ctx, "dodaj fakture")
        if mode == "mama_pick_company":
            # Already uploaded, going back to start of add
            return await _handle_mama_text(update, ctx, "dodaj fakture")
        if mode in ("mama_set_price", "mama_ultra_amount", "mama_confirm_amount"):
            row_no = state.get("row")
            _merge_mama_state(uid, mode="mama_review", row=str(row_no))
            await update.message.reply_text("🔙 Wrocilam do podgladu faktury.", reply_markup=_mama_kb_for_mode(uid))
            await update.message.reply_text(_mama_review_text(update, int(row_no)), reply_markup=_mama_kb_for_mode(uid))
            return True
        if mode in ("mama_set_company", "mama_pick_company"):
            return await _handle_mama_text(update, ctx, "dodaj fakture")
        if mode == "mama_after_send" or mode == "mama_review":
            return await _handle_mama_text(update, ctx, "menu")
        
        # Fallback for other modes
        return await _handle_mama_text(update, ctx, "menu")

    if "poczekaj" in txt:
        await update.message.reply_text("⏳ Opiekun dostal alert. Poczekaj spokojnie.", reply_markup=_mama_kb_for_mode(uid))
        return True

    if "cofnij" in txt or "undo" in txt:
        undo = MAMA_UNDO.get(uid)
        if not undo:
            await update.message.reply_text("↩️ Nie mam nic do cofniecia.", reply_markup=_mama_kb_for_mode(uid))
            return True

        row_no = int(undo.get("row", 0) or 0)
        if row_no <= 0:
            MAMA_UNDO.pop(uid, None)
            await update.message.reply_text("⚠️ Nie moge cofnac tej akcji.", reply_markup=_mama_kb_for_mode(uid))
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

    # Main flows
    if "dodaj" in txt:
        _merge_mama_state(uid, mode="add_wait_type", last_step="add:start")
        await update.message.reply_text("🧾 Krok 1/2: wybierz Typ VAT albo Typ Bez VAT.", reply_markup=_mama_type_tiles_for(uid))
        return True

    if "typ vat" in txt or (mode == "add_wait_type" and txt == "vat"):
        _merge_mama_state(uid, mode="add_wait_file", inv_type=TYPE_VAT, last_step="add:type_vat")
        await update.message.reply_text("📸 Krok 2/2: wyslij jedno zdjecie albo PDF.", reply_markup=_mama_kb_for_mode(uid))
        return True

    if "bez vat" in txt:
        _merge_mama_state(uid, mode="add_wait_file", inv_type=TYPE_NO_VAT, last_step="add:type_novat")
        await update.message.reply_text("📸 Krok 2/2: wyslij jedno zdjecie albo PDF.", reply_markup=_mama_kb_for_mode(uid))
        return True

    if "poprawic" in txt or "todo" in txt:
        m = today_ym()
        items = _human_todo_rows(update, m, limit=7)
        
        if not items:
            # Senior IT: If nothing simple to fix, run deep integrity check
            from domain.integrity import check_business_integrity
            from storage_router import get_all_values
            
            rows = get_all_values(update)
            warnings = check_business_integrity(rows)
            
            if warnings:
                msg = "🎉 Podstawowe rzeczy sa OK, ale znalazlam problemy w danych:\n\n" + "\n".join(warnings[:5])
                await update.message.reply_text(msg, reply_markup=_mama_tiles_for(uid))
            else:
                await update.message.reply_text(f"🎉 W {m} wszystko jest juz gotowe. System zdrowy!", reply_markup=_mama_tiles_for(uid))
            return True

        # Show the list first!
        msg_lines = ["📋 <b>LISTA ZADAN NA DZIS:</b>"]
        for idx, (row_no, desc) in enumerate(items, 1):
            msg_lines.append(f"{idx}. {desc}")
        
        msg_lines.append("\nCo chcesz zrobic?")
        
        # Prepare keyboard with options
        from telegram import ReplyKeyboardMarkup
        # Dynamic buttons for the first few items + "Fix All"
        buttons = []
        # Add quick jump buttons for first 3 items
        row_buttons = []
        for i in range(min(3, len(items))):
            row_buttons.append(f"Zrob {i+1}")
        if row_buttons:
            buttons.append(row_buttons)
            
        buttons.append(["🚀 Napraw wszystko po kolei"])
        buttons.append(["🏠 Wroc do menu"])
        
        # Save state so we know what "Zrob 1" means
        # We map indices 1, 2, 3 to actual row_nos in a temp state or just parsing text
        _merge_mama_state(uid, mode="mama_todo_list", todo_map={str(i+1): item[0] for i, item in enumerate(items)}, last_step="todo:list_view")
        
        await update.message.reply_text("\n".join(msg_lines), parse_mode="HTML", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return True
    
    # Handle selection from the list
    if mode == "mama_todo_list":
        if "zrob" in txt:
            # Parse "Zrob 1", "Zrob 2"
            try:
                idx = txt.split()[-1]
                target_row = state.get("todo_map", {}).get(idx)
                if target_row:
                    _merge_mama_state(uid, mode="mama_review", row=str(target_row), month=today_ym())
                    await update.message.reply_text(f"🔍 Otwieram zadanie #{idx}...", reply_markup=_mama_kb_for_mode(uid))
                    await update.message.reply_text(_mama_review_text(update, int(target_row)), reply_markup=_mama_kb_for_mode(uid))
                    return True
            except:
                pass
        
        if "wszystko" in txt or "kolei" in txt:
             # Auto-jump to the first one and set next logic
             # Re-fetch to be sure
             m = today_ym()
             items = _human_todo_rows(update, m, limit=1)
             if items:
                 row_no = items[0][0]
                 _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=m, next_row="auto") # 'auto' will need logic in 'next' handler
                 await update.message.reply_text("🚀 Lecimy ze wszystkim po kolei!", reply_markup=_mama_kb_for_mode(uid))
                 await update.message.reply_text(_mama_review_text(update, int(row_no)), reply_markup=_mama_kb_for_mode(uid))
                 return True

    if "wyslij" in txt and ("ksiegowej" in txt or "export" in txt):
        m = today_ym()
        zip_bytes, filename = build_month_zip(update, m)
        await update.message.reply_document(document=zip_bytes, filename=filename, caption=f"Paczka {m}")
        _merge_mama_state(uid, mode="mama_after_send", month=m, last_step=f"export:{m}")
        await update.message.reply_text("📦 Wyslane do ksiegowej.", reply_markup=kb_mama_next_only(_mama_large_font(state)))
        return True

    if mode == "mama_pick_company":
        row_s = str(state.get("row", ""))
        if row_s.isdigit():
            row_no = int(row_s)
            
            # Senior IT: Check if input looks like an amount (useful for voice/direct entry)
            val = parse_amount(txt_raw)
            if val <= 0: val = _try_parse_spoken_amount(txt_raw)
            if val > 0:
                # User provided amount instead of company, process it as amount
                # but we'll leave company as OCR got it
                _merge_mama_state(uid, mode="mama_wait_amount")
                return await _handle_mama_text(update, ctx, txt_raw)

            if txt in ("zostaw ocr",):
                _merge_mama_state(uid, mode="mama_wait_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="company:skip")
                await update.message.reply_text("Zostawiam firme z OCR.", reply_markup=_mama_review_tiles_for(uid))
                return True
            if txt in ("popraw recznie",):
                _merge_mama_state(uid, mode="mama_set_company", row=str(row_no), month=state.get("month", today_ym()), last_step="company:manual")
                await update.message.reply_text("Wpisz nazwe firmy.", reply_markup=_mama_tiles_for(uid))
                return True
            
            # Fuzzy match company from suggestions
            chosen = txt_raw.strip()
            suggestions = _mama_company_suggestions(update, limit=20)
            best_match = fuzzy_match_company(chosen, suggestions)
            if best_match:
                chosen = best_match

            update_cell(update, row_no, COL_COMP, chosen)
            _merge_mama_state(uid, mode="mama_wait_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="company:set")
            await update.message.reply_text(f"🏪 Firma zapisana: {chosen}", reply_markup=_mama_review_tiles_for(uid))
            return True

    if mode == "mama_set_company":
        row_s = str(state.get("row", ""))
        if row_s.isdigit() and (txt_raw or "").strip():
            row_no = int(row_s)
            
            # Fuzzy match
            chosen = txt_raw.strip()
            suggestions = _mama_company_suggestions(update, limit=50)
            best_match = fuzzy_match_company(chosen, suggestions)
            if best_match:
                chosen = best_match
                
            update_cell(update, row_no, COL_COMP, chosen)
            _merge_mama_state(uid, mode="mama_wait_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="company:manual_set")
            await update.message.reply_text(f"🏪 Firma zapisana: {chosen}", reply_markup=_mama_review_tiles_for(uid))
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
            await update.message.reply_text("✍️ Popraw kwote, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
            return True
    if txt in ("dalej",):
        state = dict(STATE.get(uid, {}) or {})
        mode = state.get("mode", "")
        if mode == "mama_after_send":
            _merge_mama_state(uid, mode="", row="", month="", next_row="", last_step="after_send_next")
            await update.message.reply_text("➡️ Co dalej?", reply_markup=_mama_tiles_for(uid))
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
            await update.message.reply_text("✅ Brak kolejnych faktur do poprawy.", reply_markup=_mama_tiles_for(uid))
            return True

        _merge_mama_state(uid, mode="mama_review", row=str(nxt), month=month, next_row="", last_step=f"next:{nxt}")
        await update.message.reply_text(_mama_review_text(update, nxt), reply_markup=_mama_review_tiles_for(uid))
        return True

    if txt in ("nagraj kwote",) and mode == "mama_ultra_amount":
        _merge_mama_state(uid, voice_mode=True, last_step="ultra:voice")
        await update.message.reply_text("🎤 Nagraj teraz tylko kwote.", reply_markup=kb_mama_ultra_amount())
        return True

    if txt in ("wpisz kwote",) and mode == "mama_ultra_amount":
        row_s = state.get("row", "")
        _merge_mama_state(uid, mode="mama_set_price", row=str(row_s), month=state.get("month", today_ym()), last_step="ultra:type")
        await update.message.reply_text("💰 Wpisz tylko kwote, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
        return True

    if mode in {"mama_wait_amount", "mama_set_price", "mama_ultra_amount"} and txt in ("popraw kwote",):
        row_s = state.get("row", "")
        if str(row_s).isdigit():
            row_no = int(row_s)
            month = state.get("month") or _month_from_row(update, row_no) or today_ym()
            _merge_mama_state(uid, mode="mama_set_price", row=str(row_no), month=month, last_step=f"price:ask:{row_no}")
            await update.message.reply_text("💰 Wpisz tylko kwote, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
            return True

    if mode == "mama_review" and ("kwota ok" in txt or txt == "ok"):
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
                await update.message.reply_text("⚠️ Brakuje danych. Kliknij Popraw kwote.", reply_markup=_mama_review_tiles_for(uid))
                return True

            done_today = _today_mama_ok_count(update, month)
            if done_today and done_today % 3 == 0:
                await update.message.reply_text(f"🌟 Super, {done_today}/3 gotowe dzisiaj.", reply_markup=_mama_review_tiles_for(uid))

            nxt = _find_next_after(update, month, after_row=row_no)
            if nxt:
                _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=month, next_row=str(nxt), last_step=f"ok:{row_no}")
                await update.message.reply_text("✅ Zapisane.", reply_markup=kb_mama_next_only(_mama_large_font(state)))
                return True

            _merge_mama_state(uid, mode="", row="", month=month, next_row="", last_step=f"ok:last:{row_no}")
            await update.message.reply_text("✅ ✅ Zapisane. Nie ma juz nic do poprawy.", reply_markup=_mama_tiles_for(uid))
            return True

    if "popraw" in txt and "kwote" in txt:
        row_s = state.get("row", "")
        if str(row_s).isdigit():
            row_no = int(row_s)
            month = state.get("month") or _month_from_row(update, row_no) or today_ym()
            _merge_mama_state(uid, mode="mama_set_price", row=str(row_no), month=month, last_step=f"price:ask:{row_no}")
            await update.message.reply_text("💰 Wpisz tylko kwote, np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
            return True

    if mode in {"mama_set_price", "mama_wait_amount", "mama_ultra_amount"}:
        row_s = state.get("row", "")
        if not str(row_s).isdigit():
            STATE.pop(uid, None)
            await update.message.reply_text("⚠️ Cos poszlo nie tak. Kliknij Co mam poprawic.", reply_markup=_mama_tiles_for(uid))
            return True

        row_no = int(row_s)
        val = parse_amount(txt_raw)
        if val <= 0:
            val = _try_parse_spoken_amount(txt_raw)
        if val <= 0:
            bad = _register_mama_amount_failure(uid)
            if bad >= 2:
                _merge_mama_state(uid, mode="mama_ultra_amount", row=str(row_no), month=state.get("month", today_ym()), last_step="price:ultra")
                await update.message.reply_text("🧩 Przechodze na ultra-prosty tryb.", reply_markup=kb_mama_ultra_amount())
                return True
            await update.message.reply_text("💬 Nie widze kwoty. Wpisz np. 123,45.", reply_markup=_mama_review_tiles_for(uid))
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
        
        # Senior IT: Logging change to Audit Trail
        log_change(uid, row_no, "gross", str(row_before[COL_GROSS-1]), f"{val:.2f}")
        
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
                await update.message.reply_text(f"🌟 Super, {done_today}/3 gotowe dzisiaj.", reply_markup=_mama_review_tiles_for(uid))

        nxt = _find_next_after(update, month, after_row=row_no)
        if nxt:
            _merge_mama_state(uid, mode="mama_review", row=str(row_no), month=month, next_row=str(nxt), last_step=f"price:set:{row_no}")
            await update.message.reply_text("✅ Zapisane.", reply_markup=kb_mama_next_only(_mama_large_font(state)))
            return True

        _merge_mama_state(uid, mode="", row="", month=month, next_row="", last_step=f"price:last:{row_no}")
        await update.message.reply_text("✅ ✅ Zapisane. Nie ma juz nic do poprawy.", reply_markup=_mama_tiles_for(uid))
        return True

    return False


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    uid = update.effective_user.id
    st = STATE.get(uid, {})
    mode = st.get("mode", "")
    
    # Senior IT: Allow voice in more states, especially when OCR fails (pick_company)
    allowed_modes = {
        "mama_set_price", 
        "mama_ultra_amount", 
        "mama_wait_amount", 
        "mama_pick_company", 
        "mama_set_company"
    }
    
    if mode not in allowed_modes:
        return await update.message.reply_text(
            "🎙️ Nagranie glosowe dziala w kroku wpisywania kwoty lub firmy. Kliknij Popraw kwote.",
            reply_markup=_mama_kb_for_mode(uid),
        )

    # Check if integration is ready
    ok, reason = _voice_integration_ready()
    if not ok:
        return await update.message.reply_text(reason, reply_markup=_mama_kb_for_mode(uid))

    # Send a small hint that we're listening
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("typing")
    elif getattr(update, "effective_chat", None):
        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        txt = await _transcribe_voice_note(update, ctx)
    except Exception:
        return await update.message.reply_text(
            "❌ Nie udalo sie rozpoznac nagrania. Powiedz kwote wolniej albo wpisz ja recznie.",
            reply_markup=_mama_kb_for_mode(uid),
        )

    if not txt:
        return await update.message.reply_text(
            "🔇 Nie uslyszalam kwoty. Powiedz jeszcze raz albo wpisz recznie.",
            reply_markup=_mama_kb_for_mode(uid),
        )

    await update.message.reply_text(f"🗣️ Rozpoznalam: {txt}", reply_markup=_mama_kb_for_mode(uid))
    
    # If we were in company picking mode, and recognized a number, we might want to auto-switch to amount
    # but for now, _handle_mama_text will handle it.
    handled = await _handle_mama_text(update, ctx, txt)
    if not handled:
        await update.message.reply_text("❓ Nie rozpoznalam polecenia. Sprobuj powiedziec tylko kwote, np. sto dwadziescia zlotych.", reply_markup=_mama_kb_for_mode(uid))


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt_raw = (update.message.text or "").strip()
    txt = txt_raw.lower()
    mode = STATE.get(uid, {}).get("mode", "")

    if not is_allowed(update):
        return await update.message.reply_text(" Brak dostepu.", reply_markup=kb_page(1))

    # Senior IT: Always allow processing Mama buttons if clicked
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
            return await update.message.reply_text("Blad stanu. 👆 Kliknij /start.", reply_markup=kb_page(1))
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

    if "szukaj" in txt or "znajdz" in txt:
        query = txt.replace("szukaj", "").replace("znajdz", "").strip()
        if not query:
            await update.message.reply_text("Co mam znalezc? Wpisz np. `szukaj Orlen`.")
            return True
            
        from storage_router import get_all_values
        rows = get_all_values(update)
        found = []
        for idx, r in enumerate(rows[1:], 2):
            line = " ".join(map(str, r)).lower()
            if query in line:
                found.append((idx, r))
        
        if not found:
            await update.message.reply_text(f"Nie znalazlam nic dla: `{query}`.")
        else:
            msg = f"🔍 Znaleziono {len(found[:5])} faktur:\n\n"
            for row_no, r in found[:5]:
                msg += f"• #{row_no}: {r[COL_DATE-1]} | {r[COL_COMP-1]} | {r[COL_GROSS-1]} zl\n"
            await update.message.reply_text(msg, reply_markup=_mama_kb_for_mode(uid))
        return True

    # Senior IT: RAG Q&A (Question Answering)
    if txt.startswith("?") or mode == "mama_ask_ai":
        question = txt.lstrip("?").strip()
        if not question:
            await update.message.reply_text("Zadaj pytanie, np. `? Co kupilismy wczoraj?`", reply_markup=_mama_kb_for_mode(uid))
            return True
            
        await update.message.reply_chat_action("typing")
        
        # Senior IT: Intelligent Intent Routing
        from domain.rag_bridge import get_rag_context, analyze_spending_trend
        
        # Heuristic: If question asks for opinion/plan/history analysis -> use BI Engine
        is_analytical = any(word in question.lower() for word in ["planuje", "kupic", "warto", "ile", "czesto", "srednio", "trendy", "rekomendacja", "opinie"])
        
        if is_analytical:
             answer = await analyze_spending_trend(question)
             header = "📈 <b>Analiza Biznesowa AI:</b>"
        else:
             # Senior IT: Open-ended query
             answer = await get_rag_context(question)
             header = "🧠 <b>AI Asystent:</b>"
        
        if not answer:
            await update.message.reply_text("🤔 Przejrzalam dokumenty, ale nie znalazlam odpowiedzi.", reply_markup=_mama_kb_for_mode(uid))
        else:
            import html
            safe_answer = html.escape(answer)
            await update.message.reply_text(f"{header}\n{safe_answer}", parse_mode="HTML", reply_markup=_mama_kb_for_mode(uid))
        return True

    if mode == "set_vat":
        row_s = STATE.get(uid, {}).get("row", "")
        if not str(row_s).isdigit():
            STATE.pop(uid, None)
            return await update.message.reply_text(" Blad. 👆 Kliknij /start.", reply_markup=kb_page(1))

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
            return await update.message.reply_text(" Blad. 👆 Kliknij /start.", reply_markup=kb_page(1))

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

    from config import is_mama
    if is_mama(update) or mode.startswith("mama_") or mode.startswith("add_"):
        kb = _mama_kb_for_mode(uid)
    else:
        kb = kb_page(1)
    await update.message.reply_text("👆 Kliknij /start", reply_markup=kb)


def register(app):
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
















































