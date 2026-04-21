## 附录：Backtrader API速查

### Cerebro常用方法

```python
cerebro = bt.Cerebro()

# 数据
cerebro.adddata(data)                    # 添加数据源
cerebro.resampledata(data, timeframe)    # 重采样数据

# 策略
cerebro.addstrategy(Strategy, param=value)  # 添加策略
cerebro.optstrategy(Strategy, param=range)  # 参数优化

# 资金和佣金
cerebro.broker.setcash(100000)           # 设置初始资金
cerebro.broker.setcommission(0.0003)     # 设置佣金
cerebro.broker.getvalue()                # 获取当前账户价值
cerebro.broker.getcash()                 # 获取当前现金

# 仓位管理
cerebro.addsizer(bt.sizers.FixedSize, stake=100)       # 固定数量
cerebro.addsizer(bt.sizers.PercentSizer, percents=95)  # 百分比仓位

# 分析器
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')

# 运行和绘图
results = cerebro.run()                  # 运行回测
cerebro.plot()                           # 绘制图表
```

### Strategy常用属性和方法

```python
class MyStrategy(bt.Strategy):
    # 访问数据
    self.data.close[0]      # 当前收盘价
    self.data.close[-1]     # 上一根K线收盘价
    self.data.open[0]       # 当前开盘价
    self.data.high[0]       # 当前最高价
    self.data.low[0]        # 当前最低价
    self.data.volume[0]     # 当前成交量

    # 持仓信息
    self.position           # 持仓对象（bool）
    self.position.size      # 持仓数量
    self.position.price     # 持仓成本

    # 发出订单
    self.buy()              # 市价买入
    self.sell()             # 市价卖出
    self.close()            # 平仓（无论多空）

    self.buy(size=100)      # 指定数量买入
    self.buy(price=100)     # 限价单买入

    # 获取账户信息
    self.broker.getvalue()  # 账户总价值
    self.broker.getcash()   # 可用现金
```
