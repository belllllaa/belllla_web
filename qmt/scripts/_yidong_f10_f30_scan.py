# -*- coding: utf-8 -*-
"""F10 / F30 单独扫描（绕过 SKIP_F 整键阻断，测各买入×持有1~3天 + 原规则）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	_num,
	build_code_trade_dates,
	build_g_zero,
	is_limit_skip_row,
	load_yidong,
	_simulate_fixed_sell,
)

CSV = Path(YIDONG_REGULATION_STOCKS_CSV)
TARGET = (10, 30)
HOLDS = (1, 2, 3)

BUYS = [
	("T收盘", 0, "close"),
	("T+1开盘", 1, "open"),
	("T+2开盘", 2, "open"),
	("T+1收盘", 1, "close"),
]

MIN_N = 8


def collect_f_rows(df: pd.DataFrame, f: int) -> pd.DataFrame:
	mask = (
		df["F"].eq(f)
		& df["G"].eq(1)
		& df["T日_收盘"].astype(str).str.strip().ne("")
		& ~df.apply(is_limit_skip_row, axis=1)
	)
	return df.loc[mask].copy().reset_index(drop=True)


def _stats(rows: list[dict]) -> dict | None:
	if len(rows) < MIN_N:
		return None
	r = pd.Series([x["收益率%"] for x in rows])
	return {
		"n": len(r),
		"wr": round(100 * (r > 0).mean(), 1),
		"avg": round(r.mean(), 2),
		"sum": round(r.sum(), 1),
		"pnl": round(sum(x.get("收益金额", 0) for x in rows), 0),
	}


def _run(sub: pd.DataFrame, g0, cd, buy_off: int, kind: str, hold: int) -> dict | None:
	rows = []
	for _, r in sub.iterrows():
		t = _simulate_fixed_sell(
			r, g0, cd,
			buy_off=buy_off, buy_kind=kind,
			sell_off=buy_off + hold,
			rule_id="h%d" % hold,
		)
		if t:
			rows.append(t)
	return _stats(rows)


def _simulate_default(row, g0, cd):
	from yidong_regulation_backtest_core import (
		MAX_DATA_DAY, MAX_SELL_DAY, STOP_MIN_DAY, STOP_PCT,
		_day_col, _pack_trade, _try_plate_close_sell,
		is_buy_day_blocked, trade_date_at_offset,
	)
	if is_buy_day_blocked(row, 0, "close"):
		return None
	buy_px = _num(row.get("T日_收盘"))
	if buy_px is None:
		return None
	code = str(row["股票代码"])
	t_day = str(row["T日"])
	stop_line = buy_px * (1.0 - STOP_PCT / 100.0)
	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows = []
	stop_active = False
	last_off = min(MAX_SELL_DAY, MAX_DATA_DAY)
	for off in range(1, MAX_DATA_DAY + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			break
		hold_lows.append(lo)
		td = trade_date_at_offset(code, t_day, off, cd)
		if td and (code, td) in g0:
			res = _try_plate_close_sell(row, off, code, t_day, cd, "G0强平")
			if res:
				sell_px, sell_day, reason = res
				break
			continue
		if off >= STOP_MIN_DAY and lo is not None and lo <= stop_line + 1e-9:
			stop_active = True
		if stop_active:
			res = _try_plate_close_sell(row, off, code, t_day, cd, "止损%d%%(T+%d收盘)" % (int(STOP_PCT), off))
			if res:
				sell_px, sell_day, reason = res
				break
			continue
		if off == last_off:
			res = _try_plate_close_sell(row, last_off, code, t_day, cd, "未触发止损 T+6收盘")
			if res:
				sell_px, sell_day, reason = res
				break
	if sell_px is None:
		return None
	return _pack_trade(
		row, buy_px=buy_px, sell_px=sell_px, sell_day=sell_day, buy_cal=t_day,
		reason=reason, rule_id="default", hold_lows=hold_lows, t_day=t_day,
	)


def scan_f(df: pd.DataFrame, g0, cd, f: int) -> None:
	sub = collect_f_rows(df, f)
	print("\n" + "=" * 88)
	print("【F%d】G=1 可测行 %d（未用 SKIP_F 整键阻断；已滤 T日涨幅带）" % (f, len(sub)))
	if len(sub) < MIN_N:
		print("  样本不足")
		return

	for hold in HOLDS:
		print("\n  ── 持有 %d 天 ──" % hold)
		print("    %-12s %5s %7s %8s %8s %10s" % ("买入", "笔数", "胜率", "均收益", "合计%", "金额"))
		best = None
		bl = ""
		for label, boff, kind in BUYS:
			s = _run(sub, g0, cd, boff, kind, hold)
			if not s:
				print("    %-12s 样本不足" % label)
				continue
			print("    %-12s %5d %6.1f%% %7.2f%% %8.1f%% %10.0f" % (
				label, s["n"], s["wr"], s["avg"], s["sum"], s["pnl"]))
			if best is None or s["sum"] > best:
				best, bl = s["sum"], label
		if bl:
			print("    ★ 持有%d天最优: %s (%.1f%%)" % (hold, bl, best))

	rows = []
	for _, r in sub.iterrows():
		t = _simulate_default(r, g0, cd)
		if t:
			rows.append(t)
	sd = _stats(rows)
	print("\n  【对照】原规则 T收+8%%止损+T+6")
	if sd:
		print("    %d笔 胜率%.1f%% 均%.2f%% 合计%.1f%% 金额%.0f" % (
			sd["n"], sd["wr"], sd["avg"], sd["sum"], sd["pnl"]))


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	print("F10/F30 扫描 | 现行 SKIP_F={1,5,10,30} 故正式回测几乎不买这两档")
	print("本脚本仅对 F=10/30 且 G=1 的行单独仿真（G0+流动性）")
	for f in TARGET:
		scan_f(df, g0, cd, f)


if __name__ == "__main__":
	main()
