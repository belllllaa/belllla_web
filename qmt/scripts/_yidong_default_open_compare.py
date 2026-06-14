# -*- coding: utf-8 -*-
"""其余 F 档：T 收盘买 vs T 开盘买 对比（其余规则不变）。"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
if str(_SCRIPT) not in sys.path:
	sys.path.insert(0, str(_SCRIPT))

from dafengniu_benchmark_ref_trades import compute_extended_metrics  # noqa: E402
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	_day_col,
	_num,
	_pack_trade,
	_try_g0_sell,
	_try_plate_close_sell,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	f_trade_rule,
	FIXED_RULE_SPECS,
	G0_DEFER_BUY_DAY_TO_NEXT_CLOSE,
	is_buy_day_blocked,
	load_yidong,
	MAX_DATA_DAY,
	MAX_SELL_DAY,
	planned_buy_calendar,
	run_backtest,
	_simulate_fixed_sell,
	STOP_MIN_DAY,
	STOP_PCT,
)

RULE_DEFAULT_CLOSE = "T收买+日历锚8%止损T+2起T+6兜底"
RULE_DEFAULT_OPEN = "其余:T日开盘买+日历锚8%止损T+2起T+6兜底"


def simulate_trade_default_open(row, g_zero, code_dates, exit_mode="time"):
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	if rule in FIXED_RULE_SPECS:
		boff, kind, sell_off = FIXED_RULE_SPECS[rule]
		return _simulate_fixed_sell(
			row, g_zero, code_dates,
			buy_off=boff, buy_kind=kind, sell_off=sell_off,
			rule_id=rule, exit_mode=exit_mode,
		)
	if is_buy_day_blocked(row, 0, "open"):
		return None
	buy_px = _num(row.get("T日_开盘"))
	if buy_px is None:
		return None
	code = str(row["股票代码"])
	t_day = str(row["T日"])
	stop_line = buy_px * (1.0 - STOP_PCT / 100.0)
	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []
	stop_active = False
	last_off = min(MAX_SELL_DAY, MAX_DATA_DAY)
	buy_off = 0
	if G0_DEFER_BUY_DAY_TO_NEXT_CLOSE:
		res = _try_g0_sell(row, 0, code, t_day, code_dates, g_zero, buy_off=buy_off)
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
		res = _try_g0_sell(row, off, code, t_day, code_dates, g_zero, buy_off=buy_off)
		if res:
			sell_px, sell_day, reason = res
			break
		if off >= STOP_MIN_DAY and lo is not None and lo <= stop_line + 1e-9:
			stop_active = True
		if stop_active:
			base = "止损%d%%(T+%d收盘)" % (int(STOP_PCT), off)
			res = _try_plate_close_sell(row, off, code, t_day, code_dates, base)
			if res:
				sell_px, sell_day, reason = res
				break
			continue
		if off == last_off:
			base = "未触发止损 T+%d收盘" % last_off
			res = _try_plate_close_sell(row, last_off, code, t_day, code_dates, base)
			if res:
				sell_px, sell_day, reason = res
				break
	if sell_px is None:
		return None
	t = _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		buy_cal=t_day,
		reason=reason,
		rule_id="default",
		hold_lows=hold_lows,
		t_day=t_day,
	)
	if t:
		t["买卖规则"] = RULE_DEFAULT_OPEN
	return t


def run_custom(df, sim_fn):
	g_zero = build_g_zero(df)
	code_dates = build_code_trade_dates(df)
	signals = collect_signals(df, skip_limit=True)
	trades: list[dict] = []
	fail: dict[str, int] = defaultdict(int)
	plan_rows: list[tuple[str, int, pd.Series]] = []
	for idx, row in signals.iterrows():
		pb = planned_buy_calendar(row, code_dates)
		if not pb:
			fail["no_buy_date"] += 1
			continue
		plan_rows.append((pb, int(idx), row))
	plan_rows.sort(key=lambda x: (x[0], x[1]))
	for _, _, row in plan_rows:
		t = sim_fn(row, g_zero, code_dates)
		if t is None:
			fail["sim_fail"] += 1
			continue
		trades.append(t)
	return pd.DataFrame(trades), dict(fail)


def summarize(tdf: pd.DataFrame, label: str) -> None:
	if tdf.empty:
		print("%s: 无成交" % label)
		return
	rets = tdf["收益率%"].astype(float).values
	n = len(rets)
	wins = int((rets > 0).sum())
	buy_days = tdf["开仓日"].astype(str).tolist()
	ext = compute_extended_metrics(rets, buy_days)
	order = np.argsort(buy_days)
	nav = float(np.prod(1.0 + rets[order] / 100.0))
	print("--- %s ---" % label)
	print(
		"笔数 %d | 胜率 %.2f%% | 均收益 %.3f%% | 中位 %.3f%% | 合计金额 %.0f | 净值 %.4f"
		% (n, 100.0 * wins / n, float(rets.mean()), float(rets.median()),
		   float(tdf["收益金额"].sum()), nav)
	)
	if ext.get("最大回撤_链式净值_pct") is not None:
		print("最大回撤 %.2f%%" % ext["最大回撤_链式净值_pct"])


def by_rule(tdf: pd.DataFrame) -> pd.DataFrame:
	return (
		tdf.groupby("买卖规则")
		.agg(n=("收益率%", "size"), win=("收益率%", lambda s: (s > 0).mean() * 100),
		     mean=("收益率%", "mean"), med=("收益率%", "median"), amt=("收益金额", "sum"))
		.round(3)
		.sort_values("n", ascending=False)
	)


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	tdf_close, _ = run_backtest(df)
	tdf_open, fail_open = run_custom(df, simulate_trade_default_open)

	summarize(tdf_close, "基准: 其余=T收盘买")
	summarize(tdf_open, "对比: 其余=T开盘买")
	print("T开盘版 sim_fail:", fail_open.get("sim_fail", 0))

	sub_c = tdf_close[tdf_close["买卖规则"] == RULE_DEFAULT_CLOSE]
	sub_o = tdf_open[tdf_open["买卖规则"] == RULE_DEFAULT_OPEN]
	print()
	print("=== 其余组 T收盘 vs T开盘 ===")
	summarize(sub_c, "其余 T收盘")
	summarize(sub_o, "其余 T开盘")
	if len(sub_c) and len(sub_o):
		kc = sub_c.set_index(["开仓日", "股票代码"])["收益率%"]
		ko = sub_o.set_index(["开仓日", "股票代码"])["收益率%"]
		common = kc.index.intersection(ko.index)
		if len(common):
			diff = ko[common] - kc[common]
			print(
				"同键对比 %d 笔 | 开盘-收盘均差 %.3f%% | 开盘更好 %d | 收盘更好 %d"
				% (len(common), float(diff.mean()), int((diff > 0).sum()), int((diff < 0).sum()))
			)
	only_close = kc.index.difference(ko.index) if len(sub_c) else []
	only_open = ko.index.difference(kc.index) if len(sub_o) else []
	if len(sub_c) and len(sub_o):
		print("仅收盘买到 %d 笔 | 仅开盘买到 %d 笔" % (len(only_close), len(only_open)))

	print()
	print("=== 基准全规则分档 ===")
	print(by_rule(tdf_close).to_string())
	print()
	print("=== T开盘版全规则分档 ===")
	print(by_rule(tdf_open).to_string())


if __name__ == "__main__":
	main()
