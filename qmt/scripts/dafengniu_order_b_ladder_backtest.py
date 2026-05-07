# -*- coding: utf-8 -*-
"""B 组（四档 gap / 仅 A·B 档建仓）：首买 + 两档补仓，回落阈值与 ORDER-C 采纳方案一致。

- 回落：**全局统一 2% / 3.0%**（`ORDER_C_ADOPTED_UNIFORM_PULLBACK_PCT`），仍以日线 **D0 最低 vs D0 开盘** 近似。
- 三腿名义（首买 / 补仓① / 补仓②）：固定 **0.5 / 0.3 / 0.2**（与 ORDER-C 中小低开档一致；不分 gap 五档）。
- 建仓口径：仅 **A、B** 档笔（与 `ORDER_GROUP_SPECS` B 组 filter_ab 一致）；D/C 档不买，不参与本回测汇总。
- 卖出：`simulate_exit_params`，锚点 **D0 开盘**（与既有扫描一致）。
"""

from __future__ import annotations

import bisect
import json
import os
import sys
from datetime import datetime
from typing import Any

import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_benchmark_ref_trades import (  # noqa: E402
	_f,
	buy_price_and_ok_with,
	compute_extended_metrics,
	gap_bracket_with,
)
from dafengniu_buy_combo_scan import (  # noqa: E402
	FIXED_D1_WEAK,
	FIXED_MAX_DAY,
	FIXED_SL,
	FIXED_SSE_TAIL,
	FIXED_TP,
)
from dafengniu_order_abc_position_canvas import ORDER_GROUP_SPECS  # noqa: E402
from dafengniu_order_c_ladder_backtest import (  # noqa: E402
	ORDER_C_ADOPTED_UNIFORM_PULLBACK_PCT,
	ret_pct_three_leg_ladder,
)
from dafengniu_paths import SYNC_OPEN_BAOSTOCK_CSV  # noqa: E402
from dafengniu_sell_combo_scan import load_data, simulate_exit_params  # noqa: E402

# B 组统一三腿（不分开盘涨跌幅五档）
GROUP_B_LADDER_LEG_FRAC: tuple[float, float, float] = (0.5, 0.3, 0.2)


def _collect_group_b_sim_rows(
	require_sse_ma5: bool,
) -> list[tuple[float, float, str, float, float | None, str, float]]:
	"""每笔：(sell_px, gap_pct%, day, d0_open, d0_low, tier D/A/B/C, bp 基准买入价)。

	与 `_collect_buy_combo_trades` 同一过滤；含 D/C 档便于分档切片。
	"""
	p = os.path.abspath(SYNC_OPEN_BAOSTOCK_CSV)
	df, sse_idx, sorted_dates = load_data(p)
	spec = ORDER_GROUP_SPECS[1]
	a_lo = float(spec["a_lo"])
	a_hi = float(spec["a_hi"])
	b_hi = float(spec["b_hi"])
	b_mult = float(spec["b_mult"])
	c_mult = float(spec["c_mult"])

	out: list[tuple[float, float, str, float, float | None, str, float]] = []

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

		gap = float(d0o / prev_c - 1.0)
		gap_pct = gap * 100.0
		br = gap_bracket_with(gap, a_lo, a_hi, b_hi)
		if br is None:
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

		d0_low_eff = d0_low if d0_low is not None else d0o
		bp, _skip = buy_price_and_ok_with(br, d0o, d0_low_eff, b_mult, c_mult)
		if bp is None:
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
			continue

		out.append(
			(
				float(sell_px),
				float(gap_pct),
				d0.strftime("%Y%m%d"),
				float(d0o),
				float(d0_low) if d0_low is not None and np.isfinite(d0_low) else None,
				str(br),
				float(bp),
			)
		)

	return out


def _metrics_pack(rets: list[float], days: list[str]) -> dict[str, Any]:
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
		}
	arr = np.array(rets, dtype=float)
	sum_r = float(np.sum(arr))
	mean_r = float(np.mean(arr))
	std_r = float(np.std(arr, ddof=1)) if n > 1 else 0.0
	sharpe = (mean_r / std_r) if std_r > 1e-12 else 0.0
	wins = float(np.sum(arr > 0))
	win_pct = wins / n * 100.0
	ext = compute_extended_metrics(arr, days)
	mdd = ext.get("最大回撤_链式净值_pct")
	return {
		"n": n,
		"sum_r": round(sum_r, 4),
		"mean_r": round(mean_r, 4),
		"sharpe": round(sharpe, 4),
		"mdd": round(mdd, 4) if mdd is not None else None,
		"win_pct": round(win_pct, 4),
	}


