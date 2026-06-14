# -*- coding: utf-8 -*-
"""现行最优规则全量回测统计（含 F10 T开盘持1天 + 16%% 止盈）。"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))

from dafengniu_benchmark_ref_trades import compute_extended_metrics  # noqa: E402
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	NO_TRADE_F,
	SKIP_F,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	f_trade_rule,
	load_yidong,
	planned_buy_calendar,
	run_backtest,
	trade_date_at_offset,
)
from _yidong_tp_scan import (  # noqa: E402
	_simulate_default_tp,
	_simulate_fixed_sell_tp,
	run_tp_backtest,
)

TP_PCT = 16.0

# 最优规则：F10 = T开盘买 T+1收盘卖
OPTIMAL_FIXED: dict[str, tuple[int, str, int]] = {
	"fix_t2o_t3c": (2, "open", 3),   # F7
	"fix_t0o_t1c": (0, "open", 1),   # F10
	"fix_t1o_t4c": (1, "open", 4),   # F8/F30
	"fix_t1o_t3c": (1, "open", 3),   # F9/F27/F28
}


def f_trade_rule_optimal(f_val) -> str | None:
	if pd.isna(f_val):
		return "default"
	f = int(f_val)
	if f in SKIP_F or f in NO_TRADE_F:
		return None
	if f == 7:
		return "fix_t2o_t3c"
	if f == 10:
		return "fix_t0o_t1c"
	if f in (8, 30):
		return "fix_t1o_t4c"
	if f in (9, 27, 28):
		return "fix_t1o_t3c"
	return "default"


def planned_buy_optimal(row, code_dates) -> str | None:
	rule = f_trade_rule_optimal(row.get("F"))
	if rule is None:
		return None
	if rule in OPTIMAL_FIXED:
		boff, _, _ = OPTIMAL_FIXED[rule]
		code = str(row["股票代码"])
		t_day = str(row["T日"])
		if boff == 0:
			return t_day if t_day else None
		return trade_date_at_offset(code, t_day, boff, code_dates)
	return planned_buy_calendar(row, code_dates, rule_id="default")


def simulate_trade_optimal(row, g_zero, code_dates):
	rule = f_trade_rule_optimal(row.get("F"))
	if rule is None:
		return None
	if rule in OPTIMAL_FIXED:
		boff, kind, sell_off = OPTIMAL_FIXED[rule]
		return _simulate_fixed_sell_tp(
			row, g_zero, code_dates,
			buy_off=boff, buy_kind=kind, sell_off=sell_off,
			rule_id=rule, tp_pct=TP_PCT, stop_pct=None,
		)
	return _simulate_default_tp(row, g_zero, code_dates, tp_pct=TP_PCT)


def run_optimal_backtest(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
	g_zero = build_g_zero(df)
	code_dates = build_code_trade_dates(df)
	signals = collect_signals(df, skip_limit=True)
	trades: list[dict] = []
	fail: dict[str, int] = defaultdict(int)
	plan_rows: list[tuple[str, int, pd.Series]] = []
	for idx, row in signals.iterrows():
		pb = planned_buy_optimal(row, code_dates)
		if not pb:
			fail["no_buy_date"] += 1
			continue
		plan_rows.append((pb, int(idx), row))
	plan_rows.sort(key=lambda x: (x[0], x[1]))
	for _, _, row in plan_rows:
		t = simulate_trade_optimal(row, g_zero, code_dates)
		if t is None:
			fail["sim_fail"] += 1
			continue
		trades.append(t)
	tdf = pd.DataFrame(trades)
	if tdf.empty:
		return tdf, {"成交笔数": 0, "失败": dict(fail)}
	rets = tdf["收益率%"].astype(float).values
	buy_days = tdf["开仓日"].astype(str).tolist()
	ext = compute_extended_metrics(rets, buy_days)
	order = np.argsort(buy_days)
	nav = float(np.prod(1.0 + rets[order] / 100.0))
	reasons = tdf["卖出原因"].astype(str)
	tp_n = int(reasons.str.contains("止盈", na=False).sum())
	sl_n = int(reasons.str.contains("止损", na=False).sum())
	g0_n = int(reasons.str.contains("G0", na=False).sum())
	hold_n = int((reasons.str.contains("持", na=False) | reasons.str.contains("未触发", na=False)).sum())
	summary = {
		"成交笔数": len(tdf),
		"胜率_pct": round(100.0 * (rets > 0).mean(), 2),
		"单笔平均收益_pct": round(float(np.mean(rets)), 4),
		"中位收益_pct": round(float(np.median(rets)), 4),
		"合计收益金额_元": round(float(tdf["收益金额"].sum()), 2),
		"净值_顺序复利": round(nav, 4),
		"单笔最大收益_pct": round(float(np.max(rets)), 4),
		"单笔最大亏损_pct": round(float(np.min(rets)), 4),
		"链式最大回撤_pct": ext.get("最大回撤_链式净值_pct"),
		"止盈触发笔数": tp_n,
		"止损触发笔数": sl_n,
		"G0强平笔数": g0_n,
		"持满/兜底笔数": hold_n,
		"失败": dict(fail),
	}
	return tdf, summary


def _tier_label(f: int) -> str:
	if f == 7:
		return "F7"
	if f == 10:
		return "F10"
	if f in (8, 30):
		return "F8/F30"
	if f in (9, 27, 28):
		return "F9/F27/F28"
	return "其余"


def print_tier_table(tdf: pd.DataFrame) -> None:
	print("\n--- 分档统计 ---")
	rows = []
	for tier in ("F7", "F10", "F8/F30", "F9/F27/F28", "其余"):
		sub = tdf[tdf.apply(lambda r: _tier_label(int(r["监控日涨幅偏离值F"])) == tier, axis=1)]
		if sub.empty:
			continue
		rets = sub["收益率%"].astype(float)
		tp_n = int(sub["卖出原因"].astype(str).str.contains("止盈", na=False).sum())
		rows.append({
			"档位": tier,
			"笔数": len(sub),
			"胜率%": round((rets > 0).mean() * 100, 1),
			"均收益%": round(float(rets.mean()), 2),
			"合计金额": round(float(sub["收益金额"].sum()), 0),
			"止盈笔": tp_n,
		})
	print(pd.DataFrame(rows).to_string(index=False))


def print_reason_top(tdf: pd.DataFrame, n: int = 12) -> None:
	print("\n--- 卖出原因 Top ---")
	vc = tdf["卖出原因"].value_counts().head(n)
	for reason, cnt in vc.items():
		sub = tdf[tdf["卖出原因"] == reason]
		mean = float(sub["收益率%"].astype(float).mean())
		print("  %3d  均%.2f%%  %s" % (cnt, mean, reason))


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("CSV 行数:", len(df))
	print("\n【最优规则】")
	print("  G=0强平贯穿 | 剔除F1-6整键不买")
	print("  F7: T+2开盘→T+3收盘(持1天) | F10: T开盘→T+1收盘(持1天)")
	print("  F8/F30: T+1开盘→T+4收盘(持3天) | F9/F27/F28: T+1开盘→T+3收盘(持2天)")
	print("  其余: T开盘 + T+2起8%%止损 + T+6兜底")
	print("  全档: 盘中16%%止盈(日高触达)")
	print("  买入过滤: 60/00 跌[-10,-8]%%或涨>8%%不买; 68/30 跌[-30,-15]%%或涨>15%%不买")

	tdf_opt, summ_opt = run_optimal_backtest(df)
	tdf_base, summ_base = run_backtest(df)
	tdf_tp16, summ_tp16 = run_tp_backtest(df, TP_PCT, label="旧规则+16%%止盈")

	print("\n========== 全策略对比 ==========")
	print(
		"现行核心(无止盈,F10=T+1开): n=%d win=%.1f%% mean=%.2f%% 金额=%.0f 净值=%.4f"
		% (
			summ_base["成交笔数"],
			summ_base["胜率_pct"],
			summ_base["单笔平均收益_pct"],
			summ_base["合计收益金额_元"],
			summ_base.get("净值_顺序复利", 0),
		)
	)
	print(
		"旧规则+16%%止盈: n=%d win=%.1f%% mean=%.2f%% 金额=%.0f 止盈=%d"
		% (
			summ_tp16["成交笔数"],
			summ_tp16["胜率_pct"],
			summ_tp16["单笔平均收益_pct"],
			summ_tp16["合计收益金额_元"],
			summ_tp16["止盈触发笔数"],
		)
	)
	print(
		"★最优规则+16%%止盈: n=%d win=%.1f%% mean=%.2f%% 金额=%.0f 净值=%.4f"
		% (
			summ_opt["成交笔数"],
			summ_opt["胜率_pct"],
			summ_opt["单笔平均收益_pct"],
			summ_opt["合计收益金额_元"],
			summ_opt["净值_顺序复利"],
		)
	)
	print(
		"  vs核心 金额 %+.0f | 均收益 %+.2f%%"
		% (
			summ_opt["合计收益金额_元"] - summ_base["合计收益金额_元"],
			summ_opt["单笔平均收益_pct"] - summ_base["单笔平均收益_pct"],
		)
	)
	print(
		"  止盈%d | 止损%d | G0%d | 持满/兜底约%d | 链式回撤%.2f%%"
		% (
			summ_opt["止盈触发笔数"],
			summ_opt["止损触发笔数"],
			summ_opt["G0强平笔数"],
			summ_opt["持满/兜底笔数"],
			summ_opt.get("链式最大回撤_pct") or 0,
		)
	)

	if not tdf_opt.empty:
		print_tier_table(tdf_opt)
		print_reason_top(tdf_opt)


if __name__ == "__main__":
	main()
