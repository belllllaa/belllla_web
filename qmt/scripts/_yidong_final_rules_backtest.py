# -*- coding: utf-8 -*-
"""最终规则回测：F7/F10按T日涨跌幅分支 + 全档16%%止盈。"""
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
	trade_date_at_offset,
)
from _yidong_tp_scan import (  # noqa: E402
	_simulate_default_tp,
	_simulate_fixed_sell_tp,
	run_tp_backtest,
)

TP_PCT = 16.0

FIXED_NO_BRANCH = {
	"fix_t1o_t4c": (1, "open", 4),
	"fix_t1o_t3c": (1, "open", 3),
}


def f_trade_rule_final(f_val) -> str | None:
	if pd.isna(f_val):
		return "default"
	f = int(f_val)
	if f in SKIP_F or f in NO_TRADE_F:
		return None
	if f == 7:
		return "fix_f7_branch"
	if f == 10:
		return "fix_f10_branch"
	if f in (8, 30):
		return "fix_t1o_t4c"
	if f in (9, 27, 28):
		return "fix_t1o_t3c"
	return "default"


def _t_up(row: pd.Series) -> bool | None:
	p = _day_close_pct_vs_prev(row, 0)
	if p is None:
		return None
	return p > 0


def f7_sell_off(row: pd.Series) -> int | None:
	up = _t_up(row)
	if up is None:
		return None
	return 3 if up else 4  # 涨: T+3收; 跌/平: T+4收; 买T+2开


def f10_sell_off(row: pd.Series) -> int | None:
	up = _t_up(row)
	if up is None:
		return None
	return 2 if up else 3  # 涨: T+2收; 跌/平: T+3收; 买T+1开


def planned_buy_final(row: pd.Series, code_dates: dict) -> str | None:
	rule = f_trade_rule_final(row.get("F"))
	if rule is None:
		return None
	f = int(row["F"])
	code, t_day = str(row["股票代码"]), str(row["T日"])
	if f in (7, 10):
		boff = 2 if f == 7 else 1
		return trade_date_at_offset(code, t_day, boff, code_dates)
	if rule in FIXED_NO_BRANCH:
		boff, _, _ = FIXED_NO_BRANCH[rule]
		return trade_date_at_offset(code, t_day, boff, code_dates)
	return planned_buy_calendar(row, code_dates, rule_id="default")


def simulate_trade_final(row, g_zero, code_dates) -> dict | None:
	rule = f_trade_rule_final(row.get("F"))
	if rule is None:
		return None
	if rule == "fix_f7_branch":
		soff = f7_sell_off(row)
		if soff is None:
			return None
		rid = "fix_f7_up1d" if _t_up(row) else "fix_f7_down2d"
		return _simulate_fixed_sell_tp(
			row, g_zero, code_dates,
			buy_off=2, buy_kind="open", sell_off=soff,
			rule_id=rid, tp_pct=TP_PCT,
		)
	if rule == "fix_f10_branch":
		soff = f10_sell_off(row)
		if soff is None:
			return None
		rid = "fix_f10_up1d" if _t_up(row) else "fix_f10_down2d"
		return _simulate_fixed_sell_tp(
			row, g_zero, code_dates,
			buy_off=1, buy_kind="open", sell_off=soff,
			rule_id=rid, tp_pct=TP_PCT,
		)
	if rule in FIXED_NO_BRANCH:
		boff, kind, soff = FIXED_NO_BRANCH[rule]
		return _simulate_fixed_sell_tp(
			row, g_zero, code_dates,
			buy_off=boff, buy_kind=kind, sell_off=soff,
			rule_id=rule, tp_pct=TP_PCT,
		)
	return _simulate_default_tp(row, g_zero, code_dates, tp_pct=TP_PCT)