def run_group_b_adopted_ladder_snapshot(
	require_sse_ma5: bool = True,
) -> dict[str, Any]:
	"""返回：原 B 组（A/B 档按 bp 满仓）、采纳补仓（A/B 档）、按 tier A/B 分档。"""
	rows = _collect_group_b_sim_rows(require_sse_ma5=require_sse_ma5)
	t1, t2 = ORDER_C_ADOPTED_UNIFORM_PULLBACK_PCT
	f0, f1, f2 = GROUP_B_LADDER_LEG_FRAC

	rets_orig_ab: list[float] = []
	days_orig_ab: list[str] = []
	rets_lad_ab: list[float] = []
	days_lad_ab: list[str] = []
	r1 = r2 = 0

	rets_lad_by_tier: dict[str, list[float]] = {"A": [], "B": []}
	days_lad_by_tier: dict[str, list[str]] = {"A": [], "B": []}

	for sell_px, _gp, d, d0o, d0_lo, tier, bp in rows:
		if tier not in ("A", "B"):
			continue
		rets_orig_ab.append(float((sell_px / bp - 1.0) * 100.0))
		days_orig_ab.append(d)

		r_l, ok1, ok2 = ret_pct_three_leg_ladder(
			sell_px, d0o, d0_lo, t1, t2, f0, f1, f2
		)
		rets_lad_ab.append(r_l)
		days_lad_ab.append(d)
		if ok1:
			r1 += 1
		if ok2:
			r2 += 1
		rets_lad_by_tier[tier].append(r_l)
		days_lad_by_tier[tier].append(d)

	n_ab = len(rets_orig_ab)
	pct1 = round(r1 / n_ab * 100.0, 2) if n_ab else None
	pct2 = round(r2 / n_ab * 100.0, 2) if n_ab else None

	m_orig = _metrics_pack(rets_orig_ab, days_orig_ab)
	m_lad = _metrics_pack(rets_lad_ab, days_lad_ab)
	m_lad["pct_fill_1"] = pct1
	m_lad["pct_fill_2"] = pct2

	m_a = _metrics_pack(rets_lad_by_tier["A"], days_lad_by_tier["A"])
	m_b = _metrics_pack(rets_lad_by_tier["B"], days_lad_by_tier["B"])

	return {
		"baseline_bp_ab": {**m_orig, "label": "B组·原（A/B档·基准买价bp满仓）"},
		"ladder_2_3_ab": {**m_lad, "label": "B组·首买+补仓（全局2%/3.0%·仅A/B）"},
		"ladder_tier_A": m_a,
		"ladder_tier_B": m_b,
		"meta": {
			"legs": GROUP_B_LADDER_LEG_FRAC,
			"pullback_pct": ORDER_C_ADOPTED_UNIFORM_PULLBACK_PCT,
		},
	}


def group_b_ladder_canvas_fragments(require_sse_ma5: bool = True) -> tuple[str, str]:
	snap = run_group_b_adopted_ladder_snapshot(require_sse_ma5=require_sse_ma5)

	def esc(x: object) -> str:
		if x is None:
			return "—"
		return str(x).replace("\\", "\\\\").replace("'", "\\'")

	intro = (
		"B（A/B 档各 1 份）：仅 **A、B gap 档** 建仓；补仓回落与 ORDER-C 采纳一致 **2% / 3.0%**（日线 D0 最低 vs 开盘）；"
		"三腿名义固定 **0.5/0.3/0.2**。对照行仍为「基准买价 bp、满仓单笔」原 Σr；补仓行按加权成本重算收益。"
		"D/C 档 B 组不买，表中不汇总。"
	)

	def row_from_metric_block(mb: dict[str, Any]) -> str:
		return (
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				esc(mb.get("label", "")),
				esc(mb.get("n")),
				esc(mb.get("sum_r")),
				esc(mb.get("mean_r")),
				esc(mb.get("win_pct")),
				esc(mb.get("sharpe")),
				esc(mb.get("mdd")),
				esc(mb.get("pct_fill_1")),
				esc(mb.get("pct_fill_2")),
			)
		)

	b0 = snap["baseline_bp_ab"]
	bl = snap["ladder_2_3_ab"]
	ma = snap["ladder_tier_A"]
	mb = snap["ladder_tier_B"]

	line_rows = [
		row_from_metric_block(b0),
		row_from_metric_block(bl),
		"\t['分档·补仓后·仅A档', '%s', '%s', '%s', '%s', '%s', '%s', '—', '—'],"
		% (
			esc(ma.get("n")),
			esc(ma.get("sum_r")),
			esc(ma.get("mean_r")),
			esc(ma.get("win_pct")),
			esc(ma.get("sharpe")),
			esc(ma.get("mdd")),
		),
		"\t['分档·补仓后·仅B档', '%s', '%s', '%s', '%s', '%s', '%s', '—', '—'],"
		% (
			esc(mb.get("n")),
			esc(mb.get("sum_r")),
			esc(mb.get("mean_r")),
			esc(mb.get("win_pct")),
			esc(mb.get("sharpe")),
			esc(mb.get("mdd")),
		),
	]

	constants = (
		"""
const ORDER_GROUP_B_LADDER_INTRO = """
		+ json.dumps(intro, ensure_ascii=False)
		+ """;

const ORDER_GROUP_B_LADDER_HEADERS = [
\t'口径',
\t'N',
\t'收益合计%',
\t'笔均%',
\t'胜率%',
\t'夏普',
\t'最大回撤%(链式)',
\t'补仓1成交%',
\t'补仓2成交%',
];

const ORDER_GROUP_B_LADDER_ROWS: string[][] = [
"""
		+ "\n".join(line_rows)
		+ """
];
"""
	)

	jsx = """

\t\t\t<Divider />

\t\t\t<H2>ORDER-B：四档 gap — 首买+补仓（全局 2%/3.0%）</H2>
\t\t\t<Text tone="secondary" size="small">{ORDER_GROUP_B_LADDER_INTRO}</Text>
\t\t\t<Table headers={ORDER_GROUP_B_LADDER_HEADERS} rows={ORDER_GROUP_B_LADDER_ROWS} />
"""

	return constants, jsx
