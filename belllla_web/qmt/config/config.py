# -*- coding: utf-8 -*-
"""
QMT 策略配置模块

配置账户、标的池、K线周期、回测时间及策略通用参数。
在 QMT 中加载策略前，请根据实际情况修改以下配置。
"""

# 账户配置
ACCOUNT_ID = ""  # 资金账号，实盘时填写
ACCOUNT_TYPE = "STOCK"  # 账户类型：STOCK / CREDIT 等

# 标的池（股票代码，格式：代码.市场）
STOCK_LIST = [
    "000001.SZ",  # 平安银行
    "600519.SH",  # 贵州茅台
    "510050.SH",  # 50ETF
]

# K线周期
# 1d=日线, 1m=1分钟, 5m=5分钟, 15m=15分钟, 30m=30分钟, 60m=60分钟
PERIOD = "1d"

# 回测时间范围（仅回测时生效）
START_TIME = "20230101"
END_TIME = "20241231"

# 除权方式：none / front / back / follow
DIVIDEND_TYPE = "front"

# 策略通用参数
POSITION_RATIO = 0.95  # 单标的最大仓位比例 (0~1)
STOP_LOSS = 0.0  # 止损比例，0 表示不启用
TAKE_PROFIT = 0.0  # 止盈比例，0 表示不启用
STRATEGY_NAME = "QMT策略"  # 策略名称，用于下单备注
