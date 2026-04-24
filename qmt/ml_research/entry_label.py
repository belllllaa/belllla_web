# -*- coding: utf-8 -*-
"""
推荐日 -> 下一根交易日开盘买入；之后按日线 high/low 判断先触及止盈或止损。

同一根 K 线同时触及止盈与止损时，默认按「先止损」处理（对多头更保守）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_daily_index(df: pd.DataFrame) -> pd.DataFrame:
    """将 index 转为 DatetimeIndex（支持 QMT 常见 YYYYMMDD 整数索引）。"""
    if df is None or df.empty:
        return df
    out = df.copy()
    idx = out.index
    if pd.api.types.is_integer_dtype(idx) or (
        len(idx) > 0 and isinstance(idx[0], (int, np.integer))
    ):
        out.index = pd.to_datetime(idx.astype(str), format="%Y%m%d", errors="coerce")
    else:
        out.index = pd.to_datetime(idx, errors="coerce")
    out = out[~out.index.isna()]
    out = out.sort_index()
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def recommend_feature_end_entry_indices(
    dates: np.ndarray,
    recommend_ts: pd.Timestamp,
):
    """
    :param dates: 与日线 df 对齐的 DatetimeIndex.values（已 normalize 到日）
    :param recommend_ts: 推荐日（日历日，时间部分忽略）
    :return: (feat_end_idx, entry_idx) 或 (None, None)
    feat_end: 最后一个 date <= recommend 的 bar（用于算特征，含该日收盘）
    entry: 第一个 date > recommend 的 bar（次日开盘买）
    """
    rd = pd.Timestamp(recommend_ts).normalize()
    dnorm = pd.to_datetime(dates).normalize()
    mask_le = dnorm <= rd
    if not np.any(mask_le):
        return None, None
    feat_end_idx = int(np.where(mask_le)[0][-1])
    mask_gt = dnorm > rd
    if not np.any(mask_gt):
        return None, None
    entry_idx = int(np.where(mask_gt)[0][0])
    if entry_idx <= feat_end_idx:
        return None, None
    return feat_end_idx, entry_idx


def simulate_long_tp_sl(
    df: pd.DataFrame,
    entry_idx: int,
    tp_pct: float,
    sl_pct: float,
    max_hold_days: int,
    same_bar_sl_first: bool = True,
):
    """
    :param df: index 为日期，含 open/high/low/close
    :param entry_idx: 买入所在行（用该行 open 为入场价）
    :return: dict outcome tp_first|sl_first|timeout, entry_open, bars_held, exit_reason
    """
    if entry_idx >= len(df) or entry_idx < 0:
        return None
    entry_open = float(df["open"].iloc[entry_idx])
    if not np.isfinite(entry_open) or entry_open <= 0:
        return None
    tp_price = entry_open * (1.0 + float(tp_pct))
    sl_price = entry_open * (1.0 - float(sl_pct))
    end_i = min(len(df), entry_idx + int(max_hold_days))
    for i in range(entry_idx, end_i):
        hi = float(df["high"].iloc[i])
        lo = float(df["low"].iloc[i])
        touch_sl = lo <= sl_price
        touch_tp = hi >= tp_price
        if touch_sl and touch_tp:
            if same_bar_sl_first:
                return {
                    "outcome": "sl_first",
                    "entry_open": entry_open,
                    "bars_held": i - entry_idx + 1,
                    "exit_bar": i,
                }
            return {
                "outcome": "tp_first",
                "entry_open": entry_open,
                "bars_held": i - entry_idx + 1,
                "exit_bar": i,
            }
        if touch_sl:
            return {
                "outcome": "sl_first",
                "entry_open": entry_open,
                "bars_held": i - entry_idx + 1,
                "exit_bar": i,
            }
        if touch_tp:
            return {
                "outcome": "tp_first",
                "entry_open": entry_open,
                "bars_held": i - entry_idx + 1,
                "exit_bar": i,
            }
    last = end_i - 1
    if last < entry_idx:
        return None
    last_close = float(df["close"].iloc[last])
    return {
        "outcome": "timeout",
        "entry_open": entry_open,
        "bars_held": last - entry_idx + 1,
        "exit_bar": last,
        "last_close": last_close,
    }
