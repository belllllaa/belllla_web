"""
参数化动量策略回测（Backtrader）

规则概要：
  - N 日动量 = 收盘 / N 日前收盘 - 1；高于阈值则满仓做多，否则空仓。
  - 可选：仅在收盘价高于 M 日均线时允许做多（趋势过滤）。

绩效：
  - 夏普比率（Backtrader 分析器 + 日收益年化）
  - 信息比率：相对买入持有基准的超额收益 / 跟踪误差（日频年化）
  - 最大回撤、累计收益

图表：
  - 策略净值 vs 买入持有基准
  - 策略回撤曲线

数据：
  先运行 utils/get_momentum_data.py 生成 CSV，或通过 --csv 指定路径。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import backtrader as bt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass
class MomentumParams:
    """策略与回测参数（均可从命令行覆盖）"""

    mom_period: int = 60
    momentum_threshold: float = 0.0
    use_ma_filter: bool = False
    ma_period: int = 200
    initial_cash: float = 100_000.0
    commission: float = 0.001
    risk_free_rate: float = 0.0
    csv_file: str | None = None
    fromdate: datetime = field(default_factory=lambda: datetime(2020, 1, 1))
    todate: datetime = field(default_factory=lambda: datetime(2026, 1, 1))
    output_dir: str = "backtest_results"
    plot: bool = True


def _resolve_csv(csv_file: str | None) -> Path:
    if csv_file:
        p = Path(csv_file)
        if not p.is_absolute():
            p = (_SCRIPT_DIR / p).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"数据文件不存在: {p}")
        return p
    for p in (
        _SCRIPT_DIR / "data" / "momentum_BTCUSDT_daily.csv",
        _SCRIPT_DIR / "utils" / "btc_daily_2020_2026.csv",
        _SCRIPT_DIR / "btc_daily_2020_2026.csv",
    ):
        rp = p.resolve()
        if rp.is_file():
            return rp
    raise FileNotFoundError(
        "未找到 CSV。请先运行: python utils/get_momentum_data.py\n"
        f"或使用 --csv 指定路径。默认查找: {_SCRIPT_DIR / 'data' / 'momentum_BTCUSDT_daily.csv'}"
    )


def _resolve_output_dir(output_dir: str) -> Path:
    p = Path(output_dir)
    if not p.is_absolute():
        p = (_SCRIPT_DIR / p).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


class MomentumStrategy(bt.Strategy):
    """
    简单时间序列动量：动量 > 阈值则 target≈100% 标的，否则空仓。
    """

    params = (
        ("mom_period", 60),
        ("momentum_threshold", 0.0),
        ("use_ma_filter", False),
        ("ma_period", 200),
        ("position_pct", 0.98),
    )

    def __init__(self):
        self.order = None
        self.sma = (
            bt.ind.SMA(self.data.close, period=self.p.ma_period)
            if self.p.use_ma_filter
            else None
        )
        self._min_bars = max(
            self.p.mom_period + 1,
            self.p.ma_period + 1 if self.p.use_ma_filter else 0,
        )
        self._first_close: float | None = None
        self.equity_log: list[tuple] = []

    def notify_order(self, order):
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.order = None

    def next(self):
        d0 = self.data.datetime.date(0)
        close0 = float(self.data.close[0])
        if self._first_close is None:
            self._first_close = close0
        v = self.broker.getvalue()
        bench = self.broker.startingcash * close0 / self._first_close
        self.equity_log.append((d0, v, close0, bench))

        if self.order:
            return
        if len(self.data) < self._min_bars:
            return

        mom = close0 / float(self.data.close[-self.p.mom_period]) - 1.0
        long_ok = mom > self.p.momentum_threshold
        if self.p.use_ma_filter and self.sma is not None:
            long_ok = long_ok and close0 > float(self.sma[0])

        target = self.p.position_pct if long_ok else 0.0
        self.order = self.order_target_percent(target=target)


def _annualized_sharpe(daily_returns: pd.Series, rf: float = 0.0, periods: int = 252) -> float:
    daily_returns = daily_returns.dropna()
    if len(daily_returns) < 2 or daily_returns.std() == 0:
        return float("nan")
    excess = daily_returns - rf / periods
    return float(np.sqrt(periods) * excess.mean() / excess.std())


def _information_ratio(
    port_ret: pd.Series,
    bench_ret: pd.Series,
    periods: int = 252,
) -> float:
    aligned = pd.concat([port_ret, bench_ret], axis=1).dropna()
    if len(aligned) < 2:
        return float("nan")
    excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    if excess.std() == 0:
        return float("nan")
    return float(np.sqrt(periods) * excess.mean() / excess.std())


def _max_drawdown(equity: pd.Series) -> float:
    cummax = equity.cummax()
    dd = equity / cummax - 1.0
    return float(dd.min())


def run_momentum_backtest(cfg: MomentumParams) -> tuple[bt.Cerebro, list, pd.DataFrame, dict]:
    csv_path = _resolve_csv(cfg.csv_file)
    out_dir = _resolve_output_dir(cfg.output_dir)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(
        MomentumStrategy,
        mom_period=cfg.mom_period,
        momentum_threshold=cfg.momentum_threshold,
        use_ma_filter=cfg.use_ma_filter,
        ma_period=cfg.ma_period,
    )

    data = bt.feeds.GenericCSVData(
        dataname=str(csv_path),
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=6,
        fromdate=cfg.fromdate,
        todate=cfg.todate,
    )
    cerebro.adddata(data)
    cerebro.broker.setcash(cfg.initial_cash)
    cerebro.broker.setcommission(commission=cfg.commission)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=cfg.risk_free_rate)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    print("=" * 70)
    print("动量策略回测")
    print("=" * 70)
    print(f"数据: {csv_path}")
    print(f"初始资金: {cfg.initial_cash:,.2f}  手续费: {cfg.commission:.2%}")
    print(
        f"动量周期={cfg.mom_period} 阈值={cfg.momentum_threshold} "
        f"MA过滤={cfg.use_ma_filter} MA周期={cfg.ma_period}"
    )
    print("=" * 70)

    results = cerebro.run()
    strat: MomentumStrategy = results[0]

    log = strat.equity_log
    df = pd.DataFrame(log, columns=["date", "strategy_value", "close", "bench_value"])
    df["date"] = pd.to_datetime(df["date"])

    r_p = df["strategy_value"].pct_change()
    r_b = df["bench_value"].pct_change()
    sharpe_np = _annualized_sharpe(r_p, rf=cfg.risk_free_rate)
    ir = _information_ratio(r_p, r_b)
    mdd = _max_drawdown(df["strategy_value"])

    sharpe_bt = strat.analyzers.sharpe.get_analysis().get("sharperatio", None)
    dd_bt = strat.analyzers.drawdown.get_analysis()
    ret_bt = strat.analyzers.returns.get_analysis()

    final_v = df["strategy_value"].iloc[-1]
    total_ret = final_v / cfg.initial_cash - 1.0
    bench_final = df["bench_value"].iloc[-1]
    bench_ret = bench_final / cfg.initial_cash - 1.0

    metrics = {
        "total_return": total_ret,
        "benchmark_total_return": bench_ret,
        "max_drawdown": mdd,
        "info_ratio": ir,
        "sharpe_numpy": sharpe_np,
        "sharpe_backtrader": sharpe_bt,
        "final_value": final_v,
        "bench_final_value": bench_final,
    }

    print("\n--- 核心指标 ---")
    print(f"策略累计收益: {total_ret * 100:.2f}%")
    print(f"基准(买入持有)累计收益: {bench_ret * 100:.2f}%")
    print(f"最大回撤(策略净值): {mdd * 100:.2f}%")
    if dd_bt.max.drawdown is not None:
        print(f"最大回撤(BT分析器): {dd_bt.max.drawdown:.2f}%")
    print(f"信息比率(相对日频基准): {ir:.4f}" if np.isfinite(ir) else "信息比率: N/A")
    print(f"夏普比率(日收益年化, rf={cfg.risk_free_rate:.2%}): {sharpe_np:.4f}" if np.isfinite(sharpe_np) else "夏普: N/A")
    if sharpe_bt is not None:
        print(f"夏普比率(Backtrader): {sharpe_bt:.4f}")
    if ret_bt:
        print(f"年化收益(Backtrader rnorm100): {ret_bt.get('rnorm100', 0):.2f}%")

    if cfg.plot:
        _plot_equity_and_drawdown(df, out_dir, cfg)

    return cerebro, results, df, metrics


def _plot_equity_and_drawdown(df: pd.DataFrame, out_dir: Path, cfg: MomentumParams) -> None:
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    ax0 = axes[0]
    ax0.plot(df["date"], df["strategy_value"], label="Strategy NAV", color="C0", linewidth=1.5)
    ax0.plot(df["date"], df["bench_value"], label="Benchmark (buy & hold)", color="C1", linewidth=1.2, alpha=0.85)
    ax0.axhline(cfg.initial_cash, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax0.set_ylabel("Equity")
    ax0.legend(loc="upper left")
    ax0.set_title(
        f"Momentum mom={cfg.mom_period} thr={cfg.momentum_threshold} "
        f"ma_filter={cfg.use_ma_filter} ma={cfg.ma_period}"
    )
    ax0.grid(True, alpha=0.3)

    cummax = df["strategy_value"].cummax()
    drawdown = df["strategy_value"] / cummax - 1.0
    ax1 = axes[1]
    ax1.fill_between(df["date"], drawdown, 0, color="C3", alpha=0.35)
    ax1.plot(df["date"], drawdown, color="C3", linewidth=1.0)
    ax1.set_ylabel("Drawdown")
    ax1.set_xlabel("Date")
    ax1.grid(True, alpha=0.3)
    ax1.set_title("Strategy drawdown")

    plt.tight_layout()
    p_equity = out_dir / "momentum_equity_vs_benchmark.png"
    plt.savefig(p_equity, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n图表已保存: {p_equity}")


def _build_cfg_from_args(ns: argparse.Namespace) -> MomentumParams:
    return MomentumParams(
        mom_period=ns.mom_period,
        momentum_threshold=ns.momentum_threshold,
        use_ma_filter=ns.use_ma_filter,
        ma_period=ns.ma_period,
        initial_cash=ns.cash,
        commission=ns.commission,
        risk_free_rate=ns.risk_free,
        csv_file=ns.csv,
        fromdate=datetime.strptime(ns.from_date, "%Y-%m-%d"),
        todate=datetime.strptime(ns.to_date, "%Y-%m-%d"),
        output_dir=ns.output_dir,
        plot=not ns.no_plot,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="动量策略回测（参数化）")
    p.add_argument("--csv", default=None, help="OHLCV CSV（无表头，与课程格式一致）")
    p.add_argument("--mom-period", type=int, default=60, help="动量回溯天数 N")
    p.add_argument("--momentum-threshold", type=float, default=0.0, help="做多需满足的动量下限")
    p.add_argument("--use-ma-filter", action="store_true", help="启用均线过滤")
    p.add_argument("--ma-period", type=int, default=200, help="均线周期")
    p.add_argument("--cash", type=float, default=100_000.0, help="初始资金")
    p.add_argument("--commission", type=float, default=0.001, help="手续费比例")
    p.add_argument("--risk-free", type=float, default=0.0, help="年化无风险利率（夏普用）")
    p.add_argument("--from-date", default="2020-01-01", help="回测起始")
    p.add_argument("--to-date", default="2026-01-01", help="回测结束")
    p.add_argument("--output-dir", default="backtest_results", help="图表输出目录")
    p.add_argument("--no-plot", action="store_true", help="不保存图表")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    cfg = _build_cfg_from_args(args)
    run_momentum_backtest(cfg)
