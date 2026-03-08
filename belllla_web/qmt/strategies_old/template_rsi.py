# -*- coding: utf-8 -*-
"""
RSI 策略：RSI < 30 买入，RSI > 70 卖出

QMT 入口：init, after_init, handlebar
在 QMT 中加载本文件即可回测或实盘运行。
"""

import sys
import os

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from config.config import STOCK_LIST, PERIOD, ACCOUNT_ID, STRATEGY_NAME


def _get_close(df):
    """从 DataFrame 提取收盘价数组"""
    if df is None:
        return None
    if hasattr(df, "columns") and "close" in df.columns:
        return df["close"].values
    if hasattr(df, "columns") and len(df.columns) > 0:
        return df.iloc[:, 3].values if len(df.columns) > 3 else df.iloc[:, -1].values
    return df.values.flatten() if hasattr(df, "values") else None
from strategies.base_strategy import BaseStrategy
from utils.data_helper import get_ohlcv_df
from utils.indicators import rsi


class RsiStrategy(BaseStrategy):
    """RSI 超买超卖策略"""

    def __init__(self, rsi_period=14, oversold=30, overbought=70, **kwargs):
        super().__init__(**kwargs)
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought

    def on_init(self, ContextInfo):
        ContextInfo.stock_list = self.stock_list
        try:
            start = getattr(ContextInfo, "start_time", "")
            end = getattr(ContextInfo, "end_time", "")
            for code in self.stock_list:
                download_history_data(code, self.period, start, end)  # noqa: F821
        except Exception:
            pass

    def on_bar(self, ContextInfo):
        for stock in self.stock_list:
            df = get_ohlcv_df(ContextInfo, stock, period=self.period, count=self.rsi_period + 20)
            if df is None or len(df) < self.rsi_period + 5:
                continue

            close = _get_close(df)
            if close is None or len(close) < self.rsi_period:
                continue
            rsi_val = rsi(close, self.rsi_period)

            if len(rsi_val) < 1:
                continue

            curr_rsi = rsi_val[-1]
            if curr_rsi != curr_rsi:  # NaN
                continue

            if curr_rsi < self.oversold:
                self._buy(ContextInfo, stock)
            elif curr_rsi > self.overbought:
                self._sell(ContextInfo, stock)

    def _buy(self, ContextInfo, stock):
        try:
            order_value(stock, 10000, ContextInfo)  # noqa: F821
        except NameError:
            from core.order_helper import buy
            buy(stock, 100, ContextInfo, account_id=self.account_id, strategy_name=self.strategy_name)

    def _sell(self, ContextInfo, stock):
        try:
            order_target_percent(stock, 0, ContextInfo)  # noqa: F821
        except NameError:
            from core.order_helper import sell
            sell(stock, 100, ContextInfo, account_id=self.account_id, strategy_name=self.strategy_name)


_strategy = RsiStrategy(
    stock_list=STOCK_LIST,
    period=PERIOD,
    account_id=ACCOUNT_ID,
    strategy_name=STRATEGY_NAME,
    rsi_period=14,
    oversold=30,
    overbought=70,
)


def init(ContextInfo):
    _strategy.init(ContextInfo)


def after_init(ContextInfo):
    _strategy.after_init(ContextInfo)


def handlebar(ContextInfo):
    _strategy.handlebar(ContextInfo)
