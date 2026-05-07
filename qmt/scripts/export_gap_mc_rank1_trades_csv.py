# -*- coding: utf-8 -*-
"""从 gap 蒙特卡洛 JSON 取排序第 1 组 (e_d,e_ab,e_bc)，对样本 CSV 逐笔导出买入/卖出明细表。

排序与回测一致：combinations[0] 为「合计% 降序、再胜率降序」后的第一组（与 Canvas 排序#1 对齐）。

卖出日：开仓日 + d_idx 个工作日（pandas BDay），未剔除春节等长假，仅作参考日历。
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_gap_mc_1k_backtest import (
	DEFAULT_CSV,
	OUT_JSON,
	classify_entry,
	simulate_exit_detail,
	_f,
)

_DEFAULT_JSON = OUT_JSON
_DEFAULT_OUT = os.path.normpath(os.path.join(_SCRIPT_DIR, "output", "dafengniu_gap_mc_rank1_trades.csv"))


def _open_date_to_sell_yyyymmdd(open_date: str, d_idx: int) -> str:
	s = str(open_date).strip().replace("-", "").replace("/", "")[:8]
	if len(s) != 8 or not s.isdigit():
		return ""
	try:
		ts = pd.Timestamp(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
	except Exception:
		return ""
	out = ts + pd.offsets.BDay(int(d_idx))
	return out.strftime("%Y%m%d")


def export_rank1_trades(
	metrics_csv: str,
	mc_json: str,
	out_csv: str,
	combo_index: int = 0,
) -> str:
	with open(mc_json, "r", encoding="utf-8") as f:
		d = json.load(f)
	comb = d.get("combinations") or []
	if not comb:
		raise SystemExit("JSON 无 combinations")
	if combo_index < 0 or combo_index >= len(comb):
		raise SystemExit("combo_index 越界")
	c0 = comb[combo_index]
	e_d = float(c0["e_d_pct"]) / 100.0
	e_ab = float(c0["e_ab_pct"]) / 100.0
	e_bc = float(c0["e_bc_pct"]) / 100.0

	df = pd.read_csv(metrics_csv, encoding="utf-8-sig")
	rows_out: list[dict] = []

	for _, row in df.iterrows():
		if str(row.get("_error", "") or "").strip() == "short_tail":
			continue
		prev = _f(row, "D0前收盘")
		d0 = _f(row, "D0_开盘")
		low = _f(row, "D0_最低")
		if prev is None or prev <= 0 or d0 is None or d0 <= 0:
			continue
		gap = d0 / prev - 1.0
		detail = simulate_exit_detail(row)
		if detail is None:
			continue
		br, ent = classify_entry(gap, e_d, e_ab, e_bc, d0, low)
		if br is None or ent is None or ent <= 0:
			continue
		xp = float(detail["exit_px"])
		d_idx = int(detail["d_idx"])
		ret = (xp - ent) / ent
		open_date = str(row.get("开仓日", "") or "").strip()
		sell_date = _open_date_to_sell_yyyymmdd(open_date, d_idx)
		code = str(row.get("代码", "") or "").strip()

		rows_out.append(
			{
				"排序组合序号": combo_index + 1,
				"组合e_d_pct": c0.get("e_d_pct"),
				"组合e_ab_pct": c0.get("e_ab_pct"),
				"组合e_bc_pct": c0.get("e_bc_pct"),
				"代码": code,
				"买入日": open_date,
				"卖出日": sell_date,
				"卖出相对日": f"D{d_idx}",
				"档位": br,
				"买入价": round(ent, 6),
				"卖出价": round(xp, 6),
				"收益率_pct": round(ret * 100.0, 4),
				"平仓原因": detail.get("reason", ""),
				"平仓价来源": detail.get("leg", ""),
			}
		)

	os.makedirs(os.path.dirname(out_csv), exist_ok=True)
	out_df = pd.DataFrame(rows_out)
	out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
	return out_csv


def main() -> None:
	metrics = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
	mc_json = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_JSON
	out_csv = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else _DEFAULT_OUT
	idx = int(sys.argv[4]) if len(sys.argv) > 4 else 0
	path = export_rank1_trades(metrics, mc_json, out_csv, combo_index=idx)
	print("[csv]", path, "rows", len(pd.read_csv(path, encoding="utf-8-sig")))


if __name__ == "__main__":
	main()
