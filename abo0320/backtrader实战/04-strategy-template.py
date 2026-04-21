class MyStrategy(bt.Strategy):
    # 【可选】定义策略参数
    params = (
        ('period', 20),  # 移动平均线周期
    )

    def __init__(self):
        """
        初始化方法，只运行一次
        作用：
        1. 创建技术指标
        2. 定义辅助变量
        3. 预计算可以预计算的东西
        """
        pass

    def next(self):
        """
        核心方法，每根K线调用一次
        作用：
        1. 读取当前市场数据
        2. 判断买卖条件
        3. 发出交易指令
        """
        pass

    def notify_order(self, order):
        """
        订单状态变化时调用
        作用：记录订单成交情况
        """
        pass

    def notify_trade(self, trade):
        """
        交易完成时调用
        作用：记录盈亏情况
        """
        pass

    def stop(self):
        """
        回测结束时调用
        作用：打印策略参数、最终结果
        """
        pass