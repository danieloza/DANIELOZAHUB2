import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import handlers.commands as commands
from config import RUN_GSHEETS_INTEGRATION


def _has_required_env() -> bool:
    required = ["SPREADSHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON"]
    return all((os.getenv(k, "").strip() for k in required))


@pytest.mark.integration
@pytest.mark.skipif(not RUN_GSHEETS_INTEGRATION, reason="Set RUN_GSHEETS_INTEGRATION=1 to run GSheets integration tests")
def test_diag_rw_integration_sheets():
    if not _has_required_env():
        pytest.skip("Missing SPREADSHEET_ID or GOOGLE_SERVICE_ACCOUNT_JSON")

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123456),
        message=message,
    )

    fake_storage = type("SheetsStorage", (), {})()
    ctx = SimpleNamespace(args=["rw"])

    with (
        patch.object(commands, "is_allowed", return_value=True),
        patch.object(commands, "get_storage", return_value=fake_storage),
    ):
        asyncio.run(commands.cmd_diag(update, ctx))

    assert message.reply_text.await_count == 1
    args, _ = message.reply_text.await_args
    assert "sheets_conn: OK" in args[0]
    assert "rw_write_ok: yes" in args[0]
