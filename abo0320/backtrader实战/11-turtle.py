"""
海龟交易策略 - BTC数据版本

本版本专门适配加密货币（BTC）数据：
    - 支持从CSV文件读取数据
    - 不依赖自定义的backtest模块
    - 使用Backtrader原生引擎
    - 适配BTC的高波动率特点

数据格式要求：
    Date,Open,High,Low,Close,Volume,OpenInterest
    2020-01-01,7194.89,7254.33,7174.94,7200.17,18565664997,0

使用方法：
    1. 下载BTC数据: python get_btc_data.py
    2. 运行策略: python turtle_strategy_btc.py
    3. 查看结果和图表
"""

import backtrader as bt
import backtrader.indicators as bi
import math
import datetime
from pathlib import Path


class TurtleStrategy(bt.Strategy):
    """
    海龟交易策略实现（系统1：20日突破）

    交易规则：
        入场：价格突破20日最高价时买入
        加仓：价格每上涨0.5个ATR就加仓一次，最多加仓3次（总共4个单位）
        止损：价格跌破入场价格2个ATR时止损
        离场：价格跌破10日最低价时平仓

    仓位管理：
        每个单位风险 = 账户价值 × 1%
        单位头寸 = (账户价值 × 1%) / ATR

    BTC特殊说明：
        - BTC以美元计价，价格范围大（几千到几万美元）
        - 波动率较高，止损2ATR在BTC上是合理的
        - 可交易小数数量（不受100股限制）
    """

    params = (
        # === 突破系统参数 ===
        ("entry_period", 20),          # 入场周期：20日突破
        ("exit_period", 10),           # 离场周期：10日突破

        # === 波动率参数 ===
        ("atr_period", 14),            # ATR计算周期

        # === 仓位管理参数 ===
        ("risk_per_unit", 0.01),       # 每单位风险：账户的1%
        ("pyramid_units", 4),          # 金字塔总单位数：4（初始1 + 加仓3次）
        ("add_unit_atr", 0.5),         # 加仓间隔：0.5个ATR

        # === 止损参数 ===
        ("stop_loss_atr", 2.0),        # 止损距离：2个ATR

        # === BTC特殊参数 ===
        ("min_position_size", 0.001),  # 最小交易数量（BTC）
        ("size_precision", 3),         # 数量精度（小数位数）

        # === 日志参数 ===
        ("printlog", True),            # 是否打印日志
    )

    def __init__(self):
        """初始化策略指标和状态变量"""

        # === 订单管理 ===
        self.order = None                    # 当前订单

        # === 持仓状态 ===
        self.buy_count = 0                   # 当前持仓单位数（0=空仓, 1-4=持仓）
        self.first_buy_price = 0             # 首次入场价格
        self.last_buy_price = 0              # 最后一次买入价格（用于计算加仓点）
        self.avg_price = 0                   # 平均持仓成本
        self.total_cost = 0                  # 累计成本
        self.total_size = 0                  # 累计持仓数量

        # === 手续费统计 ===
        self.comm = 0                        # 累计手续费

        # === 技术指标 ===
        # 1. 突破通道：基于前一日的最高/最低价计算（排除当日，避免未来函数）
        self.upper_band = bi.Highest(
            self.data.high(-1),
            period=self.p.entry_period,
            subplot=False
        )
        self.lower_band = bi.Lowest(
            self.data.low(-1),
            period=self.p.exit_period,
            subplot=False
        )

        # 2. ATR（真实波动幅度均值）：用于仓位计算和止损
        #    TR = Max(高-低, |昨收-今高|, |昨收-今低|)
        self.TR = bi.Max(
            (self.data.high(0) - self.data.low(0)),                    # 当日振幅
            abs(self.data.close(-1) - self.data.high(0)),             # 向上跳空
            abs(self.data.close(-1) - self.data.low(0))               # 向下跳空
        )
        self.ATR = bi.SimpleMovingAverage(self.TR, period=self.p.atr_period)

        # 3. 突破信号：收盘价与通道交叉
        self.buy_signal = bt.ind.CrossOver(self.data.close(0), self.upper_band)
        self.sell_signal = bt.ind.CrossOver(self.data.close(0), self.lower_band)

    def next(self):
        """
        策略主逻辑：每根K线执行一次

        执行优先级：
            1. 如果有未完成订单，等待执行
            2. 止损检查（最高优先级）
            3. 离场信号检查
            4. 加仓检查
            5. 入场信号检查
        """

        # 等待订单执行完成
        if self.order:
            return

        current_price = self.data.close[0]
        current_atr = self.ATR[0]

        # ========== 规则1：止损（最高优先级） ==========
        # 条件：持有仓位 且 价格跌破入场价2个ATR
        if self.buy_count > 0 and current_price < (self.first_buy_price - self.p.stop_loss_atr * current_atr):
            self.order = self.close()  # 全部平仓
            self.log(f'⚠️ 触发止损 | 止损价=${self.first_buy_price - self.p.stop_loss_atr * current_atr:.2f} | 当前价=${current_price:.2f}')
            return

        # ========== 规则2：离场信号 ==========
        # 条件：价格跌破10日最低价 且 持有仓位
        if self.sell_signal < 0 and self.buy_count > 0:
            self.order = self.close()  # 全部平仓
            self.log(f'📉 离场信号 | 价格跌破{self.p.exit_period}日低点 | 当前价=${current_price:.2f}')
            return

        # ========== 规则3：加仓 ==========
        # 条件：价格上涨超过0.5个ATR 且 未达到最大单位数
        if (self.buy_count > 0 and
            self.buy_count < self.p.pyramid_units and
            current_price > self.last_buy_price + self.p.add_unit_atr * current_atr):

            # 计算加仓数量
            buy_size = self._calculate_position_size()
            if buy_size >= self.p.min_position_size:
                self.order = self.buy(size=buy_size)
                self.log(f'➕ 加仓信号 | 单位{self.buy_count + 1}/{self.p.pyramid_units} | 数量={buy_size:.4f} BTC | ATR=${current_atr:.2f}')
            return

        # ========== 规则4：入场 ==========
        # 条件：价格突破20日最高价 且 当前空仓
        if self.buy_signal > 0 and self.buy_count == 0:
            # 计算首次买入数量
            buy_size = self._calculate_position_size()
            if buy_size >= self.p.min_position_size:
                self.order = self.buy(size=buy_size)
                self.log(f'📈 入场信号 | 突破{self.p.entry_period}日高点 | 数量={buy_size:.4f} BTC | ATR=${current_atr:.2f}')
            return

    def _calculate_position_size(self):
        """
        计算每个单位的持仓数量（BTC数量）

        原理：
            单位头寸 = (账户价值 × 风险比例) / ATR
            目的是让每个单位的风险暴露相同（都是账户的1%）

        举例（BTC）：
            账户价值 = 100,000 USD
            BTC价格 = 30,000 USD
            ATR = 1,500 USD
            风险比例 = 1%

            计算过程：
            风险金额 = 100,000 × 0.01 = 1,000 USD
            单位头寸 = 1,000 / 1,500 = 0.667 BTC
            成本 = 0.667 × 30,000 = 20,000 USD

            验证：
            如果价格波动1个ATR（1,500 USD）
            盈亏 = 0.667 BTC × 1,500 USD = 1,000 USD = 账户的1% ✅

        Returns:
            float: 本次买入数量（BTC），保留指定小数位
        """
        if self.ATR[0] == 0:
            return 0

        # 风险金额 = 账户价值 × 风险比例
        risk_amount = self.broker.getvalue() * self.p.risk_per_unit

        # 单位头寸（BTC数量） = 风险金额 / ATR
        unit_size = risk_amount / self.ATR[0]

        # 保留指定小数位（如0.001 BTC）
        return round(unit_size, self.p.size_precision)

    # ========== 日志和通知 ==========

    def log(self, txt, dt=None, doprint=False):
        """输出日志"""
        if self.params.printlog or doprint:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} | {txt}')

    def notify_order(self, order):
        """
        订单状态通知
        用于更新持仓状态和记录交易信息
        """
        # 订单提交或被接受，等待执行
        if order.status in [order.Submitted, order.Accepted]:
            return

        # 订单完成
        if order.status in [order.Completed]:
            if order.isbuy():
                # 买入成功：更新持仓状态
                self.buy_count += 1
                self.last_buy_price = order.executed.price

                # 记录首次入场价格（用于止损）
                if self.buy_count == 1:
                    self.first_buy_price = order.executed.price

                # 更新平均成本
                self.total_cost += order.executed.value
                self.total_size += order.executed.size
                self.avg_price = self.total_cost / self.total_size if self.total_size > 0 else 0

                # 记录手续费
                self.comm += order.executed.comm

                self.log(
                    f'✅ 买入成交 | 价格=${order.executed.price:.2f} | '
                    f'数量={order.executed.size:.4f} BTC | '
                    f'成本=${order.executed.value:.2f} | '
                    f'手续费=${order.executed.comm:.2f} | '
                    f'平均成本=${self.avg_price:.2f}'
                )
            else:
                # 卖出成功：计算盈亏
                profit = (order.executed.price - self.avg_price) * self.total_size if self.total_size > 0 else 0
                profit_pct = (order.executed.price / self.avg_price - 1) * 100 if self.avg_price > 0 else 0

                self.log(
                    f'✅ 卖出成交 | 价格=${order.executed.price:.2f} | '
                    f'数量={order.executed.size:.4f} BTC | '
                    f'成本=${order.executed.value:.2f} | '
                    f'手续费=${order.executed.comm:.2f} | '
                    f'盈亏=${profit:.2f} ({profit_pct:+.2f}%)'
                )

                # 重置持仓状态
                self.buy_count = 0
                self.first_buy_price = 0
                self.last_buy_price = 0
                self.avg_price = 0
                self.total_cost = 0
                self.total_size = 0

                # 记录手续费
                self.comm += order.executed.comm

        # 订单失败
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("❌ 交易失败：订单被拒绝或资金不足")

        # 清空订单引用
        self.order = None

    def stop(self):
        """
        回测结束时调用
        输出策略统计信息
        """
        final_value = self.broker.getvalue()
        initial_value = self.broker.startingcash
        total_return = (final_value / initial_value - 1) * 100
        comm_ratio = self.comm / final_value if final_value > 0 else 0

        self.log('=' * 70, doprint=True)
        self.log(f'📊 回测完成', doprint=True)
        self.log(f'   初始资金: ${initial_value:,.2f}', doprint=True)
        self.log(f'   期末资产: ${final_value:,.2f}', doprint=True)
        self.log(f'   总收益率: {total_return:+.2f}%', doprint=True)
        self.log(f'   累计手续费: ${self.comm:.2f}', doprint=True)
        self.log(f'   手续费占比: {comm_ratio:.4%}', doprint=True)
        self.log('=' * 70, doprint=True)


