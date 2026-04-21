# -*- coding: utf-8 -*-
"""
阿波量化 · 课后作业：纳指定投回测（思考题「策略尝试」）

任务概要：
  1) 1990–2020：纳指定投 + 交易成本，输出收益、最大回撤、夏普等
  2) 引入择时（默认：月末收盘价 > 200 日均线才在下月初定投；可选「现金累积」版）
  3) 2021–2025：样本外对比「基准定投」与「择时定投」

依赖：pip install yfinance pandas numpy
若 Yahoo 限流，可用 Yahoo Finance 导出 ^IXIC 日线为 CSV，再：
  python nasdaq_dca_abo_homework.py --csv path/to/IXIC.csv

指数：纳斯达克综合指数 Yahoo 代码 ^IXIC
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


TICKER = "^IXIC"


def _squeeze_series(s: pd.Series | pd.DataFrame) -> pd.Series:
	if isinstance(s, pd.DataFrame):
		return s.iloc[:, 0]
	return s


def load_ixic(
	start: str,
	end: str,
	csv_path: Optional[str] = None,
) -> pd.Series:
	"""日线收盘价，索引为 DatetimeIndex，auto_adjust 已反映拆股等。"""
	if csv_path:
		df = pd.read_csv(csv_path)
		col_date = "Date" if "Date" in df.columns else df.columns[0]
		df[col_date] = pd.to_datetime(df[col_date])
		df = df.set_index(col_date).sort_index()
		c = "Adj Close" if "Adj Close" in df.columns else ("Close" if "Close" in df.columns else df.columns[-1])
		close = _squeeze_series(df[c].astype(float))
	else:
		import yfinance as yf

		raw = yf.download(TICKER, start=start, end=end, auto_adjust=True, progress=False)
		if raw.empty:
			raise RuntimeError(
				"Yahoo 未返回数据（可能限流）。请稍后重试或 --csv 指定本地 CSV（含 Date, Close 或 Adj Close）。"
			)
		close = _squeeze_series(raw["Close"].astype(float))
	close = close.sort_index()
	close = close.loc[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))]
	close = close[~close.index.duplicated(keep="last")]
	return close


@dataclass
class BacktestResult:
	name: str
	total_invested: float
	final_value: float
	cagr: float
	max_drawdown: float
	sharpe_annual: float
	months_invested: int
	months_total: int
	equity_curve: pd.Series


def _monthly_first_business_close(close: pd.Series) -> pd.Series:
	"""每月第一个交易日的收盘价（用于定投成交价）。"""
	return close.resample("BMS").first().dropna()


def _max_drawdown(equity: pd.Series) -> float:
	if equity.empty or (equity <= 0).any():
		equity = equity.clip(lower=1e-12)
	peak = equity.cummax()
	dd = (equity / peak) - 1.0
	return float(dd.min())


def _cagr(start_value: float, end_value: float, years: float) -> float:
	if years <= 0 or start_value <= 0:
		return float("nan")
	return (end_value / start_value) ** (1.0 / years) - 1.0


def _sharpe_daily(equity: pd.Series, periods_per_year: int = 252) -> float:
	r = equity.pct_change().dropna()
	if r.std() == 0 or len(r) < 10:
		return float("nan")
	return float(np.sqrt(periods_per_year) * r.mean() / r.std())


def _is_first_trading_day_of_month(d, idx: pd.DatetimeIndex) -> bool:
	prev = idx[idx < d]
	if len(prev) == 0:
		return True
	p = prev[-1]
	return d.year != p.year or d.month != p.month


def simulate_dca(
	close: pd.Series,
	start: str,
	end: str,
	monthly_invest: float,
	fee_rate: float,
	timing: bool,
	timing_mode: str,
	ma_window: int,
) -> BacktestResult:
	"""
	timing_mode:
	  - 'skip': 信号为假当月不投入（总投入少于基准）
	  - 'accumulate': 每月增加现金池；信号为真时在下月初用全部现金买入股票
	"""
	c = close.loc[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))].copy()
	if c.empty:
		raise ValueError("区间内无行情数据")

	sma = c.rolling(ma_window).mean()
	idx = c.index
	shares = 0.0
	cash_pool = 0.0
	total_invested = 0.0
	months_with_buy = 0
	months_total = 0
	last_ym = None

	equity_list = []

	for d in idx:
		if _is_first_trading_day_of_month(d, idx):
			ym = (d.year, d.month)
			if last_ym != ym:
				months_total += 1
				last_ym = ym
			price = float(c.loc[d])
			if price > 0:
				prev_idx = idx[idx < d]
				prev = prev_idx[-1] if len(prev_idx) else None
				sig = False
				if prev is not None and pd.notna(sma.loc[prev]):
					sig = bool(c.loc[prev] > sma.loc[prev])

				if not timing:
					net = monthly_invest * (1.0 - fee_rate)
					shares += net / price
					total_invested += monthly_invest
					months_with_buy += 1
				elif timing_mode == "skip":
					if sig:
						net = monthly_invest * (1.0 - fee_rate)
						shares += net / price
						total_invested += monthly_invest
						months_with_buy += 1
				else:
					cash_pool += monthly_invest
					total_invested += monthly_invest
					if sig and cash_pool > 0:
						net = cash_pool * (1.0 - fee_rate)
						shares += net / price
						cash_pool = 0.0
						months_with_buy += 1

		equity_list.append(float(shares * float(c.loc[d]) + cash_pool))

	equity = pd.Series(equity_list, index=idx)
	final_value = float(equity.iloc[-1])
	years = (c.index[-1] - c.index[0]).days / 365.25
	# 以「总投入」为分母的近似复合收益（定投常用口径）
	cagr_portfolio = _cagr(1.0, final_value / max(total_invested, 1e-9), years) if total_invested > 0 else float("nan")
	mdd = _max_drawdown(equity)
	sh = _sharpe_daily(equity)

	if not timing:
		m_in = months_total
	elif timing_mode == "skip":
		m_in = months_with_buy
	else:
		m_in = months_with_buy

	return BacktestResult(
		name="",
		total_invested=total_invested,
		final_value=final_value,
		cagr=cagr_portfolio,
		max_drawdown=mdd,
		sharpe_annual=sh,
		months_invested=m_in,
		months_total=months_total,
		equity_curve=equity,
	)


def print_result(title: str, r: BacktestResult) -> None:
	print("\n" + "=" * 60)
	print(title)
	print("=" * 60)
	print(f"  总投入（含未买入的现金入账）: {r.total_invested:,.2f}")
	print(f"  期末组合市值:               {r.final_value:,.2f}")
	print(f"  期末收益率（市值/总投入）:   {r.final_value / max(r.total_invested, 1e-9) - 1.0:+.2%}")
	print(f"  CAGR（近似，以总投入为成本）: {r.cagr:+.2%}")
	print(f"  最大回撤:                    {r.max_drawdown:.2%}")
	print(f"  夏普（日收益年化）:          {r.sharpe_annual:.3f}")
	print(f"  定投月数 / 总月数:           {r.months_invested} / {r.months_total}")


def main() -> int:
	p = argparse.ArgumentParser(description="纳指定投 + 择时 阿波课后作业")
	p.add_argument("--csv", type=str, default=None, help="本地日线 CSV（Date, Close 或 Adj Close）")
	p.add_argument("--monthly", type=float, default=1000.0, help="每月定投金额（美元）")
	p.add_argument("--fee", type=float, default=0.001, help="单边交易成本比例，默认 0.1%")
	p.add_argument("--ma", type=int, default=200, help="择时均线窗口")
	args = p.parse_args()

	# 拉全样本（1990–2025）一次，再切片
	try:
		full_close = load_ixic("1990-01-01", "2026-01-01", csv_path=args.csv)
	except Exception as e:
		print("加载数据失败:", e, file=sys.stderr)
		return 1

	print("数据区间:", full_close.index[0].date(), "→", full_close.index[-1].date(), " 条数:", len(full_close))

	# --- 作业 1：1990–2020 基准 ---
	r1 = simulate_dca(
		full_close,
		"1990-01-01",
		"2020-12-31",
		monthly_invest=args.monthly,
		fee_rate=args.fee,
		timing=False,
		timing_mode="skip",
		ma_window=args.ma,
	)
	print_result("【作业1】1990–2020 纳指定投（每月，含交易成本）", r1)

	r1t = simulate_dca(
		full_close,
		"1990-01-01",
		"2020-12-31",
		monthly_invest=args.monthly,
		fee_rate=args.fee,
		timing=True,
		timing_mode="accumulate",
		ma_window=args.ma,
	)
	print_result("【作业2】1990–2020 择时定投（上月末>MA200 则下月初用累积现金买入；否则持币）", r1t)

	r1s = simulate_dca(
		full_close,
		"1990-01-01",
		"2020-12-31",
		monthly_invest=args.monthly,
		fee_rate=args.fee,
		timing=True,
		timing_mode="skip",
		ma_window=args.ma,
	)
	print_result("【备选择时】1990–2020 仅信号月为真才投入（skip 模式，总投入少于基准）", r1s)

	# --- 作业 3：2021–2025 ---
	r2 = simulate_dca(
		full_close,
		"2021-01-01",
		"2025-12-31",
		monthly_invest=args.monthly,
		fee_rate=args.fee,
		timing=False,
		timing_mode="skip",
		ma_window=args.ma,
	)
	print_result("【作业3a】2021–2025 基准定投", r2)

	r2t = simulate_dca(
		full_close,
		"2021-01-01",
		"2025-12-31",
		monthly_invest=args.monthly,
		fee_rate=args.fee,
		timing=True,
		timing_mode="accumulate",
		ma_window=args.ma,
	)
	print_result("【作业3b】2021–2025 择时定投（accumulate）", r2t)

	print("\n说明：")
	print("  · 交易成本按买入金额扣 fee（单边）；未模拟卖出费（定投长期持有）。")
	print("  · 择时信号：每个定投日（月初首个交易日）用「上一交易日」收盘与 SMA200 比较，减少前视。")
	print("  · accumulate：每月仍增加现金池，仅当信号为真时一次性买入股票；skip：信号假则当月不投入。")
	return 0


if __name__ == "__main__":
	sys.exit(main())
