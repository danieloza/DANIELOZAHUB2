# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes


log = logging.getLogger("danex.error")
_LAST_ERROR = {"at": None, "message": ""}
_ERROR_TIMES: list[datetime] = []


def _trim_errors(window_hours: int = 24) -> None:
    cut = datetime.now() - timedelta(hours=window_hours)
    while _ERROR_TIMES and _ERROR_TIMES[0] < cut:
        _ERROR_TIMES.pop(0)


def get_last_error() -> dict:
    return dict(_LAST_ERROR)


def error_count_last_24h() -> int:
    _trim_errors(24)
    return len(_ERROR_TIMES)


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    err = getattr(ctx, "error", None)
    now = datetime.now()
    _LAST_ERROR["at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    _LAST_ERROR["message"] = str(err) if err else "(unknown error)"
    _ERROR_TIMES.append(now)
    _trim_errors(24)

    log.exception("Unhandled bot error", exc_info=err)

    if not isinstance(update, Update):
        return

    chat = update.effective_chat
    if not chat:
        return

    try:
        await ctx.bot.send_message(
            chat_id=chat.id,
            text="Wystapil blad techniczny. Sprobuj ponownie za chwile.",
        )
    except Exception:
        log.exception("Failed to send error message to chat_id=%s", chat.id)
