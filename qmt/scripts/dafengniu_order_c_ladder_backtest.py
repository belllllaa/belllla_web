# -*- coding: utf-8 -*-
"""ORDER-C：「首买 + 补仓① + 补仓②」条件下落的日线近似回测。

数据来源：`dafengniu_sync_open_baostock.csv`，与 `_collect_five_bin_open_trades` 同一筛选（gap∈(-5,8]、可选上证 MA5 门控）。

补仓触发（可复核）：
  · 用 **D0 最低价相对 D0 开盘价** 的最大下探幅度（%）代表「当日相对开盘的最大回落」；
  · **T1/T2 按「开盘涨跌五档」分别取值**：每笔成交先算 gap 落在哪一档，再用该档阈值（`ORDER_C_PULLBACK_PROFILES`）；
  · 若下探 ≥ T1，则认为补仓①在 **O×(1−T1%)** 成交；若下探 ≥ T2（>T1），补仓②在 **O×(1−T2%)** 成交。
  · 卖出仍用 `simulate_exit_params`，锚点 **D0 开盘价**；单笔收益按 **加权平均建仓成本** 折算。

另含多行「全局统一」阈值作对照（五档同一组 T1/T2）。

局限：无分时序列，无法模拟「先上冲再回踩」顺序；结果偏保守或偏乐观取决于当日 K 线形态，仅供多组参数相对比较。

汇总 JSON：`python qmt/scripts/dafengniu_order_c_ladder_backtest.py` 写入 `dafengniu_order_c_ladder_summary.json`
（等权 vs `ORDER_C_BIN_WEIGHTS` 档权重加权笔均/合计等，便于与基准 summary 对照）。
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_benchmark_ref_trades import _f, compute_extended_metrics  # noqa: E402
from dafengniu_order_abc_position_canvas import ORDER_C_BIN_WEIGHTS  # noqa: E402
from dafengniu_buy_combo_scan import (  # noqa: E402
	FIXED_D1_WEAK,
	FIXED_MAX_DAY,
	FIXED_SL,
	FIXED_SSE_TAIL,
	FIXED_TP,
	_gap_pct_in_c_open_buy_bins,
)
from dafengniu_order_c_ladder import (  # noqa: E402
	ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT,
	ORDER_C_LADDER_BIN_LABELS,
	gap_pct_to_bin_index,
	ladder_leg_fractions_for_gap_pct,
)

ORDER_C_ADOPTED_UNIFORM_PULLBACK_PCT = ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT
from dafengniu_paths import ORDER_C_LADDER_SUMMARY_JSON, SYNC_OPEN_BAOSTOCK_CSV  # noqa: E402
from dafengniu_sell_combo_scan import load_data, simulate_exit_params  # noqa: E402


def _d0_max_pullback_from_open_pct(d0_open: float, d0_low: float | None) -> float:
	if d0_open is None or d0_open <= 0:
		return 0.0
	if d0_low is None or not np.isfinite(d0_low):
		return 0.0
	if float(d0_low) < float(d0_open):
		return float((float(d0_open) - float(d0_low)) / float(d0_open) * 100.0)
	return 0.0


def _ret_pct_full_open(sell_px: float, d0_open: float) -> float:
	return float((sell_px / d0_open - 1.0) * 100.0)


def ret_pct_three_leg_ladder(
	sell_px: float,
	d0_open: float,
	d0_low: float | None,
	t1: float,
	t2: float,
	f0: float,
	f1: float,
	f2: float,
) -> tuple[float, bool, bool]:
	"""给定三腿名义占比与全局回落阈值，返回 (单笔收益率%, 补仓①成交?, 补仓②成交?)。"""
	dd = _d0_max_pullback_from_open_pct(d0_open, d0_low)
	ok1 = dd >= t1 - 1e-12
	ok2 = dd >= t2 - 1e-12
	p0 = float(d0_open)
	n0 = float(f0)
	cost = n0
	shares = n0 / p0
	if ok1:
		p1 = p0 * (1.0 - t1 / 100.0)
		cost += f1
		shares += f1 / p1
	if ok2:
		p2 = p0 * (1.0 - t2 / 100.0)
		cost += f2
		shares += f2 / p2
	if cost <= 1e-15 or shares <= 1e-15:
		return 0.0, ok1, ok2
	ret = float((sell_px * shares / cost - 1.0) * 100.0)
	return ret, ok1, ok2


def _ret_pct_ladder(
	sell_px: float,
	d0_open: float,
	d0_low: float | None,
	gap_pct: float,
	t1: float,
	t2: float,
) -> tuple[float, bool, bool]:
	"""ORDER-C 五档 `ORDER_C_LADDER_LEG_FRAC` 下的三腿收益。"""
	legs = ladder_leg_fractions_for_gap_pct(gap_pct)
	if legs is None:
		return 0.0, False, False
	f0, f1, f2 = legs
	return ret_pct_three_leg_ladder(
		sell_px, d0_open, d0_low, t1, t2, f0, f1, f2
	)


def _collect_order_c_rows_with_sim(
	require_sse_ma5: bool,
) -> list[tuple[float, float, str, float, float | None]]:
	"""每笔：(sell_px, gap_pct, open_day_str, d0_open, d0_low)。"""
	p = os.path.abspath(SYNC_OPEN_BAOSTOCK_CSV)
	df, sse_idx, sorted_dates = load_data(p)
	out: list[tuple[float, float, str, float, float | None]] = []

	for _, row in df.iterrows():
		open_raw = str(row["开仓日"]).strip().replace(".0", "")
		if len(open_raw) < 8 or not open_raw[:8].isdigit():
			continue
		open_date_str = open_raw[:8]

		prev_c = _f(row, "D前1_收盘")
		d0o = _f(row, "D0_开盘")
		d0_low = _f(row, "D0_最低")
		if prev_c is None or d0o is None or prev_c <= 0 or d0o <= 0:
			continue

		gap_pct = float((d0o / prev_c - 1.0) * 100.0)
		if not _gap_pct_in_c_open_buy_bins(gap_pct):
			continue

		try:
			target = datetime.strptime(open_date_str, "%Y%m%d").date()
		except ValueError:
			continue

		j_d0 = bisect.bisect_left(sorted_dates, target)
		if j_d0 >= len(sorted_dates):
			continue
		d0 = sorted_dates[j_d0]
		if j_d0 + FIXED_MAX_DAY >= len(sorted_dates):
			continue

		if require_sse_ma5:
			if j_d0 == 0:
				continue
			t_minus_1 = sorted_dates[j_d0 - 1]
			try:
				rmi = sse_idx.loc[t_minus_1]
				sc, sm5 = float(rmi["close"]), float(rmi["ma5"])
			except (KeyError, TypeError, ValueError):
				continue
			if not (np.isfinite(sc) and np.isfinite(sm5) and sc >= sm5):
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
			continue

		out.append(
			(
				float(sell_px),
				gap_pct,
				d0.strftime("%Y%m%d"),
				float(d0o),
				float(d0_low) if d0_low is not None and np.isfinite(d0_low) else None,
			)
		)

	return out


# 五档顺序与 ORDER_C_LADDER_BIN_LABELS / gap_pct_to_bin_index 一致：
# [(-5,-2], (-2,0], (0,2], (2,5], (5,8]]
PullbackByBin = tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]


def _pair(t1: float, t2: float) -> tuple[float, float]:
	if t2 <= t1 + 1e-12:
		raise ValueError("每档须满足 补仓2% > 补仓1%")
	return (float(t1), float(t2))


def _uniform_pair(t1: float, t2: float) -> PullbackByBin:
	p = _pair(t1, t2)
	return (p, p, p, p, p)


# （方案名, None=满仓今开对照 | 五档各自的 (补仓1回落%, 补仓2回落%)）
ORDER_C_PULLBACK_PROFILES: tuple[tuple[str, PullbackByBin | None], ...] = (
	("对照·满仓今开", None),
	("全局统一·1.5%/3.0%", _uniform_pair(1.5, 3.0)),
	("全局统一·2%/3.0%", _uniform_pair(2.0, 3.0)),
	("全局统一·2.0%/3.5%", _uniform_pair(2.0, 3.5)),
	(
		"分档·递增门槛",
		(
			_pair(1.0, 2.5),
			_pair(1.5, 3.0),
			_pair(1.5, 3.0),
			_pair(2.0, 3.5),
			_pair(2.5, 4.5),
		),
	),
	(
		"分档·低开深补·高开更深补",
		(
			_pair(2.0, 4.0),
			_pair(1.5, 3.0),
			_pair(1.5, 2.8),
			_pair(2.5, 4.5),
			_pair(3.0, 5.0),
		),
	),
	(
		"分档·高开收紧·低开放宽",
		(
			_pair(2.5, 4.5),
			_pair(1.5, 3.0),
			_pair(1.5, 3.0),
			_pair(1.5, 2.5),
			_pair(2.0, 3.5),
		),
	),
	(
		"分档·中小低开敏感·大高开迟钝",
		(
			_pair(2.0, 3.8),
			_pair(1.2, 2.5),
			_pair(1.2, 2.5),
			_pair(2.5, 4.5),
			_pair(3.0, 5.5),
		),
	),
)

# 与业务约定一致：五档首买+两档补仓（`ORDER_C_LADDER_LEG_FRAC`）+ 全局统一回落补仓 **2% / 3.0%**（数值见 `dafengniu_order_c_ladder.ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT`）
ORDER_C_ADOPTED_PROFILE_LABEL: str = "全局统一·2%/3.0%"

_adopted_prof = next(
	(p for n, p in ORDER_C_PULLBACK_PROFILES if n == ORDER_C_ADOPTED_PROFILE_LABEL),
	None,
)
assert _adopted_prof is not None and _adopted_prof == _uniform_pair(2.0, 3.0), (
	"ORDER_C_ADOPTED_* 须与 ORDER_C_PULLBACK_PROFILES 中「全局统一·2%/3.0%」一致"
)


def _order_c_weighted_block(arr: np.ndarray, w: np.ndarray, n: int) -> dict[str, Any] | None:
	"""单笔资金与 ORDER_C_BIN_WEIGHTS[gap 档] 成正比时的加权笔均/夏普/胜率；收益合计近似 = N×加权笔均（与等权合计 N×笔均可比）。"""
	sw = float(np.sum(w))
	if sw <= 1e-15 or n <= 0:
		return None
	mean_w = float(np.sum(w * arr) / sw)
	var_w = float(np.sum(w * (arr - mean_w) ** 2) / sw)
	std_w = float(np.sqrt(max(var_w, 0.0)))
	sh_w = (mean_w / std_w) if std_w > 1e-12 else 0.0
	win_w = float(np.sum(w * (arr > 0.0)) / sw * 100.0)
	sum_equiv = float(n * mean_w)
	return {
		"单笔均值_pct": round(mean_w, 4),
		"收益合计近似_pct": round(sum_equiv, 4),
		"夏普_笔收益": round(sh_w, 4),
		"胜率_pct": round(win_w, 4),
	}


def run_profile_metrics(
	rows: list[tuple[float, float, str, float, float | None]],
	profile: PullbackByBin | None,
) -> dict[str, Any]:
	rets: list[float] = []
	days: list[str] = []
	w_order_c: list[float] = []
	r1 = 0
	r2 = 0
	for sell_px, gap_pct, d, d0o, d0_lo in rows:
		jw = gap_pct_to_bin_index(gap_pct)
		w_i = float(ORDER_C_BIN_WEIGHTS[jw]) if jw is not None else 0.0
		if profile is None:
			r = _ret_pct_full_open(sell_px, d0o)
			rets.append(r)
			days.append(d)
			w_order_c.append(w_i)
			continue
		j = gap_pct_to_bin_index(gap_pct)
		if j is None:
			continue
		t1, t2 = profile[j]
		r, ok1, ok2 = _ret_pct_ladder(
			sell_px, d0o, d0_lo, gap_pct, float(t1), float(t2)
		)
		rets.append(r)
		days.append(d)
		w_order_c.append(w_i)
		if ok1:
			r1 += 1
		if ok2:
			r2 += 1

	n = len(rets)
	if n == 0:
		return {
			"n": 0,
			"sum_r": None,
			"mean_r": None,
			"sharpe": None,
			"mdd": None,
			"win_pct": None,
			"pct_fill_1": None,
			"pct_fill_2": None,
			"order_c_bin_weighted": None,
			"diff_笔均_加权减等权_pp": None,
			"diff_收益合计近似_加权减等权_pct": None,
		}
	arr = np.array(rets, dtype=float)
	w_arr = np.array(w_order_c, dtype=float)
	sum_r = float(np.sum(arr))
	mean_r = float(np.mean(arr))
	std_r = float(np.std(arr, ddof=1)) if n > 1 else 0.0
	sharpe = (mean_r / std_r) if std_r > 1e-12 else 0.0
	wins = float(np.sum(arr > 0))
	win_pct = wins / n * 100.0
	ext = compute_extended_metrics(arr, days)
	mdd = ext.get("最大回撤_链式净值_pct")
	ow = _order_c_weighted_block(arr, w_arr, n)
	diff_mean = diff_sum = None
	if ow is not None:
		diff_mean = round(float(ow["单笔均值_pct"]) - mean_r, 4)
		diff_sum = round(float(ow["收益合计近似_pct"]) - sum_r, 4)
	return {
		"n": n,
		"sum_r": round(sum_r, 4),
		"mean_r": round(mean_r, 4),
		"sharpe": round(sharpe, 4),
		"mdd": round(mdd, 4) if mdd is not None else None,
		"win_pct": round(win_pct, 4),
		"pct_fill_1": round(r1 / n * 100.0, 2) if profile is not None else None,
		"pct_fill_2": round(r2 / n * 100.0, 2) if profile is not None else None,
		"order_c_bin_weighted": ow,
		"diff_笔均_加权减等权_pp": diff_mean,
		"diff_收益合计近似_加权减等权_pct": diff_sum,
	}


def run_all_pullback_profiles(require_sse_ma5: bool = True) -> list[dict[str, Any]]:
	rows = _collect_order_c_rows_with_sim(require_sse_ma5=require_sse_ma5)
	out: list[dict[str, Any]] = []
	for name, profile in ORDER_C_PULLBACK_PROFILES:
		m = run_profile_metrics(rows, profile)
		out.append(
			{
				"label": name,
				"profile": profile,
				**m,
			}
		)
	return out


def build_order_c_adopted_summary_dict(require_sse_ma5: bool = True) -> dict[str, Any]:
	"""实盘约定补仓口径下，等权与 ORDER-C 档权重加权两套指标（单笔资金∝该档 ORDER_C_BIN_WEIGHTS）。"""
	rows = _collect_order_c_rows_with_sim(require_sse_ma5=require_sse_ma5)
	m = run_profile_metrics(rows, _adopted_prof)
	note = (
		"等权口径：每笔样本权重相同，与画布 ORDER-C 梯子表一致。"
		"档权重口径：每笔按 D0 gap 所在 ORDER-C 五档取 ORDER_C_BIN_WEIGHTS，"
		"加权笔均=Σ(w_i·r_i)/Σw_i，夏普=加权笔均/加权标准差，胜率=Σ(w_i·I[r_i>0])/Σw_i×100%；"
		"收益合计近似=N×加权笔均，可与等权合计=N×等权笔均直接对比。"
		"最大回撤等为基于等权笔收益率序列的链式净值（档权重未参与回撤）。"
	)
	body: dict[str, Any] = {
		"数据来源_CSV": os.path.abspath(SYNC_OPEN_BAOSTOCK_CSV),
		"require_sse_above_ma5_for_new": require_sse_ma5,
		"ORDER_C_补仓回落口径": ORDER_C_ADOPTED_PROFILE_LABEL,
		"ORDER_C_BIN_WEIGHTS": [round(float(x), 4) for x in ORDER_C_BIN_WEIGHTS],
		"说明": note,
		"等权口径": {
			"成交笔数": m["n"],
			"收益合计_pct": m["sum_r"],
			"单笔均值_pct": m["mean_r"],
			"夏普_笔收益": m["sharpe"],
			"胜率_pct": m["win_pct"],
			"最大回撤_链式净值_pct": m["mdd"],
			"补仓1全样本成交_pct": m["pct_fill_1"],
			"补仓2全样本成交_pct": m["pct_fill_2"],
		},
		"档权重口径_ORDER_C_BIN_WEIGHTS": m.get("order_c_bin_weighted"),
		"差值_加权减等权": {
			"笔均_pp": m.get("diff_笔均_加权减等权_pp"),
			"收益合计近似_pct": m.get("diff_收益合计近似_加权减等权_pct"),
		},
	}
	return body


def write_order_c_ladder_summary_json(
	out_path: str | None = None,
	require_sse_ma5: bool = True,
) -> str:
	p = os.path.abspath(out_path or ORDER_C_LADDER_SUMMARY_JSON)
	body = build_order_c_adopted_summary_dict(require_sse_ma5=require_sse_ma5)
	os.makedirs(os.path.dirname(p), exist_ok=True)
	with open(p, "w", encoding="utf-8") as f:
		json.dump(body, f, ensure_ascii=False, indent=2)
	print(json.dumps(body, ensure_ascii=False, indent=2))
	return p


def format_profile_cells(profile: PullbackByBin | None) -> tuple[str, str, str, str, str]:
	"""画布「五档阈值」列：每格 \"补1/补2%\"。满仓对照返回五格「—」。"""
	if profile is None:
		return ("—", "—", "—", "—", "—")
	return tuple(
		"%.1f/%.1f" % (profile[i][0], profile[i][1]) for i in range(5)
	)


