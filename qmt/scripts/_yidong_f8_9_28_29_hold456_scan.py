# -*- coding: utf-8 -*-
"""F8/9/28/29：持有4~6天；并标注各档推荐买入时点。"""
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
TARGET = (8, 9, 28, 29)
HOLDS = (4, 5, 6)

# 各档持2天扫描后的推荐买入
BEST_BUY = {
	8: ("T+2开盘", 2, "open"),
	9: ("T+1开盘", 1, "open"),
	28: ("T+1开盘", 1, "open"),
	29: ("T收盘", 0, "close"),
}

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


def _run(sub: pd.DataFrame, g0, cd, buy_off: int, kind: str, hold: int) -> dict | None:
	rows = []
	for _, r in sub.iterrows():
		t = _simulate_fixed_sell(
			r,
			g0,
			cd,
			buy_off=buy_off,
			buy_kind=kind,
			sell_off=buy_off + hold,
			rule_id="h%d" % hold,
		)
		if t:
			rows.append(t)
	return _stats(rows)


def scan_f(sig: pd.DataFrame, g0, cd, f: int) -> None:
	sub = sig.loc[sig["F"] == f].copy()
	blabel, boff, bkind = BEST_BUY[f]
	print("\n【F%d】信号 %d | 推荐买入: %s" % (f, len(sub), blabel))

	print("\n  ── 推荐买入 × 持有4/5/6天 ──")
	print("    %6s %5s %7s %8s %8s %8s %10s" % ("持有", "笔数", "胜率", "均收益", "合计%", "中位数", "收益金额"))
	for hold in HOLDS:
		s = _run(sub, g0, cd, boff, bkind, hold)
		if not s:
			print("    持%d天 样本不足" % hold)
			continue
		print(
			"    %6d %5d %6.1f%% %7.2f%% %8.1f%% %7.2f%% %10.0f"
			% (hold, s["n"], s["wr"], s["avg"], s["sum"], s["med"], s["pnl"])
		)

	# 持2天 / 现行规则对照
	s2 = _run(sub, g0, cd, boff, bkind, 2)
	if s2:
		print("\n  对照 持2天(同买入): %d笔 胜率%.1f%% 均%.2f%% 合计%.1f%% 金额%.0f" % (
			s2["n"],
			s2["wr"],
			s2["avg"],
			s2["sum"],
			s2["pnl"],
		))
	if f == 29:
		rows = [simulate_trade(r, g0, cd) for _, r in sub.iterrows()]
		rows = [x for x in rows if x]
		sd = _stats(rows)
		if sd:
			print(
				"  对照 现行F29(T收+止损T+6): %d笔 胜率%.1f%% 均%.2f%% 合计%.1f%% 金额%.0f"
				% (sd["n"], sd["wr"], sd["avg"], sd["sum"], sd["pnl"])
			)

	print("\n  ── 全买入方式 × 持有4/5/6天（合计%）──")
	print("    %-12s %10s %10s %10s" % ("买入", "持4天", "持5天", "持6天"))
	for label, buy_off, kind in BUYS:
		cells = []
		for hold in HOLDS:
			s = _run(sub, g0, cd, buy_off, kind, hold)
			cells.append("%8.1f%%" % s["sum"] if s else "      —")
		print("    %-12s %s %s %s" % (label, cells[0], cells[1], cells[2]))


def print_matrix(sig: pd.DataFrame, g0, cd) -> None:
	print("\n" + "=" * 88)
	print("【总览】推荐买入 × 持有2/4/5/6天 合计收益%")
	print("=" * 88)
	print("  %4s %-10s %8s %8s %8s %8s" % ("F", "买入", "持2天", "持4天", "持5天", "持6天"))
	for f in TARGET:
		blabel, boff, bkind = BEST_BUY[f]
		vals = []
		for hold in (2, 4, 5, 6):
			sub = sig.loc[sig["F"] == f]
			s = _run(sub, g0, cd, boff, bkind, hold)
			vals.append(s["sum"] if s else None)
		print(
			"  %4d %-10s %8s %8s %8s %8s"
			% (
				f,
				blabel,
				("%.1f%%" % vals[0]) if vals[0] is not None else "—",
				("%.1f%%" % vals[1]) if vals[1] is not None else "—",
				("%.1f%%" % vals[2]) if vals[2] is not None else "—",
				("%.1f%%" % vals[3]) if vals[3] is not None else "—",
			)
		)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)
	print("F8/9/28/29 持有4~6天 | G0+流动性 | 可买信号 %d" % len(sig))
	for f in TARGET:
		scan_f(sig, g0, cd, f)
	print_matrix(sig, g0, cd)


if __name__ == "__main__":
	main()
