# -*- coding: utf-8 -*-
"""异动监管胜率优化扫描（一次性分析脚本）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from yidong_regulation_backtest_core import (  # noqa: E402
	SKIP_F,
	build_code_trade_dates,
	build_f_block_keys,
	build_g_zero,
	collect_signals,
	is_limit_skip_row,
	load_yidong,
	simulate_trade,
)

CSV = Path(__file__).resolve().parents[1] / "实盘策略" / "上游数据源" / "yidong_regulation_stocks_2026.csv"


def filter_signals(sig: pd.DataFrame, **conds) -> pd.DataFrame:
	m = pd.Series(True, index=sig.index)
	if "f_min" in conds:
		m &= sig["F"] >= conds["f_min"]
	if "f_max" in conds:
		m &= sig["F"] <= conds["f_max"]
	if "tpct_lo" in conds:
		p = pd.to_numeric(sig["T日涨跌幅%"], errors="coerce")
		m &= p >= conds["tpct_lo"]
	if "tpct_hi" in conds:
		p = pd.to_numeric(sig["T日涨跌幅%"], errors="coerce")
		m &= p <= conds["tpct_hi"]
	if conds.get("ma5_above"):
		c = pd.to_numeric(sig["T日_收盘"], errors="coerce")
		ma = pd.to_numeric(sig["T日_MA5"], errors="coerce")
		m &= (c > ma) & ma.notna()
	if conds.get("board_main"):
		m &= sig["股票代码"].str.startswith(("60", "00"))
	if conds.get("board_growth"):
		m &= sig["股票代码"].str.startswith(("68", "30"))
	return sig.loc[m]


def backtest(sig: pd.DataFrame, g0, cd, **sim_kw) -> dict | None:
	rows = []
	for _, r in sig.iterrows():
		t = simulate_trade(r, g0, cd, **sim_kw)
		if t:
			rows.append(t)
	if not rows:
		return None
	d = pd.DataFrame(rows)
	r = d["收益率%"].astype(float)
	return {
		"n": len(d),
		"wr": round(100 * (r > 0).mean(), 1),
		"avg": round(r.mean(), 2),
		"sum": round(r.sum(), 1),
		"med": round(r.median(), 2),
	}


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)
	print("baseline signals", len(sig))
	print("baseline", backtest(sig, g0, cd))

	print("\n=== 入场过滤 + 基准卖出 ===")
	for name, cond in [
		("F>=9", {"f_min": 9}),
		("F>=12", {"f_min": 12}),
		("F in [9,21]", {"f_min": 9, "f_max": 21}),
		("F in [12,30]", {"f_min": 12, "f_max": 30}),
		("T涨跌幅 2%~8%", {"tpct_lo": 2, "tpct_hi": 8}),
		("T涨跌幅 0%~5%", {"tpct_lo": 0, "tpct_hi": 5}),
		("T收盘>T日MA5", {"ma5_above": True}),
		("F>=9 & MA5上", {"f_min": 9, "ma5_above": True}),
		("F>=9 & T涨跌幅2-8%", {"f_min": 9, "tpct_lo": 2, "tpct_hi": 8}),
		("F>=9 仅主板", {"f_min": 9, "board_main": True}),
		("F>=12 仅主板", {"f_min": 12, "board_main": True}),
	]:
		b = backtest(filter_signals(sig, **cond), g0, cd)
		if b and b["n"] >= 20:
			print("%-22s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%%" % (name, b["n"], b["wr"], b["avg"], b["sum"]))

	print("\n=== F>=9 卖出变体 ===")
	s9 = filter_signals(sig, f_min=9)
	for name, kw in [
		("基准SL8 T+2", {}),
		("无止损T+6", {"stop_pct": 99, "min_day": 99}),
		("SL12 T+2", {"stop_pct": 12}),
		("SL8 T+3起", {"min_day": 3}),
		("SL8 T+4起", {"min_day": 4}),
	]:
		b = backtest(s9, g0, cd, **kw)
		if b:
			print("%-14s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%%" % (name, b["n"], b["wr"], b["avg"], b["sum"]))


if __name__ == "__main__":
	main()
