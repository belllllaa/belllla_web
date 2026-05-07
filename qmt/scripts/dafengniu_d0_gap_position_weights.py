# -*- coding: utf-8 -*-
"""根据 D0 开盘涨跌幅分档的历史胜率，给出「标准仓 1 份」下的建议下单份额（0.1～0.5 档）。

  说明：
  · **不要用皮尔逊系数做权重**：D0 开盘涨跌幅与单笔收益的 Pearson 接近 0，只适合「分桶统计」，不适合线性加权预测。
  · 本脚本用分档的 **D1 胜率** 与 **D1~D3 至少一日为正** 合成得分，再线性映射到 [w_min, w_max]（默认 0.1～0.5）。
  · 另提供一版 **人工锚定档**（与下表策略说明一致），可在实盘中用 `weight_for_gap` 查表。

  用法:
    python qmt/scripts/dafengniu_d0_gap_position_weights.py
    python qmt/scripts/dafengniu_d0_gap_position_weights.py --csv path/to/dafengniu_sync_open_baostock.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)
from dafengniu_paths import SYNC_OPEN_BAOSTOCK_CSV  # noqa: E402

# ---------- 默认分档（与 exit_scan 一致）----------
DEFAULT_BINS = [-np.inf, -5, -2, 0, 2, 5, 8, np.inf]
DEFAULT_LABELS = ["<=-5%", "(-5,-2]", "(-2,0]", "(0,2]", "(2,5]", "(5,8]", ">8%"]

# ---------- 人工锚定档：经验胜率粗区间 → 相对份额（总意图「差则轻仓、好则半仓附近」）----------
# 当 CSV 样本过少时可退回该表；keys 为 DEFAULT_LABELS
ANCHOR_WEIGHT_BY_LABEL: dict[str, float] = {
	"<=-5%": 0.10,
	"(-5,-2]": 0.15,
	"(-2,0]": 0.50,
	"(0,2]": 0.40,
	"(2,5]": 0.35,
	"(5,8]": 0.25,
	">8%": 0.20,
}


def load_exit_frame(csv_path: str) -> pd.DataFrame:
	df = pd.read_csv(csv_path, encoding="utf-8-sig")
	for c in ("D前1_收盘", "D0_开盘", "D1_收盘", "D2_收盘", "D3_收盘"):
		if c in df.columns:
			df[c] = pd.to_numeric(df[c], errors="coerce")
	df["d0_gap"] = pd.to_numeric(df["D0开盘涨跌%"], errors="coerce")
	df = df.dropna(subset=["d0_gap", "D0_开盘", "D1_收盘", "D2_收盘", "D3_收盘"])
	df = df[df["D0_开盘"] > 0]
	for k in (1, 2, 3):
		df["ret_d%d" % k] = df["D%d_收盘" % k] / df["D0_开盘"] - 1.0
	df["any123"] = (df["ret_d1"] > 0) | (df["ret_d2"] > 0) | (df["ret_d3"] > 0)
	return df


def bin_stats(
	df: pd.DataFrame,
	bins: list[float] | None = None,
	labels: list[str] | None = None,
) -> pd.DataFrame:
	bins = bins or DEFAULT_BINS
	labels = labels or DEFAULT_LABELS
	df = df.copy()
	df["bin"] = pd.cut(df["d0_gap"], bins=bins, labels=labels)
	rows: list[dict] = []
	for name, sub in df.groupby("bin", observed=True):
		m = len(sub)
		if m == 0:
			continue
		p1 = (sub["ret_d1"] > 0).mean() * 100.0
		pa = sub["any123"].mean() * 100.0
		rows.append(
			{
				"分档": str(name),
				"n": m,
				"D1胜率_pct": round(p1, 2),
				"D1to3任一胜_pct": round(pa, 2),
				"中位D1收益_pct": round(sub["ret_d1"].median() * 100.0, 4),
				"gap均值_pct": round(sub["d0_gap"].mean(), 4),
			}
		)
	return pd.DataFrame(rows)


def smooth_weights(
	stats: pd.DataFrame,
	*,
	w_min: float = 0.1,
	w_max: float = 0.5,
	d1_weight: float = 0.45,
	any_weight: float = 0.55,
) -> pd.DataFrame:
	"""用胜率在档内归一化后线性映射到 [w_min, w_max]。"""
	s = stats.copy()
	s["得分"] = (s["D1胜率_pct"] / 100.0) * d1_weight + (s["D1to3任一胜_pct"] / 100.0) * any_weight
	sco = s["得分"].to_numpy(dtype=float)
	sc_min, sc_max = float(np.min(sco)), float(np.max(sco))
	if sc_max - sc_min < 1e-12:
		s["份额_平滑"] = (w_min + w_max) / 2.0
	else:
		s["份额_平滑"] = w_min + (sco - sc_min) / (sc_max - sc_min) * (w_max - w_min)
	s["份额_平滑"] = s["份额_平滑"].round(4)
	return s


def anchor_column(stats: pd.DataFrame) -> pd.Series:
	return stats["分档"].map(lambda x: ANCHOR_WEIGHT_BY_LABEL.get(str(x), float("nan")))


def weight_for_gap(
	gap_pct: float,
	mode: str = "anchor",
	smooth_table: pd.DataFrame | None = None,
) -> float:
	"""给定 D0 开盘涨跌幅(%)，返回建议份额。mode: anchor | smooth"""
	lbl = pd.cut(pd.Series([float(gap_pct)]), bins=DEFAULT_BINS, labels=DEFAULT_LABELS).iloc[0]
	if pd.isna(lbl):
		return 0.25
	label = str(lbl)
	if mode == "anchor":
		return float(ANCHOR_WEIGHT_BY_LABEL.get(label, 0.25))
	if smooth_table is not None and len(smooth_table):
		row = smooth_table[smooth_table["分档"] == label]
		if len(row):
			return float(row["份额_平滑"].iloc[0])
	return 0.25


def _main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--csv", default=SYNC_OPEN_BAOSTOCK_CSV, help="dafengniu_sync_open_baostock.csv")
	ap.add_argument("--w-min", type=float, default=0.1)
	ap.add_argument("--w-max", type=float, default=0.5)
	ap.add_argument("--d1-weight", type=float, default=0.45, help="合成得分里 D1 胜率权重")
	ap.add_argument("--any-weight", type=float, default=0.55, help="合成得分里 任一胜 权重")
	args = ap.parse_args()

	p = os.path.abspath(args.csv)
	if not os.path.isfile(p):
		print("找不到: %s" % p)
		sys.exit(1)

	df = load_exit_frame(p)
	st = bin_stats(df)
	st = smooth_weights(
		st,
		w_min=args.w_min,
		w_max=args.w_max,
		d1_weight=args.d1_weight,
		any_weight=args.any_weight,
	)
	st["份额_锚定"] = anchor_column(st)

	cols = [
		"分档",
		"n",
		"D1胜率_pct",
		"D1to3任一胜_pct",
		"中位D1收益_pct",
		"gap均值_pct",
		"份额_平滑",
		"份额_锚定",
	]
	print("=== D0 开盘涨跌幅 → 建议份额（标准仓=1 份时的系数；非多标的之和）===\n")
	print(
		"提示：皮尔逊相关在全域上≈0，仓位请按「分档胜率」或下表锚定，不要用相关当权重。\n"
	)
	print(st[cols].to_string(index=False))
	print()

	print("=== JSON（锚定档，便于抄到策略）===")
	j = {row["分档"]: row["份额_锚定"] for _, row in st.iterrows()}
	print(json.dumps(j, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	_main()
