# -*- coding: utf-8 -*-
"""持1天：开盘买 vs 收盘买（次日/当次尾盘卖）组合对比；G=0强平贯穿。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from yidong_regulation_backtest_core import (  # noqa: E402
	_day_col,
	_num,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	trade_date_at_offset,
)
from _yidong_delayed_buy_scan import CSV, MAX_DATA_DAY  # noqa: E402

# 持1天组合：(买点偏移, 买点类型, 卖点偏移) — 卖点均为收盘
HOLD1_COMBOS = [
	("开盘买→次日尾盘卖", "open", None),  # sell_off = buy_off + 1
	("收盘买→次日尾盘卖", "close", None),
]

F_GROUPS = [
	("F2-3", (2, 3), 1),
	("F4", (4, 4), 2),
	("F7", (7, 7), 2),
	("F8-9", (8, 9), 1),
	("F7-9", (7, 9), 1),  # 统一 T+1 买点对比
	("F7-9", (7, 9), 2),  # 统一 T+2 买点对比
]


def _limit_down_band(code6: str) -> tuple[float, float]:
	if code6.startswith(("60", "00")):
		return -10.0, -8.0
	if code6.startswith(("68", "30")):
		return -30.0, -15.0
	return -10.0, -8.0


def _day_pct(row: pd.Series, off: int) -> float | None:
	if off == 0:
		from yidong_regulation_backtest_core import _day_pct_vs_prev

		return _day_pct_vs_prev(row, 0)
	prev = _num(row.get(_day_col(off - 1, "收盘")))
	cur = _num(row.get(_day_col(off, "收盘")))
	if prev and cur and prev > 0:
		return (cur / prev - 1.0) * 100.0
	return None


def is_buy_blocked_band(row: pd.Series, buy_off: int) -> bool:
	code = str(row["股票代码"]).zfill(6)
	floor, ceil = _limit_down_band(code)
	pct = _day_pct(row, buy_off)
	if pct is None:
		return False
	return pct <= ceil + 1e-6 and pct >= floor - 1e-6


def sim_hold1(
	row: pd.Series,
	g0: set,
	cd: dict,
	*,
	buy_off: int,
	buy_kind: str,
) -> dict | None:
	if is_buy_blocked_band(row, buy_off):
		return None
	if buy_kind == "open":
		buy_px = _num(row.get(_day_col(buy_off, "开盘")))
	else:
		buy_px = _num(row.get(_day_col(buy_off, "收盘")))
	if buy_px is None:
		return None
	sell_off = buy_off + 1
	if sell_off > MAX_DATA_DAY:
		return None

	code = str(row["股票代码"])
	t_day = str(row["T日"])
	sell_px = None
	for off in range(buy_off + 1, sell_off + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		if c is None:
			return None
		td = trade_date_at_offset(code, t_day, off, cd)
		if td and (code, td) in g0:
			sell_px = c
			break
	if sell_px is None:
		sell_px = _num(row.get(_day_col(sell_off, "收盘")))
		if sell_px is None:
			return None
	return {"收益率%": (sell_px / buy_px - 1.0) * 100.0}


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)

	print("=" * 78)
	print("持1天组合对比 | G=0持仓期强平 | 买入日跌幅带内不买(60/00:-8~-10%, 68/30:-15~-30%)")
	print("=" * 78)

	for gname, (flo, fhi), base_off in F_GROUPS:
		sub = sig[sig["F"].between(flo, fhi)]
		print("\n【%s】信号 %d | 基准买点 T+%d" % (gname, len(sub), base_off))
		best = ("", -1e9, 0.0)
		for label_suffix, kind, _ in HOLD1_COMBOS:
			label = "T+%d%s" % (base_off, label_suffix)
			rows = []
			for _, r in sub.iterrows():
				t = sim_hold1(r, g0, cd, buy_off=base_off, buy_kind=kind)
				if t:
					rows.append(t)
			if not rows:
				print("  %-22s 无样本" % label)
				continue
			s = pd.Series([x["收益率%"] for x in rows])
			print(
				"  %-22s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%% med=%6.2f%%"
				% (label, len(s), 100 * (s > 0).mean(), s.mean(), s.sum(), s.median())
			)
			if s.sum() > best[1]:
				best = (label, s.sum(), 100 * (s > 0).mean())
		if best[0]:
			print("  → 最优: %s (合计%.1f%%, 胜率%.1f%%)" % (best[0], best[1], best[2]))

	print("\n" + "=" * 78)
	print("说明：「开盘买→次日尾盘卖」= 买点日开盘买，持1个交易日后在下一日收盘卖")
	print("      「收盘买→次日尾盘卖」= 买点日收盘买，下一日收盘卖（非当日冲卖）")


if __name__ == "__main__":
	main()
