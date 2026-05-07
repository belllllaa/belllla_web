# -*- coding: utf-8 -*-
"""
A 档 gap 上下沿网格回测（样本：dafengniu_open_window_metrics_qmt.csv）。

固定：D / B / C 分界与策略一致（D: gap<=-5%；B: [3%,7%)；C: >=7%）。
仅 A 档：a_lo < gap <= a_hi，且 gap 落在 (-5%, 3%) 内（与 B 不重叠）时才为 A；
  即先判 D/C/B，再在 (-5%,3%) 内用 (a_lo, a_hi] 判定 A，否则不买。

卖出（与约定一致）：D1–D3 每日开盘先判止损/止盈；D1 尾盘 close < d0*(1+0.5%)；
D2–D3 尾盘 close <= 前一日收盘；D3 尾盘仍持仓则到期平仓。

买入价：D0 开盘；卖出价：触发规则当根价（开盘或收盘）。

输出：JSON 摘要 + 可选写出 Canvas 数据片段。
"""

from __future__ import annotations

import json
import math
import os
import sys

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "实盘策略", "dafengniu_open_window_metrics_qmt.csv"))

# 固定档（与图中 + 策略 B/C 一致）
D_TH = -0.05
B_LO = 0.03
B_HI = 0.07
C_TH = 0.07

# 卖出参数
SL = -0.07
TP = 0.07
D1_WEAK = 0.005
WEAKEN = 0.0


def pct_grid() -> list[float]:
	out = []
	x = -0.05
	while x <= 0.07 + 1e-9:
		out.append(round(x, 6))
		x += 0.005
	return out


def classify_buy(gap: float, a_lo: float, a_hi: float) -> str | None:
	if gap <= D_TH:
		return "D"
	if gap >= C_TH:
		return "C"
	if gap >= B_LO:
		return "B"
	# A 与 D/B 不重叠：(-5%, 3%)
	if gap > D_TH and gap < B_LO and gap > a_lo and gap <= a_hi:
		return "A"
	return None


def _f(row: pd.Series, col: str) -> float | None:
	if col not in row.index:
		return None
	v = row[col]
	if v is None or (isinstance(v, float) and math.isnan(v)):
		return None
	try:
		x = float(v)
	except (TypeError, ValueError):
		return None
	if x <= 0 and col != "D0前收盘":
		return None
	return x


def simulate_trade(row: pd.Series) -> float | None:
	"""单笔简单收益率 (exit-entry)/entry；无法模拟则 None。"""
	d0 = _f(row, "D0_开盘")
	prev = _f(row, "D0前收盘")
	if d0 is None or prev is None or prev <= 0 or d0 <= 0:
		return None
	days = []
	for k in (1, 2, 3):
		o = _f(row, "D%d_开盘" % k)
		c = _f(row, "D%d_收盘" % k)
		if o is None or c is None:
			return None
		days.append((o, c))
	entry = d0
	prev_close = _f(row, "D0_收盘")
	if prev_close is None:
		prev_close = d0

	for idx, (o, c) in enumerate(days, start=1):
		# 开盘止损 / 止盈
		if o <= d0 * (1.0 + SL):
			return (o - entry) / entry
		if o >= d0 * (1.0 + TP):
			return (o - entry) / entry
		# 尾盘
		if idx == 1:
			if c < d0 * (1.0 + D1_WEAK):
				return (c - entry) / entry
		else:
			if c <= prev_close * (1.0 + WEAKEN):
				return (c - entry) / entry
		if idx == 3:
			return (c - entry) / entry
		prev_close = c
	return None


def run_grid(csv_path: str) -> dict:
	df = pd.read_csv(csv_path, encoding="utf-8-sig")
	grid = pct_grid()
	pairs: list[tuple[float, float]] = []
	for i, lo in enumerate(grid):
		for hi in grid[i + 1 :]:
			pairs.append((lo, hi))

	rows_out: list[dict] = []
	baseline = (-0.05, 0.03)  # 与图中 A 档 (-5%,+3%) 一致；右端为 gap<3% 故上沿取 3%

	for a_lo, a_hi in pairs:
		rets: list[float] = []
		dates: list[str] = []
		codes: list[str] = []
		for _, row in df.iterrows():
			if str(row.get("_error", "") or "").strip() == "short_tail":
				continue
			prev = _f(row, "D0前收盘")
			d0o = _f(row, "D0_开盘")
			if prev is None or d0o is None or prev <= 0:
				continue
			gap = d0o / prev - 1.0
			br = classify_buy(gap, a_lo, a_hi)
			if br is None:
				continue
			r = simulate_trade(row)
			if r is None:
				continue
			rets.append(r)
			dates.append(str(row.get("开仓日", "")))
			codes.append(str(row.get("代码", "")))

		n = len(rets)
		wins = sum(1 for x in rets if x > 0)
		win_rate = (wins / n) if n else 0.0
		mean_r = sum(rets) / n if n else 0.0
		sum_r = sum(rets)
		# 按开仓日排序的等权链式净值（仅用于对比不同参数）
		order = sorted(range(n), key=lambda i: dates[i])
		nav = 1.0
		for i in order:
			nav *= 1.0 + rets[i]
		rows_out.append(
			{
				"a_lo_pct": round(a_lo * 100, 2),
				"a_hi_pct": round(a_hi * 100, 2),
				"n": n,
				"win_rate_pct": round(win_rate * 100, 2),
				"mean_return_pct": round(mean_r * 100, 4),
				"sum_return_pct": round(sum_r * 100, 4),
				"nav_chain": round(nav, 6),
				"is_baseline": abs(a_lo - baseline[0]) < 1e-9 and abs(a_hi - baseline[1]) < 1e-9,
			}
		)

	rows_out.sort(key=lambda x: (-x["win_rate_pct"], -x["mean_return_pct"]))
	best = rows_out[0] if rows_out else {}
	base_row = next((x for x in rows_out if x.get("is_baseline")), None)
	return {
		"csv": csv_path,
		"n_pairs": len(pairs),
		"n_csv_rows": len(df),
		"best": best,
		"baseline": base_row,
		"top25": rows_out[:25],
		"summary": {
			"max_win_rate": max(x["win_rate_pct"] for x in rows_out) if rows_out else None,
			"max_mean_return": max(x["mean_return_pct"] for x in rows_out) if rows_out else None,
			"max_nav": max(x["nav_chain"] for x in rows_out) if rows_out else None,
		},
	}


def main() -> None:
	csv_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
	out = run_grid(csv_path)
	out_path = os.path.join(SCRIPT_DIR, "output", "a_band_grid_open_window.json")
	os.makedirs(os.path.dirname(out_path), exist_ok=True)
	with open(out_path, "w", encoding="utf-8") as f:
		json.dump(out, f, ensure_ascii=False, indent=2)
	print(json.dumps(out["summary"], ensure_ascii=False))
	print("[json]", out_path)


if __name__ == "__main__":
	main()
