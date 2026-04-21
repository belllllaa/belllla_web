import backtrader as bt

# ========== 1. 定义策略类 ==========
class BuyAndHold(bt.Strategy):
    """
    最简单的买入持有策略：
    - 第一根K线买入
    - 一直持有到最后
    """

    def __init__(self):
        # 记录是否已买入
        self.bought = False

    def next(self):
        # 如果还没买入
        if not self.bought:
            # 打印当前状态
            print(f'{self.data.datetime.date(0)}: 买入，价格 {self.data.close[0]:.2f}')

            # 发出买入订单（默认买入所有可用资金）
            self.buy()

            # 标记已买入
            self.bought = True

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f'  → 买入成交: {order.executed.price:.2f}, '
                      f'数量: {order.executed.size:.0f}, '
                      f'佣金: {order.executed.comm:.2f}')


# ========== 2. 创建Cerebro ==========
cerebro = bt.Cerebro()

# ========== 3. 加载数据 ==========
data = bt.feeds.GenericCSVData(
    dataname='btc_daily_2020_2026.csv',
    dtformat='%Y-%m-%d',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=6
)
cerebro.adddata(data)

# ========== 4. 添加策略 ==========
cerebro.addstrategy(BuyAndHold)

# ========== 5. 设置初始资金 ==========
cerebro.broker.setcash(100000.0)

# ========== 6. 设置佣金（万分之三） ==========
cerebro.broker.setcommission(commission=0.0003)

# ========== 7. 打印起始信息 ==========
print('=' * 50)
print('回测开始')
print(f'起始资金: {cerebro.broker.getvalue():,.2f} 元')
print('=' * 50)

# ========== 8. 运行回测 ==========
cerebro.run()

# ========== 9. 打印最终结果 ==========
print('=' * 50)
print('回测结束')
print(f'最终资金: {cerebro.broker.getvalue():,.2f} 元')
print(f'收益率: {(cerebro.broker.getvalue() / 100000 - 1) * 100:.2f}%')
print('=' * 50)