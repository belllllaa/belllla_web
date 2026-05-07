# -*- coding: utf-8 -*-
"""买入规则组合扫描（方案1+方案2）：固定卖出与回测 D 一致，扫分档边界与 B/C 折扣乘数。

  固定卖出：开盘 SL=−10% · TP=+6.5%，盘中同档；上证收盘破 MA5 尾盘；D1 弱 0.5%；最长 D3。
  固定门控：T−1 上证收 ≥ T−1 MA5（--no-sse-gate 可关）。

  方案1：扫 gap 分档边界 A_LO / A_HI / B_HI（D|A|B|C 分界，与 gap_bracket 一致）。
  方案2：扫 B、C 档首买相对今开的折扣 B_MULT、C_MULT（D0_最低 需能触价方成交）。

用法：
  python qmt/scripts/dafengniu_buy_combo_scan.py
  python qmt/scripts/dafengniu_buy_combo_scan.py --coarse
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_benchmark_ref_trades import (  # noqa: E402
	A_HI as REF_A_HI,
	A_LO as REF_A_LO,
	B_HI as REF_B_HI,
	B_MULT as REF_B_MULT,
	C_MULT as REF_C_MULT,
	buy_price_and_ok_with,
	compute_extended_metrics,
	gap_bracket_with,
	_f,
	_prep_sse_index,
)
from dafengniu_paths import (  # noqa: E402
	BUY_COMBO_SCAN_META_JSON,
	BUY_COMBO_SCAN_ROUND12_CSV,
	SYNC_OPEN_BAOSTOCK_CSV,
)
from dafengniu_d0_gap_position_weights import weight_for_gap  # noqa: E402
from dafengniu_sell_combo_scan import load_data, simulate_exit_params  # noqa: E402

# ---------- 加权展示：将 Σ(w×r) 折算为与「收益合计_pct」同一量纲（笔百分点简单加总）----------
# 基准名义份额：假设每笔固定买 0.5 「标准仓」时，加权折算 Σ(w×r)/REF → 当每笔锚定 w=0.5 时等于未加权收益合计。
GAP_WEIGHT_DISPLAY_REF = 0.5

# ---------- 固定卖出（与选定回测 D / 用户约定一致）----------
FIXED_SL = -0.10
FIXED_TP = 0.065
FIXED_D1_WEAK = 0.005
FIXED_SSE_TAIL = "ma5"
FIXED_MAX_DAY = 3

# ---------- 方案1：分档边界网格（全档 3×3×3）----------
GRID_A_LO = (-0.06, -0.05, -0.04)
GRID_A_HI = (0.02, 0.03, 0.04)
GRID_B_HI = (0.06, 0.07, 0.08)

# 粗网格：仅边界与仓库默认各差一档，共 2×2×2=8 再 × 方案2
GRID_A_LO_COARSE = (-0.05, -0.04)
GRID_A_HI_COARSE = (0.02, 0.03)
GRID_B_HI_COARSE = (0.06, 0.07)

# ---------- 方案2：B/C 折扣乘数网格（3×3）----------
GRID_B_MULT = (0.96, 0.97, 0.98)
GRID_C_MULT = (0.95, 0.96, 0.97)
GRID_B_MULT_COARSE = (0.97, 0.98)
GRID_C_MULT_COARSE = (0.95, 0.96)


def _valid_bracket_order(a_lo: float, a_hi: float, b_hi: float) -> bool:
	return a_lo < a_hi < b_hi


def _label_buy_scan(a_lo: float, a_hi: float, b_hi: float, b_mult: float, c_mult: float) -> str:
	return "买扫|A_LO=%.1f%%·A_HI=%.1f%%·B_HI=%.1f%%·B×=%.2f·C×=%.2f" % (
		a_lo * 100,
		a_hi * 100,
		b_hi * 100,
		b_mult,
		c_mult,
	)


def _collect_buy_combo_trades(
	df: pd.DataFrame,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	*,
	a_lo: float,
	a_hi: float,
	b_hi: float,
	b_mult: float,
	c_mult: float,
	require_sse_ma5: bool,
) -> tuple[list[tuple[float, float, str]], dict[str, int]]:
	"""收集每笔 (收益百分点, D0开盘涨跌幅%, 开仓日字符串)；用于未加权与锚定份额加权。"""
	stats_skip = {
		"gate_ma5": 0,
		"no_bracket": 0,
		"no_buy_trigger": 0,
		"bad_gap_data": 0,
		"no_calendar": 0,
		"sim_fail": 0,
	}
	trades: list[tuple[float, float, str]] = []

	for _, row in df.iterrows():
		open_raw = str(row["开仓日"]).strip().replace(".0", "")
		if len(open_raw) < 8 or not open_raw[:8].isdigit():
			continue
		open_date_str = open_raw[:8]

		prev_c = _f(row, "D前1_收盘")
		d0o = _f(row, "D0_开盘")
		d0_low = _f(row, "D0_最低")
		if prev_c is None or d0o is None or prev_c <= 0 or d0o <= 0:
			stats_skip["bad_gap_data"] += 1
			continue

		gap = d0o / prev_c - 1.0
		gap_pct = gap * 100.0
		br = gap_bracket_with(gap, a_lo, a_hi, b_hi)
		if br is None:
			stats_skip["no_bracket"] += 1
			continue

		try:
			target = datetime.strptime(open_date_str, "%Y%m%d").date()
		except ValueError:
			stats_skip["bad_gap_data"] += 1
			continue

		j_d0 = bisect.bisect_left(sorted_dates, target)
		if j_d0 >= len(sorted_dates):
			stats_skip["no_calendar"] += 1
			continue
		d0 = sorted_dates[j_d0]
		if j_d0 + FIXED_MAX_DAY >= len(sorted_dates):
			stats_skip["no_calendar"] += 1
			continue

		if require_sse_ma5:
			if j_d0 == 0:
				stats_skip["gate_ma5"] += 1
				continue
			t_minus_1 = sorted_dates[j_d0 - 1]
			try:
				rmi = sse_idx.loc[t_minus_1]
				sc, sm5 = float(rmi["close"]), float(rmi["ma5"])
			except (KeyError, TypeError, ValueError):
				stats_skip["gate_ma5"] += 1
				continue
			if not (np.isfinite(sc) and np.isfinite(sm5) and sc >= sm5):
				stats_skip["gate_ma5"] += 1
				continue

		d0_low_eff = d0_low if d0_low is not None else d0o
		bp, _skip = buy_price_and_ok_with(br, d0o, d0_low_eff, b_mult, c_mult)
		if bp is None:
			stats_skip["no_buy_trigger"] += 1
			continue

		sell_px, _reason, _d_tag, _sell_day = simulate_exit_params(
			d0o,
			row,
			sse_idx,
			sorted_dates,
			j_d0,
			sl=FIXED_SL,
			tp=FIXED_TP,
			d1_weak=FIXED_D1_WEAK,
			sse_tail_exit=FIXED_SSE_TAIL,
			max_day=FIXED_MAX_DAY,
			skip_intraday=False,
			sl_intraday=FIXED_SL,
			tp_intraday=FIXED_TP,
		)
		if sell_px is None:
			stats_skip["sim_fail"] += 1
			continue

		ret = (sell_px / bp - 1.0) * 100.0
		trades.append((ret, gap_pct, d0.strftime("%Y%m%d")))

	return trades, stats_skip


def _gap_pct_in_c_open_buy_bins(gap_pct: float) -> bool:
	"""ORDER C 组：开盘涨跌%落在 (-5%, 8%]（与五档份额切片一致；≤−5% 与 >8% 不买）。"""
	x = float(gap_pct)
	return x > -5.0 and x <= 8.0


def _collect_five_bin_open_trades(
	df: pd.DataFrame,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	*,
	require_sse_ma5: bool,
) -> tuple[list[tuple[float, float, str]], dict[str, int]]:
	"""与四档 gap / B× / C× 无关：仅当 D0 开盘相对昨收涨跌%落入 (-5%, 8%] 时，以今开买入并回放卖出。

	五档权重系数由 ORDER 画布 `ORDER_C_GAP_BIN_COEF_RAW` 归一化后作用于 Σ(w×r)，不在此函数内处理。
	"""
	stats_skip = {
		"gate_ma5": 0,
		"outside_open_buy_bins": 0,
		"bad_gap_data": 0,
		"no_calendar": 0,
		"sim_fail": 0,
	}
	trades: list[tuple[float, float, str]] = []

	for _, row in df.iterrows():
		open_raw = str(row["开仓日"]).strip().replace(".0", "")
		if len(open_raw) < 8 or not open_raw[:8].isdigit():
			continue
		open_date_str = open_raw[:8]

		prev_c = _f(row, "D前1_收盘")
		d0o = _f(row, "D0_开盘")
		if prev_c is None or d0o is None or prev_c <= 0 or d0o <= 0:
			stats_skip["bad_gap_data"] += 1
			continue

		gap = d0o / prev_c - 1.0
		gap_pct = gap * 100.0
		if not _gap_pct_in_c_open_buy_bins(gap_pct):
			stats_skip["outside_open_buy_bins"] += 1
			continue

		try:
			target = datetime.strptime(open_date_str, "%Y%m%d").date()
		except ValueError:
			stats_skip["bad_gap_data"] += 1
			continue

		j_d0 = bisect.bisect_left(sorted_dates, target)
		if j_d0 >= len(sorted_dates):
			stats_skip["no_calendar"] += 1
			continue
		d0 = sorted_dates[j_d0]
		if j_d0 + FIXED_MAX_DAY >= len(sorted_dates):
			stats_skip["no_calendar"] += 1
			continue

		if require_sse_ma5:
			if j_d0 == 0:
				stats_skip["gate_ma5"] += 1
				continue
			t_minus_1 = sorted_dates[j_d0 - 1]
			try:
				rmi = sse_idx.loc[t_minus_1]
				sc, sm5 = float(rmi["close"]), float(rmi["ma5"])
			except (KeyError, TypeError, ValueError):
				stats_skip["gate_ma5"] += 1
				continue
			if not (np.isfinite(sc) and np.isfinite(sm5) and sc >= sm5):
				stats_skip["gate_ma5"] += 1
				continue

		bp = float(d0o)

		sell_px, _reason, _d_tag, _sell_day = simulate_exit_params(
			d0o,
			row,
			sse_idx,
			sorted_dates,
			j_d0,
			sl=FIXED_SL,
			tp=FIXED_TP,
			d1_weak=FIXED_D1_WEAK,
			sse_tail_exit=FIXED_SSE_TAIL,
			max_day=FIXED_MAX_DAY,
			skip_intraday=False,
			sl_intraday=FIXED_SL,
			tp_intraday=FIXED_TP,
		)
		if sell_px is None:
			stats_skip["sim_fail"] += 1
			continue

		ret = (sell_px / bp - 1.0) * 100.0
		trades.append((ret, gap_pct, d0.strftime("%Y%m%d")))

	return trades, stats_skip


def _metrics_unweighted(trades: list[tuple[float, float, str]], stats_skip: dict[str, int]) -> dict:
	rets = [t[0] for t in trades]
	buy_days = [t[2] for t in trades]
	arr = np.array(rets, dtype=float)
	n = len(arr)
	sum_r = float(np.sum(arr)) if n else 0.0
	mean_r = float(np.mean(arr)) if n else 0.0
	std_r = float(np.std(arr, ddof=1)) if n > 1 else 0.0
	sharpe = (mean_r / std_r) if std_r > 1e-12 else (float("inf") if n >= 1 and abs(mean_r) > 1e-12 else 0.0)
	wins = int(np.sum(arr > 0)) if n else 0
	win_rate = (wins / n * 100.0) if n else 0.0
	ext = compute_extended_metrics(arr, buy_days)

	return {
		"成交笔数": n,
		"收益合计_pct": round(sum_r, 4),
		"固定份额0p5_合计_pct": round(GAP_WEIGHT_DISPLAY_REF * sum_r, 4),
		"单笔均值_pct": round(mean_r, 4),
		"夏普_笔收益": round(sharpe, 4) if np.isfinite(sharpe) else None,
		"胜率_pct": round(win_rate, 4),
		"波动率_笔收益标准差_pct": ext.get("波动率_笔收益标准差_pct"),
		"最大回撤_链式净值_pct": ext.get("最大回撤_链式净值_pct"),
		"盈亏比_均盈除以均亏绝对值": ext.get("盈亏比_均盈除以均亏绝对值"),
		"盈亏比_总盈利除以总亏损绝对值": ext.get("盈亏比_总盈利除以总亏损绝对值"),
		"跳过统计": stats_skip,
	}


def _metrics_gap_anchor_weighted(trades: list[tuple[float, float, str]]) -> dict:
	"""D0 开盘涨跌幅 → 锚定份额；单笔组合贡献 = 份额 × 笔收益(百分点)；链式净值按每步 w*r 复利。"""
	if not trades:
		return {
			"份额合计": 0.0,
			"加权收益合计_pts": 0.0,
			"加权收益率合计_pct": 0.0,
			"加权笔均_pct": 0.0,
			"加权胜率_pct": 0.0,
			"夏普_笔收益_加权": None,
			"波动率_笔收益标准差_pct_加权": None,
			"最大回撤_链式净值_pct_加权": None,
			"盈亏比_均盈除以均亏绝对值_加权": None,
			"盈亏比_总盈利除以总亏损绝对值_加权": None,
		}
	rets = np.array([t[0] for t in trades], dtype=float)
	gap_pct = np.array([t[1] for t in trades], dtype=float)
	buy_days = [t[2] for t in trades]
	w = np.array([weight_for_gap(float(g), "anchor") for g in gap_pct], dtype=float)
	sum_w = float(np.sum(w))
	sum_wr = float(np.sum(w * rets))
	# 折算为与「收益合计_pct」（Σr）同一刻度：Σ(w×r)/REF；REF=0.5 且每笔 w=0.5 时等于 Σr
	sum_wr_scaled = sum_wr / GAP_WEIGHT_DISPLAY_REF if GAP_WEIGHT_DISPLAY_REF > 1e-15 else 0.0
	wmean = sum_wr / sum_w if sum_w > 1e-15 else 0.0
	win_w = float(np.sum(w * (rets > 0.0)) / sum_w * 100.0) if sum_w > 1e-15 else 0.0
	mu = wmean
	var = float(np.sum(w * (rets - mu) ** 2) / sum_w) if sum_w > 1e-15 else 0.0
	sharpe_w = (mu / (var**0.5)) if var > 1e-12 else 0.0
	eff_pts = w * rets
	ext_w = compute_extended_metrics(eff_pts, buy_days)
	return {
		"份额合计": round(sum_w, 4),
		"加权收益合计_pts": round(sum_wr, 4),
		"加权收益率合计_pct": round(sum_wr_scaled, 4),
		"加权笔均_pct": round(wmean, 4),
		"加权胜率_pct": round(win_w, 4),
		"夏普_笔收益_加权": round(sharpe_w, 4),
		"波动率_笔收益标准差_pct_加权": ext_w.get("波动率_笔收益标准差_pct"),
		"最大回撤_链式净值_pct_加权": ext_w.get("最大回撤_链式净值_pct"),
		"盈亏比_均盈除以均亏绝对值_加权": ext_w.get("盈亏比_均盈除以均亏绝对值"),
		"盈亏比_总盈利除以总亏损绝对值_加权": ext_w.get("盈亏比_总盈利除以总亏损绝对值"),
	}


def run_buy_combo_scenario(
	df: pd.DataFrame,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	*,
	a_lo: float,
	a_hi: float,
	b_hi: float,
	b_mult: float,
	c_mult: float,
	require_sse_ma5: bool,
) -> dict:
	"""与 dafengniu_sell_combo_scan.run_scenario 同序，但买入分档与 B/C 折扣由参数指定；卖出参数固定。"""
	trades, stats_skip = _collect_buy_combo_trades(
		df,
		sse_idx,
		sorted_dates,
		a_lo=a_lo,
		a_hi=a_hi,
		b_hi=b_hi,
		b_mult=b_mult,
		c_mult=c_mult,
		require_sse_ma5=require_sse_ma5,
	)
	return _metrics_unweighted(trades, stats_skip)


def run_buy_combo_scenario_with_gap_weights(
	df: pd.DataFrame,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	*,
	a_lo: float,
	a_hi: float,
	b_hi: float,
	b_mult: float,
	c_mult: float,
	require_sse_ma5: bool,
) -> dict:
	"""未加权指标 + D0 开盘锚定份额加权指标（见 dafengniu_d0_gap_position_weights）。"""
	trades, stats_skip = _collect_buy_combo_trades(
		df,
		sse_idx,
		sorted_dates,
		a_lo=a_lo,
		a_hi=a_hi,
		b_hi=b_hi,
		b_mult=b_mult,
		c_mult=c_mult,
		require_sse_ma5=require_sse_ma5,
	)
	uw = _metrics_unweighted(trades, stats_skip)
	wt = _metrics_gap_anchor_weighted(trades)
	out = {**uw, **wt}
	return out


def _is_baseline_row(
	a_lo: float, a_hi: float, b_hi: float, b_mult: float, c_mult: float
) -> bool:
	return (
		abs(a_lo - REF_A_LO) < 1e-9
		and abs(a_hi - REF_A_HI) < 1e-9
		and abs(b_hi - REF_B_HI) < 1e-9
		and abs(b_mult - REF_B_MULT) < 1e-9
		and abs(c_mult - REF_C_MULT) < 1e-9
	)


def scan_round_1_2(
	df: pd.DataFrame,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	require_ma5: bool,
	*,
	a_lo_list: tuple[float, ...],
	a_hi_list: tuple[float, ...],
	b_hi_list: tuple[float, ...],
	b_mult_list: tuple[float, ...],
	c_mult_list: tuple[float, ...],
) -> pd.DataFrame:
	rows: list[dict] = []
	for a_lo in a_lo_list:
		for a_hi in a_hi_list:
			for b_hi in b_hi_list:
				if not _valid_bracket_order(a_lo, a_hi, b_hi):
					continue
				for b_mult in b_mult_list:
					for c_mult in c_mult_list:
						lbl = _label_buy_scan(a_lo, a_hi, b_hi, b_mult, c_mult)
						if _is_baseline_row(a_lo, a_hi, b_hi, b_mult, c_mult):
							lbl = "基准|" + lbl
						m = run_buy_combo_scenario_with_gap_weights(
							df,
							sse_idx,
							sorted_dates,
							a_lo=a_lo,
							a_hi=a_hi,
							b_hi=b_hi,
							b_mult=b_mult,
							c_mult=c_mult,
							require_sse_ma5=require_ma5,
						)
						row_out = {
							"轮次": "买1+2",
							"方案标签": lbl,
							"A_LO": a_lo,
							"A_HI": a_hi,
							"B_HI": b_hi,
							"B_MULT": b_mult,
							"C_MULT": c_mult,
							"与仓库基准买入一致": _is_baseline_row(a_lo, a_hi, b_hi, b_mult, c_mult),
							**{k: v for k, v in m.items() if k != "跳过统计"},
						}
						rows.append(row_out)

	out = pd.DataFrame(rows)
	if not len(out):
		return out
	return out.sort_values(
		by=["收益合计_pct", "胜率_pct", "成交笔数", "最大回撤_链式净值_pct"],
		ascending=[False, False, False, True],
		na_position="last",
	).reset_index(drop=True)


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in", "-i", dest="inp", default=SYNC_OPEN_BAOSTOCK_CSV)
	ap.add_argument("--no-sse-gate", action="store_true", help="关闭 T−1 上证≥MA5 门控")
	ap.add_argument(
		"--coarse",
		action="store_true",
		help="使用较粗网格（方案1 2×2×2 × 方案2 2×2），便于快速试跑",
	)
	args = ap.parse_args()

	inp = os.path.abspath(args.inp)
	if not os.path.isfile(inp):
		print("[错误] 找不到 %s" % inp)
		sys.exit(1)

	require_ma5 = not args.no_sse_gate
	df, sse_idx, sorted_dates = load_data(inp)

	if args.coarse:
		a_lo_l, a_hi_l, b_hi_l = GRID_A_LO_COARSE, GRID_A_HI_COARSE, GRID_B_HI_COARSE
		b_ml, c_ml = GRID_B_MULT_COARSE, GRID_C_MULT_COARSE
	else:
		a_lo_l, a_hi_l, b_hi_l = GRID_A_LO, GRID_A_HI, GRID_B_HI
		b_ml, c_ml = GRID_B_MULT, GRID_C_MULT

	sheet = scan_round_1_2(
		df,
		sse_idx,
		sorted_dates,
		require_ma5,
		a_lo_list=a_lo_l,
		a_hi_list=a_hi_l,
		b_hi_list=b_hi_l,
		b_mult_list=b_ml,
		c_mult_list=c_ml,
	)

	os.makedirs(os.path.dirname(BUY_COMBO_SCAN_ROUND12_CSV), exist_ok=True)
	sheet.to_csv(BUY_COMBO_SCAN_ROUND12_CSV, index=False, encoding="utf-8-sig")

	n_combo = len(a_lo_l) * len(a_hi_l) * len(b_hi_l) * len(b_ml) * len(c_ml)
	# 无效顺序组合会略少
	meta = {
		"输入": inp,
		"require_sse_above_ma5": require_ma5,
		"固定卖出": {
			"sl": FIXED_SL,
			"tp": FIXED_TP,
			"sl_intraday": FIXED_SL,
			"tp_intraday": FIXED_TP,
			"d1_weak": FIXED_D1_WEAK,
			"sse_tail_exit": FIXED_SSE_TAIL,
			"max_day": FIXED_MAX_DAY,
			"skip_intraday": False,
		},
		"仓库基准买入参数_对照": {
			"A_LO": REF_A_LO,
			"A_HI": REF_A_HI,
			"B_HI": REF_B_HI,
			"B_MULT": REF_B_MULT,
			"C_MULT": REF_C_MULT,
		},
		"方案1_边界网格": {"A_LO": list(a_lo_l), "A_HI": list(a_hi_l), "B_HI": list(b_hi_l)},
		"方案2_折扣网格": {"B_MULT": list(b_ml), "C_MULT": list(c_ml)},
		"D0开盘锚定份额加权": (
			"dafengniu_d0_gap_position_weights.ANCHOR_WEIGHT_BY_LABEL；单笔贡献=份额×笔收益%；"
			"加权收益率合计_pct = Σ(w×r)/GAP_WEIGHT_DISPLAY_REF（默认0.5），与收益合计_pct同量纲；"
			"固定份额0p5_合计_pct = 0.5×Σr 为对照"
		),
		"coarse": bool(args.coarse),
		"约计笛卡尔积行数": n_combo,
		"输出_csv": BUY_COMBO_SCAN_ROUND12_CSV,
		"行数_实际": len(sheet),
	}
	with open(BUY_COMBO_SCAN_META_JSON, "w", encoding="utf-8") as f:
		json.dump(meta, f, ensure_ascii=False, indent=2)

	print("[完成] %s 行 %d -> %s" % (BUY_COMBO_SCAN_ROUND12_CSV, len(sheet), BUY_COMBO_SCAN_ROUND12_CSV))
	print("[完成] meta -> %s" % BUY_COMBO_SCAN_META_JSON)


if __name__ == "__main__":
	main()
