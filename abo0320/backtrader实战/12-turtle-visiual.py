import backtrader as bt
import backtrader.indicators as bi
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
import math
import warnings

warnings.filterwarnings('ignore')

_SCRIPT_DIR = Path(__file__).resolve().parent


def _resolve_btc_csv(csv_file: str | Path | None) -> Path:
    """数据 CSV 相对脚本目录解析；未指定时在脚本目录或 utils/ 下自动查找。"""
    if csv_file is None:
        for p in (
            _SCRIPT_DIR / "btc_daily_2020_2026.csv",
            _SCRIPT_DIR / "utils" / "btc_daily_2020_2026.csv",
        ):
            if p.is_file():
                return p
        raise FileNotFoundError(
            "未找到 btc_daily_2020_2026.csv。请将数据放在本目录或 utils/ 下，"
            "或先运行 utils/get_btc_data.py 生成。\n"
            f"  期望路径: {_SCRIPT_DIR / 'btc_daily_2020_2026.csv'}\n"
            f"  或: {_SCRIPT_DIR / 'utils' / 'btc_daily_2020_2026.csv'}"
        )
    p = Path(csv_file)
    if not p.is_absolute():
        p = (_SCRIPT_DIR / p).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"数据文件不存在: {p}")
    return p


def _resolve_output_dir(output_dir: str | Path) -> Path:
    p = Path(output_dir)
    if not p.is_absolute():
        p = (_SCRIPT_DIR / p).resolve()
    return p


# Set matplotlib style（仅用 matplotlib，不依赖 seaborn，避免多 Python 环境缺包）
plt.rcParams['axes.unicode_minus'] = False
for _style in ('seaborn-v0_8-whitegrid', 'seaborn-whitegrid', 'ggplot'):
    try:
        plt.style.use(_style)
        break
    except OSError:
        continue
else:
    plt.rcParams['axes.grid'] = True
    plt.rcParams['grid.alpha'] = 0.3


