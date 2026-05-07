# -*- coding: utf-8 -*-
"""ORDER 画布：A/B/C 三组。

· A/B：`_collect_buy_combo_trades`（四档 gap + B×/C× 触价）。
· C：`_collect_five_bin_open_trades` —— D0 开盘涨跌%∈(-5%,8%] 则 **今开买入**（不经四档 gap 与 B×/C×）。
     组合扫描/可比笔均仍可用 **五档归一化系数**（`ORDER_C_GAP_BIN_COEF_RAW`→`ORDER_C_BIN_WEIGHTS`，Σ=1）算 Σ(w×r)；
     **实盘 ORDER-C 资金规则**以 `dafengniu_order_c_ladder` 为准（日预算等额分笔 + 分档三腿 + 全局补仓阈值）。

A/B 买扫填 ORDER_GROUP_SPECS；C 逻辑见 `dafengniu_buy_combo_scan._collect_five_bin_open_trades`。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Literal, TypedDict

import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_benchmark_ref_trades import compute_extended_metrics, gap_bracket_with  # noqa: E402
from dafengniu_buy_combo_scan import (  # noqa: E402
	_collect_buy_combo_trades,
	_collect_five_bin_open_trades,
)
from dafengniu_order_bucket_tables import ORDER_7_LABELS, _bin7_label  # noqa: E402
from dafengniu_paths import SYNC_OPEN_BAOSTOCK_CSV  # noqa: E402
from dafengniu_sell_combo_scan import load_data  # noqa: E402

class _GroupSpecCore(TypedDict):
	row_label: str
	rule_summary: str
	a_lo: float
	a_hi: float
	b_hi: float
	b_mult: float
	c_mult: float
	position: Literal["unit", "filter_ab", "bin5"]


class _GroupSpecOpt(TypedDict, total=False):
	# grid：展示为 A_LO/A_HI/B_HI；ab_bounds：写出 B_LO（=A_HI）与 B_HI
	label_format: Literal["grid", "ab_bounds"]


class GroupSpec(_GroupSpecCore, _GroupSpecOpt):
	pass


# ---------- C 组：五档权重系数（先给相对系数，再归一化到 Σ=1，单笔 w=落档权重）----------
# 与 ORDER_C_BIN_SLICE_LABELS 顺序一致；可调只有 RAW，归一化自动保证可比量纲。
ORDER_C_GAP_BIN_COEF_RAW: tuple[float, float, float, float, float] = (
	0.57,
	1.55,
	0.65,
	0.58,
	0.42,
)


def _normalize_order_c_gap_bin_weights(
	raw: tuple[float, float, float, float, float],
	*,
	target_sum: float = 1.0,
) -> tuple[float, float, float, float, float]:
	"""相对系数缩放到 target_sum（默认 1），末档吸收舍入差。"""
	tgt = float(target_sum)
	s0 = float(sum(raw))
	if s0 <= 1e-15:
		raise ValueError("ORDER_C_GAP_BIN_COEF_RAW sum must be positive")
	out = [round(x * tgt / s0, 4) for x in raw]
	diff = round(tgt - float(sum(out)), 4)
	out[-1] = round(out[-1] + diff, 4)
	return (out[0], out[1], out[2], out[3], out[4])


ORDER_C_BIN_WEIGHTS: tuple[float, float, float, float, float] = _normalize_order_c_gap_bin_weights(
	ORDER_C_GAP_BIN_COEF_RAW,
	target_sum=1.0,
)

# 与 _bin7_label 中间五档一一对应
ORDER_C_BIN_SLICE_LABELS: tuple[str, str, str, str, str] = (
	"(-5,-2]",
	"(-2,0]",
	"(0,2]",
	"(2,5]",
	"(5,8]",
)


# ---------- 三组买扫 + 仓位：默认可先填同一套数值，再按需改成「不同买扫组合」----------
ORDER_GROUP_SPECS: tuple[GroupSpec, GroupSpec, GroupSpec] = (
	{
		"row_label": "A（基准·名义1份）",
		"rule_summary": "策略名义资金 1 份；每笔触发满仓使用该 1 份（w=1，收益合计=Σr%，Σw=有效笔数）",
		"a_lo": -0.05,
		"a_hi": 0.03,
		"b_hi": 0.07,
		"b_mult": 0.97,
		"c_mult": 0.96,
		"position": "unit",
	},
	{
		"row_label": "B（A/B 档·各1份）",
		"rule_summary": (
			"买扫 A_LO=-5%·A_HI=3%，B_LO=3%·B_HI=7%（分界上 B_LO 与 A_HI 同为 3%）；"
			"A 档成交 w=1，B 档成交 w=1，其余档 0"
		),
		"a_lo": -0.05,
		"a_hi": 0.03,
		"b_hi": 0.07,
		"b_mult": 0.97,
		"c_mult": 0.96,
		"position": "filter_ab",
		"label_format": "ab_bounds",
	},
	{
		"row_label": "C（五档·系数加权）",
		"rule_summary": (
			"开盘涨跌%∈(-5%,8%] 今开买入（不经四档gap/B×/C×）；"
			"相对系数→归一后 w（Σ=1）：(-5,-2]{w0:.4f}·(-2,0]{w1:.4f}·(0,2]{w2:.4f}·(2,5]{w3:.4f}·(5,8]{w4:.4f}".format(
				w0=ORDER_C_BIN_WEIGHTS[0],
				w1=ORDER_C_BIN_WEIGHTS[1],
				w2=ORDER_C_BIN_WEIGHTS[2],
				w3=ORDER_C_BIN_WEIGHTS[3],
				w4=ORDER_C_BIN_WEIGHTS[4],
			)
		),
		"a_lo": -0.05,
		"a_hi": 0.03,
		"b_hi": 0.07,
		"b_mult": 0.97,
		"c_mult": 0.96,
		"position": "bin5",
	},
)


def label_buy_scan(a_lo: float, a_hi: float, b_hi: float, b_mult: float, c_mult: float) -> str:
	"""与 dafengniu_buy_combo_scan._label_buy_scan 同一展示格式（百分点）。"""
	return "买扫|A_LO=%.1f%%·A_HI=%.1f%%·B_HI=%.1f%%·B×=%.2f·C×=%.2f" % (
		a_lo * 100,
		a_hi * 100,
		b_hi * 100,
		b_mult,
		c_mult,
	)


def label_from_spec(spec: GroupSpec) -> str:
	"""画布「买扫设定」列：B 组可展示显式 B_LO（数值等于 A_HI，即 A/B 分界）。"""
	if spec["position"] == "bin5":
		return "ORDER-C｜开盘%∈(-5%,8%]｜今开买入｜不经四档gap/B×/C×"
	fmt = spec.get("label_format", "grid")
	if fmt == "ab_bounds":
		return (
			"买扫|A_LO=%.1f%%·A_HI=%.1f%%·B_LO=%.1f%%·B_HI=%.1f%%·B×=%.2f·C×=%.2f"
			% (
				spec["a_lo"] * 100,
				spec["a_hi"] * 100,
				spec["a_hi"] * 100,
				spec["b_hi"] * 100,
				spec["b_mult"],
				spec["c_mult"],
			)
		)
	return label_buy_scan(
		spec["a_lo"], spec["a_hi"], spec["b_hi"], spec["b_mult"], spec["c_mult"]
	)


def _weight_group_c(gap_pct: float) -> float:
	"""按 D0 开盘涨跌% 落档给权重（ORDER_C_BIN_WEIGHTS）；区间外 0。"""
	w = ORDER_C_BIN_WEIGHTS
	x = float(gap_pct)
	if x <= -5.0 or x > 8.0:
		return 0.0
	if x <= -2.0:
		return w[0]
	if x <= 0.0:
		return w[1]
	if x <= 2.0:
		return w[2]
	if x <= 5.0:
		return w[3]
	return w[4]


def _weighted_block_metrics(
	rets: list[float],
	weights: list[float],
	days: list[str],
) -> dict[str, float | None]:
	pairs = [(r, w, d) for r, w, d in zip(rets, weights, days) if w > 1e-15]
	if not pairs:
		return {
			"n": 0,
			"sum_wr": None,
			"sum_w": None,
			"comparable_mean_pct": None,
			"win_rate_w_pct": None,
			"sharpe_w": None,
			"max_dd_pct": None,
			"vol_pct": None,
			"ratio_avg": None,
			"ratio_sum": None,
		}
	r_arr = np.array([p[0] for p in pairs], dtype=float)
	w_arr = np.array([p[1] for p in pairs], dtype=float)
	d_list = [p[2] for p in pairs]
	sum_w = float(np.sum(w_arr))
	sum_wr = float(np.sum(w_arr * r_arr))
	mu = sum_wr / sum_w if sum_w > 1e-15 else 0.0
	var = float(np.sum(w_arr * (r_arr - mu) ** 2) / sum_w) if sum_w > 1e-15 else 0.0
	sharpe_w = (mu / (var**0.5)) if var > 1e-12 else 0.0
	win_w = float(np.sum(w_arr * (r_arr > 0.0)) / sum_w * 100.0) if sum_w > 1e-15 else 0.0
	eff_pts = w_arr * r_arr
	ext = compute_extended_metrics(eff_pts, d_list)
	mdd = ext.get("最大回撤_链式净值_pct")
	ext_raw = compute_extended_metrics(np.array(rets, dtype=float), days)
	cmp_mean = round(sum_wr / sum_w, 4) if sum_w > 1e-15 else None
	return {
		"n": len(pairs),
		"sum_wr": round(sum_wr, 4),
		"sum_w": round(sum_w, 4),
		"comparable_mean_pct": cmp_mean,
		"win_rate_w_pct": round(win_w, 4),
		"sharpe_w": round(sharpe_w, 4),
		"max_dd_pct": round(mdd, 4) if mdd is not None else None,
		"vol_pct": ext_raw.get("波动率_笔收益标准差_pct"),
		"ratio_avg": ext_raw.get("盈亏比_均盈除以均亏绝对值"),
		"ratio_sum": ext_raw.get("盈亏比_总盈利除以总亏损绝对值"),
	}


def _group_unit_metrics(trades: list[tuple[float, float, str]]) -> dict[str, float | None]:
	rets = [t[0] for t in trades]
	days = [t[2] for t in trades]
	arr = np.array(rets, dtype=float)
	n = len(arr)
	if n == 0:
		return {
			"n": 0,
			"sum_r": None,
			"sum_wr": None,
			"sum_w": None,
			"comparable_mean_pct": None,
			"win_pct": None,
			"sharpe": None,
			"max_dd_pct": None,
			"vol_pct": None,
			"ratio_avg": None,
			"ratio_sum": None,
		}
	ext = compute_extended_metrics(arr, days)
	sum_r = float(np.sum(arr))
	mean_r = float(np.mean(arr))
	std_r = float(np.std(arr, ddof=1)) if n > 1 else 0.0
	sharpe = (mean_r / std_r) if std_r > 1e-12 else 0.0
	win_pct = float(np.mean(arr > 0.0) * 100.0)
	mdd = ext.get("最大回撤_链式净值_pct")
	cmp_mean = round(sum_r / float(n), 4) if n else None
	return {
		"n": n,
		"sum_r": round(sum_r, 4),
		"sum_wr": round(sum_r, 4),
		"sum_w": float(n),
		"comparable_mean_pct": cmp_mean,
		"win_pct": round(win_pct, 4),
		"sharpe": round(sharpe, 4),
		"max_dd_pct": round(mdd, 4) if mdd is not None else None,
		"vol_pct": ext.get("波动率_笔收益标准差_pct"),
		"ratio_avg": ext.get("盈亏比_均盈除以均亏绝对值"),
		"ratio_sum": ext.get("盈亏比_总盈利除以总亏损绝对值"),
	}


def load_trades_for_spec(spec: GroupSpec, require_ma5: bool) -> list[tuple[float, float, str]]:
	p = os.path.abspath(SYNC_OPEN_BAOSTOCK_CSV)
	df, sse_idx, sorted_dates = load_data(p)
	if spec["position"] == "bin5":
		trades, _ = _collect_five_bin_open_trades(
			df,
			sse_idx,
			sorted_dates,
			require_sse_ma5=require_ma5,
		)
		return trades
	trades, _ = _collect_buy_combo_trades(
		df,
		sse_idx,
		sorted_dates,
		a_lo=spec["a_lo"],
		a_hi=spec["a_hi"],
		b_hi=spec["b_hi"],
		b_mult=spec["b_mult"],
		c_mult=spec["c_mult"],
		require_sse_ma5=require_ma5,
	)
	return trades


def _weights_filter_ab(
	gaps_pct: list[float],
	a_lo: float,
	a_hi: float,
	b_hi: float,
) -> list[float]:
	out: list[float] = []
	for gp in gaps_pct:
		gf = float(gp) / 100.0
		br = gap_bracket_with(gf, a_lo, a_hi, b_hi)
		if br == "A":
			out.append(1.0)
		elif br == "B":
			out.append(1.0)
		else:
			out.append(0.0)
	return out


def compute_one_group_from_trades(
	spec: GroupSpec, trades: list[tuple[float, float, str]]
) -> dict[str, Any]:
	rets = [t[0] for t in trades]
	gaps = [t[1] for t in trades]
	days = [t[2] for t in trades]
	scan_label = label_from_spec(spec)

	pos = spec["position"]
	if pos == "unit":
		m = _group_unit_metrics(trades)
		return {
			"row_label": spec["row_label"],
			"rule_summary": spec["rule_summary"],
			"buy_scan_label": scan_label,
			"metric_kind": "unit",
			**m,
		}
	if pos == "filter_ab":
		w = _weights_filter_ab(gaps, spec["a_lo"], spec["a_hi"], spec["b_hi"])
		m = _weighted_block_metrics(rets, w, days)
		return {
			"row_label": spec["row_label"],
			"rule_summary": spec["rule_summary"],
			"buy_scan_label": scan_label,
			"metric_kind": "weighted",
			**m,
		}
	w = [_weight_group_c(gp) for gp in gaps]
	m = _weighted_block_metrics(rets, w, days)
	return {
		"row_label": spec["row_label"],
		"rule_summary": spec["rule_summary"],
		"buy_scan_label": scan_label,
		"metric_kind": "weighted",
		**m,
	}


def _share_hint_dabc(tier: str, position: Literal["unit", "filter_ab", "bin5"]) -> str:
	if position == "unit":
		return "1"
	if position == "filter_ab":
		return {"D": "0", "A": "1", "B": "1", "C": "0"}.get(tier, "—")
	return "—"


def _share_hint_bin7(bin_label: str) -> str:
	"""与 _weight_group_c / ORDER_C_BIN_WEIGHTS 一致；用于明细表「该档份额」列。"""
	if bin_label in ("≤-5%", ">8%"):
		return "0"
	for i, lb in enumerate(ORDER_C_BIN_SLICE_LABELS):
		if lb == bin_label:
			return "%.4f" % (ORDER_C_BIN_WEIGHTS[i],)
	return "—"


def _trade_weight(spec: GroupSpec, gap_pct: float) -> float:
	if spec["position"] == "unit":
		return 1.0
	if spec["position"] == "filter_ab":
		gf = float(gap_pct) / 100.0
		br = gap_bracket_with(gf, spec["a_lo"], spec["a_hi"], spec["b_hi"])
		return {"A": 1.0, "B": 1.0}.get(br, 0.0)
	return _weight_group_c(gap_pct)


def _slice_trade_metrics(rets: list[float], days: list[str]) -> dict[str, float | None]:
	"""分档内：笔收益 r 的合计、胜率、夏普、链式回撤、波动率、盈亏比（与全组同一口径）。"""
	if not rets:
		return {
			"sum_r": None,
			"win_pct": None,
			"sharpe": None,
			"mdd_pct": None,
			"vol_pct": None,
			"ratio_avg": None,
			"ratio_sum": None,
		}
	arr = np.array(rets, dtype=float)
	ext = compute_extended_metrics(arr, days)
	n = len(arr)
	std_r = float(np.std(arr, ddof=1)) if n > 1 else 0.0
	if n > 1 and not np.isfinite(std_r):
		std_r = 0.0
	sharpe = (float(np.mean(arr)) / std_r) if std_r > 1e-12 else 0.0
	return {
		"sum_r": round(float(np.sum(arr)), 4),
		"win_pct": round(float(np.mean(arr > 0.0) * 100.0), 4),
		"sharpe": round(sharpe, 4),
		"mdd_pct": ext.get("最大回撤_链式净值_pct"),
		"vol_pct": ext.get("波动率_笔收益标准差_pct"),
		"ratio_avg": ext.get("盈亏比_均盈除以均亏绝对值"),
		"ratio_sum": ext.get("盈亏比_总盈利除以总亏损绝对值"),
	}


def build_breakdown_detail(
	spec: GroupSpec, trades: list[tuple[float, float, str]]
) -> list[tuple[str, str, str, str, str, str, str, str, str, str, str, str, str]]:
	"""分档明细一行：组别、口径、分档、笔数、份额、Σr%、Σ(w×r)%、胜率%、夏普、回撤%、盈亏比均、盈亏比额、波动率%。"""
	gl = spec["row_label"]
	pos = spec["position"]
	out: list[tuple[str, str, str, str, str, str, str, str, str, str, str, str, str]] = []

	def fmt_cell(x: float | None) -> str:
		if x is None:
			return "—"
		if isinstance(x, (int, float)):
			return str(round(float(x), 4))
		return str(x)

	if pos in ("unit", "filter_ab"):
		order = ["D", "A", "B", "C"]
		buckets: dict[str, list[tuple[float, str, float]]] = {k: [] for k in order}
		for r, gp, d in trades:
			br = gap_bracket_with(float(gp) / 100.0, spec["a_lo"], spec["a_hi"], spec["b_hi"])
			if br in buckets:
				w = _trade_weight(spec, gp)
				buckets[br].append((float(r), d, w))
		for k in order:
			items = buckets[k]
			rets = [x[0] for x in items]
			days = [x[1] for x in items]
			ws = [x[2] for x in items]
			n = len(rets)
			share = _share_hint_dabc(k, pos)
			sum_wr = float(np.sum(np.array(ws) * np.array(rets))) if n else None
			if n == 0:
				row_tail = ("—",) * 8
			else:
				m = _slice_trade_metrics(rets, days)
				row_tail = (
					fmt_cell(m["sum_r"]),
					fmt_cell(sum_wr),
					fmt_cell(m["win_pct"]),
					fmt_cell(m["sharpe"]),
					fmt_cell(m["mdd_pct"]),
					fmt_cell(m["ratio_avg"]),
					fmt_cell(m["ratio_sum"]),
					fmt_cell(m["vol_pct"]),
				)
			out.append(
				(
					gl,
					"四档 gap(D/A/B/C)",
					k,
					str(n),
					share,
				)
				+ row_tail
			)
		return out

	for lb in ORDER_7_LABELS:
		items = [
			(float(r), d, _trade_weight(spec, gp))
			for r, gp, d in trades
			if _bin7_label(float(gp)) == lb
		]
		rets = [x[0] for x in items]
		days = [x[1] for x in items]
		ws = [x[2] for x in items]
		n = len(rets)
		share = _share_hint_bin7(lb)
		sum_wr = float(np.sum(np.array(ws) * np.array(rets))) if n else None
		if n == 0:
			row_tail = ("—",) * 8
		else:
			m = _slice_trade_metrics(rets, days)
			row_tail = (
				fmt_cell(m["sum_r"]),
				fmt_cell(sum_wr),
				fmt_cell(m["win_pct"]),
				fmt_cell(m["sharpe"]),
				fmt_cell(m["mdd_pct"]),
				fmt_cell(m["ratio_avg"]),
				fmt_cell(m["ratio_sum"]),
				fmt_cell(m["vol_pct"]),
			)
		out.append(
			(
				gl,
				"七档 D0 开盘涨跌%",
				lb,
				str(n),
				share,
			)
			+ row_tail
		)
	return out


def compute_blend_coefficient_rows(
	trades_per_group: list[list[tuple[float, float, str]]],
) -> list[tuple[str, str, str, str, str]]:
	"""三组若各配名义 1 份策略资金：等权、逆波动率、非负夏普归一。"""
	if len(trades_per_group) != 3:
		return []

	def sharpe_raw(rets: list[float]) -> float:
		arr = np.array(rets, dtype=float)
		if len(arr) < 2:
			return 0.0
		s = float(np.std(arr, ddof=1))
		if s < 1e-12:
			return 0.0
		return float(np.mean(arr) / s)

	stds: list[float] = []
	shs: list[float] = []
	for tr in trades_per_group:
		rets = [t[0] for t in tr]
		arr = np.array(rets, dtype=float)
		stds.append(float(np.std(arr, ddof=1)) if len(arr) > 1 else 1e-12)
		shs.append(sharpe_raw(rets))

	inv = [1.0 / s for s in stds]
	s_inv = sum(inv)
	w_inv = [round(x / s_inv, 4) for x in inv]

	shp = [max(s, 0.0) for s in shs]
	s_sh = sum(shp)
	w_sh = [round(x / s_sh, 4) if s_sh > 1e-12 else round(1.0 / 3.0, 4) for x in shp]

	return [
		(
			"等权（名义各1份）",
			"0.3333",
			"0.3333",
			"0.3333",
			"三组策略各分配 1 份资金，组合权重 1:1:1，Σw=1",
		),
		(
			"逆波动率(单笔σ)",
			str(w_inv[0]),
			str(w_inv[1]),
			str(w_inv[2]),
			"w_i ∝ 1/σ_i（σ 为该组笔收益样本标准差），用于降低高波动组权重",
		),
		(
			"非负夏普归一",
			str(w_sh[0]),
			str(w_sh[1]),
			str(w_sh[2]),
			"w_i ∝ max(夏普_i,0)，夏普为笔收益均值/笔收益标准差（与汇总表一致）",
		),
	]


def compute_abc_snapshot(require_ma5: bool = True) -> dict[str, Any]:
	group_rows: list[dict[str, Any]] = []
	breakdown_detail: list[tuple[str, ...]] = []
	trades_all: list[list[tuple[float, float, str]]] = []
	for sp in ORDER_GROUP_SPECS:
		trades = load_trades_for_spec(sp, require_ma5=require_ma5)
		trades_all.append(trades)
		group_rows.append(compute_one_group_from_trades(sp, trades))
		breakdown_detail.extend(build_breakdown_detail(sp, trades))
	blend_rows = compute_blend_coefficient_rows(trades_all)
	ref_sw = None
	if group_rows:
		ref_sw = group_rows[0].get("sum_w")
	for gr in group_rows:
		sw = gr.get("sum_w")
		swr = gr.get("sum_wr")
		if (
			ref_sw is not None
			and sw is not None
			and float(sw) > 1e-12
			and swr is not None
		):
			gr["scaled_total_wr_to_a"] = round(
				float(swr) * (float(ref_sw) / float(sw)), 4
			)
		else:
			gr["scaled_total_wr_to_a"] = None
	return {
		"groups": group_rows,
		"breakdown_detail": breakdown_detail,
		"blend_rows": blend_rows,
	}


def abc_position_canvas_fragments(require_ma5: bool = True) -> tuple[str, str]:
	snap = compute_abc_snapshot(require_ma5=require_ma5)
	rows = snap["groups"]
	bd = snap.get("breakdown_detail", [])
	blend = snap.get("blend_rows", [])

	def esc(x: object) -> str:
		if x is None:
			return "—"
		return str(x).replace("\\", "\\\\").replace("'", "\\'")

	lines: list[str] = []
	for r in rows:
		if r.get("metric_kind") == "unit":
			val_sum = esc(r.get("sum_r"))
			val_win = esc(r.get("win_pct"))
			val_sh = esc(r.get("sharpe"))
		else:
			val_sum = esc(r.get("sum_wr"))
			val_win = esc(r.get("win_rate_w_pct"))
			val_sh = esc(r.get("sharpe_w"))
		lines.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				esc(r["row_label"]),
				esc(r["rule_summary"]),
				esc(r.get("n")),
				val_sum,
				esc(r.get("sum_w")),
				esc(r.get("comparable_mean_pct")),
				esc(r.get("scaled_total_wr_to_a")),
				val_win,
				val_sh,
				esc(r.get("max_dd_pct")),
				esc(r.get("ratio_avg")),
				esc(r.get("ratio_sum")),
				esc(r.get("vol_pct")),
				esc(r["buy_scan_label"]),
			)
		)

	intro = (
		"A/B：四档 gap + B×/C× 触价买扫 + 仓位规则。"
		"C：开盘涨跌∈(-5%,8%] 即今开买入（不经四档/B×/C×）；本表「加权」为历史对比口径。"
		"「买扫设定」列：A/B 为参数标签；C 为 ORDER-C 今开口径说明。"
	)
	comp_intro = (
		"A：每笔成交 w=1。B：落在买扫 A 档或 B 档时单笔 w=1，其余 0。"
		"C（扫描汇总）：每笔 w=该档归一化系数（ORDER_C_GAP_BIN_COEF_RAW→ORDER_C_BIN_WEIGHTS），用于 Σ(w×r)/Σw；"
		"实盘 ORDER-C 分钱见 `dafengniu_order_c_ladder`（日预算等额，不按该 w 倾斜）。"
		"Σw 为本组样本内权重合计。"
		"「可比笔均%」= Σ(w×r)/Σw。"
		"「折算合计%(对齐A组Σw)」= Σ(w×r)×(Σw_A/Σw)。"
	)
	constants = (
		"""
