# -*- coding: utf-8 -*-
import time
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import (
    ENV_SHEET_ID,
    ENV_SHEET_NAME,
    HEALTH_ALERTS_ENABLED,
    HEALTH_ALERT_COOLDOWN_MIN,
    admin_ids,
    env,
    is_admin,
    is_allowed,
    is_mama,
    is_operator,
    user_role,
)
from domain.audit import count_last_hours, read_recent
from domain.backup import build_backup_zip, restore_test_latest_backup
from domain.metrics import summarize_24h
from domain.reporting import parse_month_arg
from domain.retention import apply_retention
from handlers.callbacks import build_month_zip, compute_month_stats
from handlers.errors import error_count_last_24h, get_last_error
from keyboards import kb_mama_tiles, kb_page
from sheets_service import sa_path, ws
from storage_router import get_all_values, get_storage, process_retry_backlog, retry_stats

_BOOT_TS = datetime.now()
_LAST_HEALTH_ALERT_AT: datetime | None = None
_LAST_HEALTH_ALERT_STATUS = "ok"


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await update.message.reply_text("Brak dostepu.")
    if is_mama(update):
        return await update.message.reply_text(
            "Tryb Mama\nKliknij duzy kafelek i zrob tylko jeden krok naraz.\nMasz tez: Cofnij, Potrzebuje pomocy (SOS), i opcjonalnie Tryb glosowy.",
            reply_markup=kb_mama_tiles(),
        )
    await update.message.reply_text(
        "Danex Faktury\n"
        "Kliknij Dodaj fakture, wybierz VAT/Bez VAT, wyslij PDF/zdjecie.\n"
        "Potem: Ustaw kwote / OK / Wyslane.\n\nMenu:",
        reply_markup=kb_page(1),
    )


async def cmd_whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"user_id: {update.effective_user.id}")


