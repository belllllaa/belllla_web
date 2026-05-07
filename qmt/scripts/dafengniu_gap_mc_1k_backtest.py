# -*- coding: utf-8 -*-
"""
dafengniu 风格：固定卖出规则；买入为 gap 三档分界随机组合 + D/A 直接买、B/C 需 D0 最低价触价。

gap = D0_开盘 / D0前收盘 - 1

买入（与约定一致）：
  D: gap <= e_d                    → 开仓价 = D0_开盘
  A: e_d < gap < e_ab              → 开仓价 = D0_开盘
  B: e_ab <= gap < e_bc            → 仅当 D0_最低 <= D0_开盘×0.97 时买入，开仓价 = D0_开盘×0.97
  C: gap >= e_bc                   → 仅当 D0_最低 <= D0_开盘×0.96 时买入，开仓价 = D0_开盘×0.96
  参数约束：e_d < e_ab < e_bc，且三者均在 [-9.5%, +9.5%] 内（贴近涨跌停、兼顾流动性）。

卖出（固定）：D1–D3 每日开盘止损/止盈；D1 收盘弱；D2–D3 收盘转弱；D3 收盘到期。

输出：默认 qmt/scripts/output/dafengniu_gap_mc_2k.json（默认 2000 组）

用法：
  python qmt/scripts/dafengniu_gap_mc_1k_backtest.py
  python qmt/scripts/dafengniu_gap_mc_1k_backtest.py path/to.csv 2000 42
"""

from __future__ import annotations

import json
import math
import os
import random
import sys

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "实盘策略", "dafengniu_open_window_metrics_qmt.csv"))
OUT_JSON = os.path.normpath(os.path.join(SCRIPT_DIR, "output", "dafengniu_gap_mc_2k.json"))

# 三档分界（小数 gap）允许范围：±9.5%（相对昨收的 gap 与 A 股日涨跌幅量级一致，留余量）
EDGE_LO = -0.095
EDGE_HI = 0.095

SL = -0.07
TP = 0.07
D1_WEAK = 0.005
WEAKEN = 0.0
B_MULT = 0.97
C_MULT = 0.96


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
	if x <= 0 and col not in ("D0前收盘",):
		return None
	return x


def simulate_exit_detail(row: pd.Series) -> dict | None:
	"""依赖 D0–D3 K 线，返回平仓价、发生在第几日(D1–D3)、原因（与 simulate_exit_price 逻辑一致）。"""
	d0 = _f(row, "D0_开盘")
	if d0 is None or d0 <= 0:
		return None
	days: list[tuple[float, float]] = []
	for k in (1, 2, 3):
		o = _f(row, "D%d_开盘" % k)
		c = _f(row, "D%d_收盘" % k)
		if o is None or c is None:
			return None
		days.append((o, c))
	prev_close = _f(row, "D0_收盘")
	if prev_close is None:
		prev_close = d0

	for idx, (o, c) in enumerate(days, start=1):
		if o <= d0 * (1.0 + SL):
			return {"exit_px": float(o), "d_idx": idx, "reason": "开盘触及止损(-7%)", "leg": "开盘"}
		if o >= d0 * (1.0 + TP):
			return {"exit_px": float(o), "d_idx": idx, "reason": "开盘触及止盈(+7%)", "leg": "开盘"}
		if idx == 1:
			if c < d0 * (1.0 + D1_WEAK):
				return {"exit_px": float(c), "d_idx": idx, "reason": "D1收盘弱于D0开盘+0.5%", "leg": "收盘"}
		else:
			if c <= prev_close * (1.0 + WEAKEN):
				return {"exit_px": float(c), "d_idx": idx, "reason": "收盘转弱(≤前日收盘)", "leg": "收盘"}
		if idx == 3:
			return {"exit_px": float(c), "d_idx": idx, "reason": "D3收盘到期", "leg": "收盘"}
		prev_close = c
	return None


def simulate_exit_price(row: pd.Series) -> float | None:
	d = simulate_exit_detail(row)
	return d["exit_px"] if d else None


def classify_entry(
	gap: float,
	e_d: float,
	e_ab: float,
	e_bc: float,
	d0_open: float,
	d0_low: float | None,
) -> tuple[str | None, float | None]:
	"""返回 (档位, 开仓价) 或 (None, None)。"""
	if gap <= e_d:
		return "D", d0_open
	if gap >= e_bc:
		if d0_low is None or d0_low > d0_open * C_MULT:
			return None, None
		return "C", d0_open * C_MULT
	if gap >= e_ab:
		if d0_low is None or d0_low > d0_open * B_MULT:
			return None, None
		return "B", d0_open * B_MULT
	if gap > e_d:
		return "A", d0_open
	return None, None


def sample_edges(rng: random.Random) -> tuple[float, float, float] | None:
	"""在 [EDGE_LO, EDGE_HI] 内随机三个分界点，排序得 e_d < e_ab < e_bc（均落在 ±9.5% 内）。"""
	lo, hi = EDGE_LO, EDGE_HI
	x1, x2, x3 = rng.uniform(lo, hi), rng.uniform(lo, hi), rng.uniform(lo, hi)
	a, b, c = sorted([x1, x2, x3])
	e_d, e_ab, e_bc = round(a, 4), round(b, 4), round(c, 4)
	e_d = max(lo, min(e_d, hi))
	e_ab = max(lo, min(e_ab, hi))
	e_bc = max(lo, min(e_bc, hi))
	if not (e_d < e_ab < e_bc):
		return None
	if (e_bc - e_d) < 0.015:
		return None
	return e_d, e_ab, e_bc