const ORDER_ABC_RULE_INTRO = """
		+ json.dumps(intro, ensure_ascii=False)
		+ """;

const ORDER_ABC_COMP_INTRO = """
		+ json.dumps(comp_intro, ensure_ascii=False)
		+ """;

const ORDER_ABC_HEADERS = [
\t'组别',
\t'仓位规则摘要',
\t'有效笔数N',
\t'收益合计%=Σ(w×r)',
\t'Σw',
\t'可比笔均%=Σ(w×r)/Σw',
\t'折算合计%(对齐A组Σw)',
\t'胜率%',
\t'夏普',
\t'最大回撤%(链式)',
\t'盈亏比(均)',
\t'盈亏比(额)',
\t'波动率%',
\t'买扫设定',
];

const ORDER_ABC_ROWS: string[][] = [
"""
		+ "\n".join(lines)
		+ """
];

const ORDER_ABC_BREAKDOWN_HEADERS = [
\t'组别',
\t'口径',
\t'分档',
\t'笔数',
\t'该档份额',
\t'Σr%',
\t'Σ(w×r)%',
\t'胜率%',
\t'夏普',
\t'最大回撤%(链式)',
\t'盈亏比(均)',
\t'盈亏比(额)',
\t'波动率%',
];

const ORDER_ABC_BREAKDOWN_ROWS: string[][] = [
"""
		+ (
			"\n".join(
				"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
				% tuple(esc(c) for c in t)
				for t in bd
			)
			if bd
			else "\t['—', '—', '—', '0', '—', '—', '—', '—', '—', '—', '—', '—', '—'],"
		)
		+ """
];

