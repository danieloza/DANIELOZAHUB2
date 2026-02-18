# -*- coding: utf-8 -*-
import logging
import time as _time
from datetime import time
from types import SimpleNamespace

from telegram.ext import Application

from config import (
    MAMA_STUCK_ALERT_MIN,
    REMINDER_HOUR,
    REMINDER_MINUTE,
    STATE,
    WEEKLY_REPORT_HOUR,
    WEEKLY_REPORT_MINUTE,
    WEEKLY_REPORT_WEEKDAY,
    admin_ids,
    mama_ids,
)
from domain.audit import mama_activity_last_24h, mama_weekly_summary
from domain.backup import restore_test_latest_backup
from domain.retention import apply_retention
from handlers.callbacks import compute_month_stats, today_ym
from keyboards import kb_mama_daily_one_button
from storage_router import get_all_values, process_retry_backlog

log = logging.getLogger("danex.reminders")


_MAMA_ACTIVE_MODES = {
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


def _fake_update(uid: int):
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid))


async def _send_todo_reminder(ctx):
    month = today_ym()
    for uid in sorted(admin_ids()):
        upd = _fake_update(uid)
        try:
            get_all_values(upd)
            st = compute_month_stats(upd, month)
            mama = mama_activity_last_24h(mama_ids())
            txt = (
                f"MAMA SKROT {month}\n"
                f"Dodala (24h): {mama.get('added', 0)}\n"
                f"Czeka na poprawe: {len(st['todo'])}\n"
                f"Brak kwoty: {len(st['todo_missing_price'])}\n"
                f"Wyslala do ksiegowej: {st['sent']}\n"
                f"Gotowe: {st['ok']}"
            )
            await ctx.bot.send_message(chat_id=uid, text=txt)
        except Exception as exc:
            await ctx.bot.send_message(chat_id=uid, text=f"REMINDER ERROR: {exc}")


async def _send_mama_daily_one_button(ctx):
    for uid in sorted(mama_ids()):
        try:
            await ctx.bot.send_message(
                chat_id=uid,
                text="Dzisiaj dodaj fakture",
                reply_markup=kb_mama_daily_one_button(),
            )
        except Exception:
            continue


async def _send_weekly_admin_report(ctx):
    summary = mama_weekly_summary(mama_ids(), days=7)
    tops = summary.get("top_fixed", [])
    tops_txt = "\n".join(f"- wiersz {x.get('row')}: {x.get('count')} poprawek" for x in tops) if tops else "- brak"
    msg = (
        "RAPORT TYGODNIOWY MAMA\n"
        f"dodane: {summary.get('added', 0)}\n"
        f"czeka: {summary.get('waiting', 0)}\n"
        f"wyslane: {summary.get('sent', 0)}\n"
        f"najczesciej poprawiane:\n{tops_txt}"
    )
    for uid in sorted(admin_ids()):
        try:
            await ctx.bot.send_message(chat_id=uid, text=msg)
        except Exception:
            continue


async def _monitor_mama_soft_alerts(ctx):
    ids = sorted(admin_ids())
    if not ids:
        return

    now_ts = float(_time.time())
    threshold_sec = max(1, MAMA_STUCK_ALERT_MIN) * 60
    for uid in sorted(mama_ids()):
        st = dict(STATE.get(uid, {}) or {})
        mode = str(st.get("mode", "") or "")
        if mode not in _MAMA_ACTIVE_MODES:
            continue

        last_step_ts = float(st.get("last_step_ts", 0.0) or 0.0)
        if last_step_ts <= 0:
            continue
        if now_ts - last_step_ts < threshold_sec:
            continue

        signature = f"{mode}:{st.get('row', '-') }:{st.get('last_step', '-') }"
        if st.get("stuck_alert_signature", "") == signature:
            continue

        msg = (
            "MAMA SOFT ALERT\n"
            f"reason: stuck_over_{MAMA_STUCK_ALERT_MIN}min\n"
            f"user_id: {uid}\n"
            f"mode: {mode}\n"
            f"row: {st.get('row', '-') }\n"
            f"last_step: {st.get('last_step', '-') }"
        )
        for aid in ids:
            try:
                await ctx.bot.send_message(chat_id=aid, text=msg)
            except Exception:
                continue

        st["stuck_alert_signature"] = signature
        STATE[uid] = st


async def _maintenance_job(ctx):
    res_retry = process_retry_backlog(limit=100)
    res_ret = apply_retention()
    res_restore = restore_test_latest_backup()
    mama = mama_activity_last_24h(mama_ids())
    if not admin_ids():
        return
    msg = (
        "MAINTENANCE\n"
        f"retry_ok: {res_retry.get('ok')} | retry_failed: {res_retry.get('failed')} | to_dlq: {res_retry.get('moved_to_dlq')}\n"
        f"retention: inv={res_ret.get('deleted_invoices')} logs={res_ret.get('deleted_logs')} anon={res_ret.get('anonymized_audit_rows')}\n"
        f"restore_test_ok: {res_restore.get('ok')} | rows={res_restore.get('rows', 0)} | err={res_restore.get('error', '') or 'none'}\n"
        f"mama_24h: added={mama.get('added')} status_changes={mama.get('status_changes')} events={mama.get('total_events')}"
    )
    for uid in sorted(admin_ids()):
        try:
            await ctx.bot.send_message(chat_id=uid, text=msg)
        except Exception:
            continue


def register_reminders(app: Application) -> None:
    if app.job_queue is None:
        log.warning("JobQueue unavailable. Install python-telegram-bot[job-queue] to enable reminders.")
        return

    app.job_queue.run_daily(
        _send_mama_daily_one_button,
        time=time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE),
        name="mama_daily_one_button",
    )

    app.job_queue.run_repeating(
        _monitor_mama_soft_alerts,
        interval=5 * 60,
        first=90,
        name="mama_soft_monitor",
    )

    if admin_ids():
        app.job_queue.run_daily(
            _send_todo_reminder,
            time=time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE),
            name="todo_daily_reminder",
        )
        app.job_queue.run_daily(
            _send_weekly_admin_report,
            time=time(hour=WEEKLY_REPORT_HOUR, minute=WEEKLY_REPORT_MINUTE),
            days=(max(0, min(6, WEEKLY_REPORT_WEEKDAY)),),
            name="weekly_admin_report",
        )
        app.job_queue.run_repeating(
            _maintenance_job,
            interval=4 * 60 * 60,
            first=60,
            name="maintenance_job",
        )

