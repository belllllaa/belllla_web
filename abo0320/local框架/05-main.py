"""
单因子回测主程序 - Version 5.0

"""

import pandas as pd
from data_loader import DataLoader
from factor_calculator import FactorCalculator
from signal_generator import SignalGenerator


def run_single_factor_backtest(
    data_dir: str = './data',
    start_date: str = '2020-03-01',
    end_date: str = '2020-12-31',
    top_n: int = 10,
    period: int = 20
):
    """
    运行单因子回测（简化版）

    Args:
        data_dir: 数据目录路径
        start_date: 回测起始日期
        end_date: 回测结束日期
        top_n: 每日选股数量
        period: 动量因子回看周期
    """
    print("=" * 60)
    print("🚀 开始单因子回测")
    print("=" * 60)

    # 1. 初始化模块
    loader = DataLoader(data_dir)
    calculator = FactorCalculator(loader)
    signal_gen = SignalGenerator(loader, calculator)
    factor_col = calculator.momentum_col(period)

    # 2. 计算并保存因子（如果还没有）
    print(f"\n📊 检查因子数据...")
    trade_dates = loader.get_all_dates()

    # 只计算回测期间的因子（节省时间）
    backtest_dates = [d for d in trade_dates if start_date <= d <= end_date]
    print(f"📅 回测区间: {start_date} 至 {end_date}")
    print(f"📅 交易日数量: {len(backtest_dates)}")
    if not backtest_dates:
        print("⚠️ 回测区间内无可用交易日，请检查日期或数据目录")
        return pd.Series(dtype=float)

    # 检查是否需要计算因子
    first_date = backtest_dates[0] if backtest_dates else None
    if first_date and calculator.load_factor(first_date).empty:
        print(f"⚠️  因子数据不存在，开始计算...")
        # 只计算必要的日期（回测期 + period 天缓冲）
        start_idx = trade_dates.index(backtest_dates[0])
        calc_dates = trade_dates[max(0, start_idx - period):trade_dates.index(backtest_dates[-1]) + 1]

        for i, date in enumerate(calc_dates):
            factor_df = calculator.calculate_momentum_daily(date, period)
            if not factor_df.empty:
                save_path = calculator.factor_dir / f'{date}.csv'
                factor_df.to_csv(save_path, index=False)

            if (i + 1) % 50 == 0:
                print(f"进度: {i + 1}/{len(calc_dates)}")

        print(f"✅ 因子计算完成！")
    else:
        print(f"✅ 因子数据已存在，直接使用")

    print(f"📊 每日选股数量: {top_n}")
    print("\n" + "=" * 60)

    # 3. 逐日选股并记录
    daily_holdings = {}  # 记录每日持仓

    for i, date in enumerate(backtest_dates):
        # 生成选股信号
        selected_stocks = signal_gen.generate_daily_signal(
            date=date,
            top_n=top_n,
            filter_limit=True,
            factor_col=factor_col
        )

        daily_holdings[date] = selected_stocks

        # 打印前 5 天的选股结果
        if i < 5:
            print(f"{date} | 选股: {selected_stocks[:3]}... (共{len(selected_stocks)}只)")

    print("...")
    last_holdings = daily_holdings[backtest_dates[-1]]
    print(f"{backtest_dates[-1]} | 选股: {last_holdings[:3]}... (共{len(last_holdings)}只)")

    # 4. 计算每日组合收益（简化版：等权重 + T+1）
    portfolio_returns = []
    portfolio_dates = []

    for date in backtest_dates:
        # T+1 逻辑：在 date 选股，使用 data_ret/date 的 1vwap_pct（当日→次日的 forward return）
        holdings = daily_holdings.get(date, [])

        if len(holdings) > 0:
            ret_df = loader.get_daily_returns(date)
            if not ret_df.empty and '1vwap_pct' in ret_df.columns:
                ret_df = ret_df.set_index('code')
                holdings_ret = ret_df[ret_df.index.isin(holdings)]
                if len(holdings_ret) > 0:
                    portfolio_ret = holdings_ret['1vwap_pct'].mean()
                    portfolio_returns.append(portfolio_ret)
                    portfolio_dates.append(date)
                    continue

        # 如果没有收益数据，记录为空（教学简化）
        portfolio_returns.append(None)
        portfolio_dates.append(date)

    # 5. 计算累计收益
    portfolio_returns_series = pd.Series(portfolio_returns, index=portfolio_dates, dtype='float64').dropna()
    if portfolio_returns_series.empty:
        print("⚠️ 没有可用收益数据，无法计算绩效")
        return portfolio_returns_series

    cumulative_returns = (1 + portfolio_returns_series).cumprod()

    # 6. 输出结果
    print("\n" + "=" * 60)
    print("📊 回测结果统计")
    print("=" * 60)
    total_return = (cumulative_returns.iloc[-1] - 1) * 100
    annual_return = (cumulative_returns.iloc[-1] ** (252 / len(portfolio_returns_series)) - 1) * 100
    daily_mean = portfolio_returns_series.mean() * 100
    daily_std = portfolio_returns_series.std() * 100
    sharpe = (portfolio_returns_series.mean() / portfolio_returns_series.std()) * (252 ** 0.5) if daily_std > 0 else 0

    print(f"总收益率: {total_return:.2f}%")
    print(f"年化收益率: {annual_return:.2f}%")
    print(f"日均收益率: {daily_mean:.4f}%")
    print(f"收益波动率: {daily_std:.4f}%")
    print(f"夏普比率: {sharpe:.2f}")
    print(f"最大单日收益: {portfolio_returns_series.max() * 100:.2f}%")
    print(f"最大单日亏损: {portfolio_returns_series.min() * 100:.2f}%")

    # 7. 打印累计收益曲线（前后各5天）
    print(f"\n累计净值曲线（前5天）:")
    for date in cumulative_returns.index[:5]:
        print(f"  {date}    {cumulative_returns.loc[date]:.4f}")
    print("  ...")
    print(f"累计净值曲线（后5天）:")
    for date in cumulative_returns.index[-5:]:
        print(f"  {date}    {cumulative_returns.loc[date]:.4f}")

    print("\n" + "=" * 60)
    print("✅ 回测完成！")
    print("=" * 60)

    return cumulative_returns


# ========== 主程序入口 ==========
if __name__ == '__main__':
    cumret = run_single_factor_backtest(
        data_dir='./data',
        start_date='2020-03-01',
        end_date='2020-12-31',
        top_n=10,
        period=20
    )
