# -*- coding: utf-8 -*-
"""
A 股交易日历：从 2026-01-01 起，排除周末与法定休市日。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List


# 2026 年 A 股休市日（元旦、春节、清明、劳动、端午、中秋、国庆）
HOLIDAYS_2026 = [
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07",
]
_HOLIDAY_SET = set(HOLIDAYS_2026)


def _norm_date(d: str | datetime) -> str:
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def get_trading_days(start_date: str, end_date: str) -> List[str]:
    """
    返回 [start_date, end_date] 内的所有交易日（排除周末与 2026 休市日）。
    日期格式支持 '2026-01-01' 或 '20260101'。
    """
    start = _norm_date(start_date)
    end = _norm_date(end_date)
    out = []
    d = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while d <= end_dt:
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and ds not in _HOLIDAY_SET:
            out.append(ds)
        d += timedelta(days=1)
    return out
