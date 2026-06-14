# -*- coding: utf-8 -*-
"""持有到期日大跌：当日收盘卖 vs 延后至次日收盘卖。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	_day_col,
	_day_close_pct_vs_prev,
	_day_open_pct_vs_prev,
	_num,
	build_code_trade_dates,
	build_g_zero,
	f_trade_rule,
	FIXED_RULE_SPECS,
	MAX_DATA_DAY,
	MAX_SELL_DAY,
	load_yidong,
	run_backtest,
	simulate_trade,
)


def planned_sell_off(row) -> int:
	rule = f_trade_rule(row.get("F"))
	if rule in FIXED_RULE_SPECS:
		return FIXED_RULE_SPECS[rule][2]
	return MAX_SELL_DAY


def summarize(sub: pd.DataFrame, label: str) -> None:
	if len(sub) < 3:
		print("%s n=%d (样本过少)" % (label, len(sub)))
		return
	print("--- %s n=%d ---" % (label, len(sub)))
	for c in ("ret_same", "ret_next_c", "ret_next_o", "bounce_c", "bounce_o"):
		r = sub[c].dropna()
		if len(r):
			print(
				"  %s: mean=%.2f%% med=%.2f%% win=%.1f%%"
				% (c, r.mean(), r.median(), (r > 0).mean() * 100)
			)
	better = (sub["ret_next_c"] > sub["ret_same"]).mean() * 100
	print("  次日收盘优于当日卖: %.1f%%" % better)
	print("  均收益差(次日-当日): %.2f%%" % (sub["ret_next_c"].mean() - sub["ret_same"].mean()))


def main() -> None:
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	g_zero = build_g_zero(df)
	code_dates = build_code_trade_dates(df)
	rows = []
	for _, row in df.iterrows():
		if row.get("G") != 1:
			continue
		if f_trade_rule(row.get("F")) is None:
			continue
		t = simulate_trade(row, g_zero, code_dates)
		if t is None:
			continue
		reason = str(t.get("卖出原因", ""))
		if "止损" in reason or "G0" in reason:
			continue
		m = re.search(r"T\+(\d+)", reason)
		if not m:
			continue
		actual_off = int(m.group(1))
		sell_off = planned_sell_off(row)
		if actual_off != sell_off:
			continue
		buy_px = float(t["买入价"])
		sell_px = float(t["卖出价"])
		day_pct = _day_close_pct_vs_prev(row, sell_off)
		day_open_pct = _day_open_pct_vs_prev(row, sell_off)
		next_off = sell_off + 1
		if next_off > MAX_DATA_DAY:
			continue
		c1 = _num(row.get(_day_col(next_off, "收盘")))
		o1 = _num(row.get(_day_col(next_off, "开盘")))
		if c1 is None:
			continue
		ret_same = (sell_px / buy_px - 1) * 100
		ret_next_c = (c1 / buy_px - 1) * 100
		ret_next_o = (o1 / buy_px - 1) * 100 if o1 else None
		bounce_c = (c1 / sell_px - 1) * 100
		bounce_o = (o1 / sell_px - 1) * 100 if o1 else None
		rows.append(
			{
				"day_pct": day_pct,
				"day_open_pct": day_open_pct,
				"ret_same": ret_same,
				"ret_next_c": ret_next_c,
				"ret_next_o": ret_next_o,
				"bounce_c": bounce_c,
				"bounce_o": bounce_o,
				"sell_off": sell_off,
			}
		)

	all_df = pd.DataFrame(rows)
	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("=== 计划到期日收盘卖出(排除止损/G0) n=%d ===" % len(all_df))
	summarize(all_df, "全部到期样本")
	for thr in (-5, -8, -10):
		sub = all_df[all_df["day_pct"] <= thr]
		summarize(sub, "到期日跌>=%d%%(相对昨收)" % abs(thr))

	sub5 = all_df[all_df["day_pct"] <= -5]
	if len(sub5):
		gap_up = sub5[sub5["bounce_o"] > 0]
		summarize(gap_up, "到期跌>=5%%且次日开盘>到期收盘")
	summarize(all_df[all_df["day_pct"] > -5], "到期日跌幅>-5%%")

	tdf, summ = run_backtest(df)
	print("\n=== 现行全策略回测 ===")
	print("成交笔数:", len(tdf), "均收益=%.2f%%" % tdf["收益率%"].mean())
	print("若到期样本全部当日卖 均收益=%.2f%%" % all_df["ret_same"].mean())
	print("若到期样本全部延至次日收盘卖 均收益=%.2f%%" % all_df["ret_next_c"].mean())
	big = all_df[all_df["day_pct"] <= -5]
	if len(big):
		print(
			"大跌>=5%%: 当日=%.2f%% 次日=%.2f%% 差=%.2f%% 反弹胜率=%.1f%%"
			% (
				big["ret_same"].mean(),
				big["ret_next_c"].mean(),
				big["ret_next_c"].mean() - big["ret_same"].mean(),
				(big["bounce_c"] > 0).mean() * 100,
			)
		)


if __name__ == "__main__":
	main()
