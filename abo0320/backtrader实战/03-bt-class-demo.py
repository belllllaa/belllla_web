import backtrader as bt

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        # 这个方法每根K线调用一次
        if self.ma5[0] > self.ma20[0] and not self.position:
            self.buy()  # 发出买入订单
        elif self.ma5[0] < self.ma20[0] and self.position:
            self.sell()  # 发出卖出订单