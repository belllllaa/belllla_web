# -*- coding: utf-8 -*-
"""
从 CSV 读取「推荐日 + 股票代码」。

支持列名（不区分大小写，取首个匹配）：
  日期：推荐日 / 日期 / recommend_date / date
  代码：代码 / 股票代码 / 证券代码 / code / symbol
"""

from __future__ import annotations

import os

import pandas as pd

from qmt.ml_research.stock_code import bare_six_to_code, normalize_stock_code


def _read_csv_raw(path):
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(path)
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    return pd.read_csv(path)


def _pick_col(df, candidates):
    lower = {c.lower().strip(): c for c in df.columns}
    for name in candidates:
        key = name.lower().strip()
        if key in lower:
            return lower[key]
    return None


def _parse_dates(series):
    s = series.astype(str).str.strip()
    return pd.to_datetime(s, errors="coerce")


def load_watchlist_csv(path):
    """
    :return: DataFrame 列 recommend_date (datetime64[ns]), stock_code (str)
    """
    df = _read_raw(path)
    c_date = _pick_col(df, ("推荐日", "日期", "recommend_date", "date", "推荐日期"))
    c_code = _pick_col(df, ("代码", "股票代码", "证券代码", "code", "symbol", "stock_code"))
    if c_date is None or c_code is None:
        raise ValueError(
            "CSV 需包含日期列与代码列之一；日期: 推荐日/日期/recommend_date；代码: 代码/股票代码/code 等。实际列: %s"
            % list(df.columns)
        )
    out = pd.DataFrame()
    out["recommend_date"] = _parse_dates(df[c_date]).dt.normalize()
    codes = []
    for x in df[c_code].astype(str):
        c = normalize_stock_code(x) or bare_six_to_code(x)
        codes.append(c)
    out["stock_code"] = codes
    out = out.dropna(subset=["recommend_date", "stock_code"])
    return out.reset_index(drop=True)


def _read_raw(path):
    return _read_csv_raw(path)
