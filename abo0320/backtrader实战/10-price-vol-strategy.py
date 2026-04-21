import backtrader as bt


# ========== 策略类 ==========
class VolumePriceStrategy(bt.Strategy):
    """量价共振策略"""

    params = (
        ('ma_period', 20),
        ('printlog', True),
        ('position_pct', 0.9),
    )

    def __init__(self):
        """初始化指标"""
        self.sma = bt.indicators.SMA(self.data.close, period=self.params.ma_period)
        self.volume_sma = bt.indicators.SMA(self.data.volume, period=self.params.ma_period)
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sma)
        self.order = None
        self.buy_price = None
        self.buy_comm = None

    def log(self, txt, dt=None):
        """统一日志输出"""
        dt = dt or self.data.datetime.date(0)
        if self.params.printlog:
            print('{} - {}'.format(dt.isoformat(), txt))

    def next(self):
        """每根K线调用：交易逻辑"""
        if self.order:
            return

        # 使用 position.size 明确判断持仓状态
        current_pos = self.position.size

        # 情况1: 无持仓，寻找买入机会
        if current_pos == 0:
            # 买入条件：价格上穿MA且成交量放大
            if self.crossover[0] > 0 and self.data.volume[0] > self.volume_sma[0]:
                self.log('买入信号 | 价格:{:.2f} MA:{:.2f} 量:{:.0f} 量均:{:.0f}'.format(
                    self.data.close[0], self.sma[0],
                    self.data.volume[0], self.volume_sma[0]
                ))
                # 计算买入数量（使用90%资金）
                cash = self.broker.getcash()
                size = (cash * self.params.position_pct) / self.data.close[0]  # BTC可分割
                if size > 0:
                    self.order = self.buy(size=size)

        # 情况2: 持有多仓，寻找卖出机会
        elif current_pos > 0:
            # 卖出条件：价格下穿MA
            if self.crossover[0] < 0:
                self.log('卖出信号 | 价格:{:.2f} MA:{:.2f} 当前仓位:{:.0f}'.format(
                    self.data.close[0], self.sma[0], current_pos
                ))
                # 使用 close() 平仓，而不是 sell()
                self.order = self.close()

        # 情况3: 持有空头仓位（防御性代码，理论上不应该出现）
        elif current_pos < 0:
            self.log('警告：检测到空头仓位，立即平仓 | 仓位:{:.0f}'.format(current_pos))
            self.order = self.close()

    def notify_order(self, order):
        """订单状态变化通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log('买入成交 | 价格:{:.2f} 数量:{:.4f} 佣金:{:.2f} 成本:{:.2f}'.format(
                    order.executed.price, order.executed.size,
                    order.executed.comm, order.executed.value
                ))
                self.buy_price = order.executed.price
                self.buy_comm = order.executed.comm
            elif order.issell():
                self.log('卖出成交 | 价格:{:.2f} 数量:{:.4f} 佣金:{:.2f}'.format(
                    order.executed.price, order.executed.size,
                    order.executed.comm
                ))
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单失败')

        self.order = None

    def notify_trade(self, trade):
        """交易完成通知"""
        if not trade.isclosed:
            return

        self.log('交易利润 | 毛利:{:.2f} 净利:{:.2f}'.format(
            trade.pnl, trade.pnlcomm
        ))

    # ===== 回测结束统计 =====
    def stop(self):
        """回测结束时调用"""
        self.log('(MA周期={:2d}) 期末资金:{:.2f}'.format(
            self.params.ma_period,
            self.broker.getvalue()
        ), dt=self.data.datetime.date(0))


# ========== 主程序 ==========
if __name__ == '__main__':
    cerebro = bt.Cerebro()
    cerebro.addstrategy(VolumePriceStrategy)

    data = bt.feeds.GenericCSVData(
        dataname='btc_daily_2020_2026.csv',
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=6
    )
    cerebro.adddata(data)

    start_cash = 100000.0
    cerebro.broker.setcash(start_cash)
    cerebro.broker.setcommission(commission=0.001)

    print('=' * 60)
    print('起始资金: {:.2f}'.format(cerebro.broker.getvalue()))
    print('=' * 60)

    cerebro.run()

    print('=' * 60)
    print('最终资金: {:.2f}'.format(cerebro.broker.getvalue()))
    print('收益率: {:.2f}%'.format(
        (cerebro.broker.getvalue() / start_cash - 1) * 100
    ))
    print('=' * 60)
