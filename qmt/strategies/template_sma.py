# -*- coding: utf-8 -*-
"""
双均线策略：MA5 上穿 MA20 买入，下穿卖出

QMT 入口：init, after_init, handlebar
在 QMT 中加载本文件即可回测或实盘运行。
"""

import sys
import os

# 将项目根目录加入路径，便于导入
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
from utils.indicators import ma


class SmaStrategy(BaseStrategy):
    """双均线策略"""

    def __init__(self, fast=5, slow=20, **kwargs):
        super().__init__(**kwargs)
        self.fast = fast
        self.slow = slow

    def on_init(self, ContextInfo):
        ContextInfo.stock_list = self.stock_list
        # 可选：下载历史数据（download_history_data 为 QMT 内置函数）
        try:
            start = getattr(ContextInfo, "start_time", "")
            end = getattr(ContextInfo, "end_time", "")
            for code in self.stock_list:
                download_history_data(code, self.period, start, end)  # noqa: F821
        except Exception:
            pass

    def on_bar(self, ContextInfo):
        for stock in self.stock_list:
            df = get_ohlcv_df(ContextInfo, stock, period=self.period, count=self.slow + 5)
            if df is None or len(df) < self.slow:
                continue

            close = _get_close(df)
            if close is None or len(close) < self.slow:
                continue
            ma_fast = ma(close, self.fast)
            ma_slow = ma(close, self.slow)

            if len(ma_fast) < 2 or len(ma_slow) < 2:
                continue

            # 取最新有效值
            idx = -1
            while idx >= -len(ma_fast) and (ma_fast[idx] != ma_fast[idx] or ma_slow[idx] != ma_slow[idx]):
                idx -= 1
            if idx < -len(ma_fast) + 1:
                continue

            prev_fast, curr_fast = ma_fast[idx - 1], ma_fast[idx]
            prev_slow, curr_slow = ma_slow[idx - 1], ma_slow[idx]

            # 金叉：上穿
            if prev_fast <= prev_slow and curr_fast > curr_slow:
                self._buy(ContextInfo, stock)
            # 死叉：下穿
            elif prev_fast >= prev_slow and curr_fast < curr_slow:
                self._sell(ContextInfo, stock)

    def _buy(self, ContextInfo, stock):
        """买入：回测用 order_value，实盘用 passorder"""
        try:
            order_value(stock, 10000, ContextInfo)  # noqa: F821 回测专用
        except NameError:
            from core.order_helper import buy
            buy(stock, 100, ContextInfo, account_id=self.account_id, strategy_name=self.strategy_name)

    def _sell(self, ContextInfo, stock):
        """卖出"""
        try:
            order_target_percent(stock, 0, ContextInfo)  # noqa: F821 回测专用
        except NameError:
            from core.order_helper import sell
            sell(stock, 100, ContextInfo, account_id=self.account_id, strategy_name=self.strategy_name)


# 创建策略实例并导出 QMT 入口
_strategy = SmaStrategy(
    stock_list=STOCK_LIST,
    period=PERIOD,
    account_id=ACCOUNT_ID,
    strategy_name=STRATEGY_NAME,
    fast=5,
    slow=20,
)


def init(ContextInfo):
    _strategy.init(ContextInfo)


def after_init(ContextInfo):
    _strategy.after_init(ContextInfo)


def handlebar(ContextInfo):
    _strategy.handlebar(ContextInfo)
