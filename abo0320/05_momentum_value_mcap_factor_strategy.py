# ==========================================
# 策略名称：动量 + 价值 + 市值 三因子加权评分
# 逻辑：对因子截面 Z-Score 后加权合成得分，取前 N 只；每 R 个交易日等权轮动
# 依赖：聚宽 (JoinQuant) 研究/回测环境 —— initialize / handle_data / get_fundamentals 等
# 本地：可仅导入下方 FactorStrategyConfig、FactorRotationVisualizer 做画图演示
# ==========================================

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Matplotlib（与 backtrader实战/12-turtle-visiual.py 一致的风格初始化）
# ---------------------------------------------------------------------------
import matplotlib.pyplot as plt
from matplotlib import font_manager as _fm

plt.rcParams["axes.unicode_minus"] = False

for _style in ("seaborn-v0_8-whitegrid", "seaborn-whitegrid", "ggplot"):
    try:
        plt.style.use(_style)
        break
    except OSError:
        continue
else:
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.3

# seaborn 等样式会覆盖 font.sans-serif 为 Arial，需在 style 之后再设中文字体
_cn_font_names = {f.name for f in _fm.fontManager.ttflist}
for _fname in (
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    "SimSun",
    "KaiTi",
    "FangSong",
):
    if _fname in _cn_font_names:
        plt.rcParams["font.sans-serif"] = [_fname] + [
            x for x in plt.rcParams.get("font.sans-serif", []) if x != _fname
        ]
        break


# =============================================================================
# 参数（可改权重、周期、股票数）
# =============================================================================


@dataclass
class FactorStrategyConfig:
    """三因子轮动策略参数（聚宽 context 与本地画图共用）。"""

    benchmark: str = "000300.XSHG"
    index_code: str = "000300.XSHG"
    stock_count: int = 20
    rebalance_interval: int = 20
    momentum_period: int = 20
    # 三因子权重（建议三者之和为 1，不为 1 时仍可用，仅影响得分尺度）
    weight_momentum: float = 1.0 / 3.0
    weight_value: float = 1.0 / 3.0
    weight_mcap: float = 1.0 / 3.0
    # 价值：PE 倒数；过滤极端 PE
    pe_min: float = 1e-6
    pe_max: float = 100.0
    # 市值：use_log_market_cap 用 log(总市值) 否则用原值；mcap_prefer_small=True 时小市值 Z 分高（从小到大）
    use_log_market_cap: bool = True
    mcap_prefer_small: bool = True
    # 去极值：截面分位截断后再 Z-Score（与 jq_research_mvm_factor_rotation 一致）
    clip_pct_low: float = 0.01
    clip_pct_high: float = 0.99
    # 是否每日记录净值供导出画图
    record_daily_nav: bool = True


# =============================================================================
# 因子计算（纯 pandas，便于单测）
# =============================================================================


def _winsorize_series(s: pd.Series, low: float, high: float) -> pd.Series:
    """截面分位截断，抑制极端值。"""
    s = pd.to_numeric(s, errors="coerce")
    valid = s.dropna()
    if len(valid) == 0:
        return s
    q_lo = valid.quantile(low)
    q_hi = valid.quantile(high)
    if not np.isfinite(q_lo) or not np.isfinite(q_hi):
        return s
    if q_lo > q_hi:
        q_lo, q_hi = q_hi, q_lo
    return s.clip(lower=q_lo, upper=q_hi)


def _is_empty_stock_positions(context: Any) -> bool:
    """无股票持仓（空仓）时 True。"""
    pos = context.portfolio.positions
    if not pos:
        return True
    for s in pos:
        if pos[s].total_amount > 0:
            return False
    return True


