# -*- coding: utf-8 -*-
"""F8 / F9 / F28 / F29：买入日 × 持有1~3天（现行流动性 + G0）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	simulate_trade,
	_simulate_fixed_sell,
)

CSV = Path(YIDONG_REGULATION_STOCKS_CSV)
TARGET_F = (8, 9, 28, 29)
HOLDS = (1, 2, 3)

BUYS = [
	("T收盘", 0, "close"),
	("T+1开盘", 1, "open"),
	("T+2开盘", 2, "open"),
	("T+1收盘", 1, "close"),
]

# 现行分F规则中的固定组合（便于对照）
FORMAL = {
	8: ("T+1开盘", 1, "open", 1, "现行:T+1开持1天"),
	9: ("T+1开盘", 1, "open", 1, "现行:T+1开持1天"),
	28: ("T收盘", 0, "close", 0, "现行默认:T收+止损兜底"),
	29: ("T收盘", 0, "close", 0, "现行默认:T收+止损兜底"),
}

MIN_N = 5


def _stats(rows: list[dict]) -> dict | None:
	if len(rows) < MIN_N:
		return None
	r = pd.Series([x["收益率%"] for x in rows])
	return {
		"n": len(r),
		"wr": round(100 * (r > 0).mean(), 1),
		"avg": round(r.mean(), 2),
		"sum": round(r.sum(), 1),
		"med": round(r.median(), 2),
		"pnl": round(sum(x.get("收益金额", 0) for x in rows), 0),
	}


def _run_combo(sub: pd.DataFrame, g0, cd, buy_off: int, kind: str, hold: int) -> dict | None:
	rows = []
	sell_off = buy_off + hold
	for _, r in sub.iterrows():
		t = _simulate_fixed_sell(
			r,
			g0,
			cd,
			buy_off=buy_off,
			buy_kind=kind,
			sell_off=sell_off,
			rule_id="h%d" % hold,
		)
		if t:
			rows.append(t)
	return _stats(rows)


def scan_f(sig: pd.DataFrame, g0, cd, f: int) -> list[dict]:
	sub = sig.loc[sig["F"] == f].copy()
	print("\n" + "=" * 92)
	print("【F%d】可买信号 %d" % (f, len(sub)))
	if len(sub) < MIN_N:
		print("  样本不足，跳过")
		return []

	records: list[dict] = []
	for hold in HOLDS:
		print("\n  ── 持有 %d 天（计划日收盘卖；跌停顺延次日；G0强平）──" % hold)
		print("    %-12s %5s %7s %8s %8s %8s %10s" % ("买入", "笔数", "胜率", "均收益", "合计%", "中位数", "收益金额元"))
		best_sum = None
		best_label = ""
		for label, buy_off, kind in BUYS:
			s = _run_combo(sub, g0, cd, buy_off, kind, hold)
			if not s:
				print("    %-12s 样本不足" % label)
				continue
			print(
				"    %-12s %5d %6.1f%% %7.2f%% %8.1f%% %7.2f%% %10.0f"
				% (label, s["n"], s["wr"], s["avg"], s["sum"], s["med"], s["pnl"])
			)
			records.append({"F": f, "持有天": hold, "买入": label, **s})
			if best_sum is None or s["sum"] > best_sum:
				best_sum = s["sum"]
				best_label = label
		if best_label:
			print("    ★ 本持有期合计最优: %s (%.1f%%)" % (best_label, best_sum))

	# 跨持有期：每个买入方式哪档持有最好
	print("\n  ── 各买入方式：持有1/2/3天合计%对比 ──")
	print("    %-12s %10s %10s %10s %8s" % ("买入", "持1天", "持2天", "持3天", "最优持有"))
	for label, buy_off, kind in BUYS:
		sums: list[tuple[int, float | None]] = []
		for hold in HOLDS:
			s = _run_combo(sub, g0, cd, buy_off, kind, hold)
			sums.append((hold, s["sum"] if s else None))
		cells = []
		best_h = None
		best_v = None
		for hold, v in sums:
			if v is None:
				cells.append("   —")
			else:
				cells.append("%8.1f%%" % v)
				if best_v is None or v > best_v:
					best_v = v
					best_h = hold
		print("    %-12s %s %s %s %8s" % (label, cells[0], cells[1], cells[2], ("持%d天" % best_h) if best_h else "—"))

	if f in FORMAL and f in (8, 9):
		_, buy_off, kind, hold, note = FORMAL[f]
		s = _run_combo(sub, g0, cd, buy_off, kind, hold)
		print("\n  【对照】%s" % note)
		if s:
			print(
				"    %d笔 胜率%.1f%% 均%.2f%% 合计%.1f%% 金额%.0f"
				% (s["n"], s["wr"], s["avg"], s["sum"], s["pnl"])
			)
	else:
		rows = []
		for _, r in sub.iterrows():
			t = simulate_trade(r, g0, cd)
			if t:
				rows.append(t)
		s = _stats(rows)
		print("\n  【对照】现行默认（T收盘+8%%止损+T+6兜底）")
		if s:
			print(
				"    %d笔 胜率%.1f%% 均%.2f%% 合计%.1f%% 金额%.0f"
				% (s["n"], s["wr"], s["avg"], s["sum"], s["pnl"])
			)

	return records


def print_summary(all_rec: list[dict]) -> None:
	print("\n" + "=" * 92)
	print("【总览】各 F × 持有天：全买入方式中合计%最高的一组")
	print("=" * 92)
	print("  %4s %6s %-12s %5s %7s %8s %8s" % ("F", "持有", "最优买入", "笔数", "胜率", "均收益", "合计%"))
	for f in TARGET_F:
		sub = [r for r in all_rec if r["F"] == f]
		for hold in HOLDS:
			cands = [r for r in sub if r["持有天"] == hold]
			if not cands:
				continue
			best = max(cands, key=lambda x: x["sum"])
			print(
				"  %4d %6d %-12s %5d %6.1f%% %7.2f%% %8.1f%%"
				% (f, hold, best["买入"], best["n"], best["wr"], best["avg"], best["sum"])
			)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)
	print("F8/F9/F28/F29 持有1~3天 | %s | 可买信号 %d" % (CSV.name, len(sig)))
	print("规则: 买入涨幅带 | 卖出跌停顺延次日 | G0强平")

	all_rec: list[dict] = []
	for f in TARGET_F:
		all_rec.extend(scan_f(sig, g0, cd, f))
	print_summary(all_rec)


if __name__ == "__main__":
	main()
