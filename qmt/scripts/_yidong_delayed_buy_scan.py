# -*- coding: utf-8 -*-
"""F4-6 / F7-8：T ~ T+3 延后买入对比（需 CSV 含 T+10 行情）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from yidong_regulation_backtest_core import (  # noqa: E402
	MAX_SELL_DAY,
	STOP_MIN_DAY,
	STOP_PCT,
	_day_col,
	_num,
	build_code_trade_dates,
	build_g_zero,
	collect_signals,
	load_yidong,
	trade_date_at_offset,
)

CSV = Path(__file__).resolve().parents[1] / "实盘策略" / "上游数据源" / "yidong_regulation_stocks_2026.csv"
MAX_DATA_DAY = 10  # 与 enrich T+10 列一致


def f_band(f: float) -> str:
	if 4 <= f <= 6:
		return "F4-6"
	if 7 <= f <= 8:
		return "F7-8"
	return "other"


def simulate_delayed(
	row: pd.Series,
	g_zero: set,
	code_dates: dict,
	*,
	buy_off: int,
	buy_kind: str,
	anchor: str,
	stop_pct: float = STOP_PCT,
	min_day: int = STOP_MIN_DAY,
	fallback_off: int | None = None,
) -> dict | None:
	"""buy_off: 0=T … 3=T+3。buy_kind: open|close。anchor: calendar|from_buy。"""
	if buy_kind == "open":
		buy_px = _num(row.get(_day_col(buy_off, "开盘")))
	else:
		buy_px = _num(row.get(_day_col(buy_off, "收盘")))
	if buy_px is None:
		return None

	code = str(row["股票代码"])
	t_day = str(row["T日"])
	stop_line = buy_px * (1.0 - stop_pct / 100.0)

	if anchor == "calendar":
		first_stop_off = min_day
		last_off = fallback_off if fallback_off is not None else MAX_SELL_DAY
	else:
		first_stop_off = buy_off + min_day
		last_off = buy_off + (fallback_off if fallback_off is not None else 6)

	last_off = min(last_off, MAX_DATA_DAY)

	sell_px = None
	sell_day = ""
	reason = ""

	for off in range(buy_off + 1, last_off + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			return None

		td = trade_date_at_offset(code, t_day, off, code_dates)
		if td and (code, td) in g_zero:
			sell_px, sell_day, reason = c, td, "G0强平"
			break

		if off >= first_stop_off and lo is not None and lo <= stop_line + 1e-9:
			sell_px, sell_day = c, td or ("T+%d" % off)
			reason = "止损%d%%(T+%d收盘)" % (int(stop_pct), off)
			break

	if sell_px is None:
		fc = _num(row.get(_day_col(last_off, "收盘")))
		if fc is None:
			return None
		sell_px = fc
		sell_day = trade_date_at_offset(code, t_day, last_off, code_dates) or ("T+%d" % last_off)
		reason = "未触发止损 T+%d收盘" % last_off

	ret = (sell_px / buy_px - 1.0) * 100.0
	return {
		"收益率%": ret,
		"买入价": buy_px,
		"卖出原因": reason,
	}


def run_band(sig: pd.DataFrame, g0, cd, band: str) -> None:
	sub = sig[sig["band"] == band]
	print("\n" + "=" * 68)
	print("%s  信号 %d" % (band, len(sub)))
	print("=" * 68)

	scenarios = [
		("T收盘买|日历锚(现状)", 0, "close", "calendar", 6),
		("T+1开盘买|日历锚", 1, "open", "calendar", 6),
		("T+2开盘买|日历锚", 2, "open", "calendar", 6),
		("T+3开盘买|日历锚", 3, "open", "calendar", 6),
		("T+3收盘买|日历锚", 3, "close", "calendar", 6),
		("T+1开盘买|买入锚SL+6", 1, "open", "from_buy", 6),
		("T+2开盘买|买入锚SL+6", 2, "open", "from_buy", 6),
		("T+3开盘买|买入锚SL+6", 3, "open", "from_buy", 6),
		("T+3收盘买|买入锚SL+6", 3, "close", "from_buy", 6),
		("T+3收盘买|买入锚SL+兜底3", 3, "close", "from_buy", 3),
	]

	for name, buy_off, kind, anchor, fb in scenarios:
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
		if len(rows) < 5:
			print("%-28s 样本不足" % name)
			continue
		r = pd.Series([x["收益率%"] for x in rows])
		print(
			"%-28s n=%3d wr=%5.1f%% avg=%6.2f%% sum=%7.1f%%"
			% (name, len(r), 100 * (r > 0).mean(), r.mean(), r.sum())
		)


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)
	sig = collect_signals(df).copy()
	sig["band"] = sig["F"].map(lambda x: f_band(float(x)) if pd.notna(x) else "other")
	for band in ("F4-6", "F7-8"):
		run_band(sig, g0, cd, band)


if __name__ == "__main__":
	main()
