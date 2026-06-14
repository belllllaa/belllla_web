# -*- coding: utf-8 -*-
"""F7/8/9：T收盘 vs T+1开盘 vs T+2开盘；F4/5/6：买入日 × 持有1~2天。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from _yidong_delayed_buy_scan import CSV, MAX_DATA_DAY, simulate_delayed  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	_day_col,
	_num,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	trade_date_at_offset,
)

F789_BUYS = [
	("T收盘", 0, "close"),
	("T+1开盘", 1, "open"),
	("T+2开盘", 2, "open"),
]

F456_BUYS = [
	("T收盘", 0, "close"),
	("T+1开盘", 1, "open"),
	("T+2开盘", 2, "open"),
]

ANCHORS = [
	("日历锚", "calendar", 6),
	("买入锚", "from_buy", 6),
]

MIN_N = 8


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
	}


def simulate_fixed_hold(
	row: pd.Series,
	g_zero: set,
	code_dates: dict,
	*,
	buy_off: int,
	buy_kind: str,
	hold_days: int,
	check_g0: bool = True,
) -> dict | None:
	if buy_kind == "open":
		buy_px = _num(row.get(_day_col(buy_off, "开盘")))
	else:
		buy_px = _num(row.get(_day_col(buy_off, "收盘")))
	if buy_px is None:
		return None

	sell_off = buy_off + hold_days
	if sell_off > MAX_DATA_DAY:
		return None

	code = str(row["股票代码"])
	t_day = str(row["T日"])
	sell_px = None
	reason = ""

	for off in range(buy_off + 1, sell_off + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		if c is None:
			return None
		if check_g0:
			td = trade_date_at_offset(code, t_day, off, code_dates)
			if td and (code, td) in g_zero:
				sell_px = c
				reason = "G0强平T+%d" % off
				break

	if sell_px is None:
		sell_px = _num(row.get(_day_col(sell_off, "收盘")))
		if sell_px is None:
			return None
		reason = "持有%d天T+%d收盘" % (hold_days, sell_off)

	ret = (sell_px / buy_px - 1.0) * 100.0
	return {"收益率%": ret, "卖出原因": reason}


def _filter_f(sig: pd.DataFrame, f: int) -> pd.DataFrame:
	return sig.loc[sig["F"] == f].copy()


def scan_f789(sig: pd.DataFrame, g0, cd) -> None:
	print("\n" + "=" * 78)
	print("F7 / F8 / F9：T收盘 vs T+1开盘 vs T+2开盘（8%%止损 + G0；卖出见锚定）")
	print("=" * 78)
	for f in (7, 8, 9):
		sub = _filter_f(sig, f)
		print("\n【F%d】可买信号 %d" % (f, len(sub)))
		if len(sub) < MIN_N:
			print("  样本不足")
			continue
		for anchor_name, anchor, fb in ANCHORS:
			print("  %s：" % anchor_name)
			print("    %-10s %5s %7s %8s %8s" % ("买入", "笔数", "胜率", "均收益", "合计%"))
			best_sum = None
			best_label = ""
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
				s = _stats(rows)
				if not s:
					print("    %-10s 样本不足" % label)
					continue
				print(
					"    %-10s %5d %6.1f%% %7.2f%% %8.1f%%"
					% (label, s["n"], s["wr"], s["avg"], s["sum"])
				)
				if best_sum is None or s["sum"] > best_sum:
					best_sum = s["sum"]
					best_label = label
			if best_label:
				print("    → 合计最优: %s (%.1f%%)" % (best_label, best_sum))


def scan_f456_hold(sig: pd.DataFrame, g0, cd) -> None:
	print("\n" + "=" * 78)
	print("F4 / F5 / F6：买入日 × 持有1或2天（收盘卖；持仓期遇G=0则当日收盘强平）")
	print("=" * 78)
	for f in (4, 5, 6):
		sub = _filter_f(sig, f)
		print("\n【F%d】可买信号 %d" % (f, len(sub)))
		if len(sub) < MIN_N:
			print("  样本不足（MIN_N=%d）" % MIN_N)
			continue
		for hold in (1, 2):
			print("  持有 %d 个交易日（买入当日不计入持有）：" % hold)
			print("    %-10s %5s %7s %8s %8s %8s" % ("买入", "笔数", "胜率", "均收益", "合计%", "中位数"))
			best_sum = None
			best_label = ""
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
				s = _stats(rows)
				if not s:
					print("    %-10s 样本不足" % label)
					continue
				print(
					"    %-10s %5d %6.1f%% %7.2f%% %8.1f%% %7.2f%%"
					% (label, s["n"], s["wr"], s["avg"], s["sum"], s["med"])
				)
				if best_sum is None or s["sum"] > best_sum:
					best_sum = s["sum"]
					best_label = label
			if best_label:
				print("    → 持有%d天最优买入: %s (合计%.1f%%)" % (hold, best_label, best_sum))


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)
	print("可买信号共 %d（涨跌停过滤、SKIP_F整键阻断）" % len(sig))
	scan_f789(sig, g0, cd)
	scan_f456_hold(sig, g0, cd)


if __name__ == "__main__":
	main()
