# -*- coding: utf-8 -*-
"""基准买入（仓库 A_LO/A_HI/B_HI + B/C 折扣）下：同一批成交按「四档 D/A/B/C」与「七档 D0 开盘涨跌幅」归因；每笔 1 份金额。

供 ORDER 画布 G/H 段嵌入；依赖 baostock 拉上证（与 buy_combo_scan 一致）。
"""

from __future__ import annotations

import os
import sys

import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_benchmark_ref_trades import gap_bracket_with  # noqa: E402
from dafengniu_buy_combo_scan import (  # noqa: E402
	_collect_buy_combo_trades,
	REF_A_HI,
	REF_A_LO,
	REF_B_HI,
	REF_B_MULT,
	REF_C_MULT,
)
from dafengniu_paths import SYNC_OPEN_BAOSTOCK_CSV  # noqa: E402
from dafengniu_sell_combo_scan import load_data  # noqa: E402

ORDER_4_KEYS = ("D", "A", "B", "C")


def _bin7_label(gap_pct: float) -> str:
	"""与用户给定区间一致（相对昨收%，右闭左开除首档）。"""
	x = float(gap_pct)
	if x <= -5:
		return "≤-5%"
	if x <= -2:
		return "(-5,-2]"
	if x <= 0:
		return "(-2,0]"
	if x <= 2:
		return "(0,2]"
	if x <= 5:
		return "(2,5]"
	if x <= 8:
		return "(5,8]"
	return ">8%"


ORDER_7_LABELS = ["≤-5%", "(-5,-2]", "(-2,0]", "(0,2]", "(2,5]", "(5,8]", ">8%"]

# 与下单跳过规则一致：七档归因表中不计入「≤-5%」「>8%」区间的成交（先跳过再切片）。
GAP_H_BIN_SKIP_LOW_PCT = -5.0
GAP_H_BIN_SKIP_HIGH_PCT = 8.0


def gap_pct_in_h_attribution_bins(gap_pct: float) -> bool:
	"""是否参与 H 七档归因统计（排除与 ORDER 跳过一致的极端开盘缺口）。"""
	x = float(gap_pct)
	return x > GAP_H_BIN_SKIP_LOW_PCT and x <= GAP_H_BIN_SKIP_HIGH_PCT


def _stats(rets: list[float]) -> tuple[int, float, float, float]:
	if not rets:
		return 0, 0.0, 0.0, 0.0
	arr = np.array(rets, dtype=float)
	n = len(arr)
	return (
		n,
		float(np.sum(arr)),
		float(np.mean(arr)),
		float(np.mean(arr > 0.0) * 100.0),
	)


def load_baseline_trades(require_ma5: bool = True) -> tuple[list[tuple[float, float, str]], dict[str, int]]:
	"""基准买入下全部成交笔：(收益%, D0开盘涨跌%, 开仓日)。"""
	p = os.path.abspath(SYNC_OPEN_BAOSTOCK_CSV)
	df, sse_idx, sorted_dates = load_data(p)
	return _collect_buy_combo_trades(
		df,
		sse_idx,
		sorted_dates,
		a_lo=REF_A_LO,
		a_hi=REF_A_HI,
		b_hi=REF_B_HI,
		b_mult=REF_B_MULT,
		c_mult=REF_C_MULT,
		require_sse_ma5=require_ma5,
	)


def compute_bucket_rows(require_ma5: bool = True) -> tuple[list[tuple], list[tuple]]:
	"""返回四档行列表、七档行列表；每行 (标签, N, 合计%, 笔均%, 胜率%)。"""
	trades, _skip = load_baseline_trades(require_ma5=require_ma5)

	by4: dict[str, list[float]] = {k: [] for k in ORDER_4_KEYS}
	by7: dict[str, list[float]] = {lb: [] for lb in ORDER_7_LABELS}

	for ret, gap_pct, _day in trades:
		gf = float(gap_pct) / 100.0
		br = gap_bracket_with(gf, REF_A_LO, REF_A_HI, REF_B_HI)
		if br in by4:
			by4[br].append(float(ret))
		if gap_pct_in_h_attribution_bins(float(gap_pct)):
			lb = _bin7_label(float(gap_pct))
			if lb in by7:
				by7[lb].append(float(ret))

	rows4: list[tuple] = []
	for k in ORDER_4_KEYS:
		n, s, m, w = _stats(by4[k])
		rows4.append((k, n, round(s, 4), round(m, 4), round(w, 4)))

	rows7: list[tuple] = []
	for lb in ORDER_7_LABELS:
		n, s, m, w = _stats(by7[lb])
		rows7.append((lb, n, round(s, 4), round(m, 4), round(w, 4)))

	return rows4, rows7


def bucket_canvas_fragments(require_ma5: bool = True) -> tuple[str, str]:
	"""返回 (TS 常量片段, JSX 片段)。"""
	rows4, rows7 = compute_bucket_rows(require_ma5=require_ma5)

	def esc(x: object) -> str:
		s = str(x).replace("\\", "\\\\").replace("'", "\\'")
		return s

	def line(row: tuple) -> str:
		a, b, c, d, e = row
		return (
			"\t['%s', '%s', '%s', '%s', '%s'],"
			% (esc(a), esc(b), esc(c), esc(d), esc(e))
		)

	g_body = "\n".join(line(r) for r in rows4)
	h_body = "\n".join(line(r) for r in rows7)

	gc = (
		"""
const ORDER_G_HEADERS = [
\t'档(D/A/B/C)',
\t'N',
\t'合计%',
\t'笔均%',
\t'胜率%',
];

const ORDER_G_ROWS: string[][] = [
"""
		+ g_body
		+ """
];

const ORDER_H_HEADERS = [
\t'D0开盘涨跌区间',
\t'N',
\t'合计%',
\t'笔均%',
\t'胜率%',
];

const ORDER_H_ROWS: string[][] = [
"""
		+ h_body
		+ """
];
"""
	)

	jsx = """

\t\t\t<Divider />

\t\t\t<H2>G：四档归因（基准买入触发，每笔 1 份）</H2>
\t\t\t<Text tone="secondary" size="small">
\t\t\t\t与仓库 gap 分档一致：D/A/B/C 边界 A_LO/A_HI/B_HI；成交笔与基准扫描相同。
\t\t\t</Text>
\t\t\t<Table headers={ORDER_G_HEADERS} rows={ORDER_G_ROWS} />

\t\t\t<Divider />

\t\t\t<H2>H：七档归因（按 D0 开盘涨跌幅相对昨收%，每笔 1 份）</H2>
\t\t\t<Text tone="secondary" size="small">
\t\t\t\t同一批复盘成交，按开盘跳空区间切片；先剔除开盘涨跌≤-5%、超过 8% 的成交（与下单跳过一致），故 ≤-5%、超过 8% 两档 N 恒为 0；卖出规则与 G 相同。
\t\t\t</Text>
\t\t\t<Table headers={ORDER_H_HEADERS} rows={ORDER_H_ROWS} />
"""

	return gc, jsx
