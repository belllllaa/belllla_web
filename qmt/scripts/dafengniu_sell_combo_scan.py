# -*- coding: utf-8 -*-
"""卖出规则组合扫描（第一轮）：固定基准买入，分轮次对照。

  单日模拟顺序（全体一致）：① 开盘 SL/TP → ② 盘中触价 → ③ 上证收盘破 MA5 尾盘 → ④ D1 弱 / 转弱 / 持有到期（Round D 可对 ② 单独指定盘中阈）。
  A（表）：仅统计「开盘止损/开盘止盈」平仓笔。
  B（表）：仅统计「盘中止损/盘中止盈」平仓笔（开盘未先触发）；原旧版 Round D。
  C（表）：**全路径**，不按平仓原因过滤；原旧版 Round B。
  D（表）：开盘与盘中 SL/TP 可不同；多行异质对照；原旧版 Round F 扩展。
  E（表）：**ROUND_C_SLTP ∪ ROUND_E_EXTRA_SLTP（含 −8% 多档 TP）**；**跳过盘中触价**，仅开盘→尾盘→弱/转弱/到期。

用法：
  python qmt/scripts/dafengniu_sell_combo_scan.py
  python qmt/scripts/dafengniu_sell_combo_scan.py --round A
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
	buy_price_and_ok,
	compute_extended_metrics,
	gap_bracket,
	_f,
	_prep_sse_index,
)
from dafengniu_paths import (  # noqa: E402
	SELL_COMBO_SCAN_META_JSON,
	SELL_COMBO_SCAN_ROUND_A_CSV,
	SELL_COMBO_SCAN_ROUND_B_CSV,
	SELL_COMBO_SCAN_ROUND_C_CSV,
	SELL_COMBO_SCAN_ROUND_D_CSV,
	SELL_COMBO_SCAN_ROUND_E_CSV,
	SYNC_OPEN_BAOSTOCK_CSV,
)
from export_sync_open_dates_baostock import fetch_sse_index_daily  # noqa: E402

# ---------- 基准卖出（与仓库默认一致）----------
BASE_SL = -0.07
BASE_TP = 0.07
BASE_D1_WEAK = 0.005
BASE_SSE_TAIL = "ma5"
BASE_MAX_DAY = 3

# ---------- Round A：止损 −10%～−5%、止盈 +5%～+10%，步长 0.5%（11×11=121 组）----------
ROUND_A_SL = [round(-0.10 + i * 0.005, 6) for i in range(11)]
ROUND_A_TP = [round(0.05 + i * 0.005, 6) for i in range(11)]
# 输出时剔除「最大回撤_链式净值_pct」大于该阈值的组合（基准行始终保留）
ROUND_A_MAX_MDD_PCT = 31.0
# 输出时剔除「收益合计_pct」低于该值的组合（基准行始终保留；与合计%同列）
ROUND_A_MIN_SUM_PCT = 332.0
# A 表紧跟基准后的固定对照行（与网格内 −10%/+10% 数值相同，不受合计/回撤筛选剔除）
ROUND_A_PIN_SL = -0.10
ROUND_A_PIN_TP = 0.10

# 与 Round B（盘中归因）前两档 TP 一致（−10%×6.5%/8%）：A 表固定行，亦用于 C 全路径网格
ROUND_ABC_EXTRA_SLTP = (
	(-0.10, 0.065),
	(-0.10, 0.08),
)

# A：基准行之后输出的固定对照（不经网格筛选剔除）；标签一律写「开盘」SL/TP（数值可与 B/C 档对照）
ROUND_A_PINNED_AFTER_BENCH = (
	(ROUND_A_PIN_SL, ROUND_A_PIN_TP, "A|开盘 SL=-10.0% TP=10.0%"),
) + tuple(
	(sl, tp, "A|开盘 SL=%.1f%% TP=%.1f%%" % (sl * 100, tp * 100))
	for sl, tp in ROUND_ABC_EXTRA_SLTP
)

# B：仅统计盘中触价平仓归因；开盘与盘中共用同一组 (sl,tp)
ROUND_B_INTRADAY_SLTP = ((BASE_SL, BASE_TP),) + ROUND_ABC_EXTRA_SLTP + ((-0.10, 0.10),)

# C：上证收盘低于 MA5；全路径；多档开盘/盘中同阈 SL/TP
ROUND_C_TAIL = ["ma5"]
ROUND_C_SLTP = (
	(BASE_SL, BASE_TP),
	(ROUND_A_PIN_SL, ROUND_A_PIN_TP),
) + ROUND_ABC_EXTRA_SLTP

# E：在 ROUND_C_SLTP 基础上追加（仅 Round E；无盘中·破 MA5）
ROUND_E_EXTRA_SLTP = (
	(-0.08, 0.08),
	(-0.08, 0.07),
	(-0.08, 0.065),
	(-0.08, 0.10),
	(-0.08, 0.09),
)
ROUND_E_SLTP = ROUND_C_SLTP + ROUND_E_EXTRA_SLTP

# C 表说明（原单独「按方案名列出的弱×持有」旧表与 ma5 全路径重复，已并入本 C）
ROUND_C_NOTE = (
	"全路径（不按平仓原因过滤）。单日顺序：①开盘 SL/TP →②盘中触价（与开盘同一组 sl/tp，Round D 除外）"
	"→③上证收盘低于 MA5 则尾盘清仓 →④持有期内 D1 弱（首日收盘相对开仓锚跌幅超过 d1_weak）/ 转弱（收≤前收）/ 最长持有日到期。"
	"固定参数：d1_weak=0.005（0.50%）、max_day=3、sse_tail_exit=ma5；扫描 ROUND_C_SLTP 多档对照。"
)

# D：异质开盘 / 盘中；开盘三档 × 盘中三档交叉；另追加开盘 −8%×多档 TP、盘中固定 −10%/6.5%（全表去重）；尾盘 MA5、D1 弱 0.5%、最长 D3
ROUND_D_OPEN_SLTP = (
	(-0.10, 0.08),
	(-0.10, 0.10),
	(-0.10, 0.065),
)
ROUND_D_INTRA_SLTP = (
	(-0.10, 0.10),
	(-0.10, 0.065),
	(-0.10, 0.08),
)
ROUND_D_CROSS_SCENARIOS = tuple(
	(o_sl, o_tp, i_sl, i_tp)
	for o_sl, o_tp in ROUND_D_OPEN_SLTP
	for i_sl, i_tp in ROUND_D_INTRA_SLTP
)
ROUND_D_FIXED_INTRA_FOR_MINUS8 = (-0.10, 0.065)
ROUND_D_EXTRA_OPEN_MINUS8_TP = (0.08, 0.07, 0.065, 0.10, 0.09)
ROUND_D_EXTRA_SCENARIOS = tuple(
	(-0.08, tp, ROUND_D_FIXED_INTRA_FOR_MINUS8[0], ROUND_D_FIXED_INTRA_FOR_MINUS8[1])
	for tp in ROUND_D_EXTRA_OPEN_MINUS8_TP
)


def _dedup_round_d_scenarios(*batches: tuple[tuple[float, float, float, float], ...]) -> tuple:
	seen: set[tuple[float, float, float, float]] = set()
	out: list[tuple[float, float, float, float]] = []
	for batch in batches:
		for t in batch:
			if t not in seen:
				seen.add(t)
				out.append(t)
	return tuple(out)


ROUND_D_SCENARIOS = _dedup_round_d_scenarios(ROUND_D_CROSS_SCENARIOS, ROUND_D_EXTRA_SCENARIOS)


def _round_d_label(open_sl: float, open_tp: float, intra_sl: float, intra_tp: float) -> str:
	return "D|开盘SL=%.1f%%·TP=%.1f%%·盘中SL=%.1f%%·TP=%.1f%%·破MA5·D1弱0.5%%·D3" % (
		open_sl * 100,
		open_tp * 100,
		intra_sl * 100,
		intra_tp * 100,
	)


# 仅将下列平仓原因计入对应轮次统计（完整模拟不变）
EXIT_REASONS_ROUND_A = frozenset({"开盘止损", "开盘止盈"})
EXIT_REASONS_INTRADAY_ONLY = frozenset({"盘中止损(最低触价)", "盘中止盈(最高触价)"})


def simulate_exit_params(
	d0_anchor: float,
	row: pd.Series,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	j_d0: int,
	*,
	sl: float,
	tp: float,
	d1_weak: float,
	sse_tail_exit: str,
	max_day: int,
	skip_intraday: bool = False,
	sl_intraday: float | None = None,
	tp_intraday: float | None = None,
) -> tuple[float | None, str | None, str | None, str | None]:
	for k in range(1, max_day + 1):
		o = _f(row, "D%d_开盘" % k)
		c = _f(row, "D%d_收盘" % k)
		if o is None or c is None or o <= 0 or c <= 0:
			return None, "行情缺失", None, None
		if j_d0 + k >= len(sorted_dates):
			return None, "行情缺失", None, None
		td = sorted_dates[j_d0 + k]
		td_str = td.strftime("%Y%m%d")

		if o <= d0_anchor * (1.0 + sl):
			return float(o), "开盘止损", "D%d" % k, td_str
		if o >= d0_anchor * (1.0 + tp):
			return float(o), "开盘止盈", "D%d" % k, td_str

		if not skip_intraday:
			sl_i = sl if sl_intraday is None else sl_intraday
			tp_i = tp if tp_intraday is None else tp_intraday
			sl_px = d0_anchor * (1.0 + sl_i)
			tp_px = d0_anchor * (1.0 + tp_i)
			lo = _f(row, "D%d_最低" % k)
			hi = _f(row, "D%d_最高" % k)
			# 开盘未触发后：盘中默认与开盘同档，可由 sl_intraday/tp_intraday 单独指定；同根 K 同时触达则止损优先（日线近似）
			if lo is not None and lo > 0 and lo <= sl_px:
				return float(sl_px), "盘中止损(最低触价)", "D%d" % k, td_str
			if hi is not None and hi > 0 and hi >= tp_px:
				return float(tp_px), "盘中止盈(最高触价)", "D%d" % k, td_str

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
			if c < d0_anchor * (1.0 + d1_weak):
				return float(c), "D1不强", "D%d" % k, td_str
		else:
			prev_c = _f(row, "D%d_收盘" % (k - 1))
			if prev_c is not None and c <= prev_c:
				return float(c), "转弱(收≤前收)", "D%d" % k, td_str

		if k == max_day:
			return float(c), "D%d到期" % max_day, "D%d" % k, td_str

	return None, "未平仓", None, None


def run_scenario(
	df: pd.DataFrame,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	*,
	sl: float,
	tp: float,
	d1_weak: float,
	sse_tail_exit: str,
	max_day: int,
	require_sse_ma5: bool,
	exit_reason_allow: frozenset[str] | None = None,
	skip_intraday: bool = False,
	sl_intraday: float | None = None,
	tp_intraday: float | None = None,
) -> dict:
	stats_skip = {
		"gate_ma5": 0,
		"no_bracket": 0,
		"no_buy_trigger": 0,
		"bad_gap_data": 0,
		"no_calendar": 0,
		"sim_fail": 0,
		"exit_reason_filtered": 0,
	}
	rets: list[float] = []
	buy_days: list[str] = []

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
		if j_d0 + max_day >= len(sorted_dates):
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
		bp, _skip = buy_price_and_ok(br, d0o, d0_low_eff)
		if bp is None:
			stats_skip["no_buy_trigger"] += 1
			continue

		sell_px, reason, _d_tag, _sell_day = simulate_exit_params(
			d0o,
			row,
			sse_idx,
			sorted_dates,
			j_d0,
			sl=sl,
			tp=tp,
			d1_weak=d1_weak,
			sse_tail_exit=sse_tail_exit,
			max_day=max_day,
			skip_intraday=skip_intraday,
			sl_intraday=sl_intraday,
			tp_intraday=tp_intraday,
		)
		if sell_px is None:
			stats_skip["sim_fail"] += 1
			continue
		if exit_reason_allow is not None:
			if reason not in exit_reason_allow:
				stats_skip["exit_reason_filtered"] += 1
				continue

		ret = (sell_px / bp - 1.0) * 100.0
		rets.append(ret)
		buy_days.append(d0.strftime("%Y%m%d"))

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
		"单笔均值_pct": round(mean_r, 4),
		"夏普_笔收益": round(sharpe, 4) if np.isfinite(sharpe) else None,
		"胜率_pct": round(win_rate, 4),
		"波动率_笔收益标准差_pct": ext.get("波动率_笔收益标准差_pct"),
		"最大回撤_链式净值_pct": ext.get("最大回撤_链式净值_pct"),
		"盈亏比_均盈除以均亏绝对值": ext.get("盈亏比_均盈除以均亏绝对值"),
		"盈亏比_总盈利除以总亏损绝对值": ext.get("盈亏比_总盈利除以总亏损绝对值"),
		"跳过统计": stats_skip,
	}


def _exit_bucket(reason: str | None) -> str:
	"""平仓归因：A 开盘 SL/TP；D 盘中触价；B 上证尾盘；其余归 C（D1 弱 / 转弱 / 到期等）。"""
	if reason in ("开盘止损", "开盘止盈"):
		return "A"
	if reason in ("盘中止损(最低触价)", "盘中止盈(最高触价)"):
		return "D"
	if reason and "指数清仓" in reason:
		return "B"
	return "C"


def run_scenario_attribution(
	df: pd.DataFrame,
	sse_idx: pd.DataFrame,
	sorted_dates: list,
	*,
	sl: float,
	tp: float,
	d1_weak: float,
	sse_tail_exit: str,
	max_day: int,
	require_sse_ma5: bool,
	skip_intraday: bool = False,
	sl_intraday: float | None = None,
	tp_intraday: float | None = None,
) -> dict:
	"""与 run_scenario 相同全路径模拟，不按平仓原因过滤；额外返回 A/B/C/D 笔数与占比。"""
	stats_skip = {
		"gate_ma5": 0,
		"no_bracket": 0,
		"no_buy_trigger": 0,
		"bad_gap_data": 0,
		"no_calendar": 0,
		"sim_fail": 0,
	}
	counts = {"A": 0, "D": 0, "B": 0, "C": 0}
	rets: list[float] = []
	buy_days: list[str] = []

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
		if j_d0 + max_day >= len(sorted_dates):
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
		bp, _skip = buy_price_and_ok(br, d0o, d0_low_eff)
		if bp is None:
			stats_skip["no_buy_trigger"] += 1
			continue

		sell_px, reason, _d_tag, _sell_day = simulate_exit_params(
			d0o,
			row,
			sse_idx,
			sorted_dates,
			j_d0,
			sl=sl,
			tp=tp,
			d1_weak=d1_weak,
			sse_tail_exit=sse_tail_exit,
			max_day=max_day,
			skip_intraday=skip_intraday,
			sl_intraday=sl_intraday,
			tp_intraday=tp_intraday,
		)
		if sell_px is None:
			stats_skip["sim_fail"] += 1
			continue

		counts[_exit_bucket(reason)] += 1
		ret = (sell_px / bp - 1.0) * 100.0
		rets.append(ret)
		buy_days.append(d0.strftime("%Y%m%d"))

	arr = np.array(rets, dtype=float)
	n = len(arr)
	sum_r = float(np.sum(arr)) if n else 0.0
	mean_r = float(np.mean(arr)) if n else 0.0
	std_r = float(np.std(arr, ddof=1)) if n > 1 else 0.0
	sharpe = (mean_r / std_r) if std_r > 1e-12 else (float("inf") if n >= 1 and abs(mean_r) > 1e-12 else 0.0)
	wins = int(np.sum(arr > 0)) if n else 0
	win_rate = (wins / n * 100.0) if n else 0.0
	ext = compute_extended_metrics(arr, buy_days)

	out: dict = {
		"成交笔数": n,
		"收益合计_pct": round(sum_r, 4),
		"单笔均值_pct": round(mean_r, 4),
		"夏普_笔收益": round(sharpe, 4) if np.isfinite(sharpe) else None,
		"胜率_pct": round(win_rate, 4),
		"波动率_笔收益标准差_pct": ext.get("波动率_笔收益标准差_pct"),
		"最大回撤_链式净值_pct": ext.get("最大回撤_链式净值_pct"),
		"盈亏比_均盈除以均亏绝对值": ext.get("盈亏比_均盈除以均亏绝对值"),
		"盈亏比_总盈利除以总亏损绝对值": ext.get("盈亏比_总盈利除以总亏损绝对值"),
		"笔数_A": counts["A"],
		"笔数_D": counts["D"],
		"笔数_B": counts["B"],
		"笔数_C": counts["C"],
		"跳过统计": stats_skip,
	}
	if n > 0:
		out["占比_A_pct"] = round(100.0 * counts["A"] / n, 4)
		out["占比_D_pct"] = round(100.0 * counts["D"] / n, 4)
		out["占比_B_pct"] = round(100.0 * counts["B"] / n, 4)
		out["占比_C_pct"] = round(100.0 * counts["C"] / n, 4)
	else:
		out["占比_A_pct"] = 0.0
		out["占比_D_pct"] = 0.0
		out["占比_B_pct"] = 0.0
		out["占比_C_pct"] = 0.0
	return out


def load_data(inp: str):
	try:
		import baostock as bs
	except ImportError:
		print("[错误] pip install baostock pandas")
		sys.exit(1)

	df = pd.read_csv(inp, encoding="utf-8-sig")
	if "代码" not in df.columns or "开仓日" not in df.columns:
		print("[错误] 需要列 代码、开仓日")
		sys.exit(1)

	ods = []
	for _, r in df.iterrows():
		s = str(r["开仓日"]).strip().replace(".0", "")
		if len(s) >= 8 and s[:8].isdigit():
			ods.append(s[:8])
	if not ods:
		print("[错误] 无有效开仓日")
		sys.exit(1)

	lg = bs.login()
	if lg.error_code != "0":
		print("[错误] baostock 登录: %s" % lg.error_msg)
		sys.exit(1)

	min_od, max_od = min(ods), max(ods)
	idx_bdf = fetch_sse_index_daily(bs, min_od, max_od)
	bs.logout()

	if idx_bdf is None or idx_bdf.empty:
		print("[错误] 上证指数拉取失败")
		sys.exit(1)

	sse_idx = _prep_sse_index(idx_bdf)
	sorted_dates = sorted(sse_idx.index.tolist())
	return df, sse_idx, sorted_dates


def scan_round_a(df, sse_idx, sorted_dates, require_ma5: bool) -> pd.DataFrame:
	rows: list[dict] = []
	for sl in ROUND_A_SL:
		for tp in ROUND_A_TP:
			label = "A|SL=%.1f%% TP=%.1f%%" % (sl * 100, tp * 100)
			m = run_scenario(
				df,
				sse_idx,
				sorted_dates,
				sl=sl,
				tp=tp,
				d1_weak=BASE_D1_WEAK,
				sse_tail_exit=BASE_SSE_TAIL,
				max_day=BASE_MAX_DAY,
				require_sse_ma5=require_ma5,
				exit_reason_allow=EXIT_REASONS_ROUND_A,
			)
			rows.append(
				{
					"轮次": "A",
					"方案标签": label,
					"止损_sl": sl,
					"止盈_tp": tp,
					**{k: v for k, v in m.items() if k != "跳过统计"},
				}
			)
	raw = pd.DataFrame(rows)
	if not len(raw):
		return raw
	bench_m = (raw["止损_sl"].sub(BASE_SL).abs() < 1e-9) & (raw["止盈_tp"].sub(BASE_TP).abs() < 1e-9)
	bench_df = raw.loc[bench_m].iloc[0:1].copy() if bench_m.any() else pd.DataFrame()
	if len(bench_df):
		bench_df.loc[:, "方案标签"] = "基准"
	pin_parts: list[pd.DataFrame] = []
	for sl, tp, lbl in ROUND_A_PINNED_AFTER_BENCH:
		pm = (raw["止损_sl"].sub(sl).abs() < 1e-9) & (raw["止盈_tp"].sub(tp).abs() < 1e-9)
		pdf = raw.loc[pm].iloc[0:1].copy() if pm.any() else pd.DataFrame()
		if len(pdf):
			pdf.loc[:, "方案标签"] = lbl
			pin_parts.append(pdf)
	grid = raw[raw["最大回撤_链式净值_pct"] <= ROUND_A_MAX_MDD_PCT].copy()
	grid = grid[grid["收益合计_pct"] >= ROUND_A_MIN_SUM_PCT]
	excl_g = (grid["止损_sl"].sub(BASE_SL).abs() < 1e-9) & (grid["止盈_tp"].sub(BASE_TP).abs() < 1e-9)
	for sl, tp, _ in ROUND_A_PINNED_AFTER_BENCH:
		excl_g = excl_g | (
			(grid["止损_sl"].sub(sl).abs() < 1e-9) & (grid["止盈_tp"].sub(tp).abs() < 1e-9)
		)
	grid = grid[~excl_g]
	if len(grid):
		grid = grid.sort_values(
			by=[
				"收益合计_pct",
				"胜率_pct",
				"最大回撤_链式净值_pct",
				"盈亏比_均盈除以均亏绝对值",
			],
			ascending=[False, False, True, False],
			na_position="last",
		)
	parts: list[pd.DataFrame] = []
	if len(bench_df):
		parts.append(bench_df)
	for pdf in pin_parts:
		parts.append(pdf)
	if len(grid):
		parts.append(grid)
	if parts:
		return pd.concat(parts, ignore_index=True)
	return raw.iloc[0:0]


def scan_round_b(df, sse_idx, sorted_dates, require_ma5: bool) -> pd.DataFrame:
	"""仅统计盘中触价平仓（开盘未先触发）；开盘与盘中共用同一 sl/tp。"""
	rows: list[dict] = []
	for sl, tp in ROUND_B_INTRADAY_SLTP:
		if abs(sl - BASE_SL) < 1e-9 and abs(tp - BASE_TP) < 1e-9:
			label = "B|基准 SL=%.1f%% TP=%.1f%%（开盘/盘中同档）" % (sl * 100, tp * 100)
		else:
			label = "B|盘中 SL=%.1f%% TP=%.1f%%" % (sl * 100, tp * 100)
		m = run_scenario(
			df,
			sse_idx,
			sorted_dates,
			sl=sl,
			tp=tp,
			d1_weak=BASE_D1_WEAK,
			sse_tail_exit=BASE_SSE_TAIL,
			max_day=BASE_MAX_DAY,
			require_sse_ma5=require_ma5,
			exit_reason_allow=EXIT_REASONS_INTRADAY_ONLY,
		)
		rows.append(
			{
				"轮次": "B",
				"方案标签": label,
				"止损_sl": sl,
				"止盈_tp": tp,
				**{k: v for k, v in m.items() if k != "跳过统计"},
			}
		)
	out = pd.DataFrame(rows)
	if len(out):
		out = out.sort_values(
			by=[
				"收益合计_pct",
				"胜率_pct",
				"最大回撤_链式净值_pct",
				"盈亏比_均盈除以均亏绝对值",
			],
			ascending=[False, False, True, False],
			na_position="last",
		)
	return out


def scan_round_c(df, sse_idx, sorted_dates, require_ma5: bool) -> pd.DataFrame:
	"""全路径；上证尾盘 MA5；多档 SL/TP；附四类归因成交笔数（与 run_scenario_attribution 一致）。"""
	rows: list[dict] = []
	for tail in ROUND_C_TAIL:
		for sl, tp in ROUND_C_SLTP:
			tail_lbl = "破MA5" if tail == "ma5" else tail
			if (sl, tp) in ROUND_ABC_EXTRA_SLTP:
				label = "C|%s·盘中 SL=%.1f%%·TP=%.1f%%" % (tail_lbl, sl * 100, tp * 100)
			else:
				label = "C|%s·SL=%.1f%%·TP=%.1f%%" % (tail_lbl, sl * 100, tp * 100)
			m = run_scenario_attribution(
				df,
				sse_idx,
				sorted_dates,
				sl=sl,
				tp=tp,
				d1_weak=BASE_D1_WEAK,
				sse_tail_exit=tail,
				max_day=BASE_MAX_DAY,
				require_sse_ma5=require_ma5,
			)
			_attr_drop = frozenset(
				{
					"跳过统计",
					"笔数_A",
					"笔数_B",
					"笔数_C",
					"笔数_D",
					"占比_A_pct",
					"占比_D_pct",
					"占比_B_pct",
					"占比_C_pct",
				}
			)
			base = {k: v for k, v in m.items() if k not in _attr_drop}
			rows.append(
				{
					"轮次": "C",
					"方案标签": label,
					"止损_sl": sl,
					"止盈_tp": tp,
					"sse_tail_exit": tail,
					"开盘平仓笔数": m["笔数_A"],
					"盘中平仓笔数": m["笔数_D"],
					"上证破MA5笔数": m["笔数_B"],
					"D1弱转弱到期笔数": m["笔数_C"],
					**base,
				}
			)
	out = pd.DataFrame(rows)
	return out


def scan_round_e(df, sse_idx, sorted_dates, require_ma5: bool) -> pd.DataFrame:
	"""与 C 同 SL/TP，但不执行盘中触价；附开盘/破位(上证<MA5)/D1弱·转弱·到期 笔数。"""
	rows: list[dict] = []
	_attr_drop = frozenset(
		{
			"跳过统计",
			"笔数_A",
			"笔数_B",
			"笔数_C",
			"笔数_D",
			"占比_A_pct",
			"占比_D_pct",
			"占比_B_pct",
			"占比_C_pct",
		}
	)
	for tail in ROUND_C_TAIL:
		for sl, tp in ROUND_E_SLTP:
			tail_lbl = "破MA5" if tail == "ma5" else tail
			label = "E|无盘中·%s·SL=%.1f%%·TP=%.1f%%" % (tail_lbl, sl * 100, tp * 100)
			m = run_scenario_attribution(
				df,
				sse_idx,
				sorted_dates,
				sl=sl,
				tp=tp,
				d1_weak=BASE_D1_WEAK,
				sse_tail_exit=tail,
				max_day=BASE_MAX_DAY,
				require_sse_ma5=require_ma5,
				skip_intraday=True,
			)
			base = {k: v for k, v in m.items() if k not in _attr_drop}
			rows.append(
				{
					"轮次": "E",
					"方案标签": label,
					"止损_sl": sl,
					"止盈_tp": tp,
					"sse_tail_exit": tail,
					"开盘成交数": m["笔数_A"],
					"破位成交数": m["笔数_B"],
					"D1弱转弱到期笔数": m["笔数_C"],
					**base,
				}
			)
	out = pd.DataFrame(rows)
	return out


def scan_round_d(df, sse_idx, sorted_dates, require_ma5: bool) -> pd.DataFrame:
	"""开盘与盘中 SL/TP 可不同；ROUND_D_SCENARIOS 多行；全路径。"""
	rows: list[dict] = []
	for o_sl, o_tp, i_sl, i_tp in ROUND_D_SCENARIOS:
		label = _round_d_label(o_sl, o_tp, i_sl, i_tp)
		m = run_scenario(
			df,
			sse_idx,
			sorted_dates,
			sl=o_sl,
			tp=o_tp,
			d1_weak=BASE_D1_WEAK,
			sse_tail_exit=BASE_SSE_TAIL,
			max_day=BASE_MAX_DAY,
			require_sse_ma5=require_ma5,
			sl_intraday=i_sl,
			tp_intraday=i_tp,
		)
		rows.append(
			{
				"轮次": "D",
				"方案标签": label,
				"止损_sl": o_sl,
				"止盈_tp": o_tp,
				"止损_sl_盘中": i_sl,
				"止盈_tp_盘中": i_tp,
				"sse_tail_exit": BASE_SSE_TAIL,
				"D1_weak": BASE_D1_WEAK,
				"max_day": BASE_MAX_DAY,
				**{k: v for k, v in m.items() if k != "跳过统计"},
			}
		)
	return pd.DataFrame(rows)


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in", "-i", dest="inp", default=SYNC_OPEN_BAOSTOCK_CSV)
	ap.add_argument("--no-sse-gate", action="store_true", help="关闭 MA5 门控（默认与基准一致：开门控）")
	ap.add_argument(
		"--round",
		choices=["A", "B", "C", "D", "E", "all"],
		default="all",
		help="只跑单轮或全部",
	)
	args = ap.parse_args()

	inp = os.path.abspath(args.inp)
	if not os.path.isfile(inp):
		print("[错误] 找不到 %s" % inp)
		sys.exit(1)

	require_ma5 = not args.no_sse_gate
	df, sse_idx, sorted_dates = load_data(inp)

	meta = {
		"输入": inp,
		"require_sse_above_ma5": require_ma5,
		"基准卖出": {
			"sl": BASE_SL,
			"tp": BASE_TP,
			"d1_weak": BASE_D1_WEAK,
			"sse_tail_exit": BASE_SSE_TAIL,
			"max_day": BASE_MAX_DAY,
		},
		"round_A": {
			"sl_list": ROUND_A_SL,
			"tp_list": ROUND_A_TP,
			"exclude_if_max_dd_pct_gt": ROUND_A_MAX_MDD_PCT,
			"exclude_if_sum_pct_lt": ROUND_A_MIN_SUM_PCT,
			"sort": ["收益合计_pct↓", "胜率_pct↓", "最大回撤_链式净值_pct↑", "盈亏比_均盈除以均亏绝对值↓"],
			"exit_reasons_counted": sorted(EXIT_REASONS_ROUND_A),
			"pinned_rows_after_bench": [
				{"sl": sl, "tp": tp, "label": lbl} for sl, tp, lbl in ROUND_A_PINNED_AFTER_BENCH
			],
		},
		"round_B": {
			"sl_tp_pairs": [list(x) for x in ROUND_B_INTRADAY_SLTP],
			"tie_break_same_bar": "止损优先(日线)",
			"exit_reasons_counted": sorted(EXIT_REASONS_INTRADAY_ONLY),
			"note": "同一模拟顺序；仅统计盘中触价平仓的笔（开盘未先触发）；开盘与盘中共用同一 sl/tp；含基准 −7/+7 与 −10%×TP 三档",
		},
		"round_C": {
			"sse_tail_exit": ROUND_C_TAIL,
			"d1_weak": BASE_D1_WEAK,
			"max_day": BASE_MAX_DAY,
			"sl_tp": [list(x) for x in ROUND_C_SLTP],
			"note": ROUND_C_NOTE,
			"removed_historical_redundant": "旧版按「弱×持有」单独成表的行与 ma5 全路径重复，已并入本 C 表",
		},
		"round_D": {
			"开盘_sl_tp": [list(x) for x in ROUND_D_OPEN_SLTP],
			"盘中_sl_tp": [list(x) for x in ROUND_D_INTRA_SLTP],
			"cross_3x3_count": len(ROUND_D_CROSS_SCENARIOS),
			"extra_open_minus8_tp": list(ROUND_D_EXTRA_OPEN_MINUS8_TP),
			"extra_fixed_intra": list(ROUND_D_FIXED_INTRA_FOR_MINUS8),
			"scenarios": [
				{"开盘": {"sl": o_sl, "tp": o_tp}, "盘中": {"sl": i_sl, "tp": i_tp}}
				for o_sl, o_tp, i_sl, i_tp in ROUND_D_SCENARIOS
			],
			"sse_tail_exit": BASE_SSE_TAIL,
			"d1_weak": BASE_D1_WEAK,
			"max_day": BASE_MAX_DAY,
			"note": "开盘与盘中触价可用不同 SL/TP；3×3 交叉后追加开盘 −8%×(8%/7%/6.5%/10%/9%)、盘中固定 −10%/6.5%，与已有场景按四元组去重；其余同基准；全路径",
		},
		"round_E": {
			"sse_tail_exit": ROUND_C_TAIL,
			"sl_tp": [list(x) for x in ROUND_C_SLTP],
			"sl_tp_extra_e_only": [list(x) for x in ROUND_E_EXTRA_SLTP],
			"sl_tp_e_all": [list(x) for x in ROUND_E_SLTP],
			"d1_weak": BASE_D1_WEAK,
			"max_day": BASE_MAX_DAY,
			"skip_intraday": True,
			"note": "ROUND_C_SLTP 与 E 专用 ROUND_E_EXTRA_SLTP（−8%×多档 TP）并集；不执行盘中触价。输出列：开盘成交数、破位成交数(上证收<MA5 尾盘)、D1弱转弱到期笔数；与 N 加总一致。",
		},
	}

	os.makedirs(os.path.dirname(SELL_COMBO_SCAN_ROUND_A_CSV), exist_ok=True)

	if args.round in ("A", "all"):
		dfa = scan_round_a(df, sse_idx, sorted_dates, require_ma5)
		dfa.to_csv(SELL_COMBO_SCAN_ROUND_A_CSV, index=False, encoding="utf-8-sig")
		print("[完成] A -> %s 行 %d" % (SELL_COMBO_SCAN_ROUND_A_CSV, len(dfa)))
	if args.round in ("B", "all"):
		dfb = scan_round_b(df, sse_idx, sorted_dates, require_ma5)
		dfb.to_csv(SELL_COMBO_SCAN_ROUND_B_CSV, index=False, encoding="utf-8-sig")
		print("[完成] B -> %s 行 %d" % (SELL_COMBO_SCAN_ROUND_B_CSV, len(dfb)))
	if args.round in ("C", "all"):
		dfc = scan_round_c(df, sse_idx, sorted_dates, require_ma5)
		dfc.to_csv(SELL_COMBO_SCAN_ROUND_C_CSV, index=False, encoding="utf-8-sig")
		print("[完成] C -> %s 行 %d" % (SELL_COMBO_SCAN_ROUND_C_CSV, len(dfc)))
	if args.round in ("D", "all"):
		dfd = scan_round_d(df, sse_idx, sorted_dates, require_ma5)
		dfd.to_csv(SELL_COMBO_SCAN_ROUND_D_CSV, index=False, encoding="utf-8-sig")
		print("[完成] D -> %s 行 %d" % (SELL_COMBO_SCAN_ROUND_D_CSV, len(dfd)))
	if args.round in ("E", "all"):
		dfe = scan_round_e(df, sse_idx, sorted_dates, require_ma5)
		dfe.to_csv(SELL_COMBO_SCAN_ROUND_E_CSV, index=False, encoding="utf-8-sig")
		print("[完成] E -> %s 行 %d" % (SELL_COMBO_SCAN_ROUND_E_CSV, len(dfe)))

	with open(SELL_COMBO_SCAN_META_JSON, "w", encoding="utf-8") as f:
		json.dump(meta, f, ensure_ascii=False, indent=2)
	print("[完成] meta -> %s" % SELL_COMBO_SCAN_META_JSON)


if __name__ == "__main__":
	main()
