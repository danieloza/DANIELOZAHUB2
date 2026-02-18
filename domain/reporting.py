# -*- coding: utf-8 -*-
import re
from datetime import datetime


def parse_month_arg(args: list[str]) -> str:
    if not args:
        return datetime.now().strftime("%Y-%m")
    m = (args[0] or "").strip()
    if re.match(r"^\d{4}-\d{2}$", m):
        return m
    return datetime.now().strftime("%Y-%m")