def order_c_adopted_summary_canvas_fragments(require_sse_ma5: bool = True) -> tuple[str, str]:
	"""实盘约定方案：等权 vs ORDER_C_BIN_WEIGHTS 加权汇总表（与 `dafengniu_order_c_ladder_summary.json` 同源）。"""
	d = build_order_c_adopted_summary_dict(require_sse_ma5=require_sse_ma5)

	def esc(x: object) -> str:
		if x is None:
			return "—"
		return str(x).replace("\\", "\\\\").replace("'", "\\'")

	eq = d["等权口径"]
	ow = d.get("档权重口径_ORDER_C_BIN_WEIGHTS") or {}
	diff = d.get("差值_加权减等权") or {}
	n_str = esc(eq.get("成交笔数"))

	row_eq = [
		"等权（与梯子回测表一致）",
		n_str,
		esc(eq.get("收益合计_pct")),
		esc(eq.get("单笔均值_pct")),
		esc(eq.get("夏普_笔收益")),
		esc(eq.get("胜率_pct")),
		esc(eq.get("最大回撤_链式净值_pct")),
		esc(eq.get("补仓1全样本成交_pct")),
		esc(eq.get("补仓2全样本成交_pct")),
	]
	row_w = [
		"档权重（单笔资金∝档权重）",
		n_str,
		esc(ow.get("收益合计近似_pct")),
		esc(ow.get("单笔均值_pct")),
		esc(ow.get("夏普_笔收益")),
		esc(ow.get("胜率_pct")),
		"—",
		"—",
		"—",
	]
	row_d = [
		"差值（加权−等权）",
		"—",
		esc(diff.get("收益合计近似_pct")),
		esc(diff.get("笔均_pp")),
		"—",
		"—",
		"—",
		"—",
		"—",
	]

	line_rows = (
		"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],\n"
		% tuple(row_eq)
		+ "\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],\n"
		% tuple(row_w)
		+ "\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
		% tuple(row_d)
	)

	meta = (
		"补仓口径："
		+ str(d.get("ORDER_C_补仓回落口径", ""))
		+ ("；T−1 上证收盘≥MA5 门控开启。" if require_sse_ma5 else "；上证 MA5 门控关闭。")
	)
	wline = "ORDER_C_BIN_WEIGHTS（Σ=1）：" + " / ".join("%.4f" % float(x) for x in ORDER_C_BIN_WEIGHTS)

	constants = (
		"""
const ORDER_C_ADOPTED_SUMMARY_META = """
		+ json.dumps(meta, ensure_ascii=False)
		+ """;

const ORDER_C_ADOPTED_SUMMARY_NOTE = """
		+ json.dumps(d.get("说明", ""), ensure_ascii=False)
		+ """;

const ORDER_C_BIN_WEIGHTS_LINE = """
		+ json.dumps(wline, ensure_ascii=False)
		+ """;

const ORDER_C_ADOPTED_SUMMARY_HEADERS = [
\t'口径',
\t'成交笔数',
\t'收益合计%',
\t'笔均%',
\t'夏普',
\t'胜率%',
\t'最大回撤%(链式)',
\t'补仓1全样本%',
\t'补仓2全样本%',
];

const ORDER_C_ADOPTED_SUMMARY_ROWS: string[][] = [
"""
		+ line_rows
		+ """
];
"""
	)

	jsx = """

\t\t\t<H2>ORDER-C：实盘约定 — 等权 vs 档权重汇总</H2>
\t\t\t<Text tone="secondary" size="small">{ORDER_C_ADOPTED_SUMMARY_META}</Text>
\t\t\t<Table headers={ORDER_C_ADOPTED_SUMMARY_HEADERS} rows={ORDER_C_ADOPTED_SUMMARY_ROWS} />
\t\t\t<Text tone="secondary" size="small">{ORDER_C_ADOPTED_SUMMARY_NOTE}</Text>
\t\t\t<Text tone="secondary" size="small">{ORDER_C_BIN_WEIGHTS_LINE}</Text>
"""

	return constants, jsx


