# -*- coding: utf-8 -*-
"""用户确认规则全量回测：F10分支 + 全档16%%止盈 + T日/买入日涨跌幅过滤。"""
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
	_day_close_pct_vs_prev,
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
F10_DEEP_DROP_PCT = -3.0

FIXED_SPECS: dict[str, tuple[int, str, int]] = {
	"fix_t2o_t3c": (2, "open", 3),   # F7
	"fix_t1o_t4c": (1, "open", 4),   # F8/F30
	"fix_t1o_t3c": (1, "open", 3),   # F9/F27/F28
}


def f_trade_rule_confirmed(f_val) -> str | None:
	if pd.isna(f_val):
		return "default"
	f = int(f_val)
	if f in SKIP_F or f in NO_TRADE_F:
		return None
	if f == 7:
		return "fix_t2o_t3c"
	if f == 10:
		return "fix_f10_branch"
	if f in (8, 30):
		return "fix_t1o_t4c"
	if f in (9, 27, 28):
		return "fix_t1o_t3c"
	return "default"


def f10_sell_off(row: pd.Series) -> int | None:
	pct = _day_close_pct_vs_prev(row, 0)
	if pct is None:
		return None
	if pct <= F10_DEEP_DROP_PCT:
		return 3
	return 2


def planned_buy_confirmed(row: pd.Series, code_dates: dict) -> str | None:
	rule = f_trade_rule_confirmed(row.get("F"))
	if rule is None:
		return None
	if rule == "fix_f10_branch":
		code = str(row["股票代码"])
		t_day = str(row["T日"])
		return trade_date_at_offset(code, t_day, 1, code_dates)
	if rule in FIXED_SPECS:
		boff, _, _ = FIXED_SPECS[rule]
		code = str(row["股票代码"])
		t_day = str(row["T日"])
		if boff == 0:
			return t_day if t_day else None
		return trade_date_at_offset(code, t_day, boff, code_dates)
	return planned_buy_calendar(row, code_dates, rule_id="default")


def simulate_trade_confirmed(
	row: pd.Series,
	g_zero: set,
	code_dates: dict,
) -> dict | None:
	rule = f_trade_rule_confirmed(row.get("F"))
	if rule is None:
		return None
	if rule == "fix_f10_branch":
		soff = f10_sell_off(row)
		if soff is None:
			return None
		rid = "fix_f10_deep2d" if (_day_close_pct_vs_prev(row, 0) or 0) <= F10_DEEP_DROP_PCT else "fix_f10_shallow1d"
		return _simulate_fixed_sell_tp(
			row, g_zero, code_dates,
			buy_off=1, buy_kind="open", sell_off=soff,
			rule_id=rid, tp_pct=TP_PCT,
		)
	if rule in FIXED_SPECS:
		boff, kind, soff = FIXED_SPECS[rule]
		return _simulate_fixed_sell_tp(
			row, g_zero, code_dates,
			buy_off=boff, buy_kind=kind, sell_off=soff,
			rule_id=rule, tp_pct=TP_PCT,
		)
	return _simulate_default_tp(row, g_zero, code_dates, tp_pct=TP_PCT)


