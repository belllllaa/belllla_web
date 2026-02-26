# -*- coding: utf-8 -*-
"""
QMT 策略基类

定义 init、after_init、handlebar 标准流程，预留 on_init、on_bar 等子类重写接口。
"""


class BaseStrategy:
    """
    策略基类，子类重写 on_init、on_bar 实现具体逻辑
    """

    def __init__(self, stock_list=None, period="1d", account_id="", strategy_name="QMT策略"):
        self.stock_list = stock_list or []
        self.period = period
        self.account_id = account_id
        self.strategy_name = strategy_name

    def on_init(self, ContextInfo):
        """
        初始化逻辑，子类重写
        在 init 中调用，可用于设置 stock_list、下载历史数据等
        """
        pass

    def on_after_init(self, ContextInfo):
        """
        后初始化逻辑，子类重写
        在 after_init 中调用
        """
        pass

    def on_bar(self, ContextInfo):
        """
        每根 K 线逻辑，子类重写
        在 handlebar 中调用，实现信号计算与下单
        """
        pass

    def init(self, ContextInfo):
        """QMT 入口：初始化"""
        ContextInfo.stock_list = self.stock_list
        ContextInfo.period = self.period
        ContextInfo.account_id = self.account_id
        ContextInfo.strategy_name = self.strategy_name
        self.on_init(ContextInfo)

    def after_init(self, ContextInfo):
        """QMT 入口：后初始化"""
        self.on_after_init(ContextInfo)

    def handlebar(self, ContextInfo):
        """QMT 入口：每根 K 线"""
        self.on_bar(ContextInfo)


def create_strategy_entries(strategy_instance):
    """
    将策略实例转为 QMT 所需的 init/after_init/handlebar 函数

    用法:
        strategy = MyStrategy(stock_list=[...])
        init, after_init, handlebar = create_strategy_entries(strategy)
    """
    def init(ContextInfo):
        strategy_instance.init(ContextInfo)

    def after_init(ContextInfo):
        strategy_instance.after_init(ContextInfo)

    def handlebar(ContextInfo):
        strategy_instance.handlebar(ContextInfo)

    return init, after_init, handlebar
