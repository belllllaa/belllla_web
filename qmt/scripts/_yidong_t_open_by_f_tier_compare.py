# -*- coding: utf-8 -*-
"""各 F 档：基准买入 vs T 日开盘买（卖出日不变，仅提前买入）。"""
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
	SKIP_F,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	f_trade_rule,
	load_yidong,
	run_backtest,
	simulate_trade,
	_simulate_fixed_sell,
)

# 复用其余档 T 开盘仿真
from _yidong_default_open_compare import simulate_trade_default_open  # noqa: E402

TIERS = [
	("F7", {7}),
	("F10", {10}),
	("F8/F30", {8, 30}),
	("F9/F27/F28", {9, 27, 28}),
]

BASELINE_FIXED = {
	"fix_t2o_t3c": (2, "open", 3, "T+2开盘买→T+3收盘卖"),
	"fix_t1o_t2c": (1, "open", 2, "T+1开盘买→T+2收盘卖"),
	"fix_t1o_t4c": (1, "open", 4, "T+1开盘买→T+4收盘卖"),
	"fix_t1o_t3c": (1, "open", 3, "T+1开盘买→T+3收盘卖"),
}


def _summ(tdf: pd.DataFrame) -> dict:
	if tdf.empty:
		return {"n": 0}
	rets = tdf["收益率%"].astype(float)
	n = len(rets)
	buy_days = tdf["开仓日"].astype(str).tolist()
	order = np.argsort(buy_days)
	nav = float(np.prod(1.0 + rets.values[order] / 100.0))
	return {
		"n": n,
		"win": 100.0 * (rets > 0).mean(),
		"mean": float(rets.mean()),
		"med": float(rets.median()),
		"sum_amt": float(tdf["收益金额"].sum()),
		"nav": nav,
	}


def _sim_baseline(row, g0, cd):
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	if rule in BASELINE_FIXED:
		boff, kind, soff, _ = BASELINE_FIXED[rule]
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=boff, buy_kind=kind, sell_off=soff, rule_id=rule,
		)
	return simulate_trade(row, g0, cd)


def _sim_t_open(row, g0, cd):
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	if rule in BASELINE_FIXED:
		_, _, soff, _ = BASELINE_FIXED[rule]
		return _simulate_fixed_sell(
			row, g0, cd, buy_off=0, buy_kind="open", sell_off=soff, rule_id=rule + "_t0o",
		)
	return simulate_trade_default_open(row, g0, cd)


def _run_rows(rows, sim_fn, g0, cd):
	out = []
	for _, row in rows.iterrows():
		t = sim_fn(row, g0, cd)
		if t:
			out.append(t)
	return pd.DataFrame(out)


def _print_cmp(label: str, base: dict, alt: dict, bench_desc: str) -> None:
	print("\n### %s" % label)
	print("  基准: %s" % bench_desc)
	print("  对比: T日开盘买（卖出日/规则与基准相同）")
	if base["n"] < 5:
		print("  样本不足 base n=%d" % base["n"])
		return
	print(
		"  基准 n=%d 胜率=%.1f%% 均收益=%.2f%% 合计金额=%.0f 净值=%.4f"
		% (base["n"], base["win"], base["mean"], base["sum_amt"], base["nav"])
	)
	if alt["n"] < 5:
		print("  T开盘 n=%d 样本不足" % alt["n"])
		return
	print(
		"  T开盘 n=%d 胜率=%.1f%% 均收益=%.2f%% 合计金额=%.0f 净值=%.4f"
		% (alt["n"], alt["win"], alt["mean"], alt["sum_amt"], alt["nav"])
	)
	print(
		"  差值: 均收益 %+.2f%% | 合计金额 %+.0f | 净值 %+.4f"
		% (alt["mean"] - base["mean"], alt["sum_amt"] - base["sum_amt"], alt["nav"] - base["nav"])
	)


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)

	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("说明: T-1 可知 T 日上榜 → 对比能否 T 日开盘提前买入（卖出锚点不变）")
	print("=" * 72)

	# 全策略
	tdf_base, _ = run_backtest(df)
	all_b = _run_rows(sig, _sim_baseline, g0, cd)
	all_o = _run_rows(sig, _sim_t_open, g0, cd)
	b_all = _summ(tdf_base)
	o_all = _summ(all_o)
	print("\n### 全策略合计（含组合排序同日多笔）")
	print(
		"  基准 run_backtest n=%d 均收益=%.2f%% 合计=%.0f 净值=%.4f"
		% (b_all["n"], b_all["mean"], b_all["sum_amt"], b_all["nav"])
	)
	print(
		"  全档改T开盘 n=%d 均收益=%.2f%% 合计=%.0f 净值=%.4f"
		% (o_all["n"], o_all["mean"], o_all["sum_amt"], o_all["nav"])
	)
	print(
		"  差值 均收益 %+.2f%% 合计金额 %+.0f"
		% (o_all["mean"] - b_all["mean"], o_all["sum_amt"] - b_all["sum_amt"])
	)

	for tier_name, fset in TIERS:
		sub = sig[sig["F"].isin(fset)]
		rule = f_trade_rule(list(fset)[0] if len(fset) == 1 else list(fset)[0])
		# pick representative rule id
		rid = f_trade_rule(sub.iloc[0]["F"] if len(sub) else None)
		bench_desc = BASELINE_FIXED.get(rid, ("", "", "", ""))[3] if rid in BASELINE_FIXED else ""
		tb = _run_rows(sub, _sim_baseline, g0, cd)
		to = _run_rows(sub, _sim_t_open, g0, cd)
		_print_cmp(tier_name, _summ(tb), _summ(to), bench_desc)

	# 其余档
	rest_mask = ~sig["F"].isin(SKIP_F) & ~sig["F"].isin({7, 10, 8, 30, 9, 27, 28})
	sub = sig[rest_mask]
	tb = _run_rows(sub, _sim_baseline, g0, cd)
	to = _run_rows(sub, _sim_t_open, g0, cd)
	_print_cmp(
		"其余",
		_summ(tb),
		_summ(to),
		"T日收盘买 + 8%%止损T+2起 + T+6兜底",
	)

	# 按单个 F 值
	print("\n" + "=" * 72)
	print("### 按 F 值（基准 vs T开盘，均收益差）")
	rows = []
	for f in sorted(sig["F"].dropna().unique()):
		fi = int(f)
		if fi in SKIP_F:
			continue
		sub = sig[sig["F"] == fi]
		tb = _run_rows(sub, _sim_baseline, g0, cd)
		to = _run_rows(sub, _sim_t_open, g0, cd)
		sb, so = _summ(tb), _summ(to)
		if sb["n"] < 3:
			continue
		rows.append(
			{
				"F": fi,
				"n_base": sb["n"],
				"mean_base": sb["mean"],
				"mean_t0o": so["mean"] if so["n"] else None,
				"diff": (so["mean"] - sb["mean"]) if so["n"] else None,
				"amt_diff": (so["sum_amt"] - sb["sum_amt"]) if so["n"] else None,
			}
		)
	if rows:
		rt = pd.DataFrame(rows).sort_values("diff", ascending=False)
		print(rt.to_string(index=False, float_format=lambda x: "%.2f" if abs(x) < 1000 else "%.0f"))


if __name__ == "__main__":
	main()