def _zscore_series(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    std = s.std()
    if std is None or std == 0 or not np.isfinite(std):
        return pd.Series(0.0, index=s.index)
    out = (s - s.mean()) / std
    return out.fillna(0.0)


class MomentumValueMcapSelector:
    """
    动量 + 价值（1/PE）+ 市值（默认 -log(市值)，小市值 Z 分高）截面标准化后加权得分，取头部股票。
    """

    def __init__(self, config: FactorStrategyConfig):
        self.config = config

    def select(
        self,
        stock_pool: list[str],
        momentum_period: int,
        get_fundamentals_fn,
        attribute_history_fn,
    ) -> list[str]:
        """
        聚宽内调用时传入 query/get_fundamentals 与 attribute_history 的封装。
        此处通过函数参数注入，避免在本地硬依赖 jqdata。
        """
        q = query(valuation.code, valuation.pe_ratio, valuation.market_cap).filter(
            valuation.code.in_(stock_pool)
        )
        df = get_fundamentals_fn(q)
        if df is None or len(df) == 0:
            return []

        df = df.dropna(subset=["code", "pe_ratio", "market_cap"])
        df = df[(df["pe_ratio"] > self.config.pe_min) & (df["pe_ratio"] < self.config.pe_max)]
        df = df[df["market_cap"] > 0]
        if len(df) == 0:
            return []

        df["value_pe"] = 1.0 / df["pe_ratio"]
        m = df["market_cap"].astype(float)
        if self.config.use_log_market_cap:
            size_base = np.log(m)
        else:
            size_base = m
        if self.config.mcap_prefer_small:
            df["cap_raw"] = -size_base
        else:
            df["cap_raw"] = size_base

        mom_rows = []
        for code in df["code"].tolist():
            hist = attribute_history_fn(
                code,
                count=momentum_period + 1,
                unit="1d",
                fields=["close"],
                skip_paused=True,
            )
            if hist is None or len(hist) < momentum_period + 1:
                continue
            close = hist["close"]
            momentum = (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0])
            mom_rows.append({"code": code, "momentum": momentum})

        if not mom_rows:
            return []

        mom_df = pd.DataFrame(mom_rows)
        df = df.merge(mom_df, on="code", how="inner")
        df = df.dropna()
        if len(df) == 0:
            return []

        lo, hi = self.config.clip_pct_low, self.config.clip_pct_high
        df["value_pe"] = _winsorize_series(df["value_pe"], lo, hi)
        df["momentum"] = _winsorize_series(df["momentum"], lo, hi)
        df["cap_raw"] = _winsorize_series(df["cap_raw"], lo, hi)

        df["z_mom"] = _zscore_series(df["momentum"])
        df["z_val"] = _zscore_series(df["value_pe"])
        df["z_cap"] = _zscore_series(df["cap_raw"])

        w_m, w_v, w_c = (
            self.config.weight_momentum,
            self.config.weight_value,
            self.config.weight_mcap,
        )
        df["score"] = w_m * df["z_mom"] + w_v * df["z_val"] + w_c * df["z_cap"]
        df = df.sort_values("score", ascending=False)
        top = df.head(self.config.stock_count)
        return top["code"].tolist()


# =============================================================================
# 聚宽策略控制器（类）
# =============================================================================


class FactorRotationController:
    """封装 initialize / 每日逻辑；在聚宽里挂到 g.controller。"""

    def __init__(self, config: FactorStrategyConfig | None = None):
        self.config = config or FactorStrategyConfig()
        self._selector = MomentumValueMcapSelector(self.config)

    def on_initialize(self, context: Any) -> None:
        set_benchmark(self.config.benchmark)
        context.stock_pool = get_index_stocks(self.config.index_code)
        context.stock_count = self.config.stock_count
        context.rebalance_interval = self.config.rebalance_interval
        context.momentum_period = self.config.momentum_period
        context.days_since_rebalance = 0
        context.factor_config = self.config
        if self.config.record_daily_nav:
            context.daily_nav_records = []
        context.rebalance_dates = []

        log.info(
            f"三因子轮动初始化: 池={self.config.index_code}, N={self.config.stock_count}, "
            f"R={self.config.rebalance_interval}日, w=({self.config.weight_momentum:.2f},"
            f"{self.config.weight_value:.2f},{self.config.weight_mcap:.2f})"
        )

    def on_handle_data(self, context: Any, data: Any) -> None:
        if self.config.record_daily_nav:
            context.daily_nav_records.append(
                {
                    "date": context.current_dt.date(),
                    "total_value": context.portfolio.total_value,
                    "cash": context.portfolio.cash,
                }
            )

        # 空仓：回测首日或清仓后立即调仓，不等待满 rebalance_interval 个交易日
        if _is_empty_stock_positions(context):
            selected = self._selector.select(
                context.stock_pool,
                context.momentum_period,
                get_fundamentals,
                attribute_history,
            )
            self._rebalance(context, data, selected)
            context.days_since_rebalance = 0
            log.info(f"空仓建仓/轮动，持仓数: {len(selected)}")
            return

        context.days_since_rebalance += 1
        if context.days_since_rebalance < context.rebalance_interval:
            return

        selected = self._selector.select(
            context.stock_pool,
            context.momentum_period,
            get_fundamentals,
            attribute_history,
        )
        self._rebalance(context, data, selected)
        context.days_since_rebalance = 0
        log.info(f"轮动完成，持仓数: {len(selected)}")

    def _rebalance(self, context: Any, data: Any, target_stocks: list[str]) -> None:
        context.rebalance_dates.append(context.current_dt.date())
        for stock in list(context.portfolio.positions.keys()):
            if stock not in target_stocks:
                order_target(stock, 0)
        if len(target_stocks) == 0:
            return
        per = context.portfolio.total_value / len(target_stocks)
        for stock in target_stocks:
            if stock in data and not data[stock].paused:
                order_target_value(stock, per)


