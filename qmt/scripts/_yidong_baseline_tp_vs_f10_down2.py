# -*- coding: utf-8 -*-
"""新基准(全档+16%%止盈) vs F10跌日多持1天+TP16 分档对比。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	_day_close_pct_vs_prev,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	f_trade_rule,
	load_yidong,
	planned_buy_calendar,
	trade_date_at_offset,
)
from _yidong_tp_scan import (  # noqa: E402
	_simulate_default_tp,
	_simulate_fixed_sell_tp,
	run_tp_backtest,
)

TP = 16.0
FIXED = {
	"fix_t2o_t3c": (2, "open", 3),
	"fix_t1o_t2c": (1, "open", 2),
	"fix_t1o_t4c": (1, "open", 4),
	"fix_t1o_t3c": (1, "open", 3),
}
TIERS = ("F7", "F10", "F8/F30", "F9/F27/F28", "其余")


def tier_label(f) -> str:
	f = int(f)
	if f == 7:
		return "F7"
	if f == 10:
		return "F10"
	if f in (8, 30):
		return "F8/F30"
	if f in (9, 27, 28):
		return "F9/F27/F28"
	return "其余"


def planned_buy(row, cd) -> str | None:
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	if rule in FIXED:
		boff, _, _ = FIXED[rule]
		code, t = str(row["股票代码"]), str(row["T日"])
		if boff == 0:
			return t or None
		return trade_date_at_offset(code, t, boff, cd)
	return planned_buy_calendar(row, code_dates=cd, rule_id="default")


def sim_f10_down_hold2(row, g0, cd) -> dict | None:
	f = int(row["F"])
	if f == 7:
		return _simulate_fixed_sell_tp(
			row, g0, cd, buy_off=2, buy_kind="open", sell_off=3,
			rule_id="fix_t2o_t3c", tp_pct=TP,
		)
	if f == 10:
		p = _day_close_pct_vs_prev(row, 0)
		if p is None:
			return None
		soff = 3 if p <= 0 else 2
		return _simulate_fixed_sell_tp(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=soff,
			rule_id="fix_f10_down2", tp_pct=TP,
		)
	if f in (8, 30):
		return _simulate_fixed_sell_tp(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=4,
			rule_id="fix_t1o_t4c", tp_pct=TP,
		)
	if f in (9, 27, 28):
		return _simulate_fixed_sell_tp(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=3,
			rule_id="fix_t1o_t3c", tp_pct=TP,
		)
	return _simulate_default_tp(row, g0, cd, tp_pct=TP)


def run_custom(sim_fn) -> pd.DataFrame:
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	trades: list[dict] = []
	for _, row in collect_signals(df).iterrows():
		if not planned_buy(row, cd):
			continue
		t = sim_fn(row, g0, cd)
		if t:
			trades.append(t)
	return pd.DataFrame(trades)


def tier_stats(tdf: pd.DataFrame, tier: str) -> dict | None:
	if tier == "合计":
		sub = tdf
	else:
		sub = tdf[tdf.apply(lambda r: tier_label(r["监控日涨幅偏离值F"]) == tier, axis=1)]
	if sub.empty:
		return None
	r = sub["收益率%"].astype(float)
	return {
		"档位": tier,
		"笔数": len(sub),
		"胜率%": round((r > 0).mean() * 100, 1),
		"均收益%": round(float(r.mean()), 2),
		"合计金额": round(float(sub["收益金额"].sum()), 0),
		"止盈": int(sub["卖出原因"].astype(str).str.contains("止盈", na=False).sum()),
	}


def print_table(rows: list[dict], title: str) -> None:
	print("\n=== %s ===" % title)
	print(pd.DataFrame(rows).to_string(index=False))


def f10_sub_stats(tdf: pd.DataFrame, g0, cd) -> None:
	print("\n=== F10变体 子分支（T日收盘相对T-1收盘涨跌幅，买入前决定）===")
	buckets: dict[str, list[dict]] = {"T日收涨>0 → 持1天(T+2收)": [], "T日收跌≤0 → 持2天(T+3收)": []}
	for _, row in collect_signals(df).iterrows():
		if int(row["F"]) != 10:
			continue
		if not planned_buy(row, cd):
			continue
		p = _day_close_pct_vs_prev(row, 0)
		if p is None:
			continue
		soff = 3 if p <= 0 else 2
		key = "T日收跌≤0 → 持2天(T+3收)" if p <= 0 else "T日收涨>0 → 持1天(T+2收)"
		t = _simulate_fixed_sell_tp(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=soff,
			rule_id="fix_f10_down2", tp_pct=TP,
		)
		if t:
			buckets[key].append(t)
	for key, rows in buckets.items():
		r = pd.Series([x["收益率%"] for x in rows], dtype=float)
		print(
			"  %s: n=%d win=%.1f%% mean=%.2f%% pnl=%.0f"
			% (key, len(r), (r > 0).mean() * 100, r.mean(), sum(x["收益金额"] for x in rows))
		)


if __name__ == "__main__":
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)

	tdf_base, _ = run_tp_backtest(df, TP)
	tdf_var = run_custom(sim_f10_down_hold2)

	base_rows = [tier_stats(tdf_base, t) for t in TIERS] + [tier_stats(tdf_base, "合计")]
	var_rows = [tier_stats(tdf_var, t) for t in TIERS] + [tier_stats(tdf_var, "合计")]
	base_rows = [x for x in base_rows if x]
	var_rows = [x for x in var_rows if x]

	print_table(base_rows, "新基准：全档基准买卖 + 16%%止盈（F10固定持1天）")
	print_table(var_rows, "变体：F10跌日多持1天 + TP16（其余档同新基准）")

	print("\n=== 分档差异（变体 − 新基准）===")
	diff_rows = []
	for t in TIERS:
		b = tier_stats(tdf_base, t)
		v = tier_stats(tdf_var, t)
		if not b or not v:
			continue
		diff_rows.append({
			"档位": t,
			"笔数差": v["笔数"] - b["笔数"],
			"均收益差%": round(v["均收益%"] - b["均收益%"], 2),
			"金额差": round(v["合计金额"] - b["合计金额"], 0),
		})
	bc = tier_stats(tdf_base, "合计")
	vc = tier_stats(tdf_var, "合计")
	if bc and vc:
		diff_rows.append({
			"档位": "合计",
			"笔数差": vc["笔数"] - bc["笔数"],
			"均收益差%": round(vc["均收益%"] - bc["均收益%"], 2),
			"金额差": round(vc["合计金额"] - bc["合计金额"], 0),
		})
	print(pd.DataFrame(diff_rows).to_string(index=False))

	f10_sub_stats(tdf_var, g0, cd)

	print("\n【跌日多持1天含义】")
	print("  不是到期卖出日当天涨跌幅<0再顺延；")
	print("  而是在 T 日收盘后，用 (T收-T-1收)/T-1收 判断：")
	print("  ≤0 则次日 T+1 开盘买后计划多持 1 个交易日，T+3 收盘卖；>0 则仍 T+2 收盘卖。")
