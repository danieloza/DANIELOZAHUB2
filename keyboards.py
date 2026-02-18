# -*- coding: utf-8 -*-
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def kb_page(page: int) -> InlineKeyboardMarkup:
    if page == 1:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Dodaj fakture", callback_data="m:add")],
            [InlineKeyboardButton("Podglad miesiaca", callback_data="m:snap_year")],
            [InlineKeyboardButton("Do sprawdzenia", callback_data="m:todo_year")],
            [InlineKeyboardButton("Do sprawdzenia (brak kwoty)", callback_data="m:todo_missing_year")],
            [InlineKeyboardButton("Paczka ZIP do ksiegowej", callback_data="m:pack_year")],
            [InlineKeyboardButton("Wiecej", callback_data="m:page:2")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Diagnostyka", callback_data="m:diag")],
        [InlineKeyboardButton("Menu", callback_data="m:page:1")],
    ])


def kb_mama_page() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Dodaj fakture", callback_data="m:add")],
        [InlineKeyboardButton("Co mam poprawic", callback_data="mom:todo_now")],
        [InlineKeyboardButton("Wyslij do ksiegowej", callback_data="mom:export_now")],
        [InlineKeyboardButton("Pomoc", callback_data="mom:help")],
    ])


def _mk(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(x) for x in row] for row in rows],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=True,
    )


def kb_mama_tiles(large_font: bool = False) -> ReplyKeyboardMarkup:
    if large_font:
        return _mk(
            [
                ["Dzisiaj dodaj fakture"],
                ["Co mam poprawic"],
                ["Wyslij do ksiegowej"],
                ["Duza czcionka OFF"],
                ["Cofnij ostatnia akcje"],
                ["Potrzebuje pomocy"],
                ["Pomoc"],
            ]
        )
    return _mk(
        [
            ["Dodaj fakture", "Co mam poprawic", "Wyslij do ksiegowej"],
            ["Duza czcionka ON", "Cofnij ostatnia akcje"],
            ["Potrzebuje pomocy", "Pomoc"],
        ]
    )


def kb_mama_pick_type(large_font: bool = False) -> ReplyKeyboardMarkup:
    if large_font:
        return _mk(
            [
                ["Typ VAT"],
                ["Typ Bez VAT"],
                ["Cofnij ostatnia akcje"],
                ["Potrzebuje pomocy"],
            ]
        )
    return _mk(
        [
            ["Typ VAT", "Typ Bez VAT"],
            ["Cofnij ostatnia akcje", "Potrzebuje pomocy"],
            ["Pomoc"],
        ]
    )


def kb_mama_review_tiles(large_font: bool = False) -> ReplyKeyboardMarkup:
    if large_font:
        return _mk(
            [
                ["Kwota OK"],
                ["Popraw kwote"],
                ["Dalej"],
                ["Cofnij ostatnia akcje"],
            ]
        )
    return _mk(
        [
            ["Kwota OK", "Popraw kwote"],
            ["Dalej", "Cofnij ostatnia akcje"],
        ]
    )


def kb_mama_next_only(large_font: bool = False) -> ReplyKeyboardMarkup:
    return _mk([["Dalej"]])


def kb_mama_invoice(row_no: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Kwota OK", callback_data=f"mom:ok:{row_no}")],
        [InlineKeyboardButton("Popraw kwote", callback_data=f"mom:fix:{row_no}")],
        [InlineKeyboardButton("Menu", callback_data="mom:menu")],
    ])


def kb_mama_company_suggestions(companies: list[str], large_font: bool = False) -> ReplyKeyboardMarkup:
    clean = [c.strip() for c in companies if (c or "").strip()]
    clean = clean[:8]
    rows: list[list[str]] = []
    if large_font:
        rows.extend([[c] for c in clean])
    else:
        for i in range(0, len(clean), 2):
            rows.append(clean[i : i + 2])
    rows.append(["Zostaw OCR"])
    rows.append(["Popraw recznie"])
    return _mk(rows)



