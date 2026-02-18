import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import handlers.callbacks as callbacks
import handlers.commands as commands
import handlers.files as files


def run(coro):
    return asyncio.run(coro)


def test_start_command_smoke():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123456), message=message)
    with patch.object(commands, "is_allowed", return_value=True):
        run(commands.cmd_start(update, SimpleNamespace()))
    assert message.reply_text.await_count == 1


def test_diag_command_sheets_smoke():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123456), message=message)
    fake_ws = SimpleNamespace(
        title="Arkusz1",
        row_count=100,
        col_count=11,
        row_values=lambda row_no: ["data", "numer", "firma", "brutto", "typ"] if row_no == 1 else [],
    )
    fake_storage = type("SheetsStorage", (), {})()

    with (
        patch.object(commands, "is_allowed", return_value=True),
        patch.object(commands, "user_role", return_value="operator"),
        patch.object(commands, "get_storage", return_value=fake_storage),
        patch.object(commands, "ws", return_value=fake_ws),
        patch.object(commands, "get_all_values", return_value=[["h"], ["1"]]),
        patch.object(commands, "env", side_effect=lambda k, d="": "x" if k == commands.ENV_SHEET_ID else "Arkusz1"),
        patch.object(commands, "sa_path", return_value="C:/tmp/sa.json"),
        patch.object(commands.Path, "exists", return_value=True),
    ):
        run(commands.cmd_diag(update, SimpleNamespace(args=[])))

    args, _ = message.reply_text.await_args
    assert "sheets_conn: OK" in args[0]


def test_health_command_admin_smoke():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123456), message=message)
    fake_storage = type("SheetsStorage", (), {})()
    with (
        patch.object(commands, "is_admin", return_value=True),
        patch.object(commands, "get_storage", return_value=fake_storage),
        patch.object(commands, "get_all_values", return_value=[["h1"], ["r1"]]),
        patch.object(commands, "get_last_error", return_value={"at": None, "message": ""}),
        patch.object(commands, "error_count_last_24h", return_value=0),
    ):
        run(commands.cmd_health(update, SimpleNamespace()))
    args, _ = message.reply_text.await_args
    assert "status: ok" in args[0]


def test_add_flow_callback_state_transitions():
    uid = 123456
    callbacks.STATE.pop(uid, None)
    query = SimpleNamespace(
        data="m:add",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=uid))

    with (
        patch.object(callbacks, "is_allowed", return_value=True),
        patch.object(callbacks, "is_operator", return_value=True),
    ):
        run(callbacks.on_click(update, SimpleNamespace()))
    assert callbacks.STATE[uid]["mode"] == "add_wait_type"

    query.data = "add:type:VAT"
    with (
        patch.object(callbacks, "is_allowed", return_value=True),
        patch.object(callbacks, "is_operator", return_value=True),
    ):
        run(callbacks.on_click(update, SimpleNamespace()))
    assert callbacks.STATE[uid]["mode"] == "add_wait_file"


def test_handle_file_add_invoice_smoke():
    uid = 123456
    files.STATE[uid] = {"mode": "add_wait_file", "inv_type": files.TYPE_VAT}

    fake_file = SimpleNamespace(download_to_drive=AsyncMock())
    fake_bot = SimpleNamespace(get_file=AsyncMock(return_value=fake_file))
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
        patch.object(files, "append_row", return_value=None) as append_row_mock,
        patch.object(files, "missing_fields", return_value=[]),
        patch.object(files, "user_label", return_value="tester"),
        patch.object(files, "INV_DIR", Path("C:/Users/syfsy/danex-faktury-bot/invoices")),
    ):
        run(files.handle_file(update, fake_context))

    assert append_row_mock.call_count == 1

