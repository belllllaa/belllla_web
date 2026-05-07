# -*- coding: utf-8 -*-
"""跳过规则 + 按七档（D0 开盘涨跌区间）胜率·笔均定加权系数，生成 ORDER 画布 I 段。

  跳过：
  · G：D 档、C 档不买
  · H：D0 开盘涨跌幅 ≤−5% 或 >8% 不买（与 H 段七档归因先剔除的区间一致）

  可交易样本内按七档区间聚合胜率、笔均，仅在有余额的档间 min-max 归一后 0.5/0.5 合成得分并线性映射到系数区间。
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_benchmark_ref_trades import (  # noqa: E402
	compute_extended_metrics,
	gap_bracket_with,
)
from dafengniu_buy_combo_scan import REF_A_HI, REF_A_LO, REF_B_HI  # noqa: E402
from dafengniu_order_bucket_tables import (  # noqa: E402
	ORDER_7_LABELS,
	_bin7_label,
	load_baseline_trades,
)

# ---------- 规则 ----------
SKIP_BRACKETS_G: frozenset[str] = frozenset({"D", "C"})
GAP_SKIP_LOW_PCT = -5.0  # 含等号：≤−5%
GAP_SKIP_HIGH_PCT = 8.0  # 严格大于 8%

# ---------- 系数 ----------
COEF_MIN = 0.35
COEF_MAX = 1.0
W_WIN = 0.5
W_MEAN = 0.5


def _bracket(gap_pct: float) -> str:
	gf = float(gap_pct) / 100.0
	br = gap_bracket_with(gf, REF_A_LO, REF_A_HI, REF_B_HI)
	return br if br is not None else "?"


def _skip_reason(gap_pct: float, br: str) -> str | None:
	if br in SKIP_BRACKETS_G:
		return "G档%s" % br
	if float(gap_pct) <= GAP_SKIP_LOW_PCT:
		return "H≤-5%"
	if float(gap_pct) > GAP_SKIP_HIGH_PCT:
		return "H>8%"
	return None


def _coef_map(by_eligible: dict[str, list[float]]) -> dict[str, float]:
	"""对存在成交的七档区间给系数；得分 = 胜率与笔均在档间的 min-max 归一后加权。"""
	active = [lb for lb in ORDER_7_LABELS if by_eligible.get(lb)]
	if not active:
		return {}
	if len(active) == 1:
		br = active[0]
		return {br: round((COEF_MIN + COEF_MAX) / 2.0, 4)}

	wins: dict[str, float] = {}
	means: dict[str, float] = {}
	for br in active:
		arr = np.array(by_eligible[br], dtype=float)
		wins[br] = float(np.mean(arr > 0.0) * 100.0)
		means[br] = float(np.mean(arr))

	wv = [wins[br] for br in active]
	mv = [means[br] for br in active]
	w_lo, w_hi = min(wv), max(wv)
	m_lo, m_hi = min(mv), max(mv)

	def _norm(x: float, lo: float, hi: float) -> float:
		if hi - lo < 1e-12:
			return 0.5
		return (x - lo) / (hi - lo)

	scores: dict[str, float] = {}
	for br in active:
		nw = _norm(wins[br], w_lo, w_hi)
		nm = _norm(means[br], m_lo, m_hi)
		scores[br] = W_WIN * nw + W_MEAN * nm

	sv = [scores[br] for br in active]
	s_lo, s_hi = min(sv), max(sv)
	out: dict[str, float] = {}
	for br in active:
		if s_hi - s_lo < 1e-12:
			out[br] = round((COEF_MIN + COEF_MAX) / 2.0, 4)
		else:
			t = (scores[br] - s_lo) / (s_hi - s_lo)
			out[br] = round(COEF_MIN + t * (COEF_MAX - COEF_MIN), 4)
	return out


def compute_skip_weight_snapshot(require_ma5: bool = True) -> dict:
	trades, _sk = load_baseline_trades(require_ma5=require_ma5)
	n_all = len(trades)

	skip_reasons: Counter[str] = Counter()
	eligible: list[tuple[float, float, str, str]] = []
	for ret, gap_pct, day in trades:
		br = _bracket(gap_pct)
		reason = _skip_reason(gap_pct, br)
		if reason:
			skip_reasons[reason] += 1
			continue
		eligible.append((float(ret), float(gap_pct), br, str(day)))

	by_elig: dict[str, list[float]] = {lb: [] for lb in ORDER_7_LABELS}
	for ret, gp, _br4, _d in eligible:
		lb = _bin7_label(gp)
		if lb in by_elig:
			by_elig[lb].append(ret)

	coef = _coef_map(by_elig)

	sum_r_elig = sum(r for r, _, _, _ in eligible)
	sum_coef_r = sum(
		coef.get(_bin7_label(gp), 0.0) * r for r, gp, _, __ in eligible
	)
	sum_coef = sum(coef.get(_bin7_label(gp), 0.0) for r, gp, _, __ in eligible)
	w_avg = (sum_coef_r / sum_coef) if sum_coef > 1e-12 else 0.0

	rows_coef: list[tuple] = []
	for lb in ORDER_7_LABELS:
		rets = by_elig.get(lb, [])
		if not rets:
			continue
		arr = np.array(rets, dtype=float)
		n = len(arr)
		wr = float(np.mean(arr > 0.0) * 100.0)
		mn = float(np.mean(arr))
		c = coef.get(lb, COEF_MIN)
		rows_coef.append((lb, n, round(wr, 4), round(mn, 4), c))

	rows_skip = [(k, v) for k, v in sorted(skip_reasons.items())]

	n_elig = len(eligible)
	rets_arr = np.array([t[0] for t in eligible], dtype=float) if eligible else np.array([], dtype=float)
	buy_days = [t[3] for t in eligible]
	ext_chain = compute_extended_metrics(rets_arr, buy_days) if n_elig else None
	coef_pts = (
		np.array(
			[
				coef.get(_bin7_label(gp), COEF_MIN) * r
				for r, gp, _, __ in eligible
			],
			dtype=float,
		)
		if eligible
		else np.array([], dtype=float)
	)
	ext_coef = compute_extended_metrics(coef_pts, buy_days) if n_elig else None

	mdd_full = ext_chain.get("最大回撤_链式净值_pct") if ext_chain else None
	mdd_coef = ext_coef.get("最大回撤_链式净值_pct") if ext_coef else None
	win_cnt = int(np.sum(rets_arr > 0.0)) if n_elig else 0
	win_rate_all = (win_cnt / n_elig * 100.0) if n_elig else None

	return {
		"n_all": n_all,
		"n_skip": n_all - len(eligible),
		"n_eligible": len(eligible),
		"sum_r_eligible": round(sum_r_elig, 4),
		"sum_coef_times_r": round(sum_coef_r, 4),
		"sum_coef": round(sum_coef, 4),
		"weighted_mean_pct": round(w_avg, 4),
		"max_dd_chain_pct": round(mdd_full, 4) if mdd_full is not None else None,
		"max_dd_coef_chain_pct": round(mdd_coef, 4) if mdd_coef is not None else None,
		"win_rate_all_pct": round(win_rate_all, 4) if win_rate_all is not None else None,
		"coef_map": coef,
		"rows_coef": rows_coef,
		"rows_skip": rows_skip,
	}


def skip_weight_canvas_fragments(require_ma5: bool = True) -> tuple[str, str]:
	snap = compute_skip_weight_snapshot(require_ma5=require_ma5)

	def esc(x: object) -> str:
		return str(x).replace("\\", "\\\\").replace("'", "\\'")

	def line5(row: tuple) -> str:
		a, b, c, d, e = row
		return "\t['%s', '%s', '%s', '%s', '%s']," % (
			esc(a),
			esc(b),
			esc(c),
			esc(d),
			esc(e),
		)

	def line2(row: tuple) -> str:
		a, b = row
		return "\t['%s', '%s']," % (esc(a), esc(b))

	coef_body = "\n".join(line5(r) for r in snap["rows_coef"]) if snap["rows_coef"] else "\t['(无可交易七档样本)', '', '', '', ''],"
	skip_body = "\n".join(line2(r) for r in snap["rows_skip"]) if snap["rows_skip"] else "\t['-', '0'],"

	def cell_opt(v: object) -> str:
		if v is None:
			return "—"
		return esc(v)

	ref_rule = (
		"G：跳过 D、C 档；H：跳过开盘涨跌%%≤%.1f 或 >%.1f；"
		"系数区间 [%.2f, %.2f]；得分=胜率与笔均在七档（可交易中间区间）内 min-max 归一后 %.0f%%胜率+%.0f%%笔均"
		% (
			GAP_SKIP_LOW_PCT,
			GAP_SKIP_HIGH_PCT,
			COEF_MIN,
			COEF_MAX,
			W_WIN * 100,
			W_MEAN * 100,
		)
	)

	constants = (
		"""
