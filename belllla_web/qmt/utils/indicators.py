# -*- coding: utf-8 -*-
"""
QMT 技术指标封装

基于 talib 封装 MA、EMA、RSI、MACD、布林带等常用指标。
输入支持 numpy 数组或 pandas Series，输出统一为 numpy 数组。
"""

import numpy as np

try:
    import talib
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False


def _to_array(x):
    """转换为 numpy 数组"""
    if hasattr(x, "values"):
        return np.asarray(x.values, dtype=float)
    return np.asarray(x, dtype=float)


def ma(close, period):
    """
    简单移动平均线 SMA

    :param close: 收盘价序列（numpy 或 pandas）
    :param period: 周期
    :return: numpy 数组
    """
    arr = _to_array(close)
    if HAS_TALIB:
        return talib.SMA(arr, timeperiod=period)
    return np.convolve(arr, np.ones(period) / period, mode="same")


def ema(close, period):
    """
    指数移动平均线 EMA

    :param close: 收盘价序列
    :param period: 周期
    :return: numpy 数组
    """
    arr = _to_array(close)
    if HAS_TALIB:
        return talib.EMA(arr, timeperiod=period)
    return pd_ema(arr, period)


def pd_ema(arr, period):
    """无 talib 时的 EMA 实现"""
    result = np.full_like(arr, np.nan)
    alpha = 2.0 / (period + 1)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        if np.isnan(arr[i]):
            result[i] = result[i - 1]
        else:
            result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


def rsi(close, period=14):
    """
    相对强弱指数 RSI

    :param close: 收盘价序列
    :param period: 周期，默认 14
    :return: numpy 数组
    """
    arr = _to_array(close)
    if HAS_TALIB:
        return talib.RSI(arr, timeperiod=period)
    return np_rsi(arr, period)


def np_rsi(arr, period=14):
    """无 talib 时的 RSI 实现"""
    result = np.full_like(arr, np.nan)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    for i in range(period, len(arr)):
        avg_gain = np.mean(gains[i - period : i])
        avg_loss = np.mean(losses[i - period : i])
        if avg_loss == 0:
            result[i] = 100
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - 100 / (1 + rs)
    return result


def macd(close, fastperiod=12, slowperiod=26, signalperiod=9):
    """
    MACD 指标

    :param close: 收盘价序列
    :param fastperiod: 快线周期
    :param slowperiod: 慢线周期
    :param signalperiod: 信号线周期
    :return: (macd, signal, hist) 三个 numpy 数组
    """
    arr = _to_array(close)
    if HAS_TALIB:
        macd_val, signal, hist = talib.MACD(
            arr, fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod
        )
        return macd_val, signal, hist
    ema_fast = ema(arr, fastperiod)
    ema_slow = ema(arr, slowperiod)
    macd_val = ema_fast - ema_slow
    signal = ema(macd_val[~np.isnan(macd_val)], signalperiod)
    full_signal = np.full_like(macd_val, np.nan)
    full_signal[-len(signal) :] = signal[-len(signal) :]
    hist = macd_val - full_signal
    return macd_val, full_signal, hist


def bbands(close, period=20, nbdevup=2, nbdevdn=2):
    """
    布林带

    :param close: 收盘价序列
    :param period: 周期
    :param nbdevup: 上轨标准差倍数
    :param nbdevdn: 下轨标准差倍数
    :return: (upper, middle, lower) 三个 numpy 数组
    """
    arr = _to_array(close)
    if HAS_TALIB:
        upper, middle, lower = talib.BBANDS(
            arr, timeperiod=period, nbdevup=nbdevup, nbdevdn=nbdevdn
        )
        return upper, middle, lower
    middle = ma(arr, period)
    std = np.full_like(arr, np.nan)
    for i in range(period - 1, len(arr)):
        std[i] = np.std(arr[i - period + 1 : i + 1])
    upper = middle + nbdevup * std
    lower = middle - nbdevdn * std
    return upper, middle, lower