def kb_mama_amount_confirm() -> ReplyKeyboardMarkup:
    return _mk([["Tak"], ["Popraw kwote"], ["Wroc do menu"]])
def kb_mama_ultra_amount() -> ReplyKeyboardMarkup:
    return _mk([["Nagraj kwote"], ["Wpisz kwote"], ["Wroc do menu"]])


def kb_mama_sos_safe() -> ReplyKeyboardMarkup:
    return _mk([["Wroc do menu"], ["Poczekaj"]])


def kb_mama_daily_one_button(large_font: bool = False) -> ReplyKeyboardMarkup:
    return _mk([["Dzisiaj dodaj fakture"]])


def kb_add_type() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("VAT", callback_data="add:type:VAT")],
        [InlineKeyboardButton("Bez VAT", callback_data="add:type:NOVAT")],
        [InlineKeyboardButton("Menu", callback_data="m:page:1")],
    ])


def kb_years(prefix: str) -> InlineKeyboardMarkup:
    now = datetime.now().year
    years = [now - 1, now, now + 1]
    rows = []
    for y in years:
        rows.append([InlineKeyboardButton(str(y), callback_data=f"{prefix}:Y:{y}")])
    rows.append([InlineKeyboardButton("Inny rok (wpisz)", callback_data=f"{prefix}:Y:custom")])
    rows.append([InlineKeyboardButton("Menu", callback_data="m:page:1")])
    return InlineKeyboardMarkup(rows)


def kb_months_of_year(prefix: str, year: int) -> InlineKeyboardMarkup:
    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    rows = []
    for i in range(0, 12, 3):
        rows.append([
            InlineKeyboardButton(months[i][-2:], callback_data=f"{prefix}:M:{months[i]}"),
            InlineKeyboardButton(months[i + 1][-2:], callback_data=f"{prefix}:M:{months[i + 1]}"),
            InlineKeyboardButton(months[i + 2][-2:], callback_data=f"{prefix}:M:{months[i + 2]}"),
        ])
    rows.append([InlineKeyboardButton("Menu", callback_data="m:page:1")])
    return InlineKeyboardMarkup(rows)


def kb_invoice(row_no: int, link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Otworz", callback_data=f"i:open:{row_no}")],
        [InlineKeyboardButton("Ustaw kwote", callback_data=f"i:price:{row_no}")],
        [InlineKeyboardButton("Popraw OCR", callback_data=f"i:ocr:{row_no}")],
        [InlineKeyboardButton("Ustaw VAT recznie", callback_data=f"i:vat:{row_no}")],
        [InlineKeyboardButton("Napraw (Mama)", callback_data=f"i:fix:{row_no}")],
        [InlineKeyboardButton("OK", callback_data=f"i:ok:{row_no}"), InlineKeyboardButton("Wyslane", callback_data=f"i:sent:{row_no}")],
        [InlineKeyboardButton("Menu", callback_data="m:page:1")],
    ])


def kb_fix(row_no: int, month: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ustaw kwote", callback_data=f"i:price:{row_no}")],
        [InlineKeyboardButton("Popraw OCR", callback_data=f"i:ocr:{row_no}")],
        [InlineKeyboardButton("Otworz link", callback_data=f"i:open:{row_no}")],
        [InlineKeyboardButton("Oznacz OK", callback_data=f"i:ok:{row_no}")],
        [InlineKeyboardButton("Wyslana do ksiegowej", callback_data=f"i:sent:{row_no}")],
        [InlineKeyboardButton("Kontynuuj (nastepna)", callback_data=f"m:next:{month}")],
        [InlineKeyboardButton("Menu", callback_data="m:page:1")],
    ])


def kb_accountant_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ZIP + oznacz jako Wyslana", callback_data="acc:pack_mark_year")],
        [InlineKeyboardButton("ZIP (bez zmian statusow)", callback_data="acc:pack_only_year")],
        [InlineKeyboardButton("Menu", callback_data="m:page:1")],
    ])