async def cmd_role(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await update.message.reply_text("Brak dostepu.")
    await update.message.reply_text(f"Twoja rola: {user_role(update)}")


async def cmd_backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_operator(update):
        return await update.message.reply_text("Tylko operator lub admin.")
    zip_bytes, filename = build_backup_zip(save_local=True)
    await update.message.reply_document(document=zip_bytes, filename=filename, caption="Backup ZIP")


async def cmd_restoretest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await update.message.reply_text("Brak dostepu.")
    res = restore_test_latest_backup()
    await update.message.reply_text(
        "RESTORE-TEST\n"
        f"ok: {res.get('ok')}\n"
        f"path: {res.get('path', '-') }\n"
        f"csv_files: {res.get('csv_files', 0)}\n"
        f"rows: {res.get('rows', 0)}\n"
        f"error: {res.get('error', '') or 'none'}",
        reply_markup=kb_page(1),
    )


async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_operator(update):
        return await update.message.reply_text("Tylko operator lub admin.")

    month = parse_month_arg(list(ctx.args or []))
    zip_bytes, filename = build_month_zip(update, month)
    st = compute_month_stats(update, month)
    caption = (
        f"Export {month}\n"
        f"Brutto: {st['gross']:.2f} | Netto: {st['net']:.2f} | VAT: {st['vat']:.2f}\n"
        f"TODO: {len(st['todo'])} | Brak kwoty: {len(st['todo_missing_price'])}"
    )
    await update.message.reply_document(document=zip_bytes, filename=filename, caption=caption)


async def cmd_diag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await update.message.reply_text("Brak dostepu.")

    diag_mode = ((ctx.args or [""])[0].strip().lower() if getattr(ctx, "args", None) else "")
    run_rw = diag_mode in {"rw", "write", "full"}

    backend = type(get_storage(update)).__name__
    sheet_id = env(ENV_SHEET_ID, "")
    sheet_name = env(ENV_SHEET_NAME, "Arkusz1")
    sa = sa_path()
    sa_exists = Path(sa).exists()

    lines = [
        "DIAG",
        f"user_id: {update.effective_user.id}",
        f"role: {user_role(update)}",
        f"backend: {backend}",
        f"mode: {'RW' if run_rw else 'BASIC'}",
        f"sheet_id_set: {'yes' if bool(sheet_id) else 'no'}",
        f"sheet_name: {sheet_name}",
        f"service_account_path: {sa}",
        f"service_account_exists: {'yes' if sa_exists else 'no'}",
    ]

    t0 = time.perf_counter()
    try:
        get_all_values(update)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        lines.append(f"backend_read_latency_ms: {latency_ms}")
    except Exception as exc:
        lines.append(f"backend_read_error: {exc}")

    if backend == "SheetsStorage":
        try:
            worksheet = ws()
            header = worksheet.row_values(1)
            header_preview = ", ".join(header[:5]) if header else "(empty)"
            lines.extend(
                [
                    "sheets_conn: OK",
                    f"worksheet_title: {worksheet.title}",
                    f"worksheet_rows: {worksheet.row_count}",
                    f"worksheet_cols: {worksheet.col_count}",
                    f"header_preview: {header_preview}",
                ]
            )

            if run_rw:
                def _to_a1_col(col_idx: int) -> str:
                    out = []
                    n = max(1, int(col_idx))
                    while n > 0:
                        n, r = divmod(n - 1, 26)
                        out.append(chr(ord("A") + r))
                    return "".join(reversed(out))

                probe_col = max(1, int(worksheet.col_count or 1))
                probe_row = 2 if int(worksheet.row_count or 1) >= 2 else 1
                probe_cell = f"{_to_a1_col(probe_col)}{probe_row}"
                token = f"DIAG_{datetime.now():%Y%m%d_%H%M%S}"
                old_value = worksheet.acell(probe_cell).value
                worksheet.update_acell(probe_cell, token)
                read_back = worksheet.acell(probe_cell).value
                worksheet.update_acell(probe_cell, old_value or "")
                lines.extend([f"rw_probe_cell: {probe_cell}", f"rw_write_ok: {'yes' if read_back == token else 'no'}"])
            else:
                lines.append("rw_test: skipped (use /diag rw)")

        except Exception as exc:
            lines.extend(["sheets_conn: ERROR", f"sheets_error: {exc}"])
    else:
        lines.append("sheets_conn: skipped (user routed to API backend)")

    await update.message.reply_text("\n".join(lines), reply_markup=kb_page(1))


async def cmd_metrics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await update.message.reply_text("Brak dostepu.")
    m = summarize_24h()
    rq = retry_stats()
    await update.message.reply_text(
        "METRICS 24H\n"
        f"ocr_total: {m['ocr_total_24h']}\n"
        f"ocr_success_rate: {m['ocr_success_rate']}%\n"
        f"ocr_latency_avg_ms: {m['ocr_latency_avg_ms']}\n"
        f"ocr_latency_p95_ms: {m['ocr_latency_p95_ms']}\n"
        f"errors_24h: {m['errors_24h']}\n"
        f"events_24h: {m['events_24h']}\n"
        f"retry_queue: {rq['queue']}\n"
        f"dead_letter: {rq['dlq']}",
        reply_markup=kb_page(1),
    )


async def cmd_retry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await update.message.reply_text("Brak dostepu.")
    res = process_retry_backlog(limit=50)
    rq = retry_stats()
    await update.message.reply_text(
        "RETRY QUEUE\n"
        f"processed: {res.get('processed')}\n"
        f"ok: {res.get('ok')}\n"
        f"failed: {res.get('failed')}\n"
        f"moved_to_dlq: {res.get('moved_to_dlq')}\n"
        f"queue_now: {rq['queue']}\n"
        f"dlq_now: {rq['dlq']}",
        reply_markup=kb_page(1),
    )


async def cmd_retention(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await update.message.reply_text("Brak dostepu.")
    res = apply_retention()
    await update.message.reply_text(
        "RETENTION\n"
        f"deleted_invoices: {res['deleted_invoices']}\n"
        f"deleted_logs: {res['deleted_logs']}\n"
        f"anonymized_audit_rows: {res['anonymized_audit_rows']}\n"
        f"pruned_idempotency_rows: {res['pruned_idempotency_rows']}",
        reply_markup=kb_page(1),
    )


def _health_alert_due(status: str) -> bool:
    global _LAST_HEALTH_ALERT_AT, _LAST_HEALTH_ALERT_STATUS
    if not HEALTH_ALERTS_ENABLED or status == "ok":
        return False
    now = datetime.now()
    if _LAST_HEALTH_ALERT_AT is None:
        _LAST_HEALTH_ALERT_AT = now
        _LAST_HEALTH_ALERT_STATUS = status
        return True
    elapsed_min = (now - _LAST_HEALTH_ALERT_AT).total_seconds() / 60.0
    if status != _LAST_HEALTH_ALERT_STATUS or elapsed_min >= HEALTH_ALERT_COOLDOWN_MIN:
        _LAST_HEALTH_ALERT_AT = now
        _LAST_HEALTH_ALERT_STATUS = status
        return True
    return False


async def _notify_health_alert(ctx: ContextTypes.DEFAULT_TYPE, lines: list[str]) -> None:
    ids = sorted(admin_ids())
    if not ids:
        return
    msg = "ALERT HEALTH\n" + "\n".join(lines)
    for uid in ids:
        try:
            await ctx.bot.send_message(chat_id=uid, text=msg)
        except Exception:
            continue


async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await update.message.reply_text("Brak dostepu.")

    backend = type(get_storage(update)).__name__
    status = "ok"
    detail = "ready"
    rows = 0
    latency_ms = -1

    t0 = time.perf_counter()
    try:
        allv = get_all_values(update)
        rows = max(0, len(allv) - 1)
        latency_ms = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        status = "fail"
        detail = str(exc)

    err_24h = error_count_last_24h()
    metrics = summarize_24h()
    rq = retry_stats()

    if status == "ok" and (latency_ms > 1500 or err_24h > 20 or rq["queue"] > 20):
        status = "degraded"
        detail = "high latency/errors/retry queue"

    uptime = datetime.now() - _BOOT_TS
    last_error = get_last_error()
    lines = [
        "HEALTH",
        f"status: {status}",
        f"detail: {detail}",
        f"backend: {backend}",
        f"rows_seen: {rows}",
        f"latency_ms: {latency_ms}",
        f"uptime_sec: {int(uptime.total_seconds())}",
        f"last_error_at: {last_error.get('at') or 'none'}",
        f"last_error_msg: {last_error.get('message') or 'none'}",
        f"errors_24h: {err_24h}",
        f"audit_events_24h: {count_last_hours(24)}",
        f"ocr_success_rate_24h: {metrics['ocr_success_rate']}%",
        f"ocr_latency_p95_ms_24h: {metrics['ocr_latency_p95_ms']}",
        f"retry_queue: {rq['queue']}",
        f"dead_letter: {rq['dlq']}",
        f"ts: {datetime.now():%Y-%m-%d %H:%M:%S}",
    ]
    await update.message.reply_text("\n".join(lines), reply_markup=kb_page(1))

    if _health_alert_due(status):
        await _notify_health_alert(ctx, lines[1:])


async def cmd_audit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await update.message.reply_text("Brak dostepu.")

    limit = 15
    if ctx.args and ctx.args[0].isdigit():
        limit = max(1, min(100, int(ctx.args[0])))

    events = read_recent(limit)
    if not events:
        return await update.message.reply_text("Brak wpisow audit.", reply_markup=kb_page(1))

    lines = ["AUDIT (najnowsze):"]
    for e in events[-limit:]:
        lines.append(
            f"{e.get('ts')} | {e.get('event')} | uid={e.get('user_id')} | rid={e.get('request_id', '-')} | row={e.get('row_no', '-')} | {e.get('source', '')}"
        )

    await update.message.reply_text("\n".join(lines[-30:]), reply_markup=kb_page(1))


def register(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("role", cmd_role))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("restoretest", cmd_restoretest))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("diag", cmd_diag))
    app.add_handler(CommandHandler("metrics", cmd_metrics))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("retention", cmd_retention))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("audit", cmd_audit))


