# -*- coding: utf-8 -*-
"""F8/9/28/29 旧规则 vs 持2天新规则：分档与全量对比。"""
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


def f_trade_rule_old(f_val):
	if pd.isna(f_val):
		return "default"
	f = int(f_val)
	if f in (1, 5, 10, 30):
		return None
	if f in (2, 3):
		return "fix_t1o_t2c"
	if f == 4:
		return "fix_t2o_t3c"
	if f == 6:
		return "fix_t0c_t1c"
	if f == 7:
		return "fix_t2o_t3c"
	if f in (8, 9):
		return "fix_t1o_t2c"
	return "default"


def simulate_trade_old(row, g0, cd):
	rule = f_trade_rule_old(row.get("F"))
	if rule is None:
		return None
	if rule == "fix_t1o_t2c":
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=2, rule_id=rule
		)
	if rule in ("fix_t2o_t3c",):
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=2, buy_kind="open", sell_off=3, rule_id=rule
		)
	if rule == "fix_t0c_t1c":
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=0, buy_kind="close", sell_off=1, rule_id=rule
		)
	# F28/29 old = default (import simulate_trade's default path - use simulate_trade with patched f)
	# only for 28/29 we need default; for 8/9 already handled
	from yidong_regulation_backtest_core import simulate_trade as sim_new

	f = int(row["F"]) if pd.notna(row.get("F")) else -1
	if f in (28, 29):
		# inline default same as core
		return _simulate_default(row, g0, cd)
	return sim_new(row, g0, cd)


def _simulate_default(row, g0, cd):
	"""F28/29 旧规则：T收盘 + 止损 + T+6。"""
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


def _summ(tdf: pd.DataFrame, label: str) -> None:
	if tdf.empty:
		print("[%s] 无成交" % label)
		return
	r = tdf["收益率%"].astype(float)
	print(
		"[%s] %d笔 胜率%.1f%% 均%.2f%% 合计线性%.1f%% 收益金额%.0f"
		% (label, len(tdf), 100 * (r > 0).mean(), r.mean(), r.sum(), tdf["收益金额"].sum())
	)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)

	old_rows, new_rows = [], []
	for _, row in sig.iterrows():
		f = int(row["F"]) if pd.notna(row["F"]) else -1
		if f not in TARGET:
			continue
		o = simulate_trade_old(row, g0, cd)
		n = simulate_trade(row, g0, cd)
		if o:
			old_rows.append(o)
		if n:
			new_rows.append(n)

	old_t = pd.DataFrame(old_rows)
	new_t = pd.DataFrame(new_rows)

	print("=" * 80)
	print("F8 / F9 / F28 / F29 旧规则 vs 持2天新规则（扫描口径：G0+流动性）")
	print("=" * 80)
	_summ(old_t, "四档合计-旧")
	_summ(new_t, "四档合计-新")
	print("  差额(新-旧) 收益金额: %.0f" % (new_t["收益金额"].sum() - old_t["收益金额"].sum()))

	for f in TARGET:
		print("\n--- F%d ---" % f)
		o = old_t[old_t["监控日涨幅偏离值F"] == f] if not old_t.empty else old_t
		n = new_t[new_t["监控日涨幅偏离值F"] == f] if not new_t.empty else new_t
		_summ(o, "旧")
		_summ(n, "新")
		if not o.empty and not n.empty:
			print("  差额金额: %.0f" % (n["收益金额"].sum() - o["收益金额"].sum()))

	print("\n" + "=" * 80)
	print("全量回测（新规则已写入 core）")
	print("=" * 80)
	tdf, s = run_backtest(df)
	print("成交 %d | 胜率 %.2f%% | 合计金额 %.0f | 单笔均 %.2f%%" % (
		s["成交笔数"],
		s["胜率_pct"],
		s["合计收益金额_元"],
		s["单笔平均收益_pct"],
	))
	# 全量旧：仅替换四档，其余用新 simulate — 近似用 saved baseline
	print("\n对照（会话前全量基线，约）: 521笔 胜率58.2%% 合计金额约1194985")
	sub_new = tdf[tdf["监控日涨幅偏离值F"].isin(TARGET)]
	sub_other = tdf[~tdf["监控日涨幅偏离值F"].isin(TARGET)]
	print("\n新规则全量中 F8/9/28/29:")
	_summ(sub_new, "新全量四档")
	print("其余 F:")
	_summ(sub_other, "其余")


if __name__ == "__main__":
	main()
