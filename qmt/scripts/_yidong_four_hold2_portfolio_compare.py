# -*- coding: utf-8 -*-
"""对比：①仅做F8/9/28/29持2天 ②四档持2天+其余档原规则；含收益/回撤/波动/胜率等。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from dafengniu_benchmark_ref_trades import compute_extended_metrics  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	simulate_trade,
	_simulate_fixed_sell,
)

CSV = Path(YIDONG_REGULATION_STOCKS_CSV)
TARGET = {8, 9, 28, 29}


def simulate_hold2_four(row, g0, cd) -> dict | None:
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
	return None


def f_trade_rule_other(f_val) -> str | None:
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
	return "default"


def simulate_other_original(row, g0, cd) -> dict | None:
	"""非四档：沿用改四档前的分F规则（不含四档持2/混合）。"""
	rule = f_trade_rule_other(row.get("F"))
	if rule is None:
		return None
	if rule == "fix_t1o_t2c":
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=1, buy_kind="open", sell_off=2, rule_id=rule
		)
	if rule == "fix_t2o_t3c":
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=2, buy_kind="open", sell_off=3, rule_id=rule
		)
	if rule == "fix_t0c_t1c":
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=0, buy_kind="close", sell_off=1, rule_id=rule
		)
	return simulate_trade(row, g0, cd)


def build_trades_only_four(sig: pd.DataFrame, g0, cd) -> pd.DataFrame:
	rows = []
	for _, row in sig.iterrows():
		f = int(row["F"]) if pd.notna(row["F"]) else -1
		if f not in TARGET:
			continue
		t = simulate_hold2_four(row, g0, cd)
		if t:
			rows.append(t)
	return pd.DataFrame(rows)


def build_trades_full_mix(sig: pd.DataFrame, g0, cd) -> pd.DataFrame:
	rows = []
	for _, row in sig.iterrows():
		f = int(row["F"]) if pd.notna(row["F"]) else -1
		if f in TARGET:
			t = simulate_hold2_four(row, g0, cd)
		else:
			t = simulate_other_original(row, g0, cd)
		if t:
			rows.append(t)
	return pd.DataFrame(rows)


def metrics(tdf: pd.DataFrame) -> dict:
	if tdf.empty:
		return {"成交笔数": 0}
	rets = tdf["收益率%"].astype(float).values
	days = tdf["开仓日"].astype(str).tolist()
	ext = compute_extended_metrics(rets, days)
	wins = int((rets > 0).sum())
	n = len(rets)
	order = np.argsort(days)
	nav_end = float(np.prod(1.0 + rets[order] / 100.0))
	hold_dd = tdf["持仓最大回撤%"].astype(float)

	return {
		"成交笔数": n,
		"胜率_pct": round(100.0 * wins / n, 2),
		"单笔平均收益_pct": round(float(np.mean(rets)), 4),
		"单笔收益中位数_pct": round(float(np.median(rets)), 4),
		"单笔收益标准差_pct": ext.get("波动率_笔收益标准差_pct"),
		"单笔最差_pct": round(float(np.min(rets)), 4),
		"单笔最好_pct": round(float(np.max(rets)), 4),
		"合计收益_线性加总_pct": round(float(np.sum(rets)), 2),
		"合计收益金额_元": round(float(tdf["收益金额"].sum()), 2),
		"净值_顺序复利": round(nav_end, 4),
		"最大回撤_链式净值_pct": ext.get("最大回撤_链式净值_pct"),
		"盈亏比_均盈除均亏": ext.get("盈亏比_均盈除以均亏绝对值"),
		"持仓回撤均值_pct": round(float(hold_dd.mean()), 4),
		"持仓回撤最大_pct": round(float(hold_dd.max()), 4),
	}


def print_compare(m1: dict, m2: dict, n1: str, n2: str) -> None:
	keys = [
		"成交笔数",
		"胜率_pct",
		"单笔平均收益_pct",
		"单笔收益中位数_pct",
		"单笔收益标准差_pct",
		"单笔最差_pct",
		"单笔最好_pct",
		"合计收益_线性加总_pct",
		"合计收益金额_元",
		"净值_顺序复利",
		"最大回撤_链式净值_pct",
		"盈亏比_均盈除均亏",
		"持仓回撤均值_pct",
		"持仓回撤最大_pct",
	]
	print("\n%-28s %18s %18s %12s" % ("指标", n1, n2, "②-①差额"))
	print("-" * 80)
	for k in keys:
		v1 = m1.get(k)
		v2 = m2.get(k)
		if v1 is None and v2 is None:
			continue
		diff = ""
		if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
			d = v2 - v1
			diff = "%+.2f" % d if isinstance(v1, float) else "%+d" % d
		print("%-28s %18s %18s %12s" % (k, str(v1), str(v2), diff))


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)

	tdf1 = build_trades_only_four(sig, g0, cd)
	tdf2 = build_trades_full_mix(sig, g0, cd)
	m1 = metrics(tdf1)
	m2 = metrics(tdf2)

	print("=" * 80)
	print("异动监管回测对比 | 数据源: %s | 可买信号 %d" % (CSV.name, len(sig)))
	print("=" * 80)
	print("\n【方案①】仅交易 F8/F9/F28/F29，四档均持2天新规则：")
	print("  F8: T+2开盘→持2天(T+4收) | F9/F28: T+1开盘→持2天(T+3收) | F29: T收盘→持2天(T+2收)")
	print("\n【方案②】全量可买信号：四档同上持2天；其余F档规则不变")
	print("  其余: F2-3 T+1开持1 | F4/F7 T+2开持1 | F6 T收T+1卖 | 其他 T收+8%%止损T+6")
	print("  (不含四档的旧 F8/9 T+1开持1、F28/29 单独默认等)")

	n1 = "①仅四档"
	n2 = "②四档+其余"
	print_compare(m1, m2, n1, n2)

	sub2_four = tdf2[tdf2["监控日涨幅偏离值F"].isin(TARGET)] if not tdf2.empty else tdf2
	print("\n【校验】方案②中四档子集 vs 方案①（应一致或极接近）：")
	print_compare(metrics(tdf1), metrics(sub2_four), "①仅四档", "②内四档")

	out = Path(_SCRIPT).parent / "实盘策略" / "测试组合表格"
	out.mkdir(parents=True, exist_ok=True)
	p1 = out / "yidong_compare_only_four_hold2_metrics.json"
	p2 = out / "yidong_compare_full_hold2_mix_metrics.json"
	import json

	with open(p1, "w", encoding="utf-8") as f:
		json.dump({"方案": n1, **m1}, f, ensure_ascii=False, indent=2)
	with open(p2, "w", encoding="utf-8") as f:
		json.dump({"方案": n2, **m2}, f, ensure_ascii=False, indent=2)
	print("\n指标 JSON: %s" % p1.name)
	print("         %s" % p2.name)


if __name__ == "__main__":
	main()
