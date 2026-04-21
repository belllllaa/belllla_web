import backtrader as bt
import datetime

# 定义一个只打印收盘价的策略，用于验证数据是否加载成功
class PrintCloseStrategy(bt.Strategy):
    def next(self):
        # 打印当前日期的收盘价
        # self.data.datetime.date(0) 获取当前日期
        # self.data.close[0] 获取当前收盘价
        print(f'{self.data.datetime.date(0)}: {self.data.close[0]:.2f}')

# 1. 创建Cerebro
cerebro = bt.Cerebro()

# 2. 加载数据
data = bt.feeds.GenericCSVData(
    dataname='btc_daily_2020_2026.csv',
    dtformat='%Y-%m-%d',  # 日期格式
    
    # 设置起止日期（可选）
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2020, 1, 10),
    
    datetime=0,  # 日期列在第0列
    open=1,      # 开盘价在第1列
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=6  # 持仓量
)

cerebro.adddata(data)

# 3. 添加策略
cerebro.addstrategy(PrintCloseStrategy)

# 4. 运行
print("CSV数据加载测试：")
cerebro.run()

'''
| 列名 | 含义 | 类型 |
|------|------|------|
| datetime | 日期时间 | datetime或字符串 |
| open | 开盘价 | float |
| high | 最高价 | float |
| low | 最低价 | float |
| close | 收盘价 | float |
| volume | 成交量 | float |
| openinterest | 持仓量（可选，期货用） | float |
'''