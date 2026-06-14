# -*- coding: utf-8 -*-
"""F7/F10/F8/F30/F9/F27/F28：固定持满 vs 收盘趋势延续卖出对比。"""
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
	build_code_trade_dates,
	build_f_block_keys,
	build_g_zero,
	collect_signals,
	f_trade_rule,
	hold_calendar_days,
	load_yidong,
	planned_buy_calendar,
	rule_fixed_hold_days,
	run_backtest,
	simulate_trade,
	_simulate_fixed_sell,
	_day_col,
	_g0_hit,
	_num,
	_pack_trade,
	_try_g0_sell,
	_try_plate_close_sell,
	_buy_px,
	is_buy_day_blocked,
)

FIXED_F = {7, 10, 8, 30, 9, 27, 28}


def _check_start_off(buy_off: int, hold_days: int) -> int:
	"""持满 N 天后从哪一天收盘起判断：持1/2天=计划末日；持3天=第3个持仓日收盘(T+buy_off+2)。"""
	if hold_days >= 3:
		return buy_off + hold_days - 1
	return buy_off + hold_days


def _simulate_fixed_close_trend(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
	*,
	buy_off: int,
	buy_kind: str,
	sell_off: int,
	rule_id: str,
) -> dict | None:
	"""持满天数后：收盘>昨收则多持1天；收盘<昨收则当日尾盘卖；G0/跌停顺延照旧。"""
	if is_buy_day_blocked(row, buy_off, buy_kind):
		return None
	buy_px = _buy_px(row, buy_off, buy_kind)
	if buy_px is None:
		return None

	hold_days = sell_off - buy_off
	check_start = _check_start_off(buy_off, hold_days)
	if check_start > MAX_DATA_DAY:
		return None

	code = str(row["股票代码"])
	t_day = str(row["T日"])
	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []

	from yidong_regulation_backtest_core import G0_DEFER_BUY_DAY_TO_NEXT_CLOSE

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

		if off < check_start:
			continue

		prev_c = _num(row.get(_day_col(off - 1, "收盘")))
		if prev_c is None:
			break

		if c < prev_c - 1e-9:
			res = _try_plate_close_sell(
				row, off, code, t_day, code_dates,
				"收盘走弱(T+%d收<昨收)" % off,
			)
			if res:
				sell_px, sell_day, reason = res
				break
			continue

		if c > prev_c + 1e-9:
			continue

		# 平收：视为不强，当日尾盘卖
		res = _try_plate_close_sell(
			row, off, code, t_day, code_dates,
			"收盘平盘(T+%d收=昨收)" % off,
		)
		if res:
			sell_px, sell_day, reason = res
			break

	# 数据用尽仍持仓：最后可用收盘强平
	if sell_px is None:
		last_off = None
		for off in range(MAX_DATA_DAY, check_start - 1, -1):
			if _num(row.get(_day_col(off, "收盘"))) is not None:
				last_off = off
				break
		if last_off is not None:
			res = _try_plate_close_sell(
				row, last_off, code, t_day, code_dates,
				"数据截止T+%d收盘" % last_off,
			)
			if res:
				sell_px, sell_day, reason = res

	if sell_px is None:
		return None

	buy_cal = (
		planned_buy_calendar(row, code_dates, rule_id)
		or (t_day if buy_off == 0 else None)
	)
	if buy_off > 0:
		from yidong_regulation_backtest_core import trade_date_at_offset

		buy_cal = trade_date_at_offset(code, t_day, buy_off, code_dates) or buy_cal

	return _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		buy_cal=buy_cal or t_day,
		reason=reason,
		rule_id=rule_id + "_close_trend",
		hold_lows=hold_lows,
		t_day=t_day,
	)


def simulate_trade_close_trend(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
) -> dict | None:
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	f = int(row["F"]) if pd.notna(row.get("F")) else -1
	if f not in FIXED_F:
		return simulate_trade(row, g_zero, code_dates)

	from yidong_regulation_backtest_core import FIXED_RULE_SPECS

	if rule not in FIXED_RULE_SPECS:
		return simulate_trade(row, g_zero, code_dates)
	boff, kind, sell_off = FIXED_RULE_SPECS[rule]
	return _simulate_fixed_close_trend(
		row, g_zero, code_dates,
		buy_off=boff, buy_kind=kind, sell_off=sell_off, rule_id=rule,
	)