def _iter_figures(figs):
    if not figs:
        return
    for item in figs:
        if isinstance(item, (list, tuple)):
            for sub in item:
                if hasattr(sub, "savefig"):
                    yield sub
        elif hasattr(item, "savefig"):
            yield item


def _save_plot(cerebro, output_path, style, barup, bardown, dpi=150):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figs = cerebro.plot(style=style, barup=barup, bardown=bardown)
    fig_list = list(_iter_figures(figs))
    if not fig_list:
        return []

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix or ".png"
    stem = output.stem or "backtest_plot"

    saved_paths = []
    if len(fig_list) == 1:
        path = output.with_suffix(suffix)
        fig_list[0].savefig(path, dpi=dpi, bbox_inches="tight")
        plt.close(fig_list[0])
        saved_paths.append(path)
    else:
        for idx, fig in enumerate(fig_list, start=1):
            path = output.with_name(f"{stem}_{idx}{suffix}")
            fig.savefig(path, dpi=dpi, bbox_inches="tight")
            plt.close(fig)
            saved_paths.append(path)

    return saved_paths


def run_backtest(csv_file='./btc_daily_2020_2026.csv',
                 initial_cash=100000.0,
                 commission=0.001,
                 plot=True,
                 plot_filename=None):
    """
    运行回测

    参数：
        csv_file: CSV数据文件路径
        initial_cash: 初始资金（美元）
        commission: 交易手续费率（0.001 = 0.1%）
        plot: 是否绘制图表
        plot_filename: 保存图表路径（仅保存到文件时使用）

    CSV格式要求：
        Date,Open,High,Low,Close,Volume,OpenInterest
        2020-01-01,7194.89,7254.33,7174.94,7200.17,18565664997,0
    """

    # 创建Cerebro引擎
    cerebro = bt.Cerebro()

    # 添加策略
    cerebro.addstrategy(TurtleStrategy)

    # 读取数据
    data = bt.feeds.GenericCSVData(
        dataname=csv_file,
        # 日期列
        dtformat='%Y-%m-%d',
        datetime=0,
        # OHLCV列
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=6,
        # 其他设置
        fromdate=datetime.datetime(2020, 1, 1),
        todate=datetime.datetime(2026, 1, 1),
    )

    # 添加数据到引擎
    cerebro.adddata(data)

    # 设置初始资金
    cerebro.broker.setcash(initial_cash)

    # 设置交易手续费
    cerebro.broker.setcommission(commission=commission)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # 打印初始信息
    print('=' * 70)
    print('🐢 海龟交易策略 - BTC回测')
    print('=' * 70)
    print(f'📁 数据文件: {csv_file}')
    print(f'💰 初始资金: ${initial_cash:,.2f}')
    print(f'💸 手续费率: {commission:.2%}')
    print('=' * 70)
    print(f'🚀 开始回测...\n')

    # 运行回测
    results = cerebro.run()
    strategy = results[0]

    # 输出分析结果
    print('\n' + '=' * 70)
    print('📈 策略分析')
    print('=' * 70)

    # 收益分析
    returns_analyzer = strategy.analyzers.returns.get_analysis()
    print(f"📊 年化收益率: {returns_analyzer.get('rnorm100', 0):.2f}%")

    # 夏普比率
    sharpe = strategy.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe.get('sharperatio', None)
    if sharpe_ratio:
        print(f"📉 夏普比率: {sharpe_ratio:.2f}")
    else:
        print(f"📉 夏普比率: N/A")

    # 最大回撤
    drawdown = strategy.analyzers.drawdown.get_analysis()
    print(f"⚠️  最大回撤: {drawdown.max.drawdown:.2f}%")
    print(f"📅 回撤时长: {drawdown.max.len} 天")

    # 交易统计
    trades = strategy.analyzers.trades.get_analysis()
    total_trades = trades.total.closed if trades.total.closed else 0
    won_trades = trades.won.total if hasattr(trades, 'won') and trades.won.total else 0
    lost_trades = trades.lost.total if hasattr(trades, 'lost') and trades.lost.total else 0
    win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0

    print(f"🔢 交易次数: {total_trades}")
    print(f"✅ 盈利次数: {won_trades}")
    print(f"❌ 亏损次数: {lost_trades}")
    print(f"🎯 胜率: {win_rate:.2f}%")

    if hasattr(trades, 'won') and hasattr(trades, 'lost'):
        avg_win = trades.won.pnl.average if trades.won.total > 0 else 0
        avg_loss = abs(trades.lost.pnl.average) if trades.lost.total > 0 else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        print(f"💵 平均盈利: ${avg_win:.2f}")
        print(f"💸 平均亏损: ${avg_loss:.2f}")
        print(f"📊 盈亏比: {profit_factor:.2f}")

    print('=' * 70)

    # 绘制图表
    if plot:
        print('\n📊 生成图表中...')
        if plot_filename:
            saved_paths = _save_plot(
                cerebro,
                plot_filename,
                style='candlestick',
                barup='green',
                bardown='red'
            )
            if saved_paths:
                print('📁 图表已保存:')
                for path in saved_paths:
                    print(f'   - {path}')
        else:
            cerebro.plot(style='candlestick', barup='green', bardown='red')

    return cerebro, results