const ORDER_I_RULE_TEXT = """
		+ json.dumps(ref_rule, ensure_ascii=False)
		+ """;

const ORDER_I_COEF_HEADERS = [
\t'七档区间',
\t'可交易N',
\t'胜率%',
\t'笔均%',
\t'加权系数',
];

const ORDER_I_COEF_ROWS: string[][] = [
"""
		+ coef_body
		+ """
];

const ORDER_I_SKIP_HEADERS = [
\t'跳过原因',
\t'笔数',
];

const ORDER_I_SKIP_ROWS: string[][] = [
"""
		+ skip_body
		+ """
];

const ORDER_I_SUM_HEADERS = [
\t'指标',
\t'数值',
];

const ORDER_I_SUM_ROWS: string[][] = [
\t['总成交笔', '"""
		+ esc(snap["n_all"])
		+ """'],
\t['跳过笔数', '"""
		+ esc(snap["n_skip"])
		+ """'],
\t['可交易笔数', '"""
		+ esc(snap["n_eligible"])
		+ """'],
\t['可交易Σr%', '"""
		+ esc(snap["sum_r_eligible"])
		+ """'],
\t['Σ(系数×r)%', '"""
		+ esc(snap["sum_coef_times_r"])
		+ """'],
\t['Σ系数', '"""
		+ esc(snap["sum_coef"])
		+ """'],
\t['加权笔均%=Σ coef×r / Σcoef', '"""
		+ esc(snap["weighted_mean_pct"])
		+ """'],
\t['整体胜率%(逐笔)', '"""
		+ cell_opt(snap.get("win_rate_all_pct"))
		+ """'],
\t['最大回撤%(链式·满仓等价)', '"""
		+ cell_opt(snap.get("max_dd_chain_pct"))
		+ """'],
\t['最大回撤%(链式·每步系数×r)', '"""
		+ cell_opt(snap.get("max_dd_coef_chain_pct"))
		+ """'],
];
"""
	)

	jsx = """

\t\t\t<Divider />

\t\t\t<H2>I：跳过规则 + 七档胜率·笔均加权系数</H2>
\t\t\t<Text tone="secondary" size="small">{ORDER_I_RULE_TEXT}</Text>
\t\t\t<Table headers={ORDER_I_COEF_HEADERS} rows={ORDER_I_COEF_ROWS} />

\t\t\t<Divider />

\t\t\t<Text tone="secondary" size="small">跳过笔数归因（与 G/H 切片一致的一套成交）</Text>
\t\t\t<Table headers={ORDER_I_SKIP_HEADERS} rows={ORDER_I_SKIP_ROWS} />

\t\t\t<Divider />

\t\t\t<Text tone="secondary" size="small">
\t\t\t\t可交易样本汇总（通过 G/H 跳过规则后，按七档区间加权；回撤与 A 段同为按开仓日排序的链式净值最大回撤，满仓等价列与单笔 r 一致；系数列为每步用系数×r 复利）。
\t\t\t</Text>
\t\t\t<Table headers={ORDER_I_SUM_HEADERS} rows={ORDER_I_SUM_ROWS} />
"""

	return constants, jsx
