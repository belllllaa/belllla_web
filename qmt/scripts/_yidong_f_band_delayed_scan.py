# -*- coding: utf-8 -*-
"""各 F 档：T 收盘买 vs T+1/T+2 延后买（日历锚 / 买入锚）收益与胜率对比。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from _yidong_delayed_buy_scan import CSV, simulate_delayed  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
)

# 可买信号上的 F 分布（不含 SKIP_F 键内被挡的 1/2/3/10/30 行）
F_BANDS: list[tuple[str, float, float]] = [
	("F4-6", 4, 6),
	("F7-8", 7, 8),
	("F9", 9, 9),
	("F10-21", 10, 21),
	("F22-25", 22, 25),
	("F26-29", 26, 29),
	("F9+", 9, 29),
	("全量", 4, 29),
]

BUYS = [
	("T收盘", 0, "close"),
	("T+1开盘", 1, "open"),
	("T+2开盘", 2, "open"),
	("T+1收盘", 1, "close"),
]

ANCHORS = [
	("日历", "calendar", 6),
	("买入锚", "from_buy", 6),
]

MIN_N = 15


def _stats(rows: list[dict]) -> dict | None:
	if len(rows) < MIN_N:
		return None
	r = pd.Series([x["收益率%"] for x in rows])
	return {
		"n": len(r),
		"wr": round(100 * (r > 0).mean(), 1),
		"avg": round(r.mean(), 2),
		"sum": round(r.sum(), 1),
	}


def _filter_band(sig: pd.DataFrame, lo: float, hi: float) -> pd.DataFrame:
	return sig.loc[sig["F"].between(lo, hi)].copy()


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df)

	print("可买信号 %d | 规则：8%%止损 G=0强平 | 对比各 F 档延后买是否优于 T 收盘" % len(sig))
	print("=" * 100)

	for band_name, lo, hi in F_BANDS:
		sub = _filter_band(sig, lo, hi)
		if len(sub) < MIN_N:
			print("\n[%s] 信号 %d — 样本过少，跳过" % (band_name, len(sub)))
			continue

		print("\n【%s】信号 %d" % (band_name, len(sub)))

		for anchor_label, anchor, fb in ANCHORS:
			table: dict[str, dict] = {}
			for buy_label, buy_off, kind in BUYS:
				rows = []
				for _, r in sub.iterrows():
					t = simulate_delayed(
						r,
						g0,
						cd,
						buy_off=buy_off,
						buy_kind=kind,
						anchor=anchor,
						fallback_off=fb,
					)
					if t:
						rows.append(t)
				s = _stats(rows)
				if s:
					table[buy_label] = s

			if "T收盘" not in table:
				continue

			base = table["T收盘"]
			print("  %s锚 | T收盘 n=%d wr=%.1f%% sum=%.1f%%" % (anchor_label, base["n"], base["wr"], base["sum"]))
			print("    %-10s %5s %7s %8s  Δ胜率   Δ合计" % ("买入", "笔数", "胜率", "合计%"))
			for buy_label, _, _ in BUYS:
				if buy_label not in table:
					print("    %-10s 样本不足" % buy_label)
					continue
				s = table[buy_label]
				dwr = s["wr"] - base["wr"]
				dsum = s["sum"] - base["sum"]
				mark = ""
				if buy_label != "T收盘" and dsum > 0 and dwr >= 0:
					mark = " ↑"
				elif buy_label != "T收盘" and dsum < 0 and dwr <= 0:
					mark = " ↓"
				print(
					"    %-10s %5d %6.1f%% %8.1f%% %+6.1f %+8.1f%s"
					% (buy_label, s["n"], s["wr"], s["sum"], dwr, dsum, mark)
				)

			# 该档最优延后买（相对 T 收盘）
			best = None
			for buy_label, _, _ in BUYS[1:]:
				if buy_label not in table:
					continue
				s = table[buy_label]
				if best is None or s["sum"] > best[1]["sum"]:
					best = (buy_label, s)
			if best:
				dsum = best[1]["sum"] - base["sum"]
				dwr = best[1]["wr"] - base["wr"]
				if dsum > 5 or dwr > 2:
					print("    → 延后买有益: %s (Δ合计%+.1f, Δ胜率%+.1f)" % (best[0], dsum, dwr))
				elif dsum < -5 or dwr < -2:
					print("    → 延后买无益: 最好仍 T收盘 或 %s更差" % best[0])
				else:
					print("    → 延后买影响小: 最好 %s (Δ合计%+.1f)" % (best[0], dsum))

	print("\n" + "=" * 100)
	print("↑=相对 T收盘 合计与胜率均改善；↓=均变差。MIN_N=%d" % MIN_N)


if __name__ == "__main__":
	main()
