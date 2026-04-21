import pandas as pd

# 假设我们有BTC数据
data = pd.read_csv('btc_daily_2020_2026.csv')
cash = 100000  # 初始资金
position = 0   # 持仓数量

for i in range(len(data)):
    # 简单策略：价格低于7000买入，高于8000卖出
    if data['Close'][i] < 7000 and cash > 0:
        # 买入
        position = cash / data['Close'][i]
        cash = 0
    elif data['Close'][i] > 8000 and position > 0:
        # 卖出
        cash = position * data['Close'][i]
        position = 0

print(f'最终资金: {cash}')