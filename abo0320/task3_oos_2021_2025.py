"""
任务3（阿波量化思考题）：样本外 2021–2025
对比「基准每日定投」与「改进：MA60/120 Z 加码」，均只买不卖、千一买入手续费。

规则与 invest.py 一致：每日 1 份；MA60Z<-1 加 2 份，MA120Z<-1 加 2 份（可叠加）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from invest import _ma_z_extra

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CSV = _SCRIPT_DIR / "nasdaq_fred_prices.csv"

DAILY_INVESTMENT = 100.0
FEE_RATE = 0.001
OOS_START = "2021-01-01"
OOS_END = "2025-12-31"
MA60_N, MA120_N = 60, 120
Z_THR = -1.0
MR_EXTRA_PER_SIGNAL = 2


def _resolve_path(csv_filepath: str | Path | None) -> Path:
    path = Path(csv_filepath) if csv_filepath is not None else _DEFAULT_CSV
    if not path.is_absolute():
        path = _SCRIPT_DIR / path
    return path


def _load_df(path: Path) -> tuple[pd.DataFrame, str]:
    df = pd.read_csv(path)
    close_col = "Nasdaq_Close" if "Nasdaq_Close" in df.columns else "Close"
    if close_col not in df.columns:
        raise ValueError("CSV 需要 Nasdaq_Close 或 Close 列")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df, close_col


def _max_drawdown(series: np.ndarray | pd.Series) -> float:
    s = np.asarray(series, dtype=float)
    peak = np.maximum.accumulate(s)
    dd = (s - peak) / peak
    return float(np.min(dd))


def _sharpe_from_pv(pv: np.ndarray, contrib: np.ndarray) -> float:
    """与日度现金流一致的日收益，年化夏普（无风险=0）。"""
    pv = np.asarray(pv, dtype=float)
    c = np.asarray(contrib, dtype=float)
    prev = np.roll(pv, 1)
    prev[0] = 0.0
    denom = prev + c
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(denom > 0, (pv - prev - c) / denom, np.nan)
    r = r[np.isfinite(r)]
    if r.size < 2 or np.std(r, ddof=1) == 0:
        return float("nan")
    return float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(252))


def _irr_daily_dca(n_days: int, final_value: float, daily: float) -> float:
    if n_days <= 0:
        return float("nan")
    low, high = -0.05, 0.05
    for _ in range(100):
        mid = (low + high) / 2
        if abs(mid) < 1e-12:
            fv_est = daily * n_days
        else:
            fv_est = daily * (((1 + mid) ** n_days - 1) / mid)
        if fv_est > final_value:
            high = mid
        else:
            low = mid
    d = (low + high) / 2
    return float(((1 + d) ** 252) - 1)


def run_baseline_dca_window(
    df: pd.DataFrame, close_col: str, i_start: int, i_end: int
) -> dict:
    s = df[close_col].astype(float)
    shares = 0.0
    pv_list: list[float] = []
    contrib_list: list[float] = []
    for i in range(i_start, i_end + 1):
        p = float(s.iloc[i])
        shares += DAILY_INVESTMENT * (1 - FEE_RATE) / p
        contrib_list.append(DAILY_INVESTMENT)
        pv_list.append(shares * p)
    pv = np.array(pv_list)
    c = np.array(contrib_list)
    principal = float(c.sum())
    final_v = float(pv[-1])
    total_ret = (final_v - principal) / principal if principal > 0 else float("nan")
    mdd = _max_drawdown(pv)
    sharpe = _sharpe_from_pv(pv, c)
    n = len(pv)
    irr = _irr_daily_dca(n, final_v, DAILY_INVESTMENT)
    d0, d1 = df["Date"].iloc[i_start], df["Date"].iloc[i_end]
    years = max((d1 - d0).days / 365.25, 1e-9)
    cagr = (final_v / principal) ** (1 / years) - 1 if principal > 0 else float("nan")
    return {
        "label": "基准：每日定投",
        "date_start": d0,
        "date_end": d1,
        "trading_days": n,
        "principal": principal,
        "final_value": final_v,
        "total_return": total_ret,
        "cagr": cagr,
        "irr_annual": irr,
        "max_drawdown": mdd,
        "sharpe": sharpe,
    }


def run_down_day_dca_window(
    df: pd.DataFrame,
    close_col: str,
    i_start: int,
    i_end: int,
    ma60_n: int = MA60_N,
    ma120_n: int = MA120_N,
    z_thr: float = Z_THR,
    mr_extra_per_signal: int = MR_EXTRA_PER_SIGNAL,
) -> dict:
    """
    与 invest.py 一致：每日 1 份；MA60Z/MA120Z<-1 各加 mr_extra_per_signal 份（可叠加）。
    仅在 i_start..i_end 计入投入与持仓；信号用全序列计算。
    """
    s = df[close_col].astype(float)
    _, _, _, ex60 = _ma_z_extra(s, ma60_n, z_thr)
    _, _, _, ex120 = _ma_z_extra(s, ma120_n, z_thr)
    shares = 0.0
    pv_list: list[float] = []
    contrib_list: list[float] = []
    for i in range(i_start, i_end + 1):
        p = float(s.iloc[i])
        n_extra = mr_extra_per_signal * (int(ex60[i]) + int(ex120[i]))
        c = DAILY_INVESTMENT * (1.0 + n_extra)
        shares += c * (1 - FEE_RATE) / p
        contrib_list.append(c)
        pv_list.append(shares * p)
    pv = np.array(pv_list)
    cc = np.array(contrib_list)
    principal = float(cc.sum())
    final_v = float(pv[-1])
    total_ret = (final_v - principal) / principal if principal > 0 else float("nan")
    mdd = _max_drawdown(pv)
    sharpe = _sharpe_from_pv(pv, cc)
    d0, d1 = df["Date"].iloc[i_start], df["Date"].iloc[i_end]
    years = max((d1 - d0).days / 365.25, 1e-9)
    cagr = (final_v / principal) ** (1 / years) - 1 if principal > 0 else float("nan")
    return {
        "label": f"改进：MA60/120 Z<{z_thr} 各加{mr_extra_per_signal}份可叠加",
        "date_start": d0,
        "date_end": d1,
        "trading_days": len(pv),
        "principal": principal,
        "final_value": final_v,
        "total_return": total_ret,
        "cagr": cagr,
        "irr_annual": float("nan"),
        "max_drawdown": mdd,
        "sharpe": sharpe,
    }


def _print_row(m: dict) -> None:
    irr_str = f"{m['irr_annual'] * 100:.2f}%" if not np.isnan(m["irr_annual"]) else "n/a"
    print(f"  {m['label']}")
    print(f"  区间: {m['date_start'].strftime('%Y-%m-%d')} ~ {m['date_end'].strftime('%Y-%m-%d')}  交易日: {m['trading_days']}")
    print(f"  累计投入: ${m['principal']:,.2f}  期末市值: ${m['final_value']:,.2f}")
    print(
        f"  总收益率: {m['total_return'] * 100:.2f}%  CAGR: {m['cagr'] * 100:.2f}%  "
        f"IRR(仅基准每日定投): {irr_str}"
    )
    print(f"  最大回撤: {m['max_drawdown'] * 100:.2f}%  夏普: {m['sharpe']:.2f}")


def task3_compare(
    csv_filepath: str | Path | None = None,
    oos_start: str = OOS_START,
    oos_end: str = OOS_END,
    save_csv: bool = True,
) -> None:
    path = _resolve_path(csv_filepath)
    try:
        df, close_col = _load_df(path)
    except FileNotFoundError:
        print(f"找不到文件: {path}")
        return
    except ValueError as e:
        print(e)
        return

    sub = df[(df["Date"] >= oos_start) & (df["Date"] <= oos_end)]
    if sub.empty:
        print(f"在 {oos_start} ~ {oos_end} 内无数据，请检查 CSV 日期范围。")
        return

    i_start = int(sub.index[0])
    i_end = int(sub.index[-1])

    base = run_baseline_dca_window(df, close_col, i_start, i_end)
    imp = run_down_day_dca_window(df, close_col, i_start, i_end)

    print("=" * 52)
    print("任务3 样本外对比：2021–2025（与 invest.py 规则一致）")
    print("=" * 52)
    _print_row(base)
    print("-" * 52)
    _print_row(imp)
    print("-" * 52)

    if base["principal"] > 0 and imp["principal"] > 0:
        mult_b = base["final_value"] / base["principal"]
        mult_i = imp["final_value"] / imp["principal"]
        excess_ret = imp["total_return"] - base["total_return"]
        excess_cagr = imp["cagr"] - base["cagr"]
        print(
            f"  说明: 改进策略在 MA60Z<-1 / MA120Z<-1 各多投 {MR_EXTRA_PER_SIGNAL} 份（可叠加），累计本金通常多于基准；可看「每 1 美元本金期末净值」。"
        )
        print(f"  每投入 1 美元期末净值: 基准 {mult_b:.4f}  改进 {mult_i:.4f}")
        print("  改进相对基准（总收益率差 / CAGR 差，口径见上）:")
        print(f"    总收益率多: {excess_ret * 100:+.2f} 个百分点")
        print(f"    CAGR 多: {excess_cagr * 100:+.2f} 个百分点")
    print("=" * 52)

    if save_csv:
        out = _SCRIPT_DIR / "task3_oos_2021_2025_summary.csv"
        rows = []
        for m in (base, imp):
            row = dict(m)
            row["date_start"] = row["date_start"].strftime("%Y-%m-%d")
            row["date_end"] = row["date_end"].strftime("%Y-%m-%d")
            rows.append(row)
        pd.DataFrame(rows).to_csv(out, index=False)
        print(f"摘要已保存: {out}")


if __name__ == "__main__":
    task3_compare()