# ---------- 聚宽入口（与 03 / 04 相同风格）----------

g_config = FactorStrategyConfig()


def initialize(context):
    g.controller = FactorRotationController(g_config)
    g.controller.on_initialize(context)


def handle_data(context, data):
    g.controller.on_handle_data(context, data)


# =============================================================================
# 画图（参考 backtrader实战/12-turtle-visiual.py：净值、回撤、热力图、Dashboard）
# =============================================================================


class FactorRotationVisualizer:
    """
    输入每日净值 DataFrame（至少含 date, account_value），生成与 turtle 类似的图表。
    可选：调仓日列表，在图上画竖线。
    """

    def __init__(
        self,
        df_daily: pd.DataFrame,
        initial_cash: float,
        rebalance_dates: list | None = None,
    ):
        self.df_daily = df_daily.copy()
        self.initial_cash = float(initial_cash)
        self.rebalance_dates = rebalance_dates or []

        if "date" not in self.df_daily.columns:
            raise ValueError("df_daily 需要含列: date")
        if "account_value" not in self.df_daily.columns:
            if "total_value" in self.df_daily.columns:
                self.df_daily["account_value"] = self.df_daily["total_value"]
            else:
                raise ValueError("df_daily 需要 account_value 或 total_value")

        self.df_daily["date"] = pd.to_datetime(self.df_daily["date"])
        self.df_daily = self.df_daily.sort_values("date").reset_index(drop=True)
        self._calc_metrics()

    def _calc_metrics(self) -> None:
        self.df_daily["returns"] = self.df_daily["account_value"].pct_change()
        self.df_daily["peak"] = self.df_daily["account_value"].cummax()
        self.df_daily["drawdown"] = (
            self.df_daily["account_value"] - self.df_daily["peak"]
        ) / self.df_daily["peak"]
        self.df_daily["year"] = self.df_daily["date"].dt.year
        self.df_daily["month"] = self.df_daily["date"].dt.month
        self.df_daily["year_month"] = self.df_daily["date"].dt.to_period("M")

    def generate_report(self) -> dict[str, Any]:
        final_v = float(self.df_daily["account_value"].iloc[-1])
        total_ret = (final_v / self.initial_cash - 1) * 100
        days = len(self.df_daily)
        years = max(days / 365.0, 1e-9)
        ann = (pow(final_v / self.initial_cash, 1 / years) - 1) * 100
        max_dd = float(self.df_daily["drawdown"].min() * 100)
        dr = self.df_daily["returns"].dropna()
        sharpe = (
            float(dr.mean() / dr.std() * np.sqrt(252)) if dr.std() and dr.std() > 0 else 0.0
        )

        print("\n" + "=" * 70)
        print("[三因子轮动] 净值统计")
        print("=" * 70)
        print(f"  总收益率: {total_ret:+.2f}%")
        print(f"  年化收益: {ann:.2f}%")
        print(f"  最大回撤: {max_dd:.2f}%")
        print(f"  夏普(日收益*√252): {sharpe:.2f}")
        print("=" * 70)
        return {
            "total_return_pct": total_ret,
            "annual_return_pct": ann,
            "max_drawdown_pct": max_dd,
            "sharpe": sharpe,
        }

    def plot_equity_drawdown(self, filename: str | Path) -> None:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)
        dates = self.df_daily["date"]
        ax1.plot(dates, self.df_daily["account_value"], color="blue", lw=2, label="净值")
        ax1.axhline(self.initial_cash, color="gray", ls="--", alpha=0.5)
        for d in self.rebalance_dates:
            ax1.axvline(pd.to_datetime(d), color="orange", alpha=0.35, lw=1)
        ax1.set_title("账户净值", fontsize=14, fontweight="bold")
        ax1.set_ylabel("资产")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        ax2.fill_between(dates, 0, self.df_daily["drawdown"] * 100, color="red", alpha=0.25)
        ax2.plot(dates, self.df_daily["drawdown"] * 100, color="darkred", lw=1.5)
        ax2.set_title("回撤 (%)", fontsize=14, fontweight="bold")
        ax2.set_xlabel("日期")
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  [OK] 净值与回撤: {filename}")

    def plot_monthly_returns_heatmap(self, filename: str | Path) -> None:
        monthly = self.df_daily.groupby(["year", "month"])["account_value"].agg(["first", "last"])
        monthly["ret"] = (monthly["last"] / monthly["first"] - 1) * 100
        pivot = monthly.reset_index().pivot(index="year", columns="month", values="ret")
        fig, ax = plt.subplots(figsize=(14, 6))
        data = pivot.to_numpy(dtype=float)
        data_m = np.ma.masked_invalid(data)
        im = ax.imshow(data_m, cmap="RdYlGn", aspect="auto", vmin=-10, vmax=10, interpolation="nearest")
        nrows, ncols = data.shape
        for i in range(nrows):
            for j in range(ncols):
                val = data[i, j]
                if np.isfinite(val):
                    ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8)
        ax.set_xticks(np.arange(ncols))
        ax.set_xticklabels(pivot.columns)
        ax.set_yticks(np.arange(nrows))
        ax.set_yticklabels(pivot.index)
        plt.colorbar(im, ax=ax, label="月收益 (%)")
        ax.set_title("月度收益热力图", fontsize=16, fontweight="bold")
        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  [OK] 月度热力图: {filename}")

    def plot_dashboard(self, filename: str | Path, title: str = "三因子轮动 Dashboard") -> None:
        fig = plt.figure(figsize=(20, 12))
        gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.3)
        dates = self.df_daily["date"]

        ax1 = fig.add_subplot(gs[0, :])
        ax1.plot(dates, self.df_daily["account_value"], color="blue", lw=2, label="净值")
        ax1.axhline(self.initial_cash, color="gray", ls="--", alpha=0.5)
        for d in self.rebalance_dates:
            ax1.axvline(pd.to_datetime(d), color="orange", alpha=0.3, lw=1)
        ax1.set_title(title, fontsize=18, fontweight="bold")
        ax1.set_ylabel("资产")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        ax2 = fig.add_subplot(gs[1, 0])
        ax2.fill_between(dates, 0, self.df_daily["drawdown"] * 100, color="red", alpha=0.3)
        ax2.set_title("回撤 %", fontweight="bold")
        ax2.grid(True, alpha=0.3)

        ax3 = fig.add_subplot(gs[1, 1])
        mret = self.df_daily.groupby("year_month")["account_value"].agg(["first", "last"])
        mret["r"] = (mret["last"] / mret["first"] - 1) * 100
        colors = ["green" if x > 0 else "red" for x in mret["r"]]
        ax3.bar(range(len(mret)), mret["r"], color=colors, alpha=0.6)
        ax3.axhline(0, color="black", lw=1)
        ax3.set_title("月度收益", fontweight="bold")
        ax3.grid(True, alpha=0.3)

        ax4 = fig.add_subplot(gs[1, 2])
        ax4.axis("off")
        final_v = float(self.df_daily["account_value"].iloc[-1])
        tr = (final_v / self.initial_cash - 1) * 100
        mdd = float(self.df_daily["drawdown"].min() * 100)
        txt = f"总收益: {tr:+.2f}%\n最大回撤: {mdd:.2f}%\n初始: {self.initial_cash:,.0f}\n期末: {final_v:,.0f}"
        ax4.text(0.1, 0.5, txt, transform=ax4.transAxes, fontsize=12, va="center", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

        ax5 = fig.add_subplot(gs[2, :])
        ax5.plot(dates, self.df_daily["account_value"].pct_change().fillna(0) * 100, color="steelblue", lw=0.8, alpha=0.8)
        ax5.set_title("日收益率 (%)", fontweight="bold")
        ax5.set_xlabel("日期")
        ax5.grid(True, alpha=0.3)

        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  [OK] Dashboard: {filename}")

    def plot_all(self, output_dir: str | Path = "./backtest_results") -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        print("\n生成图表...")
        self.plot_equity_drawdown(out / "mvm_equity_drawdown.png")
        self.plot_monthly_returns_heatmap(out / "mvm_monthly_heatmap.png")
        self.plot_dashboard(out / "mvm_dashboard.png")
        print(f"已保存至: {out.resolve()}")


def dataframe_from_joinquant_nav(context: Any) -> pd.DataFrame:
    """聚宽回测结束后，将 daily_nav_records 转为 DataFrame；调仓日见 context.rebalance_dates。"""
    if not hasattr(context, "daily_nav_records"):
        return pd.DataFrame()
    return pd.DataFrame(context.daily_nav_records)


# =============================================================================
# 本地演示：合成净值曲线 + 画图（无需聚宽）
# =============================================================================


def _demo_synthetic_nav(days: int = 500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.012, days)
    nav = 1_000_000.0 * np.cumprod(1 + r)
    dates = pd.date_range("2020-01-01", periods=days, freq="B")
    return pd.DataFrame({"date": dates, "account_value": nav})


if __name__ == "__main__":
    print("本地演示：合成净值 + FactorRotationVisualizer 出图（非聚宽回测）")
    df = _demo_synthetic_nav(480)
    vis = FactorRotationVisualizer(df, initial_cash=1_000_000.0, rebalance_dates=[])
    vis.generate_report()
    out = Path(__file__).resolve().parent / "backtrader实战" / "mvm_factor_demo_results"
    vis.plot_all(out)