def ladder_backtest_canvas_fragments(require_sse_ma5: bool = True) -> tuple[str, str]:
	rows_out = run_all_pullback_profiles(require_sse_ma5=require_sse_ma5)

	def esc(x: object) -> str:
		if x is None:
			return "—"
		return str(x).replace("\\", "\\\\").replace("'", "\\'")

	intro = (
		"每笔成交按其 **开盘涨跌%** 落入的五档之一，使用该档对应的 **补仓①/② 回落阈值（相对开盘价的最大下探%）**；"
		"触发仍用日线 **D0 最低 vs D0 开盘** 近似。"
		"首买/补仓名义仍为五档 `ORDER_C_LADDER_LEG_FRAC`；对照「满仓今开」不加补仓腿。"
		"当前 **实盘约定**：采用「五档优化买入（首买+两档补仓）+ "
		+ ORDER_C_ADOPTED_PROFILE_LABEL
		+ "」作为 ORDER-C 补仓回落口径（与表中该行一致）。其余方案供对照。参数表见 `ORDER_C_PULLBACK_PROFILES`。"
	)

	line_rows: list[str] = []
	def_rows: list[str] = []
	for r in rows_out:
		line_rows.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				esc(r["label"]),
				esc(r["n"]),
				esc(r["sum_r"]),
				esc(r["mean_r"]),
				esc(r["win_pct"]),
				esc(r["sharpe"]),
				esc(r["mdd"]),
				esc(r["pct_fill_1"]),
				esc(r["pct_fill_2"]),
			)
		)
		cells = format_profile_cells(r.get("profile"))
		def_rows.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				esc(r["label"]),
				esc(cells[0]),
				esc(cells[1]),
				esc(cells[2]),
				esc(cells[3]),
				esc(cells[4]),
			)
		)

	hdr_bins = "".join("\t'%s',\n" % esc(lb) for lb in ORDER_C_LADDER_BIN_LABELS)

	constants = (
		"""
const ORDER_C_LADDER_BT_INTRO = """
		+ json.dumps(intro, ensure_ascii=False)
		+ """;

const ORDER_C_LADDER_BT_HEADERS = [
\t'方案',
\t'N',
\t'收益合计%',
\t'笔均%',
\t'胜率%',
\t'夏普',
\t'最大回撤%(链式)',
\t'补仓1全样本成交%',
\t'补仓2全样本成交%',
];

const ORDER_C_LADDER_BT_ROWS: string[][] = [
"""
		+ "\n".join(line_rows)
		+ """
];

const ORDER_C_PROFILE_DEF_HEADERS = [
\t'方案',
"""
		+ hdr_bins
		+ """];

const ORDER_C_PROFILE_DEF_ROWS: string[][] = [
"""
		+ "\n".join(def_rows)
		+ """
];
"""
	)

	jsx = """

\t\t\t<Divider />

\t\t\t<H2>ORDER-C：分档回落补仓 — 组合回测（CSV 日线近似）</H2>
\t\t\t<Text tone="secondary" size="small">{ORDER_C_LADDER_BT_INTRO}</Text>
\t\t\t<Table headers={ORDER_C_LADDER_BT_HEADERS} rows={ORDER_C_LADDER_BT_ROWS} />
\t\t\t<Text tone="secondary" size="small">各方案五档阈值（补仓1%/补仓2%，相对开盘最大下探）</Text>
\t\t\t<Table headers={ORDER_C_PROFILE_DEF_HEADERS} rows={ORDER_C_PROFILE_DEF_ROWS} />
"""

	return constants, jsx


if __name__ == "__main__":
	ap = argparse.ArgumentParser(
		description="写入 ORDER-C 梯子 adopted 汇总（等权 vs ORDER_C 档权重），默认输出至 dafengniu_order_c_ladder_summary.json"
	)
	ap.add_argument(
		"-o",
		"--out",
		default=None,
		help="JSON 路径，默认见 dafengniu_paths.ORDER_C_LADDER_SUMMARY_JSON",
	)
	ap.add_argument(
		"--no-sse-gate",
		action="store_true",
		help="关闭 T-1 上证收盘≥MA5 门控（与回测表 require_sse_ma5=False 一致）",
	)
	args = ap.parse_args()
	write_order_c_ladder_summary_json(
		out_path=args.out,
		require_sse_ma5=not bool(args.no_sse_gate),
	)
