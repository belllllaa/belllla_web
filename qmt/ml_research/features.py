# -*- coding: utf-8 -*-
"""
仅用「推荐日及之前」的日线计算特征（不含入场日开盘价），避免标签泄露。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from qmt.utils.indicators import rsi as rsi_calc
except Exception:

    def rsi_calc(close, period=14):
        arr = np.asarray(close, dtype=float)
        if len(arr) < period + 1:
            return np.full_like(arr, np.nan)
        deltas = np.diff(arr, prepend=arr[0])
        gains = np.clip(deltas, 0, None)
        losses = np.clip(-deltas, 0, None)
        avg_g = pd.Series(gains).rolling(period).mean().values
        avg_l = pd.Series(losses).rolling(period).mean().values
        rs = np.divide(avg_g, np.where(avg_l == 0, np.nan, avg_l))
        return 100.0 - (100.0 / (1.0 + rs))


def build_tabular_features(df: pd.DataFrame, feat_end_idx: int) -> dict:
    """
    :param df: 已按日期排序的 OHLCV
    :param feat_end_idx: 推荐日所在 bar（含该日收盘）
    """
    if feat_end_idx < 20 or feat_end_idx >= len(df):
        return {}
    sl = df.iloc[: feat_end_idx + 1].copy()
    c = sl["close"].astype(float)
    v = sl["volume"].astype(float) if "volume" in sl.columns else pd.Series(np.nan, index=sl.index)

    def ret_n(n):
        if len(c) <= n:
            return np.nan
        a, b = float(c.iloc[-1]), float(c.iloc[-1 - n])
        if b == 0:
            return np.nan
        return a / b - 1.0

    ma20 = float(c.iloc[-20:].mean())
    ma5 = float(c.iloc[-5:].mean())
    last_c = float(c.iloc[-1])
    vol_mean_20 = float(v.iloc[-20:].mean()) if "volume" in sl.columns else np.nan
    last_v = float(v.iloc[-1]) if "volume" in sl.columns else np.nan
    rsi14 = float(rsi_calc(c.values, 14)[-1])

    feats = {
        "ret_1": ret_n(1),
        "ret_5": ret_n(5),
        "ret_20": ret_n(20),
        "close_over_ma20": (last_c / ma20 - 1.0) if ma20 and np.isfinite(ma20) else np.nan,
        "close_over_ma5": (last_c / ma5 - 1.0) if ma5 and np.isfinite(ma5) else np.nan,
        "vol_ratio_20": (last_v / vol_mean_20) if vol_mean_20 and np.isfinite(vol_mean_20) else np.nan,
        "rsi_14": rsi14,
    }
    hl = (sl["high"].astype(float) - sl["low"].astype(float)) / c.replace(0, np.nan)
    feats["mean_daily_range_5"] = float(hl.iloc[-5:].mean())
    return feats
