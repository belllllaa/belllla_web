import backtrader as bt
import datetime

# 定义一个简单的买入策略
class TestBrokerStrategy(bt.Strategy):
    def next(self):
        # 在第一根K线买入
        if len(self) == 1:
            # 获取当前收盘价
            price = self.data.close[0]
            # 买入 1 个单位的 BTC
            self.buy(size=1)
            print(f'{self.data.datetime.date(0)}: 发出买入指令, 价格 {price:.2f}')

    def notify_order(self, order):
        # 打印订单执行详情
        if order.status in [order.Completed]:
            print(f'{self.data.datetime.date(0)}: 订单成交')
            print(f'  成交价格: {order.executed.price:.2f}')
            print(f'  成交数量: {order.executed.size}')
            print(f'  手续费: {order.executed.comm:.2f}')
            # 这里的成交价包含了滑点的影响

# 1. 创建Cerebro
cerebro = bt.Cerebro()

# 2. 加载数据 (只加载前10天以便观察)
data = bt.feeds.GenericCSVData(
    dataname='btc_daily_2020_2026.csv',
    dtformat='%Y-%m-%d',
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2020, 1, 10),
    datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=6
)
cerebro.adddata(data)

# 3. 添加策略
cerebro.addstrategy(TestBrokerStrategy)

# 4. 配置Broker (关键步骤！)
# 4.1 设置初始资金 100,000
cerebro.broker.setcash(100000.0)

# 4.2 设置佣金为 万分之三 (0.0003)
cerebro.broker.setcommission(commission=0.0003)

# 4.3 设置百分比滑点 0.1% (0.001)
# 注意：set_slippage_perc 需要在 setcommission 之后调用
cerebro.broker.set_slippage_perc(0.001)

# 5. 运行回测
print(f'初始资金: {cerebro.broker.getvalue():.2f}')
cerebro.run()
print(f'最终资金: {cerebro.broker.getvalue():.2f}')