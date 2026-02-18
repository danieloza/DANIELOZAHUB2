# -*- coding: utf-8 -*-
from telegram.error import BadRequest

async def safe_answer(q):
    try:
        await q.answer()
    except BadRequest as e:
        s = str(e).lower()
        if "query is too old" in s or "query id is invalid" in s:
            return
        raise

async def safe_edit(q, text, kb=None):
    try:
        return await q.edit_message_text(text, reply_markup=kb)
    except BadRequest as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return
        if "message can't be edited" in s or "message to edit not found" in s:
            try:
                await q.message.reply_text(text, reply_markup=kb)
            except:
                pass
            return
        raise
