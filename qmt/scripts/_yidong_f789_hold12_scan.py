# -*- coding: utf-8 -*-
"""F7/F8/F9：固定持有1~2天 vs 当前正式分F规则。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from _yidong_f_single_buy_hold_scan import (  # noqa: E402
	CSV,
	F789_BUYS,
	MIN_N,
	_stats,
	simulate_fixed_hold,
)
from yidong_regulation_backtest_core import (  # noqa: E402
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	simulate_trade,
)


def _summarize_rows(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	s = _stats(rows)
	if s:
		return s
	r = pd.Series([x["收益率%"] for x in rows])
	return {
		"n": len(r),
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

	print("=" * 76)
	print("F7-9 固定持有 1~2 天（收盘卖；持仓期 G=0 强平；无 8%% 止损）")
	print("=" * 76)

	for f in (7, 8, 9):
		sub = sig[sig["F"] == f]
		print("\n【F%d】可买信号 %d" % (f, len(sub)))
		for hold in (1, 2):
			print("  持有 %d 天：" % hold)
			best = ("", -1e9)
			for label, buy_off, kind in F789_BUYS:
				rows = []
				for _, r in sub.iterrows():
					t = simulate_fixed_hold(
						r, g0, cd, buy_off=buy_off, buy_kind=kind, hold_days=hold
					)
					if t:
						rows.append(t)
				s = _summarize_rows(rows)
				if not s:
					print("    %-10s 无样本" % label)
					continue
				print(
					"    %-10s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%% med=%6.2f%%"
					% (label, s["n"], s["wr"], s["avg"], s["sum"], s["med"])
				)
				if s["sum"] > best[1]:
					best = (label, s["sum"])
			if best[0]:
				print("    → 持有%d天最优: %s (合计%.1f%%)" % (hold, best[0], best[1]))

	print("\n" + "=" * 76)
	print("对照：当前正式规则（yidong_regulation_backtest_core.simulate_trade）")
	print("  F7=T+2开盘+买入锚 | F8-9=T+1开盘+买入锚 | 其他F=默认")
	print("-" * 76)
	for f in (7, 8, 9):
		sub = sig[sig["F"] == f]
		rows = [simulate_trade(r, g0, cd) for _, r in sub.iterrows()]
		rows = [x for x in rows if x]
		if not rows:
			print("F%d 无成交" % f)
			continue
		r = pd.Series([x["收益率%"] for x in rows])
		print(
			"F%d  n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%% med=%6.2f%%"
			% (f, len(r), 100 * (r > 0).mean(), r.mean(), r.sum(), r.median())
		)

	# F7-9 合并
	print("\n【F7-9 合并】")
	for mode in ("hold1_best", "hold2_best", "current"):
		if mode == "current":
			rows = []
			for f in (7, 8, 9):
				sub = sig[sig["F"] == f]
				for _, r in sub.iterrows():
					t = simulate_trade(r, g0, cd)
					if t:
						rows.append(t)
			label = "当前正式规则"
		else:
			hold = 1 if mode == "hold1_best" else 2
			# 各F用该档持有N天时的最优买点
			best_buy = {7: (2, "open"), 8: (1, "open"), 9: (1, "open")}  # from prior scans
			if hold == 2:
				best_buy = {7: (2, "open"), 8: (1, "open"), 9: (1, "open")}
			rows = []
			for f in (7, 8, 9):
				sub = sig[sig["F"] == f]
				bo, bk = best_buy[f]
				for _, r in sub.iterrows():
					t = simulate_fixed_hold(
						r, g0, cd, buy_off=bo, buy_kind=bk, hold_days=hold
					)
					if t:
						rows.append(t)
			label = "持有%d天(各F历史最优买点)" % hold
		r = pd.Series([x["收益率%"] for x in rows])
		print(
			"  %-28s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%%"
			% (label, len(r), 100 * (r > 0).mean(), r.mean(), r.sum())
		)


if __name__ == "__main__":
	main()