def run_confirmed_backtest(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
	g_zero = build_g_zero(df)
	code_dates = build_code_trade_dates(df)
	signals = collect_signals(df, skip_limit=True)
	trades: list[dict] = []
	fail: dict[str, int] = defaultdict(int)
	plan_rows: list[tuple[str, int, pd.Series]] = []
	for idx, row in signals.iterrows():
		pb = planned_buy_confirmed(row, code_dates)
		if not pb:
			fail["no_buy_date"] += 1
			continue
		plan_rows.append((pb, int(idx), row))
	plan_rows.sort(key=lambda x: (x[0], x[1]))
	for _, _, row in plan_rows:
		t = simulate_trade_confirmed(row, g_zero, code_dates)
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
	summary = {
		"成交笔数": len(tdf),
		"胜率_pct": round(100.0 * (rets > 0).mean(), 2),
		"单笔平均收益_pct": round(float(np.mean(rets)), 4),
		"中位收益_pct": round(float(np.median(rets)), 4),
		"合计收益金额_元": round(float(tdf["收益金额"].sum()), 2),
		"净值_顺序复利": round(nav, 4),
		"止盈触发笔数": int(reasons.str.contains("止盈", na=False).sum()),
		"止损触发笔数": int(reasons.str.contains("止损", na=False).sum()),
		"G0强平笔数": int(reasons.str.contains("G0", na=False).sum()),
		"链式最大回撤_pct": ext.get("最大回撤_链式净值_pct"),
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


def print_year_table(tdf: pd.DataFrame) -> None:
	tdf = tdf.copy()
	tdf["年"] = tdf["买入日"].astype(str).str[:4]
	print("\n--- 按年 ---")
	rows = []
	for y, g in tdf.groupby("年"):
		r = g["收益率%"].astype(float)
		rows.append({
			"年": y,
			"笔数": len(g),
			"胜率%": round((r > 0).mean() * 100, 1),
			"均收益%": round(float(r.mean()), 2),
			"合计金额": round(float(g["收益金额"].sum()), 0),
		})
	print(pd.DataFrame(rows).to_string(index=False))


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("CSV 行数:", len(df))
	print("\n【确认规则】")
	print("  G=0强平 | 剔除F1-6整键不买")
	print("  F7: T+2开→T+3收 | F10: 收跌≤-3%%持2天 else持1天 | F8/F30持3天 | F9/F27/F28持2天")
	print("  其余: T开+8%%止损T+2起+T+6兜底 | 全档16%%止盈")
	print("  过滤: 60/00跌[-10,-8]%%或涨>8%%; 68/30跌[-30,-15]%%或涨>15%% (T日+买入日)")

	tdf_new, summ_new = run_confirmed_backtest(df)
	tdf_old, summ_old = run_backtest(df)
	tdf_tp, summ_tp = run_tp_backtest(df, TP_PCT)

	print("\n========== 策略对比 ==========")
	print(
		"现行核心(无止盈,F10固定持1天): n=%d win=%.1f%% mean=%.2f%% 金额=%.0f"
		% (
			summ_old["成交笔数"],
			summ_old["胜率_pct"],
			summ_old["单笔平均收益_pct"],
			summ_old["合计收益金额_元"],
		)
	)
	print(
		"旧规则+16%%止盈(F10固定持1天): n=%d win=%.1f%% mean=%.2f%% 金额=%.0f 止盈=%d"
		% (
			summ_tp["成交笔数"],
			summ_tp["胜率_pct"],
			summ_tp["单笔平均收益_pct"],
			summ_tp["合计收益金额_元"],
			summ_tp.get("止盈触发笔数", 0),
		)
	)
	print(
		"★确认规则(F10分支+全档16%%止盈): n=%d win=%.1f%% mean=%.2f%% 金额=%.0f 净值=%.4f"
		% (
			summ_new["成交笔数"],
			summ_new["胜率_pct"],
			summ_new["单笔平均收益_pct"],
			summ_new["合计收益金额_元"],
			summ_new["净值_顺序复利"],
		)
	)
	print(
		"  vs现行核心 金额 %+.0f | 均收益 %+.2f%%"
		% (
			summ_new["合计收益金额_元"] - summ_old["合计收益金额_元"],
			summ_new["单笔平均收益_pct"] - summ_old["单笔平均收益_pct"],
		)
	)
	print(
		"  vs旧规则+TP16 金额 %+.0f | 均收益 %+.2f%%"
		% (
			summ_new["合计收益金额_元"] - summ_tp["合计收益金额_元"],
			summ_new["单笔平均收益_pct"] - summ_tp["单笔平均收益_pct"],
		)
	)
	print(
		"  止盈%d | 止损%d | G0%d | 链式回撤%.2f%%"
		% (
			summ_new["止盈触发笔数"],
			summ_new["止损触发笔数"],
			summ_new["G0强平笔数"],
			summ_new.get("链式最大回撤_pct") or 0,
		)
	)

	if not tdf_new.empty:
		print_tier_table(tdf_new)
		print_year_table(tdf_new)
		# F10 子分支
		f10 = tdf_new[tdf_new["监控日涨幅偏离值F"].astype(int) == 10]
		if not f10.empty:
			print("\n--- F10 子分支 ---")
			for lbl, mask in [
				("收跌≤-3%持2天", f10["T日涨跌幅%"].astype(float) <= F10_DEEP_DROP_PCT),
				("收涨>-3%持1天", f10["T日涨跌幅%"].astype(float) > F10_DEEP_DROP_PCT),
			]:
				sub = f10.loc[mask]
				if sub.empty:
					continue
				r = sub["收益率%"].astype(float)
				print(
					"  %s: n=%d win=%.1f%% mean=%.2f%% 金额=%.0f"
					% (lbl, len(sub), (r > 0).mean() * 100, r.mean(), sub["收益金额"].sum())
				)
		print("\n--- 卖出原因 Top10 ---")
		for reason, cnt in tdf_new["卖出原因"].value_counts().head(10).items():
			sub = tdf_new[tdf_new["卖出原因"] == reason]
			print(
				"  %3d  均%.2f%%  %s"
				% (cnt, float(sub["收益率%"].astype(float).mean()), reason)
			)


if __name__ == "__main__":
	main()
