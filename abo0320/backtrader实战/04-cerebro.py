import backtrader as bt

cerebro = bt.Cerebro()

data = bt.feeds.GenericCSVData(
    dataname='btc_daily_2020_2026.csv',
    dtformat='%Y-%m-%d',
    datetime=0,  # 日期列索引
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=6  # 持仓量
)
cerebro.adddata(data)

class DummyStrategy(bt.Strategy):
    def next(self):
        pass

cerebro.addstrategy(DummyStrategy)

cerebro.broker.setcash(100000.0)
cerebro.broker.setcommission(commission=0.0003)
print(f'起始资金: {cerebro.broker.getvalue():.2f}')
cerebro.run()

print(f'最终资金: {cerebro.broker.getvalue():.2f}')


'''
| 方法 | 作用 | 示例 |
|------|------|------|
| `adddata(data)` | 添加数据源 | `cerebro.adddata(data)` |
| `addstrategy(Strategy)` | 添加策略 | `cerebro.addstrategy(MyStrategy)` |
| `broker.setcash(cash)` | 设置初始资金 | `cerebro.broker.setcash(100000)` |
| `broker.setcommission(commission)` | 设置佣金 | `cerebro.broker.setcommission(0.0003)` |
| `addsizer(Sizer)` | 设置仓位管理 | `cerebro.addsizer(bt.sizers.PercentSizer, percents=95)` |
| `addanalyzer(Analyzer)` | 添加分析器 | `cerebro.addanalyzer(bt.analyzers.SharpeRatio)` |
| `run()` | 运行回测 | `results = cerebro.run()` |
| `plot()` | 绘制图表 | `cerebro.plot()` |
'''