def run_final_backtest(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
	g_zero = build_g_zero(df)
	code_dates = build_code_trade_dates(df)
	signals = collect_signals(df, skip_limit=True)
	trades: list[dict] = []
	fail: dict[str, int] = defaultdict(int)
	plan_rows: list[tuple[str, int, pd.Series]] = []
	for idx, row in signals.iterrows():
		pb = planned_buy_final(row, code_dates)
		if not pb:
			fail["no_buy_date"] += 1
			continue
		plan_rows.append((pb, int(idx), row))
	plan_rows.sort(key=lambda x: (x[0], x[1]))
	for _, _, row in plan_rows:
		t = simulate_trade_final(row, g_zero, code_dates)
		if t is None:
			fail["sim_fail"] += 1
			continue
		trades.append(t)
	tdf = pd.DataFrame(trades)
	if tdf.empty:
		return tdf, {"成交笔数": 0, "失败": dict(fail)}
	rets = tdf["收益率%"].astype(float).values
	ext = compute_extended_metrics(rets, tdf["开仓日"].astype(str).tolist())
	order = np.argsort(tdf["开仓日"].astype(str))
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


def tier_label(f: int) -> str:
	if f == 7:
		return "F7"
	if f == 10:
		return "F10"
	if f in (8, 30):
		return "F8/F30"
	if f in (9, 27, 28):
		return "F9/F27/F28"
	return "其余"


def tier_table(tdf: pd.DataFrame) -> pd.DataFrame:
	rows = []
	for tier in ("F7", "F10", "F8/F30", "F9/F27/F28", "其余"):
		sub = tdf[tdf.apply(lambda r: tier_label(int(r["监控日涨幅偏离值F"])) == tier, axis=1)]
		if sub.empty:
			continue
		r = sub["收益率%"].astype(float)
		rows.append({
			"档位": tier,
			"笔数": len(sub),
			"胜率%": round((r > 0).mean() * 100, 1),
			"均收益%": round(float(r.mean()), 2),
			"合计金额": round(float(sub["收益金额"].sum()), 0),
			"止盈": int(sub["卖出原因"].astype(str).str.contains("止盈", na=False).sum()),
		})
	r = tdf["收益率%"].astype(float)
	rows.append({
		"档位": "合计",
		"笔数": len(tdf),
		"胜率%": round((r > 0).mean() * 100, 1),
		"均收益%": round(float(r.mean()), 2),
		"合计金额": round(float(tdf["收益金额"].sum()), 0),
		"止盈": int(tdf["卖出原因"].astype(str).str.contains("止盈", na=False).sum()),
	})
	return pd.DataFrame(rows)


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("CSV行数:", len(df))
	print("\n【最终规则】")
	print("  G=0强平 | 剔除F1-6 | 全档16%%止盈")
	print("  F7: T+2开; 收涨>0持1天(T+3收) | 收跌<=0持2天(T+4收)")
	print("  F10: T+1开; 收涨>0持1天(T+2收) | 收跌<=0持2天(T+3收)")
	print("  F8/F30持3天 | F9/F27/F28持2天 | 其余T开+止损+T+6兜底")
	print("  过滤: 60/00跌[-10,-8]%%或涨>8%%; 68/30跌[-30,-15]%%或涨>15%% (T日+买入日)")

	tdf_final, summ_final = run_final_backtest(df)
	tdf_base, summ_base = run_tp_backtest(df, TP_PCT)

	print("\n========== 策略对比 ==========")
	print(
		"对照(全档固定持满+16%%止盈,F7/F10不分支): n=%d win=%.1f%% mean=%.2f%% 金额=%.0f 止盈=%d"
		% (
			summ_base["成交笔数"],
			summ_base["胜率_pct"],
			summ_base["单笔平均收益_pct"],
			summ_base["合计收益金额_元"],
			summ_base.get("止盈触发笔数", 0),
		)
	)
	print(
		"★最终规则(F7/F10分支): n=%d win=%.1f%% mean=%.2f%% 金额=%.0f 止盈=%d"
		% (
			summ_final["成交笔数"],
			summ_final["胜率_pct"],
			summ_final["单笔平均收益_pct"],
			summ_final["合计收益金额_元"],
			summ_final.get("止盈触发笔数", 0),
		)
	)
	print(
		"  vs对照 金额 %+.0f | 均收益 %+.2f%%"
		% (
			summ_final["合计收益金额_元"] - summ_base["合计收益金额_元"],
			summ_final["单笔平均收益_pct"] - summ_base["单笔平均收益_pct"],
		)
	)
	print(
		"  止损%d | G0%d | 链式回撤%.2f%%"
		% (
			summ_final.get("止损触发笔数", 0),
			summ_final.get("G0强平笔数", 0),
			summ_final.get("链式最大回撤_pct") or 0,
		)
	)

	if not tdf_final.empty:
		print("\n--- 分档统计 ---")
		print(tier_table(tdf_final).to_string(index=False))

		tdf_final = tdf_final.copy()
		tdf_final["年"] = tdf_final["买入日"].astype(str).str[:4]
		print("\n--- 按年 ---")
		yr = []
		for y, g in tdf_final.groupby("年"):
			r = g["收益率%"].astype(float)
			yr.append({
				"年": y, "笔数": len(g),
				"胜率%": round((r > 0).mean() * 100, 1),
				"均收益%": round(float(r.mean()), 2),
				"合计金额": round(float(g["收益金额"].sum()), 0),
			})
		print(pd.DataFrame(yr).to_string(index=False))

		# F7/F10 子分支
		for f, name in [(7, "F7"), (10, "F10")]:
			sub = tdf_final[tdf_final["监控日涨幅偏离值F"].astype(int) == f]
			if sub.empty:
				continue
			print("\n--- %s 子分支 ---" % name)
			p = pd.to_numeric(sub["T日涨跌幅%"], errors="coerce")
			for lbl, mask in [("收涨>0", p > 0), ("收跌<=0", p <= 0)]:
				s = sub.loc[mask]
				if s.empty:
					continue
				r = s["收益率%"].astype(float)
				print(
					"  %s: n=%d win=%.1f%% mean=%.2f%% 金额=%.0f"
					% (lbl, len(s), (r > 0).mean() * 100, r.mean(), s["收益金额"].sum())
				)

		print("\n--- 卖出原因 Top10 ---")
		for reason, cnt in tdf_final["卖出原因"].value_counts().head(10).items():
			m = float(tdf_final.loc[tdf_final["卖出原因"] == reason, "收益率%"].astype(float).mean())
			print("  %3d  均%.2f%%  %s" % (cnt, m, reason))


if __name__ == "__main__":
	main()