if __name__ == "__main__":
    """
    主程序：BTC海龟策略回测

    数据要求：
        1. 先运行 get_btc_data.py 下载数据
        2. 确保 btc_daily_2020_2026.csv 存在于当前目录

    调整参数：
        - 修改 initial_cash 改变初始资金
        - 修改 commission 改变手续费率（币安现货约0.1%）
        - 修改策略参数见下方示例
    """

    # 基础版本：使用默认参数
    cerebro, results = run_backtest(
        csv_file='./btc_daily_2020_2026.csv',
        initial_cash=100000.0,      # 10万美元初始资金
        commission=0.001,            # 0.1%手续费（币安现货费率）
        plot=True,                   # 显示图表
        plot_filename='backtest_plot.png'  # 仅保存图表（适合无GUI环境）
    )

    # ===== 高级用法：自定义策略参数 =====
    # 如果需要调整策略参数，使用以下方式：
    """
    cerebro = bt.Cerebro()

    # 添加策略时传入自定义参数
    cerebro.addstrategy(
        TurtleStrategy,
        entry_period=55,           # 改用系统2（55日突破）
        exit_period=20,            # 20日离场
        risk_per_unit=0.02,        # 提高风险至2%
        pyramid_units=3,           # 减少加仓次数
        stop_loss_atr=1.5,         # 收紧止损
        printlog=True
    )

    # ... 后续添加数据、运行回测等
    """