class TurtleStrategyRecorder(bt.Strategy):
    """
    Turtle Strategy with Detailed Recording
    Records daily account value, positions, trades for visualization
    """

    params = (
        ("entry_period", 20),
        ("exit_period", 10),
        ("atr_period", 14),
        ("risk_per_unit", 0.01),
        ("pyramid_units", 4),
        ("add_unit_atr", 0.5),
        ("stop_loss_atr", 2.0),
        ("min_position_size", 0.001),
        ("size_precision", 3),
        ("printlog", False),
    )

    def __init__(self):
        # Order management
        self.order = None

        # Position state
        self.buy_count = 0
        self.first_buy_price = 0
        self.last_buy_price = 0
        self.avg_price = 0
        self.total_cost = 0
        self.total_size = 0
        self.comm = 0

        # Technical indicators
        self.upper_band = bi.Highest(self.data.high(-1), period=self.p.entry_period, subplot=False)
        self.lower_band = bi.Lowest(self.data.low(-1), period=self.p.exit_period, subplot=False)
        self.TR = bi.Max(
            (self.data.high(0) - self.data.low(0)),
            abs(self.data.close(-1) - self.data.high(0)),
            abs(self.data.close(-1) - self.data.low(0))
        )
        self.ATR = bi.SimpleMovingAverage(self.TR, period=self.p.atr_period)
        self.buy_signal = bt.ind.CrossOver(self.data.close(0), self.upper_band)
        self.sell_signal = bt.ind.CrossOver(self.data.close(0), self.lower_band)

        # ========== Record data ==========
        self.daily_records = []  # Daily records
        self.trade_records = []  # Trade records

    def next(self):
        """Main strategy logic"""
        if self.order:
            return

        current_price = self.data.close[0]
        current_atr = self.ATR[0]

        # Record daily data
        self.daily_records.append({
            'date': self.datas[0].datetime.date(0),
            'open': self.data.open[0],
            'high': self.data.high[0],
            'low': self.data.low[0],
            'close': current_price,
            'volume': self.data.volume[0],
            'upper_band': self.upper_band[0],
            'lower_band': self.lower_band[0],
            'atr': current_atr,
            'account_value': self.broker.getvalue(),
            'cash': self.broker.getcash(),
            'position': self.total_size,
            'position_value': self.total_size * current_price if self.total_size > 0 else 0,
            'buy_count': self.buy_count,
        })

        # Stop loss
        if self.buy_count > 0 and current_price < (self.first_buy_price - self.p.stop_loss_atr * current_atr):
            self.order = self.close()
            self.log(f'⚠️ STOP LOSS | Price=${current_price:.2f}')
            return

        # Exit signal
        if self.sell_signal < 0 and self.buy_count > 0:
            self.order = self.close()
            self.log(f'📉 EXIT | Price=${current_price:.2f}')
            return

        # Add position
        if (self.buy_count > 0 and
            self.buy_count < self.p.pyramid_units and
            current_price > self.last_buy_price + self.p.add_unit_atr * current_atr):
            buy_size = self._calculate_position_size()
            if buy_size >= self.p.min_position_size:
                self.order = self.buy(size=buy_size)
                self.log(f'➕ ADD POSITION | Unit {self.buy_count + 1} | Size={buy_size:.4f} BTC')
            return

        # Entry
        if self.buy_signal > 0 and self.buy_count == 0:
            buy_size = self._calculate_position_size()
            if buy_size >= self.p.min_position_size:
                self.order = self.buy(size=buy_size)
                self.log(f'📈 ENTRY | Size={buy_size:.4f} BTC')
            return

    def _calculate_position_size(self):
        """Calculate position size"""
        if self.ATR[0] == 0:
            return 0
        risk_amount = self.broker.getvalue() * self.p.risk_per_unit
        unit_size = risk_amount / self.ATR[0]
        return round(unit_size, self.p.size_precision)

    def log(self, txt, dt=None):
        """Output log"""
        if self.params.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} | {txt}')

    def notify_order(self, order):
        """Order notification"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_count += 1
                self.last_buy_price = order.executed.price
                if self.buy_count == 1:
                    self.first_buy_price = order.executed.price
                self.total_cost += order.executed.value
                self.total_size += order.executed.size
                self.avg_price = self.total_cost / self.total_size if self.total_size > 0 else 0
                self.comm += order.executed.comm

                # Record buy trade
                self.trade_records.append({
                    'date': self.datas[0].datetime.date(0),
                    'type': 'BUY',
                    'price': order.executed.price,
                    'size': order.executed.size,
                    'value': order.executed.value,
                    'commission': order.executed.comm,
                    'position': self.total_size,
                    'avg_price': self.avg_price,
                })

                self.log(f'✅ BUY | ${order.executed.price:.2f} | {order.executed.size:.4f} BTC | Avg=${self.avg_price:.2f}')

            else:
                profit = (order.executed.price - self.avg_price) * self.total_size if self.total_size > 0 else 0
                profit_pct = (order.executed.price / self.avg_price - 1) * 100 if self.avg_price > 0 else 0

                # Record sell trade
                self.trade_records.append({
                    'date': self.datas[0].datetime.date(0),
                    'type': 'SELL',
                    'price': order.executed.price,
                    'size': order.executed.size,
                    'value': order.executed.value,
                    'commission': order.executed.comm,
                    'position': 0,
                    'avg_price': 0,
                    'profit': profit,
                    'profit_pct': profit_pct,
                })

                self.log(f'✅ SELL | ${order.executed.price:.2f} | P/L=${profit:.2f} ({profit_pct:+.2f}%)')

                self.buy_count = 0
                self.first_buy_price = 0
                self.last_buy_price = 0
                self.avg_price = 0
                self.total_cost = 0
                self.total_size = 0
                self.comm += order.executed.comm

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("❌ TRADE FAILED")

        self.order = None

    def stop(self):
        """Backtest finished"""
        final_value = self.broker.getvalue()
        initial_value = self.broker.startingcash
        total_return = (final_value / initial_value - 1) * 100

        print('\n' + '=' * 70)
        print('📊 Backtest Completed')
        print(f'   Initial Cash: ${initial_value:,.2f}')
        print(f'   Final Value: ${final_value:,.2f}')
        print(f'   Total Return: {total_return:+.2f}%')
        print(f'   Total Commission: ${self.comm:.2f}')
        print('=' * 70)


class BacktestVisualizer:
    """Backtest Result Visualization Tool"""

    def __init__(self, strategy, initial_cash):
        self.strategy = strategy
        self.initial_cash = initial_cash

        # Convert to DataFrame
        self.df_daily = pd.DataFrame(strategy.daily_records)
        self.df_trades = pd.DataFrame(strategy.trade_records)

        # Calculate derived metrics
        self._calculate_metrics()

    def _calculate_metrics(self):
        """Calculate backtest metrics"""
        # Returns
        self.df_daily['returns'] = self.df_daily['account_value'].pct_change()
        self.df_daily['cumulative_returns'] = (1 + self.df_daily['returns']).cumprod() - 1

        # Drawdown
        self.df_daily['peak'] = self.df_daily['account_value'].cummax()
        self.df_daily['drawdown'] = (self.df_daily['account_value'] - self.df_daily['peak']) / self.df_daily['peak']

        # Monthly returns
        self.df_daily['year'] = pd.to_datetime(self.df_daily['date']).dt.year
        self.df_daily['month'] = pd.to_datetime(self.df_daily['date']).dt.month
        self.df_daily['year_month'] = pd.to_datetime(self.df_daily['date']).dt.to_period('M')

    def generate_report(self):
        """Generate statistical report"""
        print('\n' + '=' * 70)
        print('📈 Detailed Statistics Report')
        print('=' * 70)

        # Basic metrics
        final_value = self.df_daily['account_value'].iloc[-1]
        total_return = (final_value / self.initial_cash - 1) * 100
        days = len(self.df_daily)
        years = days / 365

        print(f'\n[Return Metrics]')
        print(f'  Total Return: {total_return:+.2f}%')
        print(f'  Annual Return: {(pow(final_value / self.initial_cash, 1 / years) - 1) * 100:.2f}%')
        print(f'  Trading Days: {days} days ({years:.2f} years)')

        # Risk metrics
        max_drawdown = self.df_daily['drawdown'].min() * 100
        max_dd_idx = self.df_daily['drawdown'].idxmin()
        max_dd_date = self.df_daily.loc[max_dd_idx, 'date']

        daily_returns = self.df_daily['returns'].dropna()
        sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0

        print(f'\n[Risk Metrics]')
        print(f'  Max Drawdown: {max_drawdown:.2f}%')
        print(f'  Max Drawdown Date: {max_dd_date}')
        print(f'  Sharpe Ratio: {sharpe:.2f}')
        print(f'  Daily Volatility: {daily_returns.std() * 100:.3f}%')
        print(f'  Annual Volatility: {daily_returns.std() * np.sqrt(252) * 100:.2f}%')

        # Trade statistics
        if len(self.df_trades) > 0:
            sell_trades = self.df_trades[self.df_trades['type'] == 'SELL']
            if len(sell_trades) > 0:
                total_trades = len(sell_trades)
                win_trades = len(sell_trades[sell_trades['profit'] > 0])
                loss_trades = len(sell_trades[sell_trades['profit'] <= 0])
                win_rate = win_trades / total_trades * 100 if total_trades > 0 else 0

                avg_profit = sell_trades[sell_trades['profit'] > 0]['profit'].mean() if win_trades > 0 else 0
                avg_loss = abs(sell_trades[sell_trades['profit'] <= 0]['profit'].mean()) if loss_trades > 0 else 0
                profit_factor = avg_profit / avg_loss if avg_loss > 0 else 0

                max_profit = sell_trades['profit'].max()
                max_loss = sell_trades['profit'].min()

                print(f'\n[Trade Statistics]')
                print(f'  Total Trades: {total_trades}')
                print(f'  Winning Trades: {win_trades}')
                print(f'  Losing Trades: {loss_trades}')
                print(f'  Win Rate: {win_rate:.2f}%')
                print(f'  Average Profit: ${avg_profit:.2f}')
                print(f'  Average Loss: ${avg_loss:.2f}')
                print(f'  Profit Factor: {profit_factor:.2f}')
                print(f'  Max Single Profit: ${max_profit:.2f}')
                print(f'  Max Single Loss: ${max_loss:.2f}')
                print(f'  Total Commission: ${self.strategy.comm:.2f}')

        # Monthly statistics
        monthly_returns = self.df_daily.groupby('year_month')['account_value'].agg(['first', 'last'])
        monthly_returns['return'] = (monthly_returns['last'] / monthly_returns['first'] - 1) * 100
        positive_months = len(monthly_returns[monthly_returns['return'] > 0])
        total_months = len(monthly_returns)

        print(f'\n[Monthly Statistics]')
        print(f'  Total Months: {total_months}')
        print(f'  Profitable Months: {positive_months}')
        print(f'  Monthly Win Rate: {positive_months / total_months * 100:.2f}%')
        print(f'  Best Month: {monthly_returns["return"].max():.2f}%')
        print(f'  Worst Month: {monthly_returns["return"].min():.2f}%')
        print(f'  Avg Monthly Return: {monthly_returns["return"].mean():.2f}%')

        print('=' * 70)

        return {
            'total_return': total_return,
            'annual_return': (pow(final_value / self.initial_cash, 1 / years) - 1) * 100,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'win_rate': win_rate if len(sell_trades) > 0 else 0,
            'total_trades': total_trades if len(sell_trades) > 0 else 0,
        }

    def plot_all(self, output_dir='./backtest_results'):
        """Generate all charts"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        print(f'\n📊 Starting chart generation...')

        # 1. Price & Breakout Bands
        self.plot_price_and_bands(output_path / 'price_bands.png')

        # 2. Equity Curve & Drawdown
        self.plot_equity_drawdown(output_path / 'equity_drawdown.png')

        # 3. ATR Indicator
        self.plot_atr(output_path / 'atr.png')

        # 4. Position Changes
        self.plot_position(output_path / 'position.png')

        # 5. Profit Distribution
        if len(self.df_trades[self.df_trades['type'] == 'SELL']) > 0:
            self.plot_profit_distribution(output_path / 'profit_distribution.png')

        # 6. Monthly Returns Heatmap
        self.plot_monthly_returns_heatmap(output_path / 'monthly_heatmap.png')

        # 7. Comprehensive Dashboard
        self.plot_dashboard(output_path / 'dashboard.png')

        print(f'✅ All charts saved to: {output_path}')

    def plot_price_and_bands(self, filename):
        """Price and Breakout Bands"""
        fig, ax = plt.subplots(figsize=(16, 8))

        dates = pd.to_datetime(self.df_daily['date'])

        # Plot price
        ax.plot(dates, self.df_daily['close'], label='BTC Price', color='black', linewidth=1.5, alpha=0.8)

        # Plot breakout bands
        ax.plot(dates, self.df_daily['upper_band'],
                label=f'{self.strategy.params.entry_period}-Day High (Entry)',
                color='red', linestyle='--', linewidth=1, alpha=0.7)
        ax.plot(dates, self.df_daily['lower_band'],
                label=f'{self.strategy.params.exit_period}-Day Low (Exit)',
                color='green', linestyle='--', linewidth=1, alpha=0.7)
        ax.fill_between(dates, self.df_daily['upper_band'], self.df_daily['lower_band'],
                         alpha=0.1, color='gray')

        # Mark buy/sell points
        buy_trades = self.df_trades[self.df_trades['type'] == 'BUY']
        sell_trades = self.df_trades[self.df_trades['type'] == 'SELL']

        if len(buy_trades) > 0:
            ax.scatter(pd.to_datetime(buy_trades['date']), buy_trades['price'],
                      marker='^', color='green', s=200, alpha=0.8, label='Buy', zorder=5)

        if len(sell_trades) > 0:
            ax.scatter(pd.to_datetime(sell_trades['date']), sell_trades['price'],
                      marker='v', color='red', s=200, alpha=0.8, label='Sell', zorder=5)

        ax.set_title('Turtle Strategy - Price & Breakout Bands', fontsize=16, fontweight='bold')
        ax.set_xlabel('Date', fontsize=12)
        ax.set_ylabel('Price (USD)', fontsize=12)
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f'  ✓ Price & Breakout Bands: {filename}')

    def plot_equity_drawdown(self, filename):
        """Equity Curve and Drawdown"""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

        dates = pd.to_datetime(self.df_daily['date'])

        # Equity curve
        ax1.plot(dates, self.df_daily['account_value'], label='Account Value', color='blue', linewidth=2)
        ax1.axhline(self.initial_cash, color='gray', linestyle='--', alpha=0.5, label='Initial Cash')
        ax1.fill_between(dates, self.initial_cash, self.df_daily['account_value'],
                         where=(self.df_daily['account_value'] >= self.initial_cash),
                         color='green', alpha=0.2, label='Profit Area')
        ax1.fill_between(dates, self.initial_cash, self.df_daily['account_value'],
                         where=(self.df_daily['account_value'] < self.initial_cash),
                         color='red', alpha=0.2, label='Loss Area')

        ax1.set_title('Account Value Changes', fontsize=14, fontweight='bold')
        ax1.set_ylabel('Account Value (USD)', fontsize=12)
        ax1.legend(loc='best', fontsize=10)
        ax1.grid(True, alpha=0.3)

        # Drawdown curve
        ax2.fill_between(dates, 0, self.df_daily['drawdown'] * 100,
                         color='red', alpha=0.3, label='Drawdown Area')
        ax2.plot(dates, self.df_daily['drawdown'] * 100, color='darkred', linewidth=1.5, label='Drawdown Curve')

        max_dd_idx = self.df_daily['drawdown'].idxmin()
        max_dd_date = pd.to_datetime(self.df_daily.loc[max_dd_idx, 'date'])
        max_dd = self.df_daily.loc[max_dd_idx, 'drawdown'] * 100
        ax2.scatter([max_dd_date], [max_dd], color='red', s=200, zorder=5,
                   label=f'Max Drawdown: {max_dd:.2f}%')

        ax2.set_title('Account Drawdown', fontsize=14, fontweight='bold')
        ax2.set_xlabel('Date', fontsize=12)
        ax2.set_ylabel('Drawdown (%)', fontsize=12)
        ax2.legend(loc='best', fontsize=10)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f'  ✓ Equity Curve & Drawdown: {filename}')

    def plot_atr(self, filename):
        """ATR Indicator"""
        fig, ax = plt.subplots(figsize=(16, 6))

        dates = pd.to_datetime(self.df_daily['date'])
        ax.plot(dates, self.df_daily['atr'], label='ATR (14-Day)', color='purple', linewidth=2)
        ax.fill_between(dates, 0, self.df_daily['atr'], alpha=0.2, color='purple')

        ax.set_title('ATR (Average True Range) Changes', fontsize=14, fontweight='bold')
        ax.set_xlabel('Date', fontsize=12)
        ax.set_ylabel('ATR (USD)', fontsize=12)
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f'  ✓ ATR Indicator: {filename}')

    def plot_position(self, filename):
        """Position Changes"""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

        dates = pd.to_datetime(self.df_daily['date'])

        # Position size
        ax1.fill_between(dates, 0, self.df_daily['position'],
                         where=(self.df_daily['position'] > 0),
                         color='blue', alpha=0.3, label='Position Size')
        ax1.plot(dates, self.df_daily['position'], color='darkblue', linewidth=1.5)

        ax1.set_title('Position Size Changes', fontsize=14, fontweight='bold')
        ax1.set_ylabel('Position (BTC)', fontsize=12)
        ax1.legend(loc='best', fontsize=10)
        ax1.grid(True, alpha=0.3)

        # Position value ratio
        self.df_daily['position_ratio'] = self.df_daily['position_value'] / self.df_daily['account_value'] * 100
        ax2.fill_between(dates, 0, self.df_daily['position_ratio'],
                         where=(self.df_daily['position_ratio'] > 0),
                         color='orange', alpha=0.3, label='Position Ratio')
        ax2.plot(dates, self.df_daily['position_ratio'], color='darkorange', linewidth=1.5)

        ax2.set_title('Position Value Ratio', fontsize=14, fontweight='bold')
        ax2.set_xlabel('Date', fontsize=12)
        ax2.set_ylabel('Position Ratio (%)', fontsize=12)
        ax2.legend(loc='best', fontsize=10)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f'  ✓ Position Changes: {filename}')

    def plot_profit_distribution(self, filename):
        """Profit Distribution"""
        sell_trades = self.df_trades[self.df_trades['type'] == 'SELL'].copy()

        if len(sell_trades) == 0:
            return

        fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        # 1. Profit distribution histogram
        ax = axes[0, 0]
        profits = sell_trades['profit']
        colors = ['green' if x > 0 else 'red' for x in profits]
        ax.bar(range(len(profits)), profits, color=colors, alpha=0.6)
        ax.axhline(0, color='black', linewidth=1)
        ax.set_title('Profit/Loss per Trade', fontsize=14, fontweight='bold')
        ax.set_xlabel('Trade Number', fontsize=12)
        ax.set_ylabel('Profit/Loss (USD)', fontsize=12)
        ax.grid(True, alpha=0.3, axis='y')

        # 2. Profit percentage distribution
        ax = axes[0, 1]
        profit_pcts = sell_trades['profit_pct']
        colors = ['green' if x > 0 else 'red' for x in profit_pcts]
        ax.bar(range(len(profit_pcts)), profit_pcts, color=colors, alpha=0.6)
        ax.axhline(0, color='black', linewidth=1)
        ax.set_title('Profit/Loss Percentage per Trade', fontsize=14, fontweight='bold')
        ax.set_xlabel('Trade Number', fontsize=12)
        ax.set_ylabel('Profit/Loss (%)', fontsize=12)
        ax.grid(True, alpha=0.3, axis='y')

        # 3. Cumulative profit
        ax = axes[1, 0]
        cumulative_profit = profits.cumsum()
        ax.plot(range(len(cumulative_profit)), cumulative_profit, color='blue', linewidth=2, marker='o')
        ax.fill_between(range(len(cumulative_profit)), 0, cumulative_profit,
                        where=(cumulative_profit >= 0), color='green', alpha=0.2)
        ax.fill_between(range(len(cumulative_profit)), 0, cumulative_profit,
                        where=(cumulative_profit < 0), color='red', alpha=0.2)
        ax.axhline(0, color='black', linewidth=1)
        ax.set_title('Cumulative Profit/Loss', fontsize=14, fontweight='bold')
        ax.set_xlabel('Trade Number', fontsize=12)
        ax.set_ylabel('Cumulative P/L (USD)', fontsize=12)
        ax.grid(True, alpha=0.3)

        # 4. Profit statistics boxplot
        ax = axes[1, 1]
        win_trades = sell_trades[sell_trades['profit'] > 0]['profit']
        loss_trades = sell_trades[sell_trades['profit'] <= 0]['profit']
        ax.boxplot([win_trades, loss_trades.abs()], labels=['Winning Trades', 'Losing Trades'],
                   patch_artist=True,
                   boxprops=dict(facecolor='lightblue', alpha=0.7),
                   medianprops=dict(color='red', linewidth=2))
        ax.set_title('Profit/Loss Statistics Boxplot', fontsize=14, fontweight='bold')
        ax.set_ylabel('Amount (USD)', fontsize=12)
        ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f'  ✓ Profit Distribution: {filename}')

    def plot_monthly_returns_heatmap(self, filename):
        """Monthly Returns Heatmap"""
        monthly_returns = self.df_daily.groupby(['year', 'month'])['account_value'].agg(['first', 'last'])
        monthly_returns['return'] = (monthly_returns['last'] / monthly_returns['first'] - 1) * 100

        # Reshape to year x month matrix
        pivot_table = monthly_returns.reset_index().pivot(index='year', columns='month', values='return')

        fig, ax = plt.subplots(figsize=(14, 6))
        data = pivot_table.to_numpy(dtype=float)
        data_m = np.ma.masked_invalid(data)
        im = ax.imshow(
            data_m, cmap='RdYlGn', aspect='auto', vmin=-10, vmax=10, interpolation='nearest',
        )
        nrows, ncols = data.shape
        for i in range(nrows):
            for j in range(ncols):
                val = data[i, j]
                if np.isfinite(val):
                    ax.text(j, i, f'{val:.1f}', ha='center', va='center', color='black', fontsize=8)
        ax.set_xticks(np.arange(ncols))
        ax.set_xticklabels(pivot_table.columns)
        ax.set_yticks(np.arange(nrows))
        ax.set_yticklabels(pivot_table.index)
        ax.set_xticks(np.arange(-0.5, ncols, 1), minor=True)
        ax.set_yticks(np.arange(-0.5, nrows, 1), minor=True)
        ax.grid(which='minor', color='white', linestyle='-', linewidth=1)
        ax.tick_params(which='minor', bottom=False, left=False)
        plt.colorbar(im, ax=ax, label='Return (%)')

        ax.set_title('Monthly Returns Heatmap', fontsize=16, fontweight='bold')
        ax.set_xlabel('Month', fontsize=12)
        ax.set_ylabel('Year', fontsize=12)

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f'  ✓ Monthly Returns Heatmap: {filename}')

    def plot_dashboard(self, filename):
        """Comprehensive Dashboard"""
        fig = plt.figure(figsize=(20, 12))
        gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)

        dates = pd.to_datetime(self.df_daily['date'])

        # 1. Equity curve (large chart)
        ax1 = fig.add_subplot(gs[0, :])
        ax1.plot(dates, self.df_daily['account_value'], color='blue', linewidth=2, label='Account Value')
        ax1.fill_between(dates, self.initial_cash, self.df_daily['account_value'],
                        where=(self.df_daily['account_value'] >= self.initial_cash),
                        color='green', alpha=0.2)
        ax1.set_title('Turtle Strategy Backtest - Dashboard', fontsize=18, fontweight='bold')
        ax1.set_ylabel('Account Value (USD)', fontsize=12)
        ax1.legend(loc='best')
        ax1.grid(True, alpha=0.3)

        # 2. Drawdown
        ax2 = fig.add_subplot(gs[1, 0])
        ax2.fill_between(dates, 0, self.df_daily['drawdown'] * 100, color='red', alpha=0.3)
        ax2.set_title('Drawdown', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Drawdown (%)', fontsize=10)
        ax2.grid(True, alpha=0.3)

        # 3. ATR
        ax3 = fig.add_subplot(gs[1, 1])
        ax3.plot(dates, self.df_daily['atr'], color='purple', linewidth=1.5)
        ax3.set_title('ATR Indicator', fontsize=12, fontweight='bold')
        ax3.set_ylabel('ATR (USD)', fontsize=10)
        ax3.grid(True, alpha=0.3)

        # 4. Position
        ax4 = fig.add_subplot(gs[1, 2])
        ax4.fill_between(dates, 0, self.df_daily['position'], color='blue', alpha=0.3)
        ax4.set_title('Position Size', fontsize=12, fontweight='bold')
        ax4.set_ylabel('BTC', fontsize=10)
        ax4.grid(True, alpha=0.3)

        # 5. Monthly returns
        ax5 = fig.add_subplot(gs[2, 0])
        monthly_returns = self.df_daily.groupby('year_month')['account_value'].agg(['first', 'last'])
        monthly_returns['return'] = (monthly_returns['last'] / monthly_returns['first'] - 1) * 100
        colors = ['green' if x > 0 else 'red' for x in monthly_returns['return']]
        ax5.bar(range(len(monthly_returns)), monthly_returns['return'], color=colors, alpha=0.6)
        ax5.axhline(0, color='black', linewidth=1)
        ax5.set_title('Monthly Returns', fontsize=12, fontweight='bold')
        ax5.set_ylabel('Return (%)', fontsize=10)
        ax5.grid(True, alpha=0.3, axis='y')

        # 6. Trade P/L
        ax6 = fig.add_subplot(gs[2, 1])
        sell_trades = self.df_trades[self.df_trades['type'] == 'SELL']
        if len(sell_trades) > 0:
            profits = sell_trades['profit']
            colors = ['green' if x > 0 else 'red' for x in profits]
            ax6.bar(range(len(profits)), profits, color=colors, alpha=0.6)
            ax6.axhline(0, color='black', linewidth=1)
        ax6.set_title('Profit/Loss per Trade', fontsize=12, fontweight='bold')
        ax6.set_ylabel('P/L (USD)', fontsize=10)
        ax6.grid(True, alpha=0.3, axis='y')

        # 7. Statistics (text)
        ax7 = fig.add_subplot(gs[2, 2])
        ax7.axis('off')

        stats_text = self._generate_stats_text()
        ax7.text(0.1, 0.9, stats_text, transform=ax7.transAxes,
                fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f'  ✓ Comprehensive Dashboard: {filename}')

    def _generate_stats_text(self):
        """Generate statistics text"""
        final_value = self.df_daily['account_value'].iloc[-1]
        total_return = (final_value / self.initial_cash - 1) * 100
        max_dd = self.df_daily['drawdown'].min() * 100

        sell_trades = self.df_trades[self.df_trades['type'] == 'SELL']
        total_trades = len(sell_trades)
        win_trades = len(sell_trades[sell_trades['profit'] > 0]) if total_trades > 0 else 0
        win_rate = win_trades / total_trades * 100 if total_trades > 0 else 0

        text = f"""Key Metrics

Total Return: {total_return:+.2f}%
Max Drawdown: {max_dd:.2f}%

Total Trades: {total_trades}
Win Rate: {win_rate:.1f}%

Initial Cash: ${self.initial_cash:,.0f}
Final Value: ${final_value:,.0f}
"""
        return text


def run_backtest_with_visualization(csv_file=None,
                                    initial_cash=100000.0,
                                    commission=0.001,
                                    output_dir='./backtest_results'):
    """Run backtest and generate visualization report"""

    resolved_csv = _resolve_btc_csv(csv_file)
    out_dir = _resolve_output_dir(output_dir)

    print('=' * 70)
    print('🐢 Turtle Trading Strategy - Professional Backtest Visualization')
    print('=' * 70)
    print(f'📁 Data File: {resolved_csv}')
    print(f'💰 Initial Cash: ${initial_cash:,.2f}')
    print(f'💸 Commission Rate: {commission:.2%}')
    print('=' * 70)

    # Create Cerebro engine
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(TurtleStrategyRecorder, printlog=False)

    # Load data
    data = bt.feeds.GenericCSVData(
        dataname=str(resolved_csv),
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1, high=2, low=3, close=4, volume=5, openinterest=6,
        fromdate=datetime(2020, 1, 1),
        todate=datetime(2026, 1, 1),
    )

    cerebro.adddata(data)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    # Run backtest
    print('\n🚀 Starting backtest...')
    results = cerebro.run()
    strategy = results[0]

    # Create visualizer
    visualizer = BacktestVisualizer(strategy, initial_cash)

    # Generate report
    visualizer.generate_report()

    # Generate charts
    visualizer.plot_all(out_dir)

    print(f'\n✅ Backtest completed! All results saved to: {out_dir}')

    return cerebro, results, visualizer


if __name__ == "__main__":
    """Main program"""

    # Run backtest with visualization
    cerebro, results, visualizer = run_backtest_with_visualization(
        initial_cash=100000.0,
        commission=0.001,
        output_dir='./backtest_results',
    )
