from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import handlers.callbacks as callbacks
import handlers.messages as messages
import handlers.files as files
import handlers.commands as commands

def test_calc_net_vat_from_type_vat_23():
    net, vat = messages._calc_net_vat_from_type("VAT 23", 123.00)
    assert round(net, 2) == 100.00
    assert round(vat, 2) == 23.00


def test_calc_net_vat_from_type_no_vat():
    net, vat = messages._calc_net_vat_from_type("BEZ VAT", 123.45)
    assert round(net, 2) == 123.45
    assert round(vat, 2) == 0.00


def test_compute_month_stats_and_next_missing_price():
    update = SimpleNamespace(effective_user=SimpleNamespace(id=111))
    sheet = [
        ["data", "numer", "firma", "brutto", "typ", "vat", "netto", "kat", "user", "status", "plik"],
        ["2026-02-01", "FV1", "A", "", "VAT", "", "", "inne", "u", callbacks.STATUS_TODO, "l1"],
        ["2026-02-02", "FV2", "B", "123,00", "VAT", "23,00", "100,00", "inne", "u", callbacks.STATUS_OK, "l2"],
        ["2026-01-31", "FV3", "C", "50,00", "BEZ VAT", "0,00", "50,00", "inne", "u", callbacks.STATUS_OK, "l3"],
    ]

    with patch.object(callbacks, "get_all_values", return_value=sheet):
        stats = callbacks.compute_month_stats(update, "2026-02")
        nxt = callbacks.find_next_missing_price_in_month(update, "2026-02")

    assert round(stats["gross"], 2) == 123.00
    assert stats["ok"] == 1
    assert stats["sent"] == 0
    assert stats["todo"] == [2]
    assert stats["todo_missing_price"] == [2]
    assert nxt == 2


def test_callback_sent_updates_status_with_correct_signature():
    uid = 123456
    row_no = 5
    query = SimpleNamespace(
        data=f"i:sent:{row_no}",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=uid))

    row = [""] * callbacks.COL_FILE
    row[callbacks.COL_DATE - 1] = "2026-02-17"
    row[callbacks.COL_FILE - 1] = "https://drive.example/file"

    with (
        patch.object(callbacks, "is_allowed", return_value=True),
        patch.object(callbacks, "is_operator", return_value=True),
        patch.object(callbacks, "get_row", return_value=row),
        patch.object(callbacks, "update_cell", return_value=None) as update_cell_mock,
        patch.object(callbacks, "find_next_missing_price_in_month", return_value=None),
    ):
        import asyncio

        asyncio.run(callbacks.on_click(update, SimpleNamespace()))

    update_cell_mock.assert_called_once_with(update, row_no, callbacks.COL_STATUS, callbacks.STATUS_SENT)

def test_content_hash_same_payload_same_hash():
    f1 = {"date": "2026-02-17", "no": "FV/1/2026", "company": "Danex", "gross": "123,45"}
    f2 = {"date": "2026-02-17", "no": " FV/1/2026 ", "company": "DANEX", "gross": "123,45"}
    h1 = files.content_hash_from_fields(f1, files.TYPE_VAT)
    h2 = files.content_hash_from_fields(f2, files.TYPE_VAT)
    assert h1 == h2


def test_health_alert_due_cooldown_behavior():
    commands._LAST_HEALTH_ALERT_AT = None
    commands._LAST_HEALTH_ALERT_STATUS = "ok"
    assert commands._health_alert_due("degraded") is True
    assert commands._health_alert_due("degraded") is False

def test_mama_human_todo_rows_are_readable():
    update = SimpleNamespace(effective_user=SimpleNamespace(id=111))
    sheet = [
        ["data", "numer", "firma", "brutto", "typ", "vat", "netto", "kat", "user", "status", "plik"],
        ["2026-02-17", "FV-1", "Biedronka", "", "VAT", "", "", "inne", "u", messages.STATUS_TODO, "l1"],
    ]

    with patch.object(messages, "get_all_values", return_value=sheet):
        items = messages._human_todo_rows(update, "2026-02")

    assert items
    assert items[0][0] == 2
    assert "Faktura z Biedronka, 17 lutego, brak kwoty." in items[0][1]


def test_mama_undo_restores_last_action():
    import asyncio

    uid = 123
    messages.MAMA_UNDO[uid] = {
        "row": 7,
        "month": "2026-02",
        "action": "mama_set_price",
        "gross": "10.00",
        "net": "8.13",
        "vat": "1.87",
        "status": messages.STATUS_TODO,
    }
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=uid),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )

    with (
        patch.object(messages, "update_cell", return_value=None) as update_cell_mock,
        patch.object(messages, "get_row", return_value=[""] * messages.COL_FILE),
    ):
        handled = asyncio.run(messages._handle_mama_text(update, SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock())), "cofnij"))

    assert handled is True
    assert update_cell_mock.call_count == 4
    assert uid not in messages.MAMA_UNDO

def test_parse_spoken_amount_polish_words():
    v = messages._try_parse_spoken_amount("sto dwadziescia trzy czterdziesci piec")
    assert round(v, 2) == 123.45

def test_mama_on_voice_transcribes_and_routes():
    import asyncio

    uid = 123
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=uid),
        message=SimpleNamespace(voice=SimpleNamespace(file_id="v1"), reply_text=AsyncMock()),
    )
    ctx = SimpleNamespace(bot=SimpleNamespace())
    messages.STATE[uid] = {"mode": "mama_set_price", "row": "7", "month": "2026-02", "voice_mode": True}

    with (
        patch.object(messages, "is_allowed", return_value=True),
        patch.object(messages, "is_mama", return_value=True),
        patch.object(messages, "_voice_integration_ready", return_value=(True, "")),
        patch.object(messages, "_transcribe_voice_note", new=AsyncMock(return_value="sto dwadziescia trzy czterdziesci piec")),
        patch.object(messages, "_handle_mama_text", new=AsyncMock(return_value=True)) as handle_mock,
    ):
        asyncio.run(messages.on_voice(update, ctx))

    assert handle_mock.await_count == 1
