# -*- coding: utf-8 -*-
"""固定持满 + 可选止盈(日内最高价触达) 对比扫描。"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	MAX_DATA_DAY,
	MAX_SELL_DAY,
	STOP_MIN_DAY,
	STOP_PCT,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	f_trade_rule,
	load_yidong,
	planned_buy_calendar,
	run_backtest,
	trade_date_at_offset,
	_day_col,
	_buy_px,
	_pack_trade,
	_try_g0_sell,
	_try_plate_close_sell,
	is_buy_day_blocked,
	G0_DEFER_BUY_DAY_TO_NEXT_CLOSE,
	FIXED_RULE_SPECS,
)
from yidong_regulation_backtest_core import _num  # noqa: E402

FIXED_F = {7, 10, 8, 30, 9, 27, 28}


def _tp_quote(
	row: pd.Series,
	off: int,
	code: str,
	t_day: str,
	code_dates: dict[str, list[str]],
	buy_px: float,
	tp_pct: float,
) -> tuple[float, str, str] | None:
	hi = _num(row.get(_day_col(off, "最高")))
	if hi is None:
		return None
	target = buy_px * (1.0 + tp_pct / 100.0)
	if hi < target - 1e-9:
		return None
	td = trade_date_at_offset(code, t_day, off, code_dates) or ("T+%d" % off)
	return target, td, "止盈%.0f%%(T+%d触达)" % (tp_pct, off)


def _trail_tp_step(
	row: pd.Series,
	off: int,
	code: str,
	t_day: str,
	code_dates: dict[str, list[str]],
	buy_px: float,
	armed: bool,
	arm_pct: float,
	exit_pct: float,
) -> tuple[bool, tuple[float, str, str] | None]:
	"""先触达 arm_pct 激活；已激活且最低价触及 exit 价则按 exit 价卖。"""
	hi = _num(row.get(_day_col(off, "最高")))
	lo = _num(row.get(_day_col(off, "最低")))
	if hi is not None and hi >= buy_px * (1.0 + arm_pct / 100.0) - 1e-9:
		armed = True
	if armed and lo is not None:
		exit_px = buy_px * (1.0 + exit_pct / 100.0)
		if lo <= exit_px + 1e-9:
			td = trade_date_at_offset(code, t_day, off, code_dates) or ("T+%d" % off)
			reason = "回落止盈%.0f触%.0f(T+%d)" % (arm_pct, exit_pct, off)
			return armed, (exit_px, td, reason)
	return armed, None


def _simulate_fixed_sell_tp(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
	*,
	buy_off: int,
	buy_kind: str,
	sell_off: int,
	rule_id: str,
	tp_pct: float | None = None,
	stop_pct: float | None = None,
	trail_arm_pct: float | None = None,
	trail_exit_pct: float | None = None,
) -> dict | None:
	if is_buy_day_blocked(row, buy_off, buy_kind):
		return None
	buy_px = _buy_px(row, buy_off, buy_kind)
	if buy_px is None or sell_off > MAX_DATA_DAY:
		return None

	code = str(row["股票代码"])
	t_day = str(row["T日"])
	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []
	stop_line = (
		buy_px * (1.0 - stop_pct / 100.0) if stop_pct is not None else None
	)
	first_stop_off = buy_off + STOP_MIN_DAY
	stop_active = False
	trail_armed = False

	loop_start = buy_off if G0_DEFER_BUY_DAY_TO_NEXT_CLOSE else buy_off + 1
	for off in range(loop_start, MAX_DATA_DAY + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			break
		hold_lows.append(lo)

		res = _try_g0_sell(
			row, off, code, t_day, code_dates, g_zero, buy_off=buy_off,
		)
		if res:
			sell_px, sell_day, reason = res
			break

		if trail_arm_pct is not None and trail_exit_pct is not None:
			trail_armed, res = _trail_tp_step(
				row, off, code, t_day, code_dates, buy_px,
				trail_armed, trail_arm_pct, trail_exit_pct,
			)
			if res:
				sell_px, sell_day, reason = res
				break
		elif tp_pct is not None:
			res = _tp_quote(row, off, code, t_day, code_dates, buy_px, tp_pct)
			if res:
				sell_px, sell_day, reason = res
				break

		if stop_line is not None and off >= first_stop_off and lo is not None:
			if lo <= stop_line + 1e-9:
				stop_active = True
		if stop_active:
			res = _try_plate_close_sell(
				row, off, code, t_day, code_dates,
				"止损%.0f%%(T+%d收盘)" % (stop_pct, off),
			)
			if res:
				sell_px, sell_day, reason = res
				break
			continue

		if off == sell_off:
			hold_n = sell_off - buy_off
			res = _try_plate_close_sell(
				row, sell_off, code, t_day, code_dates,
				"持%d天T+%d收盘" % (hold_n, sell_off),
			)
			if res:
				sell_px, sell_day, reason = res
				break

	if sell_px is None:
		return None

	buy_cal = (
		trade_date_at_offset(code, t_day, buy_off, code_dates)
		if buy_off > 0
		else t_day
	)
	rid = rule_id
	if trail_arm_pct is not None and trail_exit_pct is not None:
		rid = "%s_trail%.0f_%.0f" % (rule_id, trail_arm_pct, trail_exit_pct)
	elif tp_pct is not None:
		rid = "%s_tp%.0f" % (rule_id, tp_pct)
	if stop_pct is not None:
		rid = "%s_sl%.0f" % (rid, stop_pct)
	return _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		buy_cal=buy_cal or t_day,
		reason=reason,
		rule_id=rid,
		hold_lows=hold_lows,
		t_day=t_day,
	)


def _simulate_default_tp(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
	*,
	tp_pct: float | None = None,
	stop_pct: float | None = STOP_PCT,
	trail_arm_pct: float | None = None,
	trail_exit_pct: float | None = None,
) -> dict | None:
	if is_buy_day_blocked(row, 0, "open"):
		return None
	buy_px = _num(row.get("T日_开盘"))
	if buy_px is None:
		return None
	code = str(row["股票代码"])
	t_day = str(row["T日"])
	sl = stop_pct if stop_pct is not None else STOP_PCT
	stop_line = buy_px * (1.0 - sl / 100.0)

	sell_px: float | None = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []
	stop_active = False
	last_off = min(MAX_SELL_DAY, MAX_DATA_DAY)
	buy_off = 0
	trail_armed = False

	if G0_DEFER_BUY_DAY_TO_NEXT_CLOSE:
		res = _try_g0_sell(
			row, 0, code, t_day, code_dates, g_zero, buy_off=buy_off,
		)
		if res:
			sell_px, sell_day, reason = res
			lo0 = _num(row.get(_day_col(0, "最低")))
			if lo0 is not None:
				hold_lows.append(lo0)

	for off in range(1, MAX_DATA_DAY + 1):
		if sell_px is not None:
			break
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			break
		hold_lows.append(lo)

		res = _try_g0_sell(
			row, off, code, t_day, code_dates, g_zero, buy_off=buy_off,
		)
		if res:
			sell_px, sell_day, reason = res
			break

		if trail_arm_pct is not None and trail_exit_pct is not None:
			trail_armed, res = _trail_tp_step(
				row, off, code, t_day, code_dates, buy_px,
				trail_armed, trail_arm_pct, trail_exit_pct,
			)
			if res:
				sell_px, sell_day, reason = res
				break
		elif tp_pct is not None:
			res = _tp_quote(row, off, code, t_day, code_dates, buy_px, tp_pct)
			if res:
				sell_px, sell_day, reason = res
				break

		if off >= STOP_MIN_DAY and lo is not None and lo <= stop_line + 1e-9:
			stop_active = True

		if stop_active:
			res = _try_plate_close_sell(
				row, off, code, t_day, code_dates,
				"止损%.0f%%(T+%d收盘)" % (sl, off),
			)
			if res:
				sell_px, sell_day, reason = res
				break
			continue

		if off == last_off:
			res = _try_plate_close_sell(
				row, last_off, code, t_day, code_dates,
				"未触发止损 T+%d收盘" % last_off,
			)
			if res:
				sell_px, sell_day, reason = res
				break

	if sell_px is None:
		return None

	if trail_arm_pct is not None and trail_exit_pct is not None:
		rid = "default_trail%.0f_%.0f" % (trail_arm_pct, trail_exit_pct)
	elif tp_pct is not None:
		rid = "default_tp%.0f" % tp_pct
	else:
		rid = "default"
	return _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		buy_cal=t_day,
		reason=reason,
		rule_id=rid,
		hold_lows=hold_lows,
		t_day=t_day,
	)


def simulate_trade_tp(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
	*,
	tp_pct: float | None = None,
	fixed_stop_pct: float | None = None,
	trail_arm_pct: float | None = None,
	trail_exit_pct: float | None = None,
) -> dict | None:
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	if rule in FIXED_RULE_SPECS:
		boff, kind, sell_off = FIXED_RULE_SPECS[rule]
		return _simulate_fixed_sell_tp(
			row, g_zero, code_dates,
			buy_off=boff, buy_kind=kind, sell_off=sell_off,
			rule_id=rule,
			tp_pct=tp_pct,
			stop_pct=fixed_stop_pct,
			trail_arm_pct=trail_arm_pct,
			trail_exit_pct=trail_exit_pct,
		)
	return _simulate_default_tp(
		row, g_zero, code_dates,
		tp_pct=tp_pct,
		stop_pct=STOP_PCT,
		trail_arm_pct=trail_arm_pct,
		trail_exit_pct=trail_exit_pct,
	)


def run_tp_backtest(
	df: pd.DataFrame,
	tp_pct: float | None = None,
	*,
	fixed_stop_pct: float | None = None,
	trail_arm_pct: float | None = None,
	trail_exit_pct: float | None = None,
	label: str | None = None,
) -> tuple[pd.DataFrame, dict]:
	g_zero = build_g_zero(df)
	code_dates = build_code_trade_dates(df)
	signals = collect_signals(df, skip_limit=True)
	trades: list[dict] = []
	fail = defaultdict(int)

	plan_rows: list[tuple[str, int, pd.Series]] = []
	for idx, row in signals.iterrows():
		pb = planned_buy_calendar(row, code_dates)
		if not pb:
			fail["no_buy_date"] += 1
			continue
		plan_rows.append((pb, int(idx), row))
	plan_rows.sort(key=lambda x: (x[0], x[1]))

	for _, _, row in plan_rows:
		t = simulate_trade_tp(
			row, g_zero, code_dates,
			tp_pct=tp_pct,
			fixed_stop_pct=fixed_stop_pct,
			trail_arm_pct=trail_arm_pct,
			trail_exit_pct=trail_exit_pct,
		)
		if t is None:
			fail["sim_fail"] += 1
			continue
		trades.append(t)

	tdf = pd.DataFrame(trades)
	if tdf.empty:
		return tdf, {"成交笔数": 0}

	rets = tdf["收益率%"].astype(float)
	if label is None:
		if trail_arm_pct is not None and trail_exit_pct is not None:
			label = "回落止盈%.0f触%.0f" % (trail_arm_pct, trail_exit_pct)
		elif tp_pct is None:
			label = "固定持满"
		else:
			label = "止盈%.0f%%" % tp_pct
		if fixed_stop_pct is not None:
			label += "+止损%.0f%%" % fixed_stop_pct
	tp_hits = int(tdf["卖出原因"].astype(str).str.contains("止盈|回落", regex=True, na=False).sum())
	sl_hits = int(tdf["卖出原因"].astype(str).str.contains("止损", na=False).sum())

	summary = {
		"标签": label,
		"止盈_pct": tp_pct,
		"止损_pct": fixed_stop_pct,
		"成交笔数": len(tdf),
		"胜率_pct": round((rets > 0).mean() * 100, 2),
		"单笔平均收益_pct": round(float(rets.mean()), 4),
		"合计收益金额_元": round(float(tdf["收益金额"].sum()), 2),
		"止盈触发笔数": tp_hits,
		"止损触发笔数": sl_hits,
		"失败": dict(fail),
	}
	return tdf, summary


def print_f_bucket(tdf: pd.DataFrame, label: str) -> None:
	sub = tdf[tdf["监控日涨幅偏离值F"].isin(FIXED_F)]
	if sub.empty:
		return
	rets = sub["收益率%"].astype(float)
	tp_n = int(sub["卖出原因"].astype(str).str.contains("止盈", na=False).sum())
	print(
		"  六档 n=%d win=%.1f%% mean=%.2f%% sum=%.0f 止盈触发=%d"
		% (len(sub), (rets > 0).mean() * 100, rets.mean(), sub["收益金额"].sum(), tp_n)
	)


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	_, base_summ = run_backtest(df)

	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("止盈规则: 持仓期内任一日最高价触达买入价×(1+止盈%%)则按止盈价成交; G0/止损/持满照旧")
	print("\n--- 全量对比 ---")
	print(
		"固定持满: n=%d win=%.1f%% mean=%.2f%% sum=%.0f"
		% (
			base_summ["成交笔数"],
			base_summ["胜率_pct"],
			base_summ["单笔平均收益_pct"],
			base_summ["合计收益金额_元"],
		)
	)

	scenarios = [
		(12.0, None, "止盈12%"),
		(15.0, None, "止盈15%"),
		(15.0, STOP_PCT, "止盈15%+止损8%(六档加止损,其余原8%止损)"),
		(12.0, STOP_PCT, "止盈12%+止损8%(六档加止损,其余原8%止损)"),
		(18.0, None, "止盈18%"),
		(20.0, None, "止盈20%"),
	]
	for tp, sl, lbl in scenarios:
		tdf, summ = run_tp_backtest(df, tp, fixed_stop_pct=sl, label=lbl)
		print(
			"%s: n=%d win=%.1f%% mean=%.2f%% sum=%.0f 止盈=%d 止损=%d"
			% (
				summ["标签"],
				summ["成交笔数"],
				summ["胜率_pct"],
				summ["单笔平均收益_pct"],
				summ["合计收益金额_元"],
				summ["止盈触发笔数"],
				summ["止损触发笔数"],
			)
		)
		print_f_bucket(tdf, summ["标签"])
		delta = summ["合计收益金额_元"] - base_summ["合计收益金额_元"]
		print("  vs基准 金额差 %+.0f  均收益差 %+.2f%%" % (delta, summ["单笔平均收益_pct"] - base_summ["单笔平均收益_pct"]))


if __name__ == "__main__":
	main()
