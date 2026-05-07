# -*- coding: utf-8 -*-
"""参考基准（默认）：四档跳空买入 + 指数 MA5 门控 + grid_d3 卖出 + 尾盘上证收盘低于 MA5 清仓。

数据来源：dafengniu_sync_open_baostock.csv（个股 OHLC）；上证指数日线单独 Baostock 拉取用于 MA5/MA10 与交易日历。

买入：
  gap = D0_开盘 / D前1_收盘 - 1
  D: gap≤−5% → 买价=D0_开盘；A: (−5%,+3%) → D0_开盘
  B: [+3%,+7%) 且 D0_最低≤今开×0.97 → 买价=今开×0.97
  C: ≥+7% 且 D0_最低≤今开×0.96 → 买价=今开×0.96
  门控 require_sse_above_ma5_for_new：T−1 上证收盘 ≥ T−1 上证 MA5

卖出（相对 d0_open=D0_开盘）：
  持仓日 D1～D3：优先开盘止损 −7% / 止盈 +7%
  尾盘指数清仓（默认低于 MA5；可选 MA10 或关闭）：上证收盘低于所选均线则清仓
       清仓价=当日个股收盘价
  其后：D1 收盘 < d0×(1+0.5%) → 卖
       D2/D3：收盘 ≤ 前一日个股收盘 → 卖
       D3 收盘：到期清仓

等权：每笔独立占用等额资金，合计收益=单笔收益率之和（%% 百分点）；夏普=笔收益率均值/标准差。
汇总扩展：最大回撤（按买入日链式净值）、盈亏比、笔收益波动率（标准差）。

用法：
  python qmt/scripts/dafengniu_benchmark_ref_trades.py
  python qmt/scripts/dafengniu_benchmark_ref_trades.py --no-sse-gate
  python qmt/scripts/dafengniu_benchmark_ref_trades.py --no-sse-ma10-exit
  python qmt/scripts/dafengniu_benchmark_ref_trades.py --sse-tail-exit ma5
  python qmt/scripts/dafengniu_benchmark_ref_trades.py --no-sse-gate --no-sse-ma10-exit
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

from dafengniu_metrics_core import _norm_date_series  # noqa: E402
from dafengniu_paths import (  # noqa: E402
	BENCHMARK_REF_SUMMARY_JSON,
	BENCHMARK_REF_SUMMARY_NO_GATE_JSON,
	BENCHMARK_REF_SUMMARY_NO_GATE_NO_SSE_MA10_EXIT_JSON,
	BENCHMARK_REF_SUMMARY_NO_SSE_MA10_EXIT_JSON,
	BENCHMARK_REF_SUMMARY_NO_GATE_SSE_EXIT_MA5_JSON,
	BENCHMARK_REF_SUMMARY_SSE_EXIT_MA10_JSON,
	BENCHMARK_REF_TRADES_CSV,
	BENCHMARK_REF_TRADES_NO_GATE_CSV,
	BENCHMARK_REF_TRADES_NO_GATE_NO_SSE_MA10_EXIT_CSV,
	BENCHMARK_REF_TRADES_NO_GATE_SSE_EXIT_MA5_CSV,
	BENCHMARK_REF_TRADES_NO_SSE_MA10_EXIT_CSV,
	BENCHMARK_REF_TRADES_SSE_EXIT_MA10_CSV,
	SYNC_OPEN_BAOSTOCK_CSV,
)
from export_sync_open_dates_baostock import (  # noqa: E402
	fetch_sse_index_daily,
)

_SSE_TS = "sh.000001"
SL = -0.07
TP = 0.07
D1_WEAK = 0.005
B_MULT = 0.97
C_MULT = 0.96
A_LO = -0.05
A_HI = 0.03
B_HI = 0.07


def compute_extended_metrics(rets_pct: np.ndarray, buy_days: list[str]) -> dict[str, float | None]:
	"""rets_pct: 单笔收益率（百分点）；buy_days 与 rets 同序，用于链式净值回撤。"""
	n = len(rets_pct)
	if n == 0:
		return {
			"波动率_笔收益标准差_pct": None,
			"最大回撤_链式净值_pct": None,
			"盈亏比_均盈除以均亏绝对值": None,
			"盈亏比_总盈利除以总亏损绝对值": None,
		}

	std_r = float(np.std(rets_pct, ddof=1)) if n > 1 else 0.0

	pos = rets_pct[rets_pct > 0.0]
	neg = rets_pct[rets_pct < 0.0]
	avg_win = float(np.mean(pos)) if len(pos) else None
	avg_loss_abs = float(np.mean(np.abs(neg))) if len(neg) else None
	ratio_avg = None
	if avg_win is not None and avg_loss_abs is not None and avg_loss_abs > 1e-12:
		ratio_avg = avg_win / avg_loss_abs

	sum_win = float(np.sum(pos)) if len(pos) else 0.0
	sum_loss_abs = float(np.sum(np.abs(neg))) if len(neg) else 0.0
	ratio_sum = None
	if sum_loss_abs > 1e-12:
		ratio_sum = sum_win / sum_loss_abs

	if len(buy_days) == n:
		order = np.argsort(buy_days)
		r_ord = rets_pct[order]
	else:
		r_ord = rets_pct
	nav = np.cumprod(1.0 + r_ord / 100.0)
	if len(nav):
		peak = np.maximum.accumulate(nav)
		dd = np.where(peak > 1e-15, (peak - nav) / peak, 0.0)
		max_dd_pct = float(np.max(dd) * 100.0)
	else:
		max_dd_pct = 0.0

	return {
		"波动率_笔收益标准差_pct": round(std_r, 4),
		"最大回撤_链式净值_pct": round(max_dd_pct, 4),
		"盈亏比_均盈除以均亏绝对值": round(ratio_avg, 4) if ratio_avg is not None else None,
		"盈亏比_总盈利除以总亏损绝对值": round(ratio_sum, 4) if ratio_sum is not None else None,
	}


def _f(row: pd.Series, col: str) -> float | None:
	if col not in row.index:
		return None
	v = row[col]
	try:
		x = float(v)
	except (TypeError, ValueError):
		return None
	if pd.isna(x):
		return None
	return x


def gap_bracket(gap: float) -> str | None:
	if gap <= A_LO:
		return "D"
	if gap < A_HI:
		return "A"
	if gap < B_HI:
		return "B"
	return "C"


def buy_price_and_ok(bracket: str, d0_open: float, d0_low: float) -> tuple[float | None, str | None]:
	if bracket in ("D", "A"):
		return d0_open, None
	if bracket == "B":
		if d0_low <= d0_open * B_MULT:
			return d0_open * B_MULT, None
		return None, "B档未触价"
	if bracket == "C":
		if d0_low <= d0_open * C_MULT:
			return d0_open * C_MULT, None
		return None, "C档未触价"
	return None, "未知档"


def gap_bracket_with(gap: float, a_lo: float, a_hi: float, b_hi: float) -> str | None:
	"""与 gap_bracket 相同逻辑，分档边界由参数给出（用于买入规则网格扫描）。"""
	if gap <= a_lo:
		return "D"
	if gap < a_hi:
		return "A"
	if gap < b_hi:
		return "B"
	return "C"


def buy_price_and_ok_with(
	bracket: str, d0_open: float, d0_low: float, b_mult: float, c_mult: float
) -> tuple[float | None, str | None]:
	"""与 buy_price_and_ok 相同逻辑，B/C 折扣由参数给出。"""
	if bracket in ("D", "A"):
		return d0_open, None
	if bracket == "B":
		if d0_low <= d0_open * b_mult:
			return d0_open * b_mult, None
		return None, "B档未触价"
	if bracket == "C":
		if d0_low <= d0_open * c_mult:
			return d0_open * c_mult, None
		return None, "C档未触价"
	return None, "未知档"


def _prep_sse_index(bdf: pd.DataFrame) -> pd.DataFrame:
	w = bdf.sort_values("date").reset_index(drop=True)
	for col in ("open", "high", "low", "close"):
		w[col] = pd.to_numeric(w[col], errors="coerce")
	w["date"] = _norm_date_series(w["date"])
	w["ma5"] = w["close"].rolling(5, min_periods=5).mean()
	w["ma10"] = w["close"].rolling(10, min_periods=10).mean()
	w["d"] = pd.to_datetime(w["date"]).dt.date
	return w.set_index("d")


def simulate_exit(
	d0_anchor: float,
	row: pd.Series,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	j_d0: int,
	*,
	sse_tail_exit: str = "ma5",
) -> tuple[float | None, str | None, str | None, str | None]:
	"""返回 (卖出价, 原因, D标签, 卖出日YYYYMMDD)。

	sse_tail_exit：none | ma5 | ma10 — 尾盘上证收盘低于对应均线则按个股收盘价清仓（默认 ma5 与仓库基准一致）。
	"""
	for k in (1, 2, 3):
		o = _f(row, "D%d_开盘" % k)
		c = _f(row, "D%d_收盘" % k)
		if o is None or c is None or o <= 0 or c <= 0:
			return None, "行情缺失", None, None
		td = sorted_dates[j_d0 + k]
		td_str = td.strftime("%Y%m%d")

		if o <= d0_anchor * (1.0 + SL):
			return float(o), "开盘止损", "D%d" % k, td_str
		if o >= d0_anchor * (1.0 + TP):
			return float(o), "开盘止盈", "D%d" % k, td_str

		if sse_tail_exit in ("ma5", "ma10"):
			try:
				sse_row = sse_idx.loc[td]
			except KeyError:
				return None, "指数日历缺失", None, None
			sse_c = float(sse_row["close"]) if pd.notna(sse_row["close"]) else float("nan")
			key_ma = "ma5" if sse_tail_exit == "ma5" else "ma10"
			sse_ma = float(sse_row[key_ma]) if pd.notna(sse_row[key_ma]) else float("nan")
			if np.isfinite(sse_c) and np.isfinite(sse_ma) and sse_c < sse_ma:
				lbl = "指数清仓(上证收<MA5)" if sse_tail_exit == "ma5" else "指数清仓(上证收<MA10)"
				return float(c), lbl, "D%d" % k, td_str

		if k == 1:
			if c < d0_anchor * (1.0 + D1_WEAK):
				return float(c), "D1不强", "D%d" % k, td_str
		else:
			prev_c = _f(row, "D%d_收盘" % (k - 1))
			if prev_c is not None and c <= prev_c:
				return float(c), "转弱(收≤前收)", "D%d" % k, td_str

		if k == 3:
			return float(c), "D3到期", "D%d" % k, td_str

	return None, "未平仓", None, None


def run_benchmark(
	inp: str,
	out_trades: str,
	out_summary: str,
	require_sse_ma5: bool,
	sse_tail_exit: str = "ma5",
) -> None:
	df = pd.read_csv(inp, encoding="utf-8-sig")
	if "代码" not in df.columns or "开仓日" not in df.columns:
		print("[错误] 需要列 代码、开仓日")
		sys.exit(1)

	try:
		import baostock as bs
	except ImportError:
		print("[错误] pip install baostock pandas")
		sys.exit(1)

	lg = bs.login()
	if lg.error_code != "0":
		print("[错误] baostock 登录: %s" % lg.error_msg)
		sys.exit(1)

	ods = []
	for _, r in df.iterrows():
		s = str(r["开仓日"]).strip().replace(".0", "")
		if len(s) >= 8 and s[:8].isdigit():
			ods.append(s[:8])
	if not ods:
		print("[错误] 无有效开仓日")
		bs.logout()
		sys.exit(1)

	min_od, max_od = min(ods), max(ods)
	idx_bdf = fetch_sse_index_daily(bs, min_od, max_od)
	bs.logout()

	if idx_bdf is None or idx_bdf.empty:
		print("[错误] 上证指数拉取失败")
		sys.exit(1)

	sse_idx = _prep_sse_index(idx_bdf)
	sorted_dates = sorted(sse_idx.index.tolist())

	stats_skip = {"gate_ma5": 0, "no_bracket": 0, "no_buy_trigger": 0, "bad_gap_data": 0, "no_calendar": 0, "sim_fail": 0}

	rows_out: list[dict] = []

	for _, row in df.iterrows():
		code = str(row["代码"]).strip()
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
		br = gap_bracket(gap)
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
		if j_d0 + 3 >= len(sorted_dates):
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
		bp, skip_buy = buy_price_and_ok(br, d0o, d0_low_eff)
		if bp is None:
			stats_skip["no_buy_trigger"] += 1
			continue

		sell_px, reason, d_tag, sell_day = simulate_exit(
			d0o, row, sse_idx, sorted_dates, j_d0, sse_tail_exit=sse_tail_exit
		)
		if sell_px is None:
			stats_skip["sim_fail"] += 1
			continue

		ret = (sell_px / bp - 1.0) * 100.0
		buy_day = d0.strftime("%Y%m%d")

		rows_out.append(
			{
				"代码": code,
				"开仓日_原始": open_date_str,
				"买入日": buy_day,
				"卖出日": sell_day or "",
				"档位": br,
				"gap_pct": round(gap * 100.0, 4),
				"买入价": round(bp, 4),
				"卖出价": round(sell_px, 4),
				"单笔收益率_pct": round(ret, 4),
				"卖出原因": reason or "",
				"卖出锚点日": d_tag or "",
			}
		)

	out_df = pd.DataFrame(rows_out)
	os.makedirs(os.path.dirname(out_trades), exist_ok=True)
	out_df.to_csv(out_trades, index=False, encoding="utf-8-sig")

	rets = out_df["单笔收益率_pct"].astype(float).values if len(out_df) else np.array([])
	buy_days = out_df["买入日"].astype(str).tolist() if len(out_df) and "买入日" in out_df.columns else []
	n = int(len(rets))
	sum_r = float(np.sum(rets)) if n else 0.0
	mean_r = float(np.mean(rets)) if n else 0.0
	std_r = float(np.std(rets, ddof=1)) if n > 1 else 0.0
	sharpe = (mean_r / std_r) if std_r > 1e-12 else (float("inf") if n >= 1 and abs(mean_r) > 1e-12 else 0.0)
	wins = int(np.sum(rets > 0)) if n else 0
	win_rate = (wins / n * 100.0) if n else 0.0
	ext = compute_extended_metrics(rets, buy_days)

	summary = {
		"输入CSV": os.path.abspath(inp),
		"输出明细": os.path.abspath(out_trades),
		"require_sse_above_ma5_for_new": require_sse_ma5,
		"sse_tail_exit": sse_tail_exit,
		"成交笔数": n,
		"收益合计_pct": round(sum_r, 4),
		"单笔均值_pct": round(mean_r, 4),
		"单笔标准差_pct": round(std_r, 4),
		"夏普_笔收益": round(sharpe, 4) if np.isfinite(sharpe) else None,
		"胜率_pct": round(win_rate, 4),
		"盈利笔数": wins,
		"波动率_笔收益标准差_pct": ext.get("波动率_笔收益标准差_pct"),
		"最大回撤_链式净值_pct": ext.get("最大回撤_链式净值_pct"),
		"盈亏比_均盈除以均亏绝对值": ext.get("盈亏比_均盈除以均亏绝对值"),
		"盈亏比_总盈利除以总亏损绝对值": ext.get("盈亏比_总盈利除以总亏损绝对值"),
		"跳过统计": stats_skip,
	}

	with open(out_summary, "w", encoding="utf-8") as f:
		json.dump(summary, f, ensure_ascii=False, indent=2)

	print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in", "-i", dest="inp", default=SYNC_OPEN_BAOSTOCK_CSV)
	ap.add_argument(
		"--out-trades",
		"-t",
		default=None,
		help="默认：基准(M5门控+M5尾盘)→dafengniu_benchmark_ref_trades.csv；详见 dafengniu_paths",
	)
	ap.add_argument(
		"--out-summary",
		"-s",
		default=None,
		help="默认与门控模式对应，见 dafengniu_paths 中 BENCHMARK_REF_SUMMARY*.json",
	)
	ap.add_argument("--no-sse-gate", action="store_true", help="关闭 T-1 上证≥MA5 门控")
	ap.add_argument(
		"--no-sse-ma10-exit",
		action="store_true",
		help="等价于 --sse-tail-exit none（与 --sse-tail-exit 同用时以此为准则关闭尾盘指数清仓）",
	)
	ap.add_argument(
		"--sse-tail-exit",
		choices=["ma10", "ma5", "none"],
		default="ma5",
		help="尾盘指数清仓线：上证收盘低于 MA5 / MA10，或 none 关闭；默认 ma5（仓库基准）",
	)
	args = ap.parse_args()

	inp = os.path.abspath(args.inp)
	if not os.path.isfile(inp):
		print("[错误] 找不到 %s" % inp)
		sys.exit(1)

	sse_tail = "none" if args.no_sse_ma10_exit else args.sse_tail_exit

	out_t = args.out_trades
	out_s = args.out_summary
	if out_t is None:
		if args.no_sse_gate:
			if sse_tail == "ma5":
				out_t = BENCHMARK_REF_TRADES_NO_GATE_SSE_EXIT_MA5_CSV
			elif sse_tail == "none":
				out_t = BENCHMARK_REF_TRADES_NO_GATE_NO_SSE_MA10_EXIT_CSV
			else:
				out_t = BENCHMARK_REF_TRADES_NO_GATE_CSV
		else:
			if sse_tail == "ma5":
				out_t = BENCHMARK_REF_TRADES_CSV
			elif sse_tail == "ma10":
				out_t = BENCHMARK_REF_TRADES_SSE_EXIT_MA10_CSV
			elif sse_tail == "none":
				out_t = BENCHMARK_REF_TRADES_NO_SSE_MA10_EXIT_CSV
			else:
				out_t = BENCHMARK_REF_TRADES_CSV
	if out_s is None:
		if args.no_sse_gate:
			if sse_tail == "ma5":
				out_s = BENCHMARK_REF_SUMMARY_NO_GATE_SSE_EXIT_MA5_JSON
			elif sse_tail == "none":
				out_s = BENCHMARK_REF_SUMMARY_NO_GATE_NO_SSE_MA10_EXIT_JSON
			else:
				out_s = BENCHMARK_REF_SUMMARY_NO_GATE_JSON
		else:
			if sse_tail == "ma5":
				out_s = BENCHMARK_REF_SUMMARY_JSON
			elif sse_tail == "ma10":
				out_s = BENCHMARK_REF_SUMMARY_SSE_EXIT_MA10_JSON
			elif sse_tail == "none":
				out_s = BENCHMARK_REF_SUMMARY_NO_SSE_MA10_EXIT_JSON
			else:
				out_s = BENCHMARK_REF_SUMMARY_JSON

	run_benchmark(
		inp,
		os.path.abspath(out_t),
		os.path.abspath(out_s),
		require_sse_ma5=not args.no_sse_gate,
		sse_tail_exit=sse_tail,
	)


if __name__ == "__main__":
	main()
