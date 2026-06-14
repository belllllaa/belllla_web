# -*- coding: utf-8 -*-
"""F4-6 不买；仅 F7-8：T+1 开盘 / T+2 开盘 / T+1 收盘 延后买入对比。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from _yidong_delayed_buy_scan import CSV, MAX_DATA_DAY, simulate_delayed  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	STOP_PCT,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
)

F78_MIN, F78_MAX = 7, 8

SCENARIOS = [
	("T+1开盘买", 1, "open"),
	("T+2开盘买", 2, "open"),
	("T+1收盘买", 1, "close"),
]

ANCHORS = [
	("日历锚(T+2止损/T+6兜底)", "calendar", 6),
	("买入锚(+2止损/+6兜底)", "from_buy", 6),
]


def _filter_f78(sig: pd.DataFrame) -> pd.DataFrame:
	m = sig["F"].between(F78_MIN, F78_MAX)
	out = sig.loc[m].copy()
	print("全量可买信号 %d → 剔除 F4-6 及其他 → F7-8 信号 %d" % (len(sig), len(out)))
	return out


def _summarize(rows: list[dict]) -> dict:
	if not rows:
		return {}
	r = pd.Series([x["收益率%"] for x in rows])
	reasons = Counter(x.get("卖出原因", "") for x in rows)
	stop_n = sum(1 for k in reasons if k.startswith("止损"))
	g0_n = reasons.get("G0强平", 0)
	fb_n = sum(v for k, v in reasons.items() if k.startswith("未触发"))
	wins = r[r > 0]
	losses = r[r <= 0]
	return {
		"n": len(r),
		"wr": 100 * (r > 0).mean(),
		"avg": r.mean(),
		"sum": r.sum(),
		"median": r.median(),
		"avg_win": wins.mean() if len(wins) else 0.0,
		"avg_loss": losses.mean() if len(losses) else 0.0,
		"stop_n": stop_n,
		"g0_n": g0_n,
		"fallback_n": fb_n,
	}


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)
	sub = _filter_f78(sig)

	print("\n规则：F∈[7,8]；F4-6 不买；8%%止损；G=0强平；涨跌停过滤同核心")
	print("=" * 72)

	for anchor_name, anchor, fb in ANCHORS:
		print("\n【%s】" % anchor_name)
		print("-" * 72)
		print(
			"%-12s %5s %7s %8s %8s %7s %5s %5s %5s"
			% ("买入", "笔数", "胜率", "均收益", "合计%", "中位数", "止损", "G0", "兜底")
		)
		for label, buy_off, kind in SCENARIOS:
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
			s = _summarize(rows)
			if not s:
				print("%-12s 样本不足" % label)
				continue
			print(
				"%-12s %5d %6.1f%% %7.2f%% %8.1f%% %6.2f%% %5d %5d %5d"
				% (
					label,
					s["n"],
					s["wr"],
					s["avg"],
					s["sum"],
					s["median"],
					s["stop_n"],
					s["g0_n"],
					s["fallback_n"],
				)
			)
			print(
				"             盈利笔均 %+.2f%% | 亏损笔均 %+.2f%%"
				% (s["avg_win"], s["avg_loss"])
			)

	print("\n" + "=" * 72)
	print("说明：合计%%=各笔收益率相加（与此前扫描一致，便于横向比）。")


if __name__ == "__main__":
	main()
