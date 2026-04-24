# -*- coding: utf-8 -*-
"""股票代码规范化（与导出板块 txt 逻辑一致思路）。"""

import re


def normalize_stock_code(token):
    t = str(token).strip().upper().replace("\u3000", " ")
    if not t or t.startswith("#"):
        return None
    t = t.split()[0]
    if not t:
        return None
    if "." in t:
        a, b = t.split(".", 1)
        if len(a) == 6 and a.isdigit() and b in ("SH", "SZ", "BJ"):
            return "%s.%s" % (a, b)
        if a in ("SH", "SZ", "BJ") and len(b) == 6 and b.isdigit():
            return "%s.%s" % (b, a)
        return None
    if len(t) == 8 and t[:2] in ("SH", "SZ", "BJ") and t[2:].isdigit():
        return "%s.%s" % (t[2:], t[:2])
    return None


def bare_six_to_code(part):
    s = str(part).strip().upper().replace(" ", "")
    if not re.match(r"^\d{6}$", s):
        return None
    if s.startswith(("600", "601", "603", "605", "688", "689")):
        return "%s.SH" % s
    if s.startswith(("11", "51", "58")):
        return "%s.SH" % s
    return "%s.SZ" % s
