from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CSV = _SCRIPT_DIR / "nasdaq_fred_prices.csv"


def calculate_dca_performance(csv_filepath: str | Path | None = None, save_result_csv: bool = True):
    """定投回测。csv_filepath 默认与 invest.py 同目录下的 nasdaq_fred_prices.csv。"""
    path = Path(csv_filepath) if csv_filepath is not None else _DEFAULT_CSV
    if not path.is_absolute():
        path = _SCRIPT_DIR / path

    print("正在读取数据并进行定投回测计算...")
    
    # 1. 读取数据与预处理
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        print(f"找不到文件: {path}")
        print(f"请把 nasdaq_fred_prices.csv 放在与本脚本同一目录: {_SCRIPT_DIR}")
        return
        
    # 兼容不同数据源的列名
    close_col = 'Nasdaq_Close' if 'Nasdaq_Close' in df.columns else 'Close'
    if close_col not in df.columns:
        print("CSV 中找不到收盘价列（需要 Nasdaq_Close 或 Close），请检查文件。")
        return
        
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date').reset_index(drop=True)
    
    # 2. 设定定投核心参数
    DAILY_INVESTMENT = 100.0  # 每天固定投入 100 美元
    FEE_RATE = 0.001          # 手续费千分之一 (0.1%)
    
    # 实际用于购买指数的金额 = 投入金额 * (1 - 手续费率)
    actual_buy_amount = DAILY_INVESTMENT * (1 - FEE_RATE)
    
    # 3. 核心资产流转计算逻辑
    # 每天买入的份额 = 实际买入金额 / 当天收盘价
    df['Shares_Bought'] = actual_buy_amount / df[close_col]
    
    # 累计持仓份额
    df['Cumulative_Shares'] = df['Shares_Bought'].cumsum()
    
    # 累计投入本金 (包含手续费)
    df['Cumulative_Principal'] = DAILY_INVESTMENT * (df.index + 1)
    
    # 每日持仓总市值 = 累计份额 * 当天收盘价
    df['Portfolio_Value'] = df['Cumulative_Shares'] * df[close_col]
    
    # 每日累计绝对收益率 = (持仓市值 - 累计本金) / 累计本金
    df['Cumulative_Return'] = (df['Portfolio_Value'] - df['Cumulative_Principal']) / df['Cumulative_Principal']
    
    # 4. 计算最大回撤 (Max Drawdown)
    # 记录历史最高市值
    df['Peak_Value'] = df['Portfolio_Value'].cummax()
    # 当前回撤幅度 = (当前市值 - 历史最高市值) / 历史最高市值
    df['Drawdown'] = (df['Portfolio_Value'] - df['Peak_Value']) / df['Peak_Value']
    max_drawdown = df['Drawdown'].min()
    
    # 5. 计算夏普比率 (Sharpe Ratio)
    # 策略每日收益率 = (今天市值 - 昨天市值 - 今天投入本金) / (昨天市值 + 今天投入本金)
    prev_value = df['Portfolio_Value'].shift(1).fillna(0)
    df['Daily_Strategy_Return'] = (df['Portfolio_Value'] - prev_value - DAILY_INVESTMENT) / (prev_value + DAILY_INVESTMENT)
    
    # 假设无风险利率为 0，年化交易日为 252 天
    mean_daily_return = df['Daily_Strategy_Return'].mean()
    std_daily_return = df['Daily_Strategy_Return'].std()
    sharpe_ratio = (mean_daily_return / std_daily_return) * np.sqrt(252)
    
    # 6. 计算年化收益率 (IRR - 内部收益率)
    total_days = len(df)
    final_value = df['Portfolio_Value'].iloc[-1]
    total_principal = df['Cumulative_Principal'].iloc[-1]
    total_return_pct = df['Cumulative_Return'].iloc[-1]
    
    # 使用二分法求解每日 IRR（因为每天都有现金流，这是最准确的年化计算方式）
    low, high = -0.05, 0.05
    for _ in range(100):
        mid = (low + high) / 2
        if mid == 0:
            fv_est = DAILY_INVESTMENT * total_days
        else:
            # 等额多次投入的终值公式
            fv_est = DAILY_INVESTMENT * (((1 + mid)**total_days - 1) / mid)
            
        if fv_est > final_value:
            high = mid
        else:
            low = mid
            
    daily_irr = (low + high) / 2
    annualized_irr = ((1 + daily_irr) ** 252) - 1

    if save_result_csv:
        out_path = _SCRIPT_DIR / "invest_dca_backtest_series.csv"
        df.to_csv(out_path, index=False)
        print(f"逐日回测明细已保存: {out_path}")

    # 7. 打印最终回测报告
    print("\n" + "=" * 45)
    print("纳斯达克指数定投回测报告 (含千一手续费)")
    print("=" * 45)
    print(f"回测区间: {df['Date'].iloc[0].strftime('%Y-%m-%d')} 至 {df['Date'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f"总交易天数: {total_days} 天")
    print(f"累计投入本金: ${total_principal:,.2f}")
    print(f"期末持仓总市值: ${final_value:,.2f}")
    print("-" * 45)
    print(f"截至目前的总收益率: {total_return_pct * 100:.2f}%")
    print(f"年化收益率 (IRR): {annualized_irr * 100:.2f}%")
    print(f"累计收益的最大回撤: {max_drawdown * 100:.2f}%")
    print(f"策略夏普比率: {sharpe_ratio:.2f}")
    print("=" * 45)


def _ma_z_extra(
    s: pd.Series,
    ma_n: int,
    z_thr: float = -1.0,
) -> tuple[pd.Series, pd.Series, pd.Series, list[bool]]:
    """
    Z = (Close - MA_ma_n) / ma_n 日收盘标准差；当日 Z < z_thr（默认 -1）为 True。
    """
    ma = s.rolling(ma_n, min_periods=ma_n).mean()
    std = s.rolling(ma_n, min_periods=ma_n).std()
    z = (s - ma) / std.replace(0, np.nan)
    n = len(s)
    extras: list[bool] = []
    for i in range(n):
        zi = z.iloc[i]
        if pd.isna(zi):
            extras.append(False)
        else:
            extras.append(bool(zi < z_thr))
    return ma, std, z, extras


def calculate_dca_ma_cross_performance(
    csv_filepath: str | Path | None = None,
    save_result_csv: bool = True,
):
    """
    任务2：只买不卖。
    每日定投 1 份；MA60Z<-1 再加 2 份，MA120Z<-1 再加 2 份（可叠加）。
    Z = (Close-MA_n)/(n日收盘标准差)。
    """
    path = Path(csv_filepath) if csv_filepath is not None else _DEFAULT_CSV
    if not path.is_absolute():
        path = _SCRIPT_DIR / path

    ma60_n, ma120_n = 60, 120
    z_thr = -1.0
    mr_extra_per_signal = 2

    print(
        "正在读取数据并进行「每日定投 + MA60Z<-1/MA120Z<-1 各加2份(可叠加)」回测..."
    )

    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        print(f"找不到文件: {path}")
        print(f"请把 nasdaq_fred_prices.csv 放在与本脚本同一目录: {_SCRIPT_DIR}")
        return

    close_col = "Nasdaq_Close" if "Nasdaq_Close" in df.columns else "Close"
    if close_col not in df.columns:
        print("CSV 中找不到收盘价列（需要 Nasdaq_Close 或 Close），请检查文件。")
        return

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    DAILY_INVESTMENT = 100.0
    FEE_RATE = 0.001

    s = df[close_col].astype(float)
    ma60, std60, z60, ex60 = _ma_z_extra(s, ma60_n, z_thr)
    ma120, std120, z120, ex120 = _ma_z_extra(s, ma120_n, z_thr)
    n_days = len(df)

    shares = 0.0
    portfolio_values = []
    daily_contribs = []

    for i in range(n_days):
        price = float(s.iloc[i])
        n_extra = mr_extra_per_signal * (int(ex60[i]) + int(ex120[i]))
        contrib = DAILY_INVESTMENT * (1.0 + n_extra)
        buy_amt = contrib * (1 - FEE_RATE)
        shares += buy_amt / price

        port_value = shares * price
        portfolio_values.append(port_value)
        daily_contribs.append(contrib)

    df[f"MA{ma60_n}"] = ma60
    df[f"STD{ma60_n}"] = std60
    df[f"Z_MA{ma60_n}"] = z60
    df["Extra_MA60Z"] = ex60
    df[f"MA{ma120_n}"] = ma120
    df[f"STD{ma120_n}"] = std120
    df[f"Z_MA{ma120_n}"] = z120
    df["Extra_MA120Z"] = ex120
    df["N_Extra_Units"] = [
        mr_extra_per_signal * (int(ex60[i]) + int(ex120[i])) for i in range(n_days)
    ]

    df["Portfolio_Value"] = portfolio_values
    df["Daily_Contribution"] = daily_contribs
    df["Cumulative_Principal"] = df["Daily_Contribution"].cumsum()
    df["Cumulative_Return"] = np.where(
        df["Cumulative_Principal"] > 0,
        (df["Portfolio_Value"] - df["Cumulative_Principal"]) / df["Cumulative_Principal"],
        0.0,
    )

    df["Peak_Value"] = df["Portfolio_Value"].cummax()
    df["Drawdown"] = (df["Portfolio_Value"] - df["Peak_Value"]) / df["Peak_Value"]
    max_drawdown = df["Drawdown"].min()

    pv = df["Portfolio_Value"]
    prev_pv = pv.shift(1).fillna(0)
    c = df["Daily_Contribution"]
    df["Daily_Strategy_Return"] = (pv - prev_pv - c) / (prev_pv + c).replace(0, np.nan)

    mean_daily_return = df["Daily_Strategy_Return"].mean()
    std_daily_return = df["Daily_Strategy_Return"].std()
    sharpe_ratio = (
        (mean_daily_return / std_daily_return) * np.sqrt(252)
        if std_daily_return and std_daily_return > 0
        else float("nan")
    )

    total_days = len(df)
    final_value = df["Portfolio_Value"].iloc[-1]
    total_principal = df["Cumulative_Principal"].iloc[-1]
    total_return_pct = df["Cumulative_Return"].iloc[-1]

    dates = df["Date"]
    years = max((dates.iloc[-1] - dates.iloc[0]).days / 365.25, 1e-9)
    if total_principal > 0:
        cagr = (final_value / total_principal) ** (1 / years) - 1
    else:
        cagr = float("nan")

    if save_result_csv:
        out_path = _SCRIPT_DIR / "invest_dca_ma_cross_series.csv"
        df.to_csv(out_path, index=False)
        print(f"择时逐日明细已保存: {out_path}")

    print("\n" + "=" * 45)
    print(
        f"纳指定投 + 每日一份、MA60/120 Z<{z_thr} 各加{mr_extra_per_signal}份可叠加 (仅买入千一手续费)"
    )
    print("=" * 45)
    print(f"回测区间: {df['Date'].iloc[0].strftime('%Y-%m-%d')} 至 {df['Date'].iloc[-1].strftime('%Y-%m-%d')}")
    print(f"总日历日数: {total_days} 天")
    print(f"累计定投本金: ${total_principal:,.2f}")
    print(f"期末组合总市值: ${final_value:,.2f}")
    print("-" * 45)
    print(f"截至目前的总收益率: {total_return_pct * 100:.2f}%")
    print(f"年化收益率 (CAGR): {cagr * 100:.2f}%")
    print(f"累计收益的最大回撤: {max_drawdown * 100:.2f}%")
    print(f"策略夏普比率: {sharpe_ratio:.2f}")
    print("=" * 45)


if __name__ == "__main__":
    # 数据默认读同目录 nasdaq_fred_prices.csv；也可传入绝对路径
    calculate_dca_performance()
    calculate_dca_ma_cross_performance()
