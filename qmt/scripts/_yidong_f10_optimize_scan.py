# -*- coding: utf-8 -*-
"""F10 专项优化扫描：以 T+1开→T+2收 为基准，多维度组合测试。"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	_day_close_pct_vs_prev,
	_day_open_pct_vs_prev,
	build_code_trade_dates,
	build_f_block_keys,
	build_g_zero,
	is_limit_skip_row,
	load_yidong,
	_simulate_fixed_sell,
)
from _yidong_tp_scan import _simulate_fixed_sell_tp  # noqa: E402

CSV = Path(YIDONG_REGULATION_STOCKS_CSV)
BASE_BUY = (1, "open")
BASE_SELL_OFF = 2
MIN_N = 15
TP_PCT = 16.0


@dataclass(frozen=True)
class Spec:
	label: str
	buy_off: int
	buy_kind: str
	sell_off: int
	tp_pct: float | None = None
	filter_fn: Optional[Callable[[pd.Series], bool]] = None


def collect_f10(df: pd.DataFrame) -> pd.DataFrame:
	blocked = build_f_block_keys(df)
	mask = (
		df["F"].eq(10)
		& df["G"].eq(1)
		& df["T日_收盘"].astype(str).str.strip().ne("")
		& ~df.apply(lambda r: (str(r["T日"]), str(r["股票代码"])) in blocked, axis=1)
		& ~df.apply(is_limit_skip_row, axis=1)
	)
	return df.loc[mask].copy().reset_index(drop=True)


def t_close_pct(row: pd.Series) -> float | None:
	return _day_close_pct_vs_prev(row, 0)


def t_open_pct(row: pd.Series) -> float | None:
	return _day_open_pct_vs_prev(row, 0)


def t1_open_pct(row: pd.Series) -> float | None:
	return _day_open_pct_vs_prev(row, 1)


def run_spec(
	sub: pd.DataFrame,
	g0: set,
	cd: dict,
	spec: Spec,
) -> list[dict]:
	rows: list[dict] = []
	for _, row in sub.iterrows():
		if spec.filter_fn is not None and not spec.filter_fn(row):
			continue
		if spec.tp_pct is not None:
			t = _simulate_fixed_sell_tp(
				row, g0, cd,
				buy_off=spec.buy_off,
				buy_kind=spec.buy_kind,
				sell_off=spec.sell_off,
				rule_id="f10",
				tp_pct=spec.tp_pct,
			)
		else:
			t = _simulate_fixed_sell(
				row, g0, cd,
				buy_off=spec.buy_off,
				buy_kind=spec.buy_kind,
				sell_off=spec.sell_off,
				rule_id="f10",
			)
		if t:
			rows.append(t)
	return rows


def summarize(rows: list[dict]) -> dict | None:
	if len(rows) < MIN_N:
		return None
	r = pd.Series([x["收益率%"] for x in rows], dtype=float)
	return {
		"n": len(r),
		"win": round(100 * (r > 0).mean(), 1),
		"mean": round(r.mean(), 2),
		"med": round(r.median(), 2),
		"sum_pct": round(r.sum(), 1),
		"pnl": round(sum(x.get("收益金额", 0) for x in rows), 0),
	}


def branch_run(
	sub: pd.DataFrame,
	g0: set,
	cd: dict,
	label: str,
	pick_fn: Callable[[pd.Series], Spec | None],
) -> dict | None:
	rows: list[dict] = []
	for _, row in sub.iterrows():
		spec = pick_fn(row)
		if spec is None:
			continue
		if spec.tp_pct is not None:
			t = _simulate_fixed_sell_tp(
				row, g0, cd,
				buy_off=spec.buy_off,
				buy_kind=spec.buy_kind,
				sell_off=spec.sell_off,
				rule_id="f10",
				tp_pct=spec.tp_pct,
			)
		else:
			t = _simulate_fixed_sell(
				row, g0, cd,
				buy_off=spec.buy_off,
				buy_kind=spec.buy_kind,
				sell_off=spec.sell_off,
				rule_id="f10",
			)
		if t:
			rows.append(t)
	s = summarize(rows)
	if s:
		s["label"] = label
	return s


def print_table(title: str, items: list[dict], top: int = 15) -> None:
	print("\n" + "=" * 96)
	print(title)
	print("%-48s %5s %6s %7s %7s %10s" % ("方案", "笔数", "胜率", "均收益", "合计%", "金额"))
	for s in items[:top]:
		print(
			"%-48s %5d %5.1f%% %6.2f%% %7.1f%% %10.0f"
			% (s["label"], s["n"], s["win"], s["mean"], s["sum_pct"], s["pnl"])
		)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sub = collect_f10(df)
	print("数据源:", CSV)
	print("F10 可买信号(正式过滤):", len(sub))

	# ── 1. 基准 ──
	base_rows = run_spec(
		sub, g0, cd,
		Spec("基准 T+1开→T+2收 持1天", *BASE_BUY, BASE_SELL_OFF),
	)
	base = summarize(base_rows)
	if base:
		base["label"] = "★基准 T+1开→T+2收"
		print("\n基准:", base)

	# ── 2. 买入×持有网格 ──
	buys = [
		("T开盘", 0, "open"),
		("T收盘", 0, "close"),
		("T+1开盘", 1, "open"),
		("T+1收盘", 1, "close"),
		("T+2开盘", 2, "open"),
	]
	grid: list[dict] = []
	for bl, boff, kind in buys:
		for hold in range(1, 7):
			soff = boff + hold
			label = "%s 持%d天→T+%d收" % (bl, hold, soff)
			s = summarize(run_spec(sub, g0, cd, Spec(label, boff, kind, soff)))
			if s:
				s["label"] = label
				grid.append(s)
	grid.sort(key=lambda x: x["mean"], reverse=True)
	print_table("【1】买入时点 × 持有天数（无止盈）Top15 按均收益", grid)

	grid_pnl = sorted(grid, key=lambda x: x["pnl"], reverse=True)
	print_table("【1b】同上 Top15 按合计金额", grid_pnl)

	# ── 3. T日涨跌幅分段（基准买卖不变）──
	t_splits: list[dict] = []
	for name, fn in [
		("T收涨>0", lambda r: (t_close_pct(r) or 0) > 0),
		("T收涨≤0", lambda r: (t_close_pct(r) or 0) <= 0),
		("T收涨≥3%", lambda r: (t_close_pct(r) or -999) >= 3),
		("T收涨≥5%", lambda r: (t_close_pct(r) or -999) >= 5),
		("T收涨≥8%", lambda r: (t_close_pct(r) or -999) >= 8),
		("T收跌<0", lambda r: (t_close_pct(r) or 0) < 0),
		("T收跌≤-3%", lambda r: (t_close_pct(r) or 999) <= -3),
		("T收跌≤-5%", lambda r: (t_close_pct(r) or 999) <= -5),
		("T收涨0~5%", lambda r: 0 <= (t_close_pct(r) or -999) <= 5),
		("T收涨0~8%", lambda r: 0 <= (t_close_pct(r) or -999) <= 8),
	]:
		label = "基准+仅%s" % name
		s = summarize(
			run_spec(
				sub, g0, cd,
				Spec(label, *BASE_BUY, BASE_SELL_OFF, filter_fn=fn),
			)
		)
		if s:
			s["label"] = label
			t_splits.append(s)
	t_splits.sort(key=lambda x: x["mean"], reverse=True)
	print_table("【2】T日收盘涨跌幅过滤 + 基准买卖", t_splits)

	# ── 4. T日涨跌幅分段 + 各自最优持有（子网格）──
	branch_specs_up = [
		("T+1开持1", 1, "open", 2),
		("T+1开持2", 1, "open", 3),
		("T收盘持1", 0, "close", 1),
		("T收盘持2", 0, "close", 2),
		("T开盘持1", 0, "open", 1),
	]
	branch_specs_dn = branch_specs_up + [
		("T+1开持3", 1, "open", 4),
		("T+2开持1", 2, "open", 3),
	]
	cond_rows: list[dict] = []
	for up_name, up_fn in [("T收涨>0", lambda r: (t_close_pct(r) or 0) > 0), ("T收涨≥3%", lambda r: (t_close_pct(r) or -999) >= 3)]:
		for dn_name, dn_fn in [("T收跌<0", lambda r: (t_close_pct(r) or 0) < 0), ("T收跌≤-3%", lambda r: (t_close_pct(r) or 999) <= -3)]:
			for ul, u_boff, u_kind, u_soff in branch_specs_up:
				for dl, d_boff, d_kind, d_soff in branch_specs_dn:
					label = "涨%s→%s | 跌%s→%s" % (up_name, ul, dn_name, dl)

					def pick(row: pd.Series) -> Spec | None:
						p = t_close_pct(row)
						if p is None:
							return None
						if up_fn(row):
							return Spec("", u_boff, u_kind, u_soff)
						if dn_fn(row):
							return Spec("", d_boff, d_kind, d_soff)
						return None

					s = branch_run(sub, g0, cd, label, pick)
					if s:
						cond_rows.append(s)
	cond_rows.sort(key=lambda x: x["mean"], reverse=True)
	print_table("【3】T收涨/收跌分支不同买卖（无止盈）Top15", cond_rows)

	# ── 5. T+1 开盘涨跌幅过滤（仍 T+1开买）──
	t1_filters: list[dict] = []
	for name, fn in [
		("T+1开盘涨>0", lambda r: (t1_open_pct(r) or 0) > 0),
		("T+1开盘涨≥1%", lambda r: (t1_open_pct(r) or -999) >= 1),
		("T+1开盘涨≥3%", lambda r: (t1_open_pct(r) or -999) >= 3),
		("T+1开盘涨≥5%", lambda r: (t1_open_pct(r) or -999) >= 5),
		("T+1开盘跌<0", lambda r: (t1_open_pct(r) or 0) < 0),
		("T+1开盘跌≤-1%", lambda r: (t1_open_pct(r) or 999) <= -1),
		("T+1开盘跌≤-3%", lambda r: (t1_open_pct(r) or 999) <= -3),
		("T+1开盘-2~5%", lambda r: -2 <= (t1_open_pct(r) or -999) <= 5),
	]:
		for hold in (1, 2, 3):
			soff = 1 + hold
			label = "%s 持%d天" % (name, hold)
			s = summarize(
				run_spec(
					sub, g0, cd,
					Spec(label, 1, "open", soff, filter_fn=fn),
				)
			)
			if s:
				s["label"] = label
				t1_filters.append(s)
	t1_filters.sort(key=lambda x: x["mean"], reverse=True)
	print_table("【4】T+1开盘涨跌幅过滤 × 持有天数 Top15", t1_filters)

	# ── 6. T日收盘买专项 ──
	t0c: list[dict] = []
	for hold in range(1, 7):
		label = "T收盘买 持%d天" % hold
		s = summarize(run_spec(sub, g0, cd, Spec(label, 0, "close", hold)))
		if s:
			s["label"] = label
			t0c.append(s)
	for name, fn in [
		("T收涨>0", lambda r: (t_close_pct(r) or 0) > 0),
		("T收涨≥3%", lambda r: (t_close_pct(r) or -999) >= 3),
		("T收跌<0", lambda r: (t_close_pct(r) or 0) < 0),
	]:
		for hold in (1, 2, 3):
			label = "T收盘买+%s 持%d天" % (name, hold)
			s = summarize(
				run_spec(sub, g0, cd, Spec(label, 0, "close", hold, filter_fn=fn))
			)
			if s:
				s["label"] = label
				t0c.append(s)
	t0c.sort(key=lambda x: x["mean"], reverse=True)
	print_table("【5】T日收盘买入专项 Top12", t0c)

	# ── 7. 基准 + 16%止盈 & 网格优胜 + 止盈 ──
	tp_rows: list[dict] = []
	s = summarize(
		run_spec(
			sub, g0, cd,
			Spec("基准+16%止盈", *BASE_BUY, BASE_SELL_OFF, tp_pct=TP_PCT),
		)
	)
	if s:
		s["label"] = "基准+16%止盈"
		tp_rows.append(s)
	for g in grid[:5]:
		# parse from label — re-run with tp
		for bl, boff, kind in buys:
			for hold in range(1, 7):
				soff = boff + hold
				lbl = "%s 持%d天→T+%d收" % (bl, hold, soff)
				if lbl != g["label"]:
					continue
				s2 = summarize(
					run_spec(sub, g0, cd, Spec(lbl + "+TP16", boff, kind, soff, tp_pct=TP_PCT))
				)
				if s2:
					s2["label"] = lbl + "+TP16"
					tp_rows.append(s2)
	tp_rows.sort(key=lambda x: x["mean"], reverse=True)
	print_table("【6】16%止盈：基准与网格Top5", tp_rows)

	# ── 8. 推荐组合（分支+止盈）──
	def pick_best_branch(row: pd.Series) -> Spec | None:
		p = t_close_pct(row)
		if p is None:
			return None
		if p > 0:
			return Spec("", 1, "open", 2, tp_pct=TP_PCT)  # 涨：基准+止盈
		if p <= -3:
			return Spec("", 0, "close", 2, tp_pct=TP_PCT)  # 深跌：T收持2
		return Spec("", 1, "open", 3, tp_pct=TP_PCT)  # 浅跌：多持1天

	rec = branch_run(
		sub, g0, cd,
		"分支:涨>0→基准+TP | 跌≤-3%→T收持2+TP | 其余→T+1持2+TP",
		pick_best_branch,
	)
	alt_picks = [
		branch_run(
			sub, g0, cd,
			"涨>0→T+1持1+TP | 跌<0→T收持2+TP",
			lambda r: (
				Spec("", 1, "open", 2, tp_pct=TP_PCT)
				if (t_close_pct(r) or 0) > 0
				else Spec("", 0, "close", 2, tp_pct=TP_PCT)
				if (t_close_pct(r) or 0) < 0
				else None
			),
		),
		branch_run(
			sub, g0, cd,
			"涨≥3%→T+1持1+TP | 其余不买",
			lambda r: Spec("", 1, "open", 2, tp_pct=TP_PCT) if (t_close_pct(r) or -999) >= 3 else None,
		),
		branch_run(
			sub, g0, cd,
			"T+1开盘涨>0→持1+TP | T+1开盘跌<0→T收持2+TP",
			lambda r: (
				Spec("", 1, "open", 2, tp_pct=TP_PCT)
				if (t1_open_pct(r) or 0) > 0
				else Spec("", 0, "close", 2, tp_pct=TP_PCT)
				if (t1_open_pct(r) or 0) < 0
				else None
			),
		),
	]
	print("\n" + "=" * 96)
	print("【7】推荐组合方案")
	print("%-48s %5s %6s %7s %7s %10s" % ("方案", "笔数", "胜率", "均收益", "合计%", "金额"))
	if base:
		print(
			"%-48s %5d %5.1f%% %6.2f%% %7.1f%% %10.0f"
			% (base["label"], base["n"], base["win"], base["mean"], base["sum_pct"], base["pnl"])
		)
	for item in [rec] + [x for x in alt_picks if x]:
		print(
			"%-48s %5d %5.1f%% %6.2f%% %7.1f%% %10.0f"
			% (item["label"], item["n"], item["win"], item["mean"], item["sum_pct"], item["pnl"])
		)
		if base:
			print(
				"  vs基准 均收益 %+.2f%% 金额 %+.0f"
				% (item["mean"] - base["mean"], item["pnl"] - base["pnl"])
			)


if __name__ == "__main__":
	main()
