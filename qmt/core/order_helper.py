# -*- coding: utf-8 -*-
"""
QMT 下单封装模块

封装 passorder 函数，简化 opType/orderType/prType 等枚举参数。
提供 buy、sell 等简洁接口，支持按股数、按金额两种下单方式。
"""

# QMT 枚举常量
OP_BUY = 23
OP_SELL = 24
ORDER_BY_SHARES = 1101  # 按股数
ORDER_BY_VALUE = 1102   # 按金额
PR_LATEST = 5           # 最新价
PR_LIMIT = 11           # 指定价
QUICK_TRADE = 1         # 非历史bar立即触发


def buy(
    stock_code,
    volume,
    ContextInfo,
    account_id=None,
    price_type=PR_LATEST,
    price=0,
    by_value=False,
    strategy_name="",
    user_order_id="",
):
    """
    买入股票

    :param stock_code: 股票代码，如 '000001.SZ'
    :param volume: 数量（股数或金额，由 by_value 决定）
    :param ContextInfo: QMT 上下文对象
    :param account_id: 账户ID，若为空则从 ContextInfo 获取
    :param price_type: 5=最新价, 11=指定价
    :param price: 指定价时的价格，最新价时传 0
    :param by_value: True=按金额下单, False=按股数下单
    :param strategy_name: 策略名
    :param user_order_id: 用户备注
    """
    _passorder(
        op_type=OP_BUY,
        stock_code=stock_code,
        volume=volume,
        ContextInfo=ContextInfo,
        account_id=account_id,
        price_type=price_type,
        price=price,
        by_value=by_value,
        strategy_name=strategy_name,
        user_order_id=user_order_id,
    )


def sell(
    stock_code,
    volume,
    ContextInfo,
    account_id=None,
    price_type=PR_LATEST,
    price=0,
    by_value=False,
    strategy_name="",
    user_order_id="",
):
    """
    卖出股票

    参数同 buy
    """
    _passorder(
        op_type=OP_SELL,
        stock_code=stock_code,
        volume=volume,
        ContextInfo=ContextInfo,
        account_id=account_id,
        price_type=price_type,
        price=price,
        by_value=by_value,
        strategy_name=strategy_name,
        user_order_id=user_order_id,
    )


def _passorder(
    op_type,
    stock_code,
    volume,
    ContextInfo,
    account_id=None,
    price_type=PR_LATEST,
    price=0,
    by_value=False,
    strategy_name="",
    user_order_id="",
):
    """
    内部调用 passorder

    注意：需在 QMT 环境中运行，passorder 为 QMT 内置函数。
    """
    acc = account_id or getattr(ContextInfo, "account_id", "")
    order_type = ORDER_BY_VALUE if by_value else ORDER_BY_SHARES
    strategy_name = strategy_name or getattr(ContextInfo, "strategy_name", "QMT策略")

    # passorder 为 QMT 内置函数，需在 QMT 环境中运行
    import sys
    try:
        _passorder_fn = getattr(sys.modules["__main__"], "passorder")
    except (KeyError, AttributeError):
        _passorder_fn = globals().get("passorder")
    if _passorder_fn is None:
        print("[OrderHelper] passorder 未找到，请在 QMT 环境中运行")
        return

    _passorder_fn(
        op_type,
        order_type,
        acc,
        stock_code,
        price_type,
        price,
        volume,
        strategy_name,
        QUICK_TRADE,
        user_order_id,
        ContextInfo,
    )


class OrderHelper:
    """
    下单辅助类，可预置账户、策略名等参数
    """

    def __init__(self, account_id="", strategy_name="QMT策略"):
        self.account_id = account_id
        self.strategy_name = strategy_name

    def buy(
        self,
        stock_code,
        volume,
        ContextInfo,
        price_type=PR_LATEST,
        price=0,
        by_value=False,
        user_order_id="",
    ):
        buy(
            stock_code,
            volume,
            ContextInfo,
            account_id=self.account_id,
            price_type=price_type,
            price=price,
            by_value=by_value,
            strategy_name=self.strategy_name,
            user_order_id=user_order_id,
        )

    def sell(
        self,
        stock_code,
        volume,
        ContextInfo,
        price_type=PR_LATEST,
        price=0,
        by_value=False,
        user_order_id="",
    ):
        sell(
            stock_code,
            volume,
            ContextInfo,
            account_id=self.account_id,
            price_type=price_type,
            price=price,
            by_value=by_value,
            strategy_name=self.strategy_name,
            user_order_id=user_order_id,
        )