def run_mc(csv_path: str, n: int = 1000, seed: int = 42) -> dict:
	df = pd.read_csv(csv_path, encoding="utf-8-sig")
	rng = random.Random(seed)

	rows_data: list[dict] = []
	for _, row in df.iterrows():
		if str(row.get("_error", "") or "").strip() == "short_tail":
			continue
		prev = _f(row, "D0前收盘")
		d0 = _f(row, "D0_开盘")
		low = _f(row, "D0_最低")
		if prev is None or prev <= 0 or d0 is None or d0 <= 0:
			continue
		gap = d0 / prev - 1.0
		xp = simulate_exit_price(row)
		if xp is None:
			continue
		rows_data.append(
			{
				"code": str(row.get("代码", "")),
				"open_date": str(row.get("开仓日", "")),
				"gap": gap,
				"d0": d0,
				"low": low,
				"exit_px": xp,
			}
		)

	def one_combo(e_d: float, e_ab: float, e_bc: float) -> dict:
		rets: list[float] = []
		dates: list[str] = []
		for r in rows_data:
			br, ent = classify_entry(r["gap"], e_d, e_ab, e_bc, r["d0"], r["low"])
			if br is None or ent is None or ent <= 0:
				continue
			xp = r["exit_px"]
			rets.append((xp - ent) / ent)
			dates.append(r["open_date"])

		n_tr = len(rets)
		if n_tr <= 0:
			return None
		wins = sum(1 for x in rets if x > 0)
		win_rate = wins / n_tr
		mean_r = sum(rets) / n_tr
		sum_r = sum(rets)
		order = sorted(range(n_tr), key=lambda i: dates[i])
		nav = 1.0
		for i in order:
			nav *= 1.0 + rets[i]

		return {
			"e_d_pct": round(e_d * 100, 2),
			"e_ab_pct": round(e_ab * 100, 2),
			"e_bc_pct": round(e_bc * 100, 2),
			"n": n_tr,
			"win_rate_pct": round(win_rate * 100, 2),
			"mean_return_pct": round(mean_r * 100, 4),
			"sum_return_pct": round(sum_r * 100, 4),
			"nav_chain": round(nav, 6),
		}

	bm = one_combo(-0.05, 0.03, 0.07)
	baseline_metrics = bm if bm is not None else {}
	if baseline_metrics:
		baseline_metrics = dict(baseline_metrics)
		baseline_metrics["label"] = "baseline_-5_3_7"

	results: list[dict] = []
	attempts = 0
	while len(results) < n and attempts < n * 500:
		attempts += 1
		trip = sample_edges(rng)
		if trip is None:
			continue
		e_d, e_ab, e_bc = trip
		# 避免与基准完全重复占名额
		if abs(e_d + 0.05) < 1e-6 and abs(e_ab - 0.03) < 1e-6 and abs(e_bc - 0.07) < 1e-6:
			continue
		row = one_combo(e_d, e_ab, e_bc)
		if row is None:
			continue
		results.append(row)

	# 展示排序：合计% 优先，其次胜率（与「找总收益更强」一致）
	results.sort(key=lambda x: (-x["sum_return_pct"], -x["win_rate_pct"]))

	return {
		"csv": os.path.abspath(csv_path),
		"seed": seed,
		"n_requested": n,
		"n_valid_results": len(results),
		"n_stocks_prepared": len(rows_data),
		"gap_edge_bounds_pct": {"lo": round(EDGE_LO * 100, 2), "hi": round(EDGE_HI * 100, 2)},
		"baseline_edges_pct": {"e_d": -5.0, "e_ab": 3.0, "e_bc": 7.0},
		"baseline_metrics": baseline_metrics,
		"best": results[0] if results else None,
		"summary": {
			"max_win_rate": max(x["win_rate_pct"] for x in results) if results else None,
			"max_mean_return": max(x["mean_return_pct"] for x in results) if results else None,
			"max_nav": max(x["nav_chain"] for x in results) if results else None,
		},
		"top30": results[:30],
		"combinations": results,
		"note": "e_d<e_ab<e_bc 均在 ±9.5% 内随机（三均匀排序）；不含与基准(-5,3,7)完全相同的重复；B/C 需 D0_最低触价；combinations 按合计%、胜率降序；另单独 baseline_metrics。",
	}


def main() -> None:
	csv_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
	n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
	seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
	out = run_mc(csv_path, n=n, seed=seed)
	os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
	with open(OUT_JSON, "w", encoding="utf-8") as f:
		json.dump(out, f, ensure_ascii=False, indent=2)
	print(json.dumps(out["summary"], ensure_ascii=False))
	print("[json]", OUT_JSON, "n_valid", out["n_valid_results"], "stocks", out["n_stocks_prepared"])


if __name__ == "__main__":
	main()
