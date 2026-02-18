# -*- coding: utf-8 -*-
from typing import Any
from telegram import Update
from sheets_service import ws as _ws, get_all_values as _gav, get_row as _gr, update_cell as _uc, append_row as _ar, next_row as _nr

class SheetsStorage:
    def ws(self, update: Update): return _ws()
    def get_all_values(self, update: Update): return _gav()
    def get_row(self, update: Update, row_no: int): return _gr(row_no)
    def update_cell(self, update: Update, row_no: int, col: int, value: Any): return _uc(row_no, col, value)
    def append_row(self, update: Update, values, value_input_option: str = "USER_ENTERED"): return _ar(values, value_input_option=value_input_option)
    def next_row(self, update: Update): return _nr()