def run_variant(df: pd.DataFrame, *, use_close_trend: bool) -> tuple[pd.DataFrame, dict]:
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
		if use_close_trend:
			t = simulate_trade_close_trend(row, g_zero, code_dates)
		else:
			t = simulate_trade(row, g_zero, code_dates)
		if t is None:
			fail["sim_fail"] += 1
			continue
		trades.append(t)

	tdf = pd.DataFrame(trades)
	if tdf.empty:
		return tdf, {"成交笔数": 0}

	rets = tdf["收益率%"].astype(float)
	summary = {
		"成交笔数": len(tdf),
		"胜率_pct": round((rets > 0).mean() * 100, 2),
		"单笔平均收益_pct": round(float(rets.mean()), 4),
		"合计收益金额_元": round(float(tdf["收益金额"].sum()), 2),
		"失败": dict(fail),
	}
	return tdf, summary


def bucket_stats(tdf: pd.DataFrame, label: str) -> None:
	if tdf.empty:
		print(label, "无成交")
		return
	sub = tdf[tdf["监控日涨幅偏离值F"].isin(FIXED_F)]
	print("\n=== %s | F7/F10/F8/F30/F9/F27/F28 合计 ===" % label)
	rets = sub["收益率%"].astype(float)
	print(
		"  n=%d 胜率=%.1f%% 均收益=%.2f%% 合计=%.0f元"
		% (len(sub), (rets > 0).mean() * 100, rets.mean(), sub["收益金额"].sum())
	)
	for f in sorted(FIXED_F):
		b = sub[sub["监控日涨幅偏离值F"] == f]
		if len(b) == 0:
			continue
		r = b["收益率%"].astype(float)
		print(
			"  F%d: n=%d win=%.0f%% mean=%.2f%% sum=%.0f"
			% (f, len(b), (r > 0).mean() * 100, r.mean(), b["收益金额"].sum())
		)


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	tdf_base, summ_base = run_backtest(df)
	tdf_new, summ_new = run_variant(df, use_close_trend=True)

	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("\n--- 全量回测（其余档仍用原规则）---")
	print(
		"固定持满: n=%d 胜率=%.1f%% 均=%.2f%% 合计=%.0f"
		% (
			summ_base["成交笔数"],
			summ_base["胜率_pct"],
			summ_base["单笔平均收益_pct"],
			summ_base["合计收益金额_元"],
		)
	)
	print(
		"收盘趋势: n=%d 胜率=%.1f%% 均=%.2f%% 合计=%.0f"
		% (
			summ_new["成交笔数"],
			summ_new["胜率_pct"],
			summ_new["单笔平均收益_pct"],
			summ_new["合计收益金额_元"],
		)
	)
	print(
		"差额: 均收益 %+.2f%%  合计金额 %+.0f元"
		% (
			summ_new["单笔平均收益_pct"] - summ_base["单笔平均收益_pct"],
			summ_new["合计收益金额_元"] - summ_base["合计收益金额_元"],
		)
	)

	bucket_stats(tdf_base, "固定持满")
	bucket_stats(tdf_new, "收盘趋势")

	# 配对对比（同信号键）
	key_cols = ["股票代码", "开仓日", "监控日涨幅偏离值F"]
	base = tdf_base[tdf_base["监控日涨幅偏离值F"].isin(FIXED_F)].copy()
	new = tdf_new[tdf_new["监控日涨幅偏离值F"].isin(FIXED_F)].copy()
	merged = base.merge(
		new,
		on=key_cols,
		suffixes=("_固定", "_趋势"),
		how="inner",
	)
	if len(merged):
		d = merged["收益率%_趋势"].astype(float) - merged["收益率%_固定"].astype(float)
		print("\n--- 配对差值（趋势-固定，仅六档可配对）---")
		print("  配对 n=%d 均差=%.2f%% 合计差=%.0f元" % (len(merged), d.mean(), (d * 1000).sum()))
		print("  趋势更好笔数: %d / %d" % ((d > 0).sum(), len(merged)))

		# 卖出原因分布（趋势）
		if "卖出原因_趋势" in merged.columns:
			print("\n  趋势卖出原因样例:")
			for reason, cnt in merged["卖出原因_趋势"].value_counts().head(8).items():
				print("    %s: %d" % (reason, cnt))


if __name__ == "__main__":
	main()
