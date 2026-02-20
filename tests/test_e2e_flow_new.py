import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import handlers.callbacks as callbacks
import handlers.commands as commands
import handlers.files as files
import handlers.reminders as reminders
from domain.backup import restore_test_zip
from domain.retry_queue import enqueue, process_queue
from domain.secrets import secret_env


def run(coro):
    return asyncio.run(coro)


def test_secret_env_sm_provider_env(monkeypatch):
    monkeypatch.setenv("SECRET_PROVIDER", "env")
    monkeypatch.setenv("BOT_API_PASSWORD", "sm://BOT_API_PASSWORD_SECRET")
    monkeypatch.setenv("BOT_API_PASSWORD_SECRET", "abc123")
    assert secret_env("BOT_API_PASSWORD") == "abc123"


def test_retry_queue_moves_to_dlq_after_failures(tmp_path, monkeypatch):
    monkeypatch.setattr("domain.retry_queue._QUEUE_FILE", tmp_path / "q.json")
    monkeypatch.setattr("domain.retry_queue._DLQ_FILE", tmp_path / "dlq.json")

    enqueue("append_row", {"backend": "SheetsStorage", "user_id": 1, "values": []}, error="x", max_attempts=1, delay_sec=0)

    def always_fail(_):
        raise RuntimeError("boom")

    out = process_queue(always_fail, limit=10)
    assert out["moved_to_dlq"] == 1


def test_restore_test_zip_ok():
    zip_bytes, _ = callbacks.build_month_zip(
        SimpleNamespace(effective_user=SimpleNamespace(id=1)),
        "2026-02",
    ) if False else (b"", "")

    # Build a minimal valid zip without hitting storage layer.
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("export_2026-02.csv", "h1,h2\n1,2\n")
    res = restore_test_zip(buf.getvalue())
    assert res["ok"] is True
    assert res["rows"] >= 2


def test_e2e_upload_to_export_to_reminder():
    uid = 123456
    files.STATE[uid] = {"mode": "add_wait_file", "inv_type": files.TYPE_VAT}

    fake_file = SimpleNamespace(download_to_drive=AsyncMock())
    fake_bot = SimpleNamespace(get_file=AsyncMock(return_value=fake_file), send_message=AsyncMock())
    fake_context = SimpleNamespace(bot=fake_bot)

    fake_message = SimpleNamespace(document=None, photo=[SimpleNamespace(file_id="photo-file-id")], reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=uid), message=fake_message)

    with (
        patch.object(files, "is_allowed", return_value=True),
        patch.object(files, "is_operator", return_value=True),
        patch.object(files, "setup_tesseract", return_value=None),
        patch.object(files, "ocr_image", return_value="OCR"),
        patch.object(files, "extract_fields", return_value={
            "date": "2026-02-17",
            "no": "FV/1/2026",
            "company": "Danex",
            "gross": "123,45",
        }),
        patch.object(files, "sha256_file", return_value="hash-1"),
        patch.object(files, "find_duplicate", return_value=None),
        patch.object(files, "find_duplicate_content", return_value=None),
        patch.object(files, "register_file_hash", return_value=None),
        patch.object(files, "register_content_hash", return_value=None),
        patch.object(files, "upload_to_drive", return_value="https://drive.example/fv"),
        patch.object(files, "_validate_saved_file", return_value=(True, "")),
        patch.object(files, "next_row", return_value=42),
        patch.object(files, "append_row", return_value=None),
        patch.object(files, "missing_fields", return_value=[]),
        patch.object(files, "user_label", return_value="tester"),
        patch.object(files, "INV_DIR", Path("C:/Users/syfsy/danex-faktury-bot/invoices")),
    ):
        run(files.handle_file(update, fake_context))

    # status update via callback
    query = SimpleNamespace(
        data="i:ok:42",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    cb_update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=uid))
    row = [""] * callbacks.COL_FILE
    row[callbacks.COL_DATE - 1] = "2026-02-17"
    row[callbacks.COL_STATUS - 1] = callbacks.STATUS_TODO
    row[callbacks.COL_FILE - 1] = "https://drive.example/fv"

    with (
        patch.object(callbacks, "is_allowed", return_value=True),
        patch.object(callbacks, "is_operator", return_value=True),
        patch.object(callbacks, "get_row", return_value=row),
        patch.object(callbacks, "update_cell", return_value=None),
        patch.object(callbacks, "find_next_missing_price_in_month", return_value=None),
    ):
        run(callbacks.on_click(cb_update, SimpleNamespace()))

    # export command
    export_msg = SimpleNamespace(reply_document=AsyncMock())
    export_update = SimpleNamespace(effective_user=SimpleNamespace(id=uid), message=export_msg)
    with (
        patch.object(commands, "is_operator", return_value=True),
        patch.object(commands, "build_month_zip", return_value=(b"zip", "exp.zip")),
        patch.object(commands, "compute_month_stats", return_value={"gross": 1.0, "net": 1.0, "vat": 0.0, "todo": [], "todo_missing_price": []}),
    ):
        run(commands.cmd_export(export_update, SimpleNamespace(args=["2026-02"])))
    assert export_msg.reply_document.await_count == 1

    # reminder command flow
    with (
        patch.object(reminders, "admin_ids", return_value={uid}),
        patch.object(reminders, "get_all_values", return_value=[["h"], ["r"]]),
        patch.object(reminders, "compute_month_stats", return_value={"todo": [2], "todo_missing_price": [], "ok": 1, "sent": 0}),
        patch.object(reminders, "today_ym", return_value="2026-02"),
    ):
        run(reminders._send_todo_reminder(fake_context))
    assert fake_bot.send_message.await_count == 1


def test_start_command_mama_tiles():
    import handlers.commands as commands

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=987654), message=message)
    with (
        patch.object(commands, "is_allowed", return_value=True),
        patch.object(commands, "is_mama", return_value=True),
    ):
        run(commands.cmd_start(update, SimpleNamespace()))
    assert message.reply_text.await_count == 1


def test_mama_type_selection_text_flow():
    import handlers.messages as messages

    uid = 777
    message = SimpleNamespace(text="Typ VAT", reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=uid), message=message)

    with (
        patch.object(messages, "is_allowed", return_value=True),
        patch.object(messages, "is_mama", return_value=True),
    ):
        run(messages.on_text(update, SimpleNamespace()))

    assert messages.STATE[uid]["mode"] == "add_wait_file"


def test_mama_kwota_ok_sets_status_when_complete():
    import handlers.messages as messages

    uid = 778
    messages.STATE[uid] = {"mode": "mama_review", "row": "5", "month": "2026-02"}
    message = SimpleNamespace(text="Kwota OK", reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=uid), message=message)

    row = [""] * messages.COL_FILE
    row[messages.COL_DATE - 1] = "2026-02-17"
    row[messages.COL_COMP - 1] = "Danex"
    row[messages.COL_NO - 1] = "FV/1"
    row[messages.COL_GROSS - 1] = "123.00"
    row[messages.COL_TYPE - 1] = "VAT"

    with (
        patch.object(messages, "is_allowed", return_value=True),
        patch.object(messages, "is_mama", return_value=True),
        patch.object(messages, "get_row", return_value=row),
        patch.object(messages, "_find_next_after", return_value=None),
        patch.object(messages, "missing_fields", return_value=[]),
        patch.object(messages, "update_cell", return_value=None) as upd,
    ):
        run(messages.on_text(update, SimpleNamespace()))

    assert upd.call_count >= 1
