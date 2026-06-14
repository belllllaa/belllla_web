# -*- coding: utf-8 -*-
"""F1/F2/F3：此前 SKIP_F 整键不买；本脚本忽略该阻断，单独回测各档买入时点。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from _yidong_delayed_buy_scan import simulate_delayed  # noqa: E402
from _yidong_f_single_buy_hold_scan import (  # noqa: E402
	ANCHORS,
	CSV,
	F456_BUYS,
	F789_BUYS,
	MIN_N,
	_stats,
	simulate_fixed_hold,
)
from yidong_regulation_backtest_core import (  # noqa: E402
	SKIP_F,
	build_code_trade_dates,
	build_g_zero,
	is_limit_skip_row,
	load_yidong,
)


def collect_f123_signals(df: pd.DataFrame, f: int, *, skip_limit: bool = True) -> pd.DataFrame:
	"""G=1、有 T 收盘；不应用 SKIP_F 整键阻断。"""
	mask = df["T日_收盘"].astype(str).str.strip().ne("") & df["G"].eq(1) & df["F"].eq(f)
	if skip_limit:
		mask &= ~df.apply(is_limit_skip_row, axis=1)
	return df.loc[mask].copy().reset_index(drop=True)


def scan_buy_times(sig: pd.DataFrame, g0, cd, f: int) -> None:
	sub = sig
	print("\n【F%d】信号 %d（已忽略 SKIP_F=%s 不买规则）" % (f, len(sub), sorted(SKIP_F)))
	if len(sub) < 3:
		print("  样本过少，仅作参考")
	if len(sub) == 0:
		return

	for anchor_name, anchor, fb in ANCHORS:
		print("  %s（8%%止损+G0）：" % anchor_name)
		print("    %-10s %5s %7s %8s %8s" % ("买入", "笔数", "胜率", "均收益", "合计%"))
		best = ("", -1e9)
		for label, buy_off, kind in F789_BUYS:
			rows = []
			for _, r in sub.iterrows():
				t = simulate_delayed(
					r,
					g0,
					cd,
					buy_off=buy_off,
					buy_kind=kind,
					anchor=anchor,
					fallback_off=fb,
				)
				if t:
					rows.append(t)
			s = _stats(rows) if rows else None
			if not s and len(rows) < MIN_N:
				print("    %-10s n=%3d (不足%d笔统计)" % (label, len(rows), MIN_N))
				continue
			if not s:
				s = {
					"n": len(rows),
					"wr": round(100 * sum(x["收益率%"] > 0 for x in rows) / len(rows), 1),
					"avg": round(sum(x["收益率%"] for x in rows) / len(rows), 2),
					"sum": round(sum(x["收益率%"] for x in rows), 1),
				}
			print(
				"    %-10s %5d %6.1f%% %7.2f%% %8.1f%%"
				% (label, s["n"], s["wr"], s["avg"], s["sum"])
			)
			if s["sum"] > best[1]:
				best = (label, s["sum"])
		if best[0]:
			print("    → 合计最优: %s (%.1f%%)" % best)

	# 短持 1~2 天（无止损，仅 G0）
	print("  短持1~2天（收盘卖，无8%%止损）：")
	for hold in (1, 2):
		print("    持有%d天：" % hold)
		best = ("", -1e9)
		for label, buy_off, kind in F456_BUYS:
			rows = []
			for _, r in sub.iterrows():
				t = simulate_fixed_hold(
					r,
					g0,
					cd,
					buy_off=buy_off,
					buy_kind=kind,
					hold_days=hold,
					check_g0=True,
				)
				if t:
					rows.append(t)
			if not rows:
				print("      %-10s 无样本" % label)
				continue
			r = pd.Series([x["收益率%"] for x in rows])
			print(
				"      %-10s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%%"
				% (label, len(r), 100 * (r > 0).mean(), r.mean(), r.sum())
			)
			if r.sum() > best[1]:
				best = (label, r.sum())
		if best[0]:
			print("      → 最优: %s (合计%.1f%%)" % best)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)

	print("=" * 78)
	print("F1 / F2 / F3 专项分析")
	print("说明：生产逻辑中 F∈{1,2,3,10,30} 会整键(T日+代码)阻断；此处仅看 F=1/2/3 且 G=1 的行")
	print("=" * 78)

	for f in (1, 2, 3):
		sig = collect_f123_signals(df, f)
		scan_buy_times(sig, g0, cd, f)

	# 与现行 collect_signals 对比：这些行是否曾进入回测
	from yidong_regulation_backtest_core import collect_signals  # noqa: E402

	all_sig = collect_signals(df)
	in_bt = all_sig["F"].isin([1, 2, 3]).sum()
	print("\n【对照】现行 collect_signals 中 F1/2/3 笔数: %d（应为 0）" % in_bt)


if __name__ == "__main__":
	main()
