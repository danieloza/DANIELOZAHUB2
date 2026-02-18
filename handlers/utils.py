# -*- coding: utf-8 -*-
from typing import Optional
from telegram import Update

from config import env, ENV_ALLOWED

def parse_allowed_set() -> Optional[set]:
    raw = env(ENV_ALLOWED, "")
    if not raw:
        return None
    s = set()
    for p in raw.split(","):
        p = p.strip()
        if p.isdigit():
            s.add(int(p))
    return s if s else None

ALLOWED = parse_allowed_set()

def is_allowed(update: Update) -> bool:
    if ALLOWED is None:
        return True
    uid = update.effective_user.id if update.effective_user else None
    return uid in ALLOWED

async def deny(update: Update):
    if update.callback_query:
        await update.callback_query.answer(" Brak dostepu", show_alert=True)
    elif update.message:
        await update.message.reply_text(" Brak dostepu do bota.")
