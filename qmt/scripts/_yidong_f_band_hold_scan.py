# -*- coding: utf-8 -*-
"""F 档 4-6 / 7-8：持有期与卖出规则扫描。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from yidong_regulation_backtest_core import (  # noqa: E402
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	simulate_trade,
)

CSV = Path(__file__).resolve().parents[1] / "实盘策略" / "上游数据源" / "yidong_regulation_stocks_2026.csv"


def f_band(f: float) -> str:
	if 4 <= f <= 6:
		return "F4-6"
	if 7 <= f <= 8:
		return "F7-8"
	if 9 <= f <= 11:
		return "F9-11"
	if f >= 12:
		return "F12+"
	return "other"


def backtest_sub(sig: pd.DataFrame, g0, cd, **kw) -> dict | None:
	rows = []
	for _, r in sig.iterrows():
		t = simulate_trade(r, g0, cd, **kw)
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
		"worst": round(r.min(), 2),
	}


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)
	sig = sig.copy()
	sig["band"] = sig["F"].map(lambda x: f_band(float(x)) if pd.notna(x) else "other")

	rules = [
		("基准 SL8 T+2→T+6", {}),
		("仅T+3收盘", {"stop_pct": 99, "min_day": 99, "fallback_day": 3}),
		("仅T+4收盘", {"stop_pct": 99, "min_day": 99, "fallback_day": 4}),
		("仅T+5收盘", {"stop_pct": 99, "min_day": 99, "fallback_day": 5}),
		("仅T+6收盘", {"stop_pct": 99, "min_day": 99, "fallback_day": 6}),
		("SL8 T+2→T+4", {"fallback_day": 4}),
		("SL8 T+2→T+5", {"fallback_day": 5}),
		("SL8 T+1起→T+4", {"min_day": 1, "fallback_day": 4}),
		("SL8 T+2起→T+3", {"fallback_day": 3}),
		("SL6 T+2→T+6", {"stop_pct": 6}),
		("SL10 T+2→T+6", {"stop_pct": 10}),
	]

	for band in ("F4-6", "F7-8", "F9-11"):
		sub = sig[sig["band"] == band]
		print("\n" + "=" * 60)
		print("%s  可买信号行 %d" % (band, len(sub)))
		print("=" * 60)
		for name, kw in rules:
			b = backtest_sub(sub, g0, cd, **kw)
			if not b or b["n"] < 5:
				continue
			print(
				"%-22s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%6.1f%% med=%6.2f%% worst=%6.2f%%"
				% (name, b["n"], b["wr"], b["avg"], b["sum"], b["med"], b["worst"])
			)

	# 基准规则下按实际卖出日偏移分布
	print("\n--- 基准规则：卖出日相对 T 的偏移（成交笔）---")
	for band in ("F4-6", "F7-8"):
		sub = sig[sig["band"] == band]
		rows = []
		for _, r in sub.iterrows():
			t = simulate_trade(r, g0, cd)
			if t:
				rows.append(t)
		if not rows:
			continue
		d = pd.DataFrame(rows)
		# parse T+n from reason
		def sell_off(reason: str) -> str:
			if "G0" in reason:
				return "G0"
			if "T+2" in reason:
				return "T+2"
			if "T+3" in reason:
				return "T+3"
			if "T+4" in reason:
				return "T+4"
			if "T+5" in reason:
				return "T+5"
			if "T+6" in reason:
				return "T+6兜底"
			return "other"

		d["off"] = d["卖出原因"].map(sell_off)
		d["win"] = d["收益率%"].astype(float) > 0
		print(band)
		for off, g in d.groupby("off"):
			r = g["收益率%"].astype(float)
			print(
				"  %-8s n=%3d wr=%4.0f%% avg=%6.2f%%"
				% (off, len(g), 100 * (r > 0).mean(), r.mean())
			)


if __name__ == "__main__":
	main()
