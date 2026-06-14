# -*- coding: utf-8 -*-
"""F28 / F29：买入日 × 持有1~2天（现行涨跌幅带 + 跌停顺延次日卖 + G0）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	simulate_trade,
	_simulate_fixed_sell,
)

CSV = Path(YIDONG_REGULATION_STOCKS_CSV)

BUYS = [
	("T收盘", 0, "close"),
	("T+1开盘", 1, "open"),
	("T+2开盘", 2, "open"),
	("T+1收盘", 1, "close"),
]

MIN_N = 5


def _stats(rows: list[dict]) -> dict | None:
	if len(rows) < MIN_N:
		return None
	r = pd.Series([x["收益率%"] for x in rows])
	return {
		"n": len(r),
		"wr": round(100 * (r > 0).mean(), 1),
		"avg": round(r.mean(), 2),
		"sum": round(r.sum(), 1),
		"med": round(r.median(), 2),
		"pnl": round(sum(x.get("收益金额", 0) for x in rows), 0),
	}


def _filter_f(sig: pd.DataFrame, f: int) -> pd.DataFrame:
	return sig.loc[sig["F"] == f].copy()


def scan_hold(sig: pd.DataFrame, g0, cd, f: int) -> None:
	sub = _filter_f(sig, f)
	print("\n【F%d】可买信号 %d（G=1、SKIP_F整键、T日涨幅带过滤后）" % (f, len(sub)))
	if len(sub) < MIN_N:
		print("  样本不足")
		return

	for hold in (1, 2):
		print("\n  持有 %d 个交易日（买入当日不计；计划日收盘卖，跌停顺延次日；持仓期 G0 强平）：" % hold)
		print("    %-12s %5s %7s %8s %8s %8s %10s" % ("买入", "笔数", "胜率", "均收益", "合计%", "中位数", "收益金额"))
		best_sum = None
		best_label = ""
		for label, buy_off, kind in BUYS:
			rows = []
			sell_off = buy_off + hold
			for _, r in sub.iterrows():
				t = _simulate_fixed_sell(
					r,
					g0,
					cd,
					buy_off=buy_off,
					buy_kind=kind,
					sell_off=sell_off,
					rule_id="hold%d" % hold,
				)
				if t:
					rows.append(t)
			s = _stats(rows)
			if not s:
				print("    %-12s 样本不足(n<%d)" % (label, MIN_N))
				continue
			print(
				"    %-12s %5d %6.1f%% %7.2f%% %8.1f%% %7.2f%% %10.0f"
				% (label, s["n"], s["wr"], s["avg"], s["sum"], s["med"], s["pnl"])
			)
			if best_sum is None or s["sum"] > best_sum:
				best_sum = s["sum"]
				best_label = label
		if best_label:
			print("    → 持有%d天合计最优: %s (%.1f%%)" % (hold, best_label, best_sum))


def scan_default(sig: pd.DataFrame, g0, cd, f: int) -> None:
	sub = _filter_f(sig, f)
	rows = []
	for _, r in sub.iterrows():
		t = simulate_trade(r, g0, cd)
		if t:
			rows.append(t)
	s = _stats(rows)
	print("\n  【对照】现行默认规则（T收盘买 + 日历锚8%%止损T+2起 + T+6兜底 + 流动性）：")
	if not s:
		print("    样本不足")
		return
	print(
		"    成交 %d | 胜率 %.1f%% | 均收益 %.2f%% | 合计 %.1f%% | 收益金额 %.0f"
		% (s["n"], s["wr"], s["avg"], s["sum"], s["pnl"])
	)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)
	print("=" * 88)
	print("F28 / F29 持有1~2天扫描 | 数据源: %s" % CSV.name)
	print("可买信号全量 %d | 买入: 涨幅带过滤(收盘买看收盘/开盘买看开盘) | 卖出: 跌停顺延次日" % len(sig))
	print("=" * 88)

	for f in (28, 29):
		scan_hold(sig, g0, cd, f)
		scan_default(sig, g0, cd, f)

	# F28+29 合并
	sub = sig.loc[sig["F"].isin([28, 29])].copy()
	print("\n" + "=" * 88)
	print("【F28+29 合并】信号 %d" % len(sub))
	for hold in (1, 2):
		print("\n  持有 %d 天：" % hold)
		print("    %-12s %5s %7s %8s %8s" % ("买入", "笔数", "胜率", "均收益", "合计%"))
		for label, buy_off, kind in BUYS:
			rows = []
			for _, r in sub.iterrows():
				t = _simulate_fixed_sell(
					r,
					g0,
					cd,
					buy_off=buy_off,
					buy_kind=kind,
					sell_off=buy_off + hold,
					rule_id="hold%d" % hold,
				)
				if t:
					rows.append(t)
			s = _stats(rows)
			if s:
				print(
					"    %-12s %5d %6.1f%% %7.2f%% %8.1f%%"
					% (label, s["n"], s["wr"], s["avg"], s["sum"])
				)


if __name__ == "__main__":
	main()
