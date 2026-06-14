# -*- coding: utf-8 -*-
"""对比：仅跌幅带 vs 涨跌幅对称带 — 列出减少的成交及原因。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))

import yidong_regulation_backtest_core as core
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV
from yidong_regulation_backtest_core import (
	_BAND_EDGE_TOL,
	_day_pct_vs_prev,
	_limit_down_band,
	build_code_trade_dates,
	build_f_block_keys,
	build_g_zero,
	f_trade_rule,
	is_day_in_limit_up_band,
	is_day_in_skip_band,
	load_yidong,
)


def _is_limit_skip_row_old(row: pd.Series) -> bool:
	code = str(row["股票代码"]).zfill(6)
	pct = _day_pct_vs_prev(row, 0)
	if pct is None:
		return False
	hi = 15.0 if code.startswith(("68", "30")) else 8.0
	if pct > hi:
		return True
	floor, ceil = _limit_down_band(code)
	return pct <= ceil + 1e-6 and pct >= floor - _BAND_EDGE_TOL


def _is_buy_day_blocked_old(row: pd.Series, buy_off: int, buy_kind: str) -> bool:
	code = str(row["股票代码"]).zfill(6)
	floor, ceil = _limit_down_band(code)
	pct = _day_pct_vs_prev(row, buy_off)
	if pct is None:
		return False
	return pct <= ceil + 1e-6 and pct >= floor - _BAND_EDGE_TOL


def _buy_off_kind(f_val) -> tuple[int, str]:
	rule = f_trade_rule(f_val)
	if rule == "fix_t1o_t2c":
		return 1, "open"
	if rule == "fix_t2o_t3c":
		return 2, "open"
	if rule == "fix_t0c_t1c":
		return 0, "close"
	return 0, "close"


def _run_old() -> pd.DataFrame:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	blocked = build_f_block_keys(df)
	mask = (
		df["T日_收盘"].astype(str).str.strip().ne("")
		& df["G"].eq(1)
		& ~df.apply(lambda r: (str(r["T日"]), str(r["股票代码"])) in blocked, axis=1)
		& ~df.apply(_is_limit_skip_row_old, axis=1)
	)
	sig = df.loc[mask]
	orig = core.is_buy_day_blocked
	core.is_buy_day_blocked = _is_buy_day_blocked_old
	rows = []
	try:
		for _, r in sig.iterrows():
			t = core.simulate_trade(r, g0, cd)
			if t:
				rows.append(t)
	finally:
		core.is_buy_day_blocked = orig
	return pd.DataFrame(rows)


def _run_new() -> pd.DataFrame:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = core.collect_signals(df)
	rows = []
	for _, r in sig.iterrows():
		t = core.simulate_trade(r, g0, cd)
		if t:
			rows.append(t)
	return pd.DataFrame(rows)


def _trade_key(df: pd.DataFrame) -> pd.Series:
	return (
		df["开仓日"].astype(str)
		+ "|"
		+ df["股票代码"].astype(str)
		+ "|"
		+ df["监控日涨幅偏离值F"].astype(str)
	)


def _summ(df: pd.DataFrame) -> dict:
	r = df["收益率%"].astype(float)
	return {
		"成交数": len(df),
		"胜率%": round(100 * (r > 0).mean(), 1),
		"均值%": round(r.mean(), 2),
		"中位数%": round(r.median(), 2),
		"合计收益%": round(r.sum(), 1),
		"合计金额": round(df["收益金额"].astype(float).sum(), 0),
	}


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	old = _run_old()
	new = _run_new()

	print("=" * 72)
	print("规则对比：旧=仅跌幅带 + T日涨>8/15跳过 | 新=涨跌幅对称带")
	print("=" * 72)
	s_old, s_new = _summ(old), _summ(new)
	print("\n【整体】")
	print("         旧规则    新规则    变化")
	for k in s_old:
		d = s_new[k] - s_old[k] if isinstance(s_old[k], (int, float)) else "-"
		print("  %-8s %8s %8s %8s" % (k, s_old[k], s_new[k], d))

	ko, kn = set(_trade_key(old)), set(_trade_key(new))
	removed = old[_trade_key(old).isin(ko - kn)].copy()
	added = new[_trade_key(new).isin(kn - ko)].copy()
	print("\n减少成交: %d 笔 | 新增成交: %d 笔" % (len(removed), len(added)))

	# 逐笔剔除原因
	rows_out = []
	for _, t in removed.iterrows():
		t_day = str(t["开仓日"]).replace("-", "")[:8]
		code = str(t["股票代码"]).zfill(6)
		fv = t["监控日涨幅偏离值F"]
		sub = df[(df["T日"] == t_day) & (df["股票代码"] == code) & (df["F"] == fv)]
		if sub.empty:
			sub = df[(df["T日"] == t_day) & (df["股票代码"] == code)]
		if sub.empty:
			continue
		r = sub.iloc[0]
		bo, bk = _buy_off_kind(r["F"])
		tp = _day_pct_vs_prev(r, 0)
		bp = _day_pct_vs_prev(r, bo)
		reason = []
		if is_day_in_limit_up_band(r, 0):
			reason.append("T日涨幅带")
		if is_day_in_limit_up_band(r, bo):
			reason.append("买入日涨幅带")
		if core.is_day_in_limit_down_band(r, bo) and not _is_buy_day_blocked_old(r, bo, bk):
			reason.append("买入日跌幅带(新一致)")
		if not reason:
			reason.append("买入日涨幅带/仿真失败")
		rows_out.append(
			{
				"开仓日": t_day,
				"代码": code,
				"名称": t["股票名称"],
				"F": int(fv) if pd.notna(fv) else fv,
				"买卖规则": t.get("买卖规则", ""),
				"旧规则收益率%": round(float(t["收益率%"]), 2),
				"旧规则收益金额": round(float(t["收益金额"]), 0),
				"T日涨跌%": round(tp, 2) if tp is not None else None,
				"买入日涨跌%": round(bp, 2) if bp is not None else None,
				"买入偏移": "T+%d %s" % (bo, bk),
				"剔除原因": "+".join(reason),
			}
		)

	detail = pd.DataFrame(rows_out)
	if not detail.empty:
		print("\n【剔除原因分布】")
		print(Counter(detail["剔除原因"]).most_common())

		print("\n【按 F 档汇总剔除】")
		g = detail.groupby("F").agg(
			笔数=("旧规则收益率%", "count"),
			旧合计收益=("旧规则收益金额", "sum"),
			旧均收益=("旧规则收益率%", "mean"),
			盈利笔=("旧规则收益率%", lambda s: int((s > 0).sum())),
		)
		print(g.round(2).to_string())

		print("\n【减少的 24 笔明细】")
		print(
			detail.sort_values(["F", "开仓日"])[
				[
					"开仓日",
					"代码",
					"名称",
					"F",
					"买入偏移",
					"T日涨跌%",
					"买入日涨跌%",
					"剔除原因",
					"旧规则收益率%",
					"旧规则收益金额",
				]
			].to_string(index=False)
		)

		out = Path(YIDONG_REGULATION_STOCKS_CSV).parents[1] / "测试组合表格" / "yidong_band_rule_change_removed.csv"
		detail.to_csv(out, index=False, encoding="utf-8-sig")
		print("\n[OK] 明细已写: %s" % out)

	# 新规则下：因涨幅带放开而「理论上可买」但需看信号层
	print("\n【规则语义变化说明】")
	print("  旧: T日涨>8%(60/00)或>15%(68/30) 即跳过 → 新: 仅 [8,10] / [15,30] 涨幅带跳过")
	print("  新规则 T日信号数:", len(core.collect_signals(df)), "(旧可成交路径基于旧信号略多)")


if __name__ == "__main__":
	main()
