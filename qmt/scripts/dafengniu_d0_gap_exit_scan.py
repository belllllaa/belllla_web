# -*- coding: utf-8 -*-
"""遍历 dafengniu_sync_open_baostock.csv：D0开盘涨跌幅 与 D1/D2/D3 收盘相对 D0 开盘买入 的相关性与分档胜率。

  定义：
  · D0 开盘涨跌幅：列 D0开盘涨跌%（与 D0_开盘/D前1_收盘-1 基本一致）
  · 持仓收益：以 D0_开盘 为买入价，Dk_收盘 为卖出价，ret_k = Dk_收盘/D0_开盘 - 1
  · 「D1~D3 任一为正」: max(ret1,ret2,ret3) > 0

  用法: python qmt/scripts/dafengniu_d0_gap_exit_scan.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)
from dafengniu_paths import SYNC_OPEN_BAOSTOCK_CSV  # noqa: E402


def _spearman(a: pd.Series, b: pd.Series) -> float:
	return a.rank().corr(b.rank())


def main() -> None:
	p = os.path.abspath(SYNC_OPEN_BAOSTOCK_CSV)
	if not os.path.isfile(p):
		print("找不到: %s" % p)
		sys.exit(1)

	df = pd.read_csv(p, encoding="utf-8-sig")
	for c in ("D前1_收盘", "D0_开盘", "D1_开盘", "D1_收盘", "D2_收盘", "D3_收盘"):
		if c in df.columns:
			df[c] = pd.to_numeric(df[c], errors="coerce")
	df["d0_gap"] = pd.to_numeric(df["D0开盘涨跌%"], errors="coerce")
	df = df.dropna(subset=["d0_gap", "D0_开盘", "D前1_收盘", "D1_收盘", "D2_收盘", "D3_收盘"])
	df = df[df["D0_开盘"] > 0]

	for k in (1, 2, 3):
		df["ret_d%d" % k] = df["D%d_收盘" % k] / df["D0_开盘"] - 1.0

	df["d1_day"] = df["D1_收盘"] / df["D1_开盘"] - 1.0
	df["any123"] = (df["ret_d1"] > 0) | (df["ret_d2"] > 0) | (df["ret_d3"] > 0)
	df["all123"] = (df["ret_d1"] > 0) & (df["ret_d2"] > 0) & (df["ret_d3"] > 0)
	df["best123"] = df[["ret_d1", "ret_d2", "ret_d3"]].max(axis=1)

	n = len(df)
	print("样本 N=%d（已剔除行情缺失行）" % n)
	print()

	print("【相关性】D0开盘涨跌幅(%%) vs 持仓收益(Dk收/D0开-1)")
	for k in (1, 2, 3):
		r = df["ret_d%d" % k]
		print(
			"  D%d 卖出  Pearson=%7.4f  Spearman=%7.4f"
			% (k, df["d0_gap"].corr(r), _spearman(df["d0_gap"], r))
		)
	print(
		"  D1当日涨跌(D1收/D1开-1)  Pearson=%7.4f  Spearman=%7.4f"
		% (df["d0_gap"].corr(df["d1_day"]), _spearman(df["d0_gap"], df["d1_day"]))
	)
	print(
		"  max(ret_d1,d2,d3)      Pearson=%7.4f"
		% (df["d0_gap"].corr(df["best123"]),)
	)
	print()

	print("【全样本胜率】买入=D0开盘，卖出=Dk收盘，收益>0")
	for k in (1, 2, 3):
		print("  D%d: %.1f%%" % (k, (df["ret_d%d" % k] > 0).mean() * 100.0))
	print("  D1~D3 至少一日为正: %.1f%%" % (df["any123"].mean() * 100.0))
	print("  D1~D3 三日全为正: %.1f%%" % (df["all123"].mean() * 100.0))
	print("  max(D1~D3收盘收益)>0: %.1f%%" % ((df["best123"] > 0).mean() * 100.0))
	print()

	print("【固定分档】D0开盘涨跌幅 -> D1/D2/D3 胜率(%%) / 任一为正 / 中位 ret_d1(%%)")
	bins = [-np.inf, -5, -2, 0, 2, 5, 8, np.inf]
	labels = ["<=-5", "(-5,-2]", "(-2,0]", "(0,2]", "(2,5]", "(5,8]", ">8"]
	df["bin"] = pd.cut(df["d0_gap"], bins=bins, labels=labels)
	for name, sub in df.groupby("bin", observed=True):
		m = len(sub)
		if m == 0:
			continue
		print(
			"  %-8s n=%4d  D1=%5.1f%% D2=%5.1f%% D3=%5.1f%% 任一=%5.1f%%  中位D1=%7.2f%%  gap均值=%.2f%%"
			% (
				str(name),
				m,
				(sub["ret_d1"] > 0).mean() * 100,
				(sub["ret_d2"] > 0).mean() * 100,
				(sub["ret_d3"] > 0).mean() * 100,
				sub["any123"].mean() * 100,
				sub["ret_d1"].median() * 100,
				sub["d0_gap"].mean(),
			)
		)
	print()

	print("【五分位】按 D0 开盘涨跌幅")
	df["q5"] = pd.qcut(df["d0_gap"], 5, duplicates="drop")
	for name, sub in df.groupby("q5", observed=True):
		print(
			"  %s  n=%d  gap∈[%.2f, %.2f] 均值=%.2f%% -> D1胜率=%.1f%% 任一=%.1f%%"
			% (
				str(name),
				len(sub),
				sub["d0_gap"].min(),
				sub["d0_gap"].max(),
				sub["d0_gap"].mean(),
				(sub["ret_d1"] > 0).mean() * 100,
				sub["any123"].mean() * 100,
			)
		)


if __name__ == "__main__":
	main()
