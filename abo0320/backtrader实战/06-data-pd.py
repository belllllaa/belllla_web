import backtrader as bt
import pandas as pd
import datetime

class PrintCloseStrategy(bt.Strategy):
    def next(self):
        print(f'{self.data.datetime.date(0)}: {self.data.close[0]:.2f}')

# 1. 从Pandas读取数据
# 确保解析日期列，并将其设为索引
df = pd.read_csv('btc_daily_2020_2026.csv', parse_dates=['Date'], index_col='Date')

# 2. 创建Cerebro
cerebro = bt.Cerebro()

# 3. 转换为Backtrader数据格式
data = bt.feeds.PandasData(
    dataname=df,
    # 设置起止日期（可选）
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2020, 1, 10)
)

cerebro.adddata(data)

# 4. 添加策略
cerebro.addstrategy(PrintCloseStrategy)

# 5. 运行
print("\nPandas数据加载测试：")
cerebro.run()