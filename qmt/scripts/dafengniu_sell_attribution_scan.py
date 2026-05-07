# -*- coding: utf-8 -*-
"""SL/TP 双轴网格上的平仓归因统计。

- 轴：相对 D0 开盘的止损/止盈，自 −10%～+10%，步长 1%（各 21 点 → 21×21 组）。
- 模拟顺序与 dafengniu_sell_combo_scan 一致：开盘 → 同档盘中 → B 上证尾盘(MA5) → C（D1 弱/转弱/到期）；B、C 参数同仓库基准。
- 输出：各组 笔数_A/D/B/C、占比、全路径收益与回撤等。
- 过滤（仅保留行）：最大回撤(链式净值) ≤ 30；收益合计% ≥ 基准全路径（基准 SL/TP=−7%/+7% 同条件）。

用法：
  python qmt/scripts/dafengniu_sell_attribution_scan.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_sell_combo_scan import (  # noqa: E402
	BASE_D1_WEAK,
	BASE_MAX_DAY,
	BASE_SL,
	BASE_SSE_TAIL,
	BASE_TP,
	load_data,
	run_scenario,
	run_scenario_attribution,
)
from dafengniu_paths import SELL_ATTRIBUTION_GRID_CSV, SYNC_OPEN_BAOSTOCK_CSV

# 双轴：−10%～+10% 步长 1%（共 21 个取值）
def _grid_pcts() -> list[float]:
	return [round(-0.10 + i * 0.01, 6) for i in range(21)]


MAX_DD_PCT = 30.0


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in", "-i", dest="inp", default=SYNC_OPEN_BAOSTOCK_CSV)
	ap.add_argument("--no-sse-gate", action="store_true", help="关闭 T−1 上证≥MA5 门控")
	args = ap.parse_args()

	inp = os.path.abspath(args.inp)
	if not os.path.isfile(inp):
		print("[错误] 找不到 %s" % inp)
		sys.exit(1)

	require_ma5 = not args.no_sse_gate
	df, sse_idx, sorted_dates = load_data(inp)

	bench = run_scenario(
		df,
		sse_idx,
		sorted_dates,
		sl=BASE_SL,
		tp=BASE_TP,
		d1_weak=BASE_D1_WEAK,
		sse_tail_exit=BASE_SSE_TAIL,
		max_day=BASE_MAX_DAY,
		require_sse_ma5=require_ma5,
	)
	bench_sum = float(bench["收益合计_pct"])
	bench_n = int(bench["成交笔数"])
	bench_mdd = bench.get("最大回撤_链式净值_pct")

	sl_list = _grid_pcts()
	tp_list = _grid_pcts()
	rows_out: list[dict] = []
	n_scan = 0
	for sl in sl_list:
		for tp in tp_list:
			n_scan += 1
			m = run_scenario_attribution(
				df,
				sse_idx,
				sorted_dates,
				sl=sl,
				tp=tp,
				d1_weak=BASE_D1_WEAK,
				sse_tail_exit=BASE_SSE_TAIL,
				max_day=BASE_MAX_DAY,
				require_sse_ma5=require_ma5,
			)
			mdd = m.get("最大回撤_链式净值_pct")
			sum_r = float(m["收益合计_pct"])
			if mdd is None or float(mdd) > MAX_DD_PCT:
				continue
			if sum_r < bench_sum:
				continue
			label = "ATTR|SL=%.1f%% TP=%.1f%%" % (sl * 100, tp * 100)
			row = {
				"方案标签": label,
				"止损_sl": sl,
				"止盈_tp": tp,
				"基准收益合计_pct": bench_sum,
				**{k: v for k, v in m.items() if k != "跳过统计"},
			}
			rows_out.append(row)

	out_df = pd.DataFrame(rows_out)
	if len(out_df):
		out_df = out_df.sort_values("收益合计_pct", ascending=False)

	os.makedirs(os.path.dirname(SELL_ATTRIBUTION_GRID_CSV), exist_ok=True)
	out_df.to_csv(SELL_ATTRIBUTION_GRID_CSV, index=False, encoding="utf-8-sig")

	meta_path = SELL_ATTRIBUTION_GRID_CSV.replace(".csv", "_meta.json")
	meta = {
		"输入": inp,
		"网格": {"sl_tp": "-10%~+10% 步长1%", "每轴点数": 21, "组合数": 21 * 21},
		"扫描组合数": n_scan,
		"过滤后行数": len(out_df),
		"过滤规则": {
			"最大回撤_链式净值_pct上限": MAX_DD_PCT,
			"收益合计不低于基准全路径": True,
		},
		"基准全路径": {
			"止损_sl": BASE_SL,
			"止盈_tp": BASE_TP,
			"收益合计_pct": bench_sum,
			"成交笔数": bench_n,
			"最大回撤_链式净值_pct": bench_mdd,
		},
		"归因分组": "A=开盘止损止盈 D=盘中触价 B=上证指数清仓 C=D1弱/转弱/到期等",
	}
	with open(meta_path, "w", encoding="utf-8") as f:
		json.dump(meta, f, ensure_ascii=False, indent=2)

	print("[完成] 扫描 %d 组，过滤后 %d 行 -> %s" % (n_scan, len(out_df), SELL_ATTRIBUTION_GRID_CSV))
	print("[完成] meta -> %s" % meta_path)


if __name__ == "__main__":
	main()
