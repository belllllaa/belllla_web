# -*- coding: utf-8 -*-
"""F8/9/28/29：原始规则 vs 四档持2天 vs 混合规则（F8/F28持2天，F9/F29默认）。"""
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
	run_backtest,
	simulate_trade,
	_simulate_fixed_sell,
)

CSV = Path(YIDONG_REGULATION_STOCKS_CSV)
TARGET = (8, 9, 28, 29)


def _summ(tdf: pd.DataFrame, label: str) -> dict | None:
	if tdf.empty:
		print("[%s] 无成交" % label)
		return None
	r = tdf["收益率%"].astype(float)
	d = {
		"n": len(tdf),
		"wr": round(100 * (r > 0).mean(), 1),
		"avg": round(r.mean(), 2),
		"sum_pct": round(r.sum(), 1),
		"pnl": round(float(tdf["收益金额"].sum()), 0),
	}
	print(
		"[%s] %d笔 胜率%.1f%% 均%.2f%% 合计线性%.1f%% 金额%.0f"
		% (label, d["n"], d["wr"], d["avg"], d["sum_pct"], d["pnl"])
	)
	return d


def simulate_old(row, g0, cd):
	f = int(row["F"]) if pd.notna(row.get("F")) else -1
	if f in (8, 9):
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=2, rule_id="old"
		)
	if f in (28, 29):
		return simulate_default(row, g0, cd)
	return simulate_trade(row, g0, cd)


def simulate_hold2_all(row, g0, cd):
	f = int(row["F"]) if pd.notna(row.get("F")) else -1
	if f == 8:
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=2, buy_kind="open", sell_off=4, rule_id="h2"
		)
	if f in (9, 28):
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=3, rule_id="h2"
		)
	if f == 29:
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=0, buy_kind="close", sell_off=2, rule_id="h2"
		)
	return simulate_trade(row, g0, cd)


def simulate_default(row, g0, cd):
	from yidong_regulation_backtest_core import (
		MAX_DATA_DAY,
		MAX_SELL_DAY,
		STOP_MIN_DAY,
		STOP_PCT,
		_day_col,
		_num,
		_pack_trade,
		_try_plate_close_sell,
		is_buy_day_blocked,
		trade_date_at_offset,
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
			res = _try_plate_close_sell(
				row, off, code, t_day, cd, "止损%d%%(T+%d收盘)" % (int(STOP_PCT), off)
			)
			if res:
				sell_px, sell_day, reason = res
				break
			continue
		if off == last_off:
			res = _try_plate_close_sell(
				row, last_off, code, t_day, cd, "未触发止损 T+%d收盘" % last_off
			)
			if res:
				sell_px, sell_day, reason = res
				break
	if sell_px is None:
		return None
	return _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		reason=reason,
		rule_id="default",
		hold_lows=hold_lows,
		t_day=t_day,
	)


def run_four(sig, g0, cd, sim_fn) -> pd.DataFrame:
	rows = []
	for _, row in sig.iterrows():
		f = int(row["F"]) if pd.notna(row["F"]) else -1
		if f not in TARGET:
			continue
		t = sim_fn(row, g0, cd)
		if t:
			rows.append(t)
	return pd.DataFrame(rows)


def run_full(sig, g0, cd, sim_fn_for_target, use_core_for_rest: bool) -> pd.DataFrame:
	rows = []
	for _, row in sig.iterrows():
		f = int(row["F"]) if pd.notna(row["F"]) else -1
		if f in TARGET:
			t = sim_fn_for_target(row, g0, cd)
		elif use_core_for_rest:
			t = simulate_trade(row, g0, cd)
		else:
			continue
		if t:
			rows.append(t)
	return pd.DataFrame(rows)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)

	old4 = run_four(sig, g0, cd, simulate_old)
	mid4 = run_four(sig, g0, cd, simulate_hold2_all)
	new4 = run_four(sig, g0, cd, simulate_trade)

	print("=" * 88)
	print("F8/9/28/29 三版对比（G0 + 流动性）")
	print("  原始: F8/9 T+1开持1天 | F28/29 T收+止损T+6")
	print("  持2天: F8 T+2开持2 | F9/28 T+1开持2 | F29 T收持2")
	print("  混合: F8 T+2开持2 | F28 T+1开持2 | F9/F29 T收+止损T+6")
	print("=" * 88)

	d0 = _summ(old4, "四档-原始")
	d1 = _summ(mid4, "四档-全持2天")
	d2 = _summ(new4, "四档-混合(新)")
	if d0 and d2:
		print("  混合 vs 原始 四档金额差额: %.0f" % (d2["pnl"] - d0["pnl"]))
	if d1 and d2:
		print("  混合 vs 全持2天 四档金额差额: %.0f" % (d2["pnl"] - d1["pnl"]))

	for f in TARGET:
		print("\n--- F%d ---" % f)
		for name, tdf in (
			("原始", old4),
			("全持2", mid4),
			("混合", new4),
		):
			sub = tdf[tdf["监控日涨幅偏离值F"] == f] if not tdf.empty else tdf
			_summ(sub, name)

	print("\n" + "=" * 88)
	print("全量回测（混合规则已写入 core）")
	tdf, s = run_backtest(df)
	_summ(tdf, "全量-混合")
	print("\n基线参考:")
	print("  原始四档前全量约: 521笔 119.5万")
	print("  四档全持2天全量: 525笔 126.0万")
	print(
		"  本次混合全量: %d笔 胜率%.1f%% 金额%.0f"
		% (s["成交笔数"], s["胜率_pct"], s["合计收益金额_元"])
	)


if __name__ == "__main__":
	main()
