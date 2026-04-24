# -*- coding: utf-8 -*-
"""
日线 OHLCV：优先 xtquant（QMT 自带 Python）；若在策略内可传入 ContextInfo 用 data_helper。
"""

from __future__ import annotations

import pandas as pd


def _dict_to_df(stock_code, node) -> pd.DataFrame | None:
    if node is None:
        return None
    if isinstance(node, pd.DataFrame):
        df = node.copy()
    elif isinstance(node, dict):
        df = pd.DataFrame(node)
    else:
        return None
    if df.empty:
        return None
    for c in ("open", "high", "low", "close", "volume"):
        if c not in df.columns:
            return None
    return df


def get_daily_ohlcv_xtdata(stock_code: str, start_time: str, end_time: str, dividend_type: str = "front"):
    """
    使用 xtquant.xtdata.get_market_data_ex 拉日线。

    :param start_time/end_time: YYYYMMDD
    """
    try:
        from xtquant import xtdata
    except ImportError as e:
        raise ImportError("请使用迅投 QMT 安装目录下的 python 运行，或确保已安装 xtquant") from e

    field_list = ["open", "high", "low", "close", "volume"]
    get_ex = getattr(xtdata, "get_market_data_ex", None)
    if not callable(get_ex):
        raise RuntimeError("xtdata 无 get_market_data_ex")

    kwargs = dict(
        field_list=field_list,
        stock_list=[stock_code],
        period="1d",
        start_time=start_time or "",
        end_time=end_time or "",
        count=-1,
        dividend_type=dividend_type,
        fill_data=True,
    )
    raw = None
    try:
        raw = get_ex(**kwargs)
    except TypeError:
        kwargs.pop("count", None)
        try:
            raw = get_ex(**kwargs)
        except TypeError:
            raw = get_ex(field_list, [stock_code], period="1d", start_time=start_time, end_time=end_time)

    if not raw or stock_code not in raw:
        return None
    df = _dict_to_df(stock_code, raw[stock_code])
    if df is None:
        return None
    if not isinstance(df.index, pd.DatetimeIndex) and "time" in df.columns:
        tcol = pd.to_datetime(df["time"], errors="coerce")
        if tcol.notna().any():
            df = df.drop(columns=["time"], errors="ignore")
            df.index = tcol.values
    return df


def get_daily_ohlcv_context(C, stock_code: str, start_time: str, end_time: str, dividend_type: str = "front"):
    """策略 / 回测内使用 ContextInfo。"""
    from qmt.utils.data_helper import get_ohlcv_df

    return get_ohlcv_df(
        C,
        stock_code,
        period="1d",
        start_time=start_time,
        end_time=end_time,
        dividend_type=dividend_type,
        fill_data=True,
    )
