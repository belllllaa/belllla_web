# -*- coding: utf-8 -*-
"""全档应用「T日收跌<=0多持1天+TP16」vs 新基准(全档固定持满+TP16)。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	MAX_DATA_DAY,
	STOP_MIN_DAY,
	STOP_PCT,
	_day_close_pct_vs_prev,
	_day_col,
	_num,
	_pack_trade,
	_try_g0_sell,
	_try_plate_close_sell,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	f_trade_rule,
	is_buy_day_blocked,
	load_yidong,
	planned_buy_calendar,
	trade_date_at_offset,
	G0_DEFER_BUY_DAY_TO_NEXT_CLOSE,
)
from _yidong_tp_scan import (  # noqa: E402
	_simulate_fixed_sell_tp,
	_tp_quote,
	run_tp_backtest,
)

TP = 16.0
TIERS = ("F7", "F10", "F8/F30", "F9/F27/F28", "其余")

# 基准固定档: (buy_off, buy_kind, sell_off)
BASE_FIXED = {
	7: (2, "open", 3),
	10: (1, "open", 2),
	8: (1, "open", 4),
	30: (1, "open", 4),
	9: (1, "open", 3),
	27: (1, "open", 3),
	28: (1, "open", 3),
}
BASE_DEFAULT_FALLBACK = 6  # T+6收盘兜底(买入日T开盘)


def tier_label(f) -> str:
	f = int(f)
	if f == 7:
		return "F7"
	if f == 10:
		return "F10"
	if f in (8, 30):
		return "F8/F30"
	if f in (9, 27, 28):
		return "F9/F27/F28"
	return "其余"


def planned_buy(row, cd) -> str | None:
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	f = int(row["F"])
	if f in BASE_FIXED:
		boff, _, _ = BASE_FIXED[f]
		code, t = str(row["股票代码"]), str(row["T日"])
		if boff == 0:
			return t or None
		return trade_date_at_offset(code, t, boff, cd)
	return planned_buy_calendar(row, code_dates=cd, rule_id="default")


def t_day_down(row: pd.Series) -> bool | None:
	p = _day_close_pct_vs_prev(row, 0)
	if p is None:
		return None
	return p <= 0


def _simulate_default_tp_fallback(
	row: pd.Series,
	g_zero: set,
	code_dates: dict,
	*,
	tp_pct: float,
	fallback_off: int,
) -> dict | None:
	"""其余档: T开盘买 + 止损 + 兜底收盘(可延长) + 止盈。"""
	if is_buy_day_blocked(row, 0, "open"):
		return None
	buy_px = _num(row.get("T日_开盘"))
	if buy_px is None:
		return None
	code = str(row["股票代码"])
	t_day = str(row["T日"])
	stop_line = buy_px * (1.0 - STOP_PCT / 100.0)
	last_off = min(fallback_off, MAX_DATA_DAY)
	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []
	stop_active = False
	buy_off = 0

	if G0_DEFER_BUY_DAY_TO_NEXT_CLOSE:
		res = _try_g0_sell(row, 0, code, t_day, code_dates, g_zero, buy_off=buy_off)
		if res:
			sell_px, sell_day, reason = res
			lo0 = _num(row.get(_day_col(0, "最低")))
			if lo0 is not None:
				hold_lows.append(lo0)

	for off in range(1, MAX_DATA_DAY + 1):
		if sell_px is not None:
			break
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			break
		hold_lows.append(lo)
		res = _try_g0_sell(row, off, code, t_day, code_dates, g_zero, buy_off=buy_off)
		if res:
			sell_px, sell_day, reason = res
			break
		if tp_pct is not None:
			res = _tp_quote(row, off, code, t_day, code_dates, buy_px, tp_pct)
			if res:
				sell_px, sell_day, reason = res
				break
		if off >= STOP_MIN_DAY and lo is not None and lo <= stop_line + 1e-9:
			stop_active = True
		if stop_active:
			res = _try_plate_close_sell(
				row, off, code, t_day, code_dates,
				"止损%.0f%%(T+%d收盘)" % (STOP_PCT, off),
			)
			if res:
				sell_px, sell_day, reason = res
				break
			continue
		if off == last_off:
			res = _try_plate_close_sell(
				row, last_off, code, t_day, code_dates,
				"未触发止损 T+%d收盘" % last_off,
			)
			if res:
				sell_px, sell_day, reason = res
				break
	if sell_px is None:
		return None
	rid = "default_tp%.0f_fb%d" % (tp_pct, fallback_off)
	return _pack_trade(
		row, buy_px=buy_px, sell_px=sell_px, sell_day=sell_day, buy_cal=t_day,
		reason=reason, rule_id=rid, hold_lows=hold_lows, t_day=t_day,
	)


def sim_tier(
	row: pd.Series,
	g0: set,
	cd: dict,
	*,
	only_f10_branch: bool = False,
	all_tiers_branch: bool = False,
) -> dict | None:
	f = int(row["F"])
	down = t_day_down(row)
	if down is None:
		return None
	extra = 1 if (all_tiers_branch and down) or (only_f10_branch and f == 10 and down) else 0

	if f in BASE_FIXED:
		boff, kind, soff = BASE_FIXED[f]
		soff = soff + extra
		rule = "fix_f%d_down%d" % (f, extra) if extra else f_trade_rule(f)
		return _simulate_fixed_sell_tp(
			row, g0, cd,
			buy_off=boff, buy_kind=kind, sell_off=soff,
			rule_id=str(rule), tp_pct=TP,
		)
	fallback = BASE_DEFAULT_FALLBACK + (extra if all_tiers_branch else 0)
	return _simulate_default_tp_fallback(row, g0, cd, tp_pct=TP, fallback_off=fallback)


def run_variant(only_f10: bool, all_tiers: bool) -> pd.DataFrame:
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	trades: list[dict] = []
	for _, row in collect_signals(df).iterrows():
		if not planned_buy(row, cd):
			continue
		t = sim_tier(
			row, g0, cd,
			only_f10_branch=only_f10,
			all_tiers_branch=all_tiers,
		)
		if t:
			trades.append(t)
	return pd.DataFrame(trades)


def tier_stats(tdf: pd.DataFrame, tier: str) -> dict | None:
	sub = tdf if tier == "合计" else tdf[tdf.apply(
		lambda r: tier_label(r["监控日涨幅偏离值F"]) == tier, axis=1,
	)]
	if sub.empty:
		return None
	r = sub["收益率%"].astype(float)
	return {
		"档位": tier,
		"笔数": len(sub),
		"胜率%": round((r > 0).mean() * 100, 1),
		"均收益%": round(float(r.mean()), 2),
		"合计金额": round(float(sub["收益金额"].sum()), 0),
		"止盈": int(sub["卖出原因"].astype(str).str.contains("止盈", na=False).sum()),
	}


def print_table(rows: list[dict], title: str) -> None:
	print("\n=== %s ===" % title)
	print(pd.DataFrame(rows).to_string(index=False))


def diff_table(base: pd.DataFrame, alt: pd.DataFrame, label: str) -> None:
	print("\n=== 差异: %s - 新基准 ===" % label)
	rows = []
	for t in TIERS:
		b, a = tier_stats(base, t), tier_stats(alt, t)
		if not b or not a:
			continue
		rows.append({
			"档位": t,
			"笔数差": a["笔数"] - b["笔数"],
			"均收益差%": round(a["均收益%"] - b["均收益%"], 2),
			"金额差": round(a["合计金额"] - b["合计金额"], 0),
		})
	bc, ac = tier_stats(base, "合计"), tier_stats(alt, "合计")
	if bc and ac:
		rows.append({
			"档位": "合计",
			"笔数差": ac["笔数"] - bc["笔数"],
			"均收益差%": round(ac["均收益%"] - bc["均收益%"], 2),
			"金额差": round(ac["合计金额"] - bc["合计金额"], 0),
		})
	print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
	df = load_yidong(Path(YIDONG_REGULATION_STOCKS_CSV))
	print("数据源:", YIDONG_REGULATION_STOCKS_CSV)
	print("规则: T日收盘相对T-1收盘 <=0 则计划持有天数+1; >0 不变; 全档16%%止盈")
	print("固定档延长: F7 T+3->T+4 | F10 T+2->T+3 | F8/F30 T+4->T+5 | F9系 T+3->T+4")
	print("其余档: 兜底 T+6->T+7 (仍T开盘买+T+2起止损)")

	tdf_base, _ = run_tp_backtest(df, TP)
	tdf_f10 = run_variant(only_f10=True, all_tiers=False)
	tdf_all = run_variant(only_f10=False, all_tiers=True)

	base_rows = [tier_stats(tdf_base, t) for t in TIERS] + [tier_stats(tdf_base, "合计")]
	f10_rows = [tier_stats(tdf_f10, t) for t in TIERS] + [tier_stats(tdf_f10, "合计")]
	all_rows = [tier_stats(tdf_all, t) for t in TIERS] + [tier_stats(tdf_all, "合计")]

	print_table([x for x in base_rows if x], "A 新基准: 全档固定持满 + 16%%止盈")
	print_table([x for x in f10_rows if x], "B 仅F10跌日多持1天 + TP16")
	print_table([x for x in all_rows if x], "C 全档跌日多持1天 + TP16")

	diff_table(tdf_base, tdf_f10, "B仅F10")
	diff_table(tdf_base, tdf_all, "C全档")