const ORDER_ABC_BLEND_INTRO = """
		+ json.dumps(
			"若三条策略各准备「名义 1 份」资金并行运行：等权即各 1/3；"
			"逆波动率用该组笔收益标准差 σ；夏普权重用 max(夏普,0) 归一。"
			"系数仅作组合示例，实盘需考虑相关性、容量与杠杆约束。",
			ensure_ascii=False,
		)
		+ """;

const ORDER_ABC_BLEND_HEADERS = [
\t'组合方案',
\t'w_A',
\t'w_B',
\t'w_C',
\t'说明',
];

const ORDER_ABC_BLEND_ROWS: string[][] = [
"""
		+ (
			"\n".join(
				"\t['%s', '%s', '%s', '%s', '%s'],"
				% tuple(esc(c) for c in t)
				for t in blend
			)
			if blend
			else "\t['—', '—', '—', '—', '—'],"
		)
		+ """
];
"""
	)

	jsx = """

\t\t\t<H2>ORDER：A / B / C — 买扫与仓位</H2>
\t\t\t<Text tone="secondary" size="small">{ORDER_ABC_RULE_INTRO}</Text>
\t\t\t<Text tone="secondary" size="small">{ORDER_ABC_COMP_INTRO}</Text>
\t\t\t<Text tone="secondary" size="small">
\t\t\t\t汇总：A 每笔名义 1 份 → Σr；B/C 在名义 1 份规则下收益合计为 Σ(w×r)；夏普在 B/C 组为份额加权夏普。
\t\t\t\t盈亏比、波动率为笔收益 r 的样本指标。组级回撤为链式净值最大回撤（B/C 每步为 w×r）。
\t\t\t</Text>
\t\t\t<Table headers={ORDER_ABC_HEADERS} rows={ORDER_ABC_ROWS} />

\t\t\t<Divider />

\t\t\t<H2>ORDER：分档明细（笔数 + 分档指标）</H2>
\t\t\t<Text tone="secondary" size="small">
\t\t\t\tA/B 为四档 gap；C 为七档开盘涨跌%。分档内 Σr、夏普、回撤、盈亏比、波动率均仅使用该分档内成交（按时间链式回撤）。
\t\t\t\tΣ(w×r) 为该分档内持仓份额加权收益合计。
\t\t\t</Text>
\t\t\t<Table headers={ORDER_ABC_BREAKDOWN_HEADERS} rows={ORDER_ABC_BREAKDOWN_ROWS} />

\t\t\t<Divider />

\t\t\t<H2>ORDER：三组名义各 1 份 — 组合权重示例</H2>
\t\t\t<Text tone="secondary" size="small">{ORDER_ABC_BLEND_INTRO}</Text>
\t\t\t<Table headers={ORDER_ABC_BLEND_HEADERS} rows={ORDER_ABC_BLEND_ROWS} />
"""

	return constants, jsx
