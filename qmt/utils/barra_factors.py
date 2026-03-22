# -*- coding: utf-8 -*-
"""
Barra CNE5S 风格因子计算（基于阅微堂/官方文档）

当前实现：
- MOMENTUM：过去 525 个交易日去掉最近 21 日的指数加权超额收益，半衰期 126 日。
  公式：MOMENTUM = Σ w_t * (ln(1+r_t) - ln(1+r_ft))，t 从 22 到 525 日。
  参考：https://zhiqiang.org/finance/barra-cne5s-methodology.html
       https://zhiqiang.org/finance/barra-momentum-is-not-revert.html
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# Barra MOMENTUM 默认参数（CNE5S）
MOMENTUM_LOOKBACK = 525   # 回溯交易日数
MOMENTUM_SKIP_DAYS = 21   # 去掉最近 N 日（避免短期反转）
MOMENTUM_HALFLIFE = 126   # 指数权半衰期（日）


def _exponential_weights(n: int, half_life: float) -> np.ndarray:
    """指数衰减权重，最近（索引 0）权重最大，半衰期为 half_life 个周期。"""
    # w_i ∝ 0.5^(i / half_life)，i=0,1,...,n-1
    i = np.arange(n, dtype=float)
    w = np.power(0.5, i / half_life)
    return w / w.sum()


def barra_momentum(
    close: pd.Series,
    market_close: pd.Series | None = None,
    lookback: int = MOMENTUM_LOOKBACK,
    skip_days: int = MOMENTUM_SKIP_DAYS,
    half_life: int = MOMENTUM_HALFLIFE,
) -> float:
    """
    计算 Barra CNE5S 风格 MOMENTUM 因子（单截面，取序列末尾一日）。

    公式：MOMENTUM = Σ w_t * (ln(1+r_t) - ln(1+r_ft))
    - 使用过去 lookback 日，去掉最近 skip_days 日（即用 t = skip_days+1 .. lookback 的收益）
    - w_t 为指数加权，半衰期 half_life

    :param close: 标的收盘价序列（按时间升序），长度至少 lookback+1
    :param market_close: 市场（或基准）收盘价序列，与 close 同长、同索引；为 None 时不减市场
    :param lookback: 回溯交易日数，默认 525
    :param skip_days: 去掉最近几日，默认 21
    :param half_life: 权重半衰期（日），默认 126
    :return: 标量，当前截面 MOMENTUM 值；数据不足时返回 np.nan
    """
    if close is None or len(close) < lookback + 1:
        return np.nan
    close = close.astype(float).dropna()
    if len(close) < lookback + 1:
        return np.nan
    # 取最后 lookback+1 根 K 线，算 lookback 个日收益（ret[0]=最旧，ret[-1]=最近）
    last = close.iloc[-lookback - 1 :]
    ret = np.log(last.values[1:] / last.values[:-1])  # ln(1+r)，长 lookback
    # 去掉最近 skip_days 日：用 ret[0 : lookback-skip_days]，即 22 日 ago ～ 525 日 ago，共 504 个
    n_use = lookback - skip_days
    if n_use <= 0 or n_use > len(ret):
        return np.nan
    excess = ret[:n_use].copy()  # 最旧的在 excess[0]，最新（22 日 ago）在 excess[-1]

    if market_close is not None and len(market_close) >= lookback + 1:
        market_close = market_close.reindex(close.index).astype(float).ffill().bfill()
        if len(market_close) >= lookback + 1:
            mkt_last = market_close.iloc[-lookback - 1 :].values
            mkt_ret = np.log(mkt_last[1:] / mkt_last[:-1])
            if len(mkt_ret) >= n_use:
                excess = excess - mkt_ret[:n_use]

    # 窗口内“较近的日期”权重大：excess[-1] 为 22 日 ago，权最大
    w = _exponential_weights(n_use, float(half_life))[::-1]
    return float(np.dot(w, excess))


def barra_momentum_rolling(
    close: pd.Series,
    market_close: pd.Series | None = None,
    lookback: int = MOMENTUM_LOOKBACK,
    skip_days: int = MOMENTUM_SKIP_DAYS,
    half_life: int = MOMENTUM_HALFLIFE,
) -> pd.Series:
    """
    逐日滚动计算 Barra MOMENTUM，返回与 close 同索引的 Series。
    前 lookback 个位置为 np.nan。
    """
    if close is None or len(close) < lookback + 1:
        return pd.Series(index=close.index if close is not None else [], dtype=float)
    out = np.full(len(close), np.nan, dtype=float)
    for i in range(lookback, len(close)):
        out[i] = barra_momentum(
            close.iloc[: i + 1],
            market_close.iloc[: i + 1] if market_close is not None else None,
            lookback=lookback,
            skip_days=skip_days,
            half_life=half_life,
        )
    return pd.Series(out, index=close.index)


def barra_momentum_from_dataframe(
    df: pd.DataFrame,
    close_col: str = "close",
    date_col: str = "日期",
    market_series: pd.Series | None = None,
    lookback: int = MOMENTUM_LOOKBACK,
    skip_days: int = MOMENTUM_SKIP_DAYS,
    half_life: int = MOMENTUM_HALFLIFE,
) -> pd.Series:
    """
    从带日期与收盘价的 DataFrame 计算滚动 MOMENTUM，便于回测/扫描直接使用。

    :param df: 至少包含 close_col、date_col 的 DataFrame，按日期升序
    :param close_col: 收盘价列名
    :param date_col: 日期列名（用于索引）
    :param market_series: 市场收盘价 Series，索引与 df 的 date_col 对齐；可选
    :param lookback: 回溯日数
    :param skip_days: 去掉最近几日
    :param half_life: 权重半衰期
    :return: 与 df 同长的 Series，索引为 df.index
    """
    if df is None or df.empty or close_col not in df.columns:
        return pd.Series(dtype=float)
    close = df[close_col].astype(float)
    if date_col in df.columns:
        close.index = pd.to_datetime(df[date_col])
    if market_series is not None and not market_series.empty:
        market_series = market_series.reindex(close.index).ffill().bfill()
    return barra_momentum_rolling(
        close,
        market_close=market_series,
        lookback=lookback,
        skip_days=skip_days,
        half_life=half_life,
    )
