import pandas as pd
import numpy as np

# 加载数据
df = pd.read_csv('btc_daily_2020_2026.csv')

# 一次性计算所有指标
df['MA5'] = df['Close'].rolling(5).mean()
df['MA20'] = df['Close'].rolling(20).mean()

# 一次性生成所有信号
df['signal'] = np.where(df['MA5'] > df['MA20'], 1, 0)  # 1=买入，0=卖出
df['position'] = df['signal'].diff()  # 持仓变化

# 计算收益
df['returns'] = df['Close'].pct_change() * df['signal'].shift(1)
total_return = df['returns'].sum()

# 打印结果看看发生什么
print("策略信号预览：")
print(df[['Close', 'MA5', 'MA20', 'signal']].tail())
print(f'策略总收益: {total_return:.2%}')