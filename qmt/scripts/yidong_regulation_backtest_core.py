# -*- coding: utf-8 -*-
"""异动监管回测核心：买入/卖出仿真、过滤与汇总。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from dafengniu_benchmark_ref_trades import compute_extended_metrics  # noqa: E402

# 同 T日+代码任一行 F∈SKIP_F → 整键不买
SKIP_F = {1, 2, 3, 4, 5, 6}
# 该行 F 命中则该信号不做（整行跳过）；F1-6 已整键阻断时通常为空
NO_TRADE_F: set[int] = set()
CAP_PER_STOCK = 100_000.0
MAX_SELL_DAY = 6
MAX_DATA_DAY = 10
STOP_PCT = 8.0
STOP_MIN_DAY = 2  # 默认日历锚：信号日 T+2 起（含 T+2）
FROM_BUY_FALLBACK = 6  # 买入锚兜底：买入日后第 6 个交易日收盘

# 固定持满规则: rule_id -> (buy_off, buy_kind, sell_off)
FIXED_RULE_SPECS: dict[str, tuple[int, str, int]] = {
	"fix_t0c_t1c": (0, "close", 1),
	"fix_t0c_t2c": (0, "close", 2),
	"fix_t0c_t3c": (0, "close", 3),
	"fix_t1o_t2c": (1, "open", 2),
	"fix_t1o_t3c": (1, "open", 3),
	"fix_t1o_t4c": (1, "open", 4),
	"fix_t1c_t2c": (1, "close", 2),
	"fix_t1c_t3c": (1, "close", 3),
	"fix_t1c_t4c": (1, "close", 4),
	"fix_t2o_t3c": (2, "open", 3),
	"fix_t2o_t4c": (2, "open", 4),
}
G0_DEFER_BUY_DAY_TO_NEXT_CLOSE = True
G0_BUY_DAY_DEFER_REASON = "G0强平(买入日触发顺延次日收盘)"
STRATEGY_NAME = "分F档买卖规则"
# 买入过滤：up_band=涨幅带[8,10]/[15,30]不买；pct_threshold=跌幅带不买且涨幅>8%/15%不买
BUY_FILTER_UP_BAND = "up_band"
BUY_FILTER_PCT_THRESHOLD = "pct_threshold"
BUY_FILTER_MODE = BUY_FILTER_PCT_THRESHOLD
# 卖出：time=持满计划天数收盘；ma_break=持仓期任一日尾盘收盘破位MA5或MA10则卖
EXIT_MODE_TIME = "time"
EXIT_MODE_MA_BREAK = "ma_break"


def _parse_float(v) -> float | None:
	"""解析数值（含涨跌幅等可正可负字段）。"""
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return None
	s = str(v).strip()
	if not s or s.lower() == "nan":
		return None
	try:
		return float(s)
	except ValueError:
		return None


def _num(v) -> float | None:
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return None
	s = str(v).strip()
	if not s or s.lower() == "nan":
		return None
	try:
		x = float(s)
	except ValueError:
		return None
	return x if x > 0 else None


def _norm_date(v) -> str:
	s = str(v).strip()[:10].replace("-", "")
	return s if len(s) == 8 and s.isdigit() else ""


def _day_col(off: int, field: str) -> str:
	if off < 0:
		return "T%d日_%s" % (off, field)
	if off == 0:
		return "T日_%s" % field
	return "T+%d日_%s" % (off, field)


_BAND_EDGE_TOL = 0.05  # 允许 10.01% / -10.01% 等贴板日归入带内


def _limit_up_band(code6: str) -> tuple[float, float]:
	"""涨幅带 [floor, ceil]：60/00 [8,10]；68/30 [15,30]。"""
	if code6.startswith(("68", "30")):
		return 15.0, 30.0
	return 8.0, 10.0


def _limit_down_band(code6: str) -> tuple[float, float]:
	"""跌幅带下限、上限（%）：落在 [floor, ceil] 内则不买。60/00: [-10,-8]；68/30: [-30,-15]。"""
	if code6.startswith(("60", "00")):
		return -10.0, -8.0
	if code6.startswith(("68", "30")):
		return -30.0, -15.0
	return -10.0, -8.0


def _limit_threshold(code6: str) -> tuple[float, float]:
	"""兼容旧引用：涨幅带上限、跌幅带下限。"""
	up_lo, up_hi = _limit_up_band(code6)
	dn_lo, _ = _limit_down_band(code6)
	return up_hi, dn_lo


def _prev_close_for_off(row: pd.Series, off: int) -> float | None:
	return _num(row.get(_day_col(off - 1, "收盘")))


def _day_close_pct_vs_prev(row: pd.Series, off: int) -> float | None:
	"""当日收盘价相对昨收的涨跌幅 %。"""
	if off == 0:
		pct = _parse_float(row.get("T日涨跌幅%"))
		if pct is not None:
			return pct
	prev_c = _prev_close_for_off(row, off)
	cur_c = _num(row.get(_day_col(off, "收盘")))
	if prev_c is None or cur_c is None or prev_c <= 0:
		return None
	return (cur_c / prev_c - 1.0) * 100.0


def _day_open_pct_vs_prev(row: pd.Series, off: int) -> float | None:
	"""当日开盘价相对昨收的涨跌幅 %。"""
	prev_c = _prev_close_for_off(row, off)
	op = _num(row.get(_day_col(off, "开盘")))
	if prev_c is None or op is None or prev_c <= 0:
		return None
	return (op / prev_c - 1.0) * 100.0


def is_day_in_limit_up_band(row: pd.Series, off: int, *, price_kind: str = "close") -> bool:
	"""涨幅落在板块涨停带内则不买（含略超 +10%/+30% 的贴板日）。"""
	code = str(row["股票代码"]).zfill(6)
	floor, ceil = _limit_up_band(code)
	if price_kind == "open":
		pct = _day_open_pct_vs_prev(row, off)
	else:
		pct = _day_close_pct_vs_prev(row, off)
	if pct is None:
		return False
	return pct >= floor - 1e-6 and pct <= ceil + _BAND_EDGE_TOL


def is_day_in_limit_down_band(row: pd.Series, off: int) -> bool:
	"""卖出日收盘价相对昨收落在跌幅带内视为跌停卖不出。"""
	code = str(row["股票代码"]).zfill(6)
	floor, ceil = _limit_down_band(code)
	pct = _day_close_pct_vs_prev(row, off)
	if pct is None:
		return False
	return pct <= ceil + 1e-6 and pct >= floor - _BAND_EDGE_TOL


def _day_pct_vs_prev(row: pd.Series, off: int, *, price_kind: str) -> float | None:
	if price_kind == "open":
		return _day_open_pct_vs_prev(row, off)
	return _day_close_pct_vs_prev(row, off)


def _buy_pct_threshold(code6: str) -> float:
	if code6.startswith(("68", "30")):
		return 15.0
	return 8.0


def is_day_in_limit_down_band_at(row: pd.Series, off: int, *, price_kind: str = "close") -> bool:
	"""买入日：相对昨收跌幅落在板块跌停带内则不买。"""
	code = str(row["股票代码"]).zfill(6)
	floor, ceil = _limit_down_band(code)
	pct = _day_pct_vs_prev(row, off, price_kind=price_kind)
	if pct is None:
		return False
	return pct <= ceil + 1e-6 and pct >= floor - _BAND_EDGE_TOL


def is_buy_day_blocked_up_band(row: pd.Series, buy_off: int, buy_kind: str) -> bool:
	"""买入流动性（旧）：涨幅带内不买。"""
	price_kind = "open" if buy_kind == "open" else "close"
	return is_day_in_limit_up_band(row, buy_off, price_kind=price_kind)


def is_buy_day_blocked_pct_threshold(row: pd.Series, buy_off: int, buy_kind: str) -> bool:
	"""买入流动性（新）：跌幅带内不买；或涨幅超过 8%/15% 不买。"""
	code = str(row["股票代码"]).zfill(6)
	price_kind = "open" if buy_kind == "open" else "close"
	pct = _day_pct_vs_prev(row, buy_off, price_kind=price_kind)
	if pct is None:
		return False
	if is_day_in_limit_down_band_at(row, buy_off, price_kind=price_kind):
		return True
	return pct > _buy_pct_threshold(code) + 1e-6


def is_buy_day_blocked(row: pd.Series, buy_off: int, buy_kind: str) -> bool:
	"""买入流动性：收盘买看收盘价/昨收，开盘买看开盘价/昨收。"""
	if BUY_FILTER_MODE == BUY_FILTER_PCT_THRESHOLD:
		return is_buy_day_blocked_pct_threshold(row, buy_off, buy_kind)
	return is_buy_day_blocked_up_band(row, buy_off, buy_kind)


def is_limit_skip_row(row: pd.Series) -> bool:
	"""信号池：T 日收盘价/昨收不满足流动性则整行不进可买信号。"""
	return is_buy_day_blocked(row, 0, "close")


def load_yidong(path: Path) -> pd.DataFrame:
	df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
	df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)
	df["T日"] = df["T日"].map(_norm_date)
	df["上榜日"] = df["上榜日"].map(_norm_date)
	df["F"] = pd.to_numeric(df["监控日涨幅偏离值"], errors="coerce")
	df["G"] = pd.to_numeric(df["当日是否成功卡异动"], errors="coerce")
	return df


def build_g_zero(df: pd.DataFrame) -> set[tuple[str, str]]:
	out: set[tuple[str, str]] = set()
	for _, r in df.iterrows():
		if r["G"] == 0 and r["T日"]:
			out.add((str(r["股票代码"]), str(r["T日"])))
	return out


def build_code_trade_dates(df: pd.DataFrame) -> dict[str, list[str]]:
	dates: dict[str, set[str]] = defaultdict(set)
	for _, r in df.iterrows():
		t = str(r["T日"])
		if t:
			dates[str(r["股票代码"])].add(t)
	return {k: sorted(v) for k, v in dates.items()}


def trade_date_at_offset(code: str, t0: str, off: int, code_dates: dict[str, list[str]]) -> str | None:
	ds = code_dates.get(code, [])
	if t0 not in ds:
		return None
	i = ds.index(t0)
	j = i + off
	if j >= len(ds):
		return None
	return ds[j]


def rule_buy_spec(rule_id: str | None) -> tuple[int, str] | None:
	"""返回 (buy_off, buy_kind)。"""
	if rule_id in FIXED_RULE_SPECS:
		boff, kind, _ = FIXED_RULE_SPECS[rule_id]
		return boff, kind
	if rule_id == "default":
		return 0, "close"
	return None


def rule_fixed_hold_days(rule_id: str) -> int:
	if rule_id in FIXED_RULE_SPECS:
		boff, _, sell_off = FIXED_RULE_SPECS[rule_id]
		return sell_off - boff
	return 0


def planned_buy_calendar(
	row: pd.Series, code_dates: dict[str, list[str]], rule_id: str | None = None
) -> str | None:
	"""计划买入的日历日（用于排序与同日禁买检查）。"""
	rid = rule_id if rule_id is not None else f_trade_rule(row.get("F"))
	spec = rule_buy_spec(rid)
	if spec is None:
		return None
	buy_off, _ = spec
	code = str(row["股票代码"])
	t_day = str(row["T日"])
	if buy_off == 0:
		return t_day if t_day else None
	return trade_date_at_offset(code, t_day, buy_off, code_dates)


def hold_calendar_days(
	code: str, buy_cal: str, sell_cal: str, code_dates: dict[str, list[str]]
) -> list[str]:
	"""持仓区间日历日（含买入日与卖出日）。"""
	buy_cal = _norm_date(buy_cal)
	sell_cal = _norm_date(sell_cal)
	if not buy_cal:
		return []
	if not sell_cal:
		return [buy_cal]
	ds = code_dates.get(code, [])
	if buy_cal in ds and sell_cal in ds:
		i, j = ds.index(buy_cal), ds.index(sell_cal)
		if i > j:
			i, j = j, i
		return ds[i : j + 1]
	return [buy_cal] if buy_cal == sell_cal else [buy_cal, sell_cal]


def build_f_block_keys(df: pd.DataFrame) -> set[tuple[str, str]]:
	"""同 T日+代码：任一行 F∈SKIP_F → 该键当日整键不买。"""
	blocked: set[tuple[str, str]] = set()
	for _, r in df.iterrows():
		if pd.isna(r["F"]) or int(r["F"]) not in SKIP_F:
			continue
		t, c = str(r["T日"]), str(r["股票代码"])
		if t and c:
			blocked.add((t, c))
	return blocked


def collect_signals(df: pd.DataFrame, *, skip_limit: bool = True) -> pd.DataFrame:
	blocked = build_f_block_keys(df)
	mask = (
		df["T日_收盘"].astype(str).str.strip().ne("")
		& df["G"].eq(1)
		& ~df.apply(lambda r: (str(r["T日"]), str(r["股票代码"])) in blocked, axis=1)
	)
	if skip_limit:
		mask &= ~df.apply(is_limit_skip_row, axis=1)
	mask &= ~df["F"].isin(NO_TRADE_F)
	return df.loc[mask].copy().reset_index(drop=True)


def f_trade_rule(f_val) -> str | None:
	"""F7 T+2开持1; F10 T+1开持1; F8/F30 T+1开持3; F9/F27/F28 T+1开持2; 其余原规则; F1-6 整键不买。"""
	if pd.isna(f_val):
		return "default"
	f = int(f_val)
	if f in SKIP_F or f in NO_TRADE_F:
		return None
	if f == 7:
		return "fix_t2o_t3c"
	if f == 10:
		return "fix_t1o_t2c"
	if f in (8, 30):
		return "fix_t1o_t4c"
	if f in (9, 27, 28):
		return "fix_t1o_t3c"
	return "default"


def _rule_label(rule_id: str) -> str:
	return {
		"fix_t1o_t2c": "F10:T+1开买持1天",
		"fix_t1o_t3c": "F9/F27/F28:T+1开买持2天",
		"fix_t1o_t4c": "F8/F30:T+1开买持3天",
		"fix_t2o_t3c": "F7:T+2开买持1天",
		"fix_t2o_t4c": "F7:T+2开买持2天",
		"default": "其余:T日开盘买+日历锚8%止损T+2起T+6兜底",
	}.get(rule_id, rule_id)


def is_sell_liquidity_blocked(row: pd.Series, off: int) -> bool:
	"""卖出日处于跌幅带内视为跌停流动性不足，收盘无法卖出。"""
	return is_day_in_limit_down_band(row, off)


def _close_sell_quote(
	row: pd.Series,
	off: int,
	code: str,
	t_day: str,
	code_dates: dict[str, list[str]],
	reason: str,
) -> tuple[float, str, str] | None:
	c = _num(row.get(_day_col(off, "收盘")))
	if c is None:
		return None
	td = trade_date_at_offset(code, t_day, off, code_dates) or ("T+%d" % off)
	return c, td, reason


def _try_plate_close_sell(
	row: pd.Series,
	off: int,
	code: str,
	t_day: str,
	code_dates: dict[str, list[str]],
	reason: str,
) -> tuple[float, str, str] | None:
	"""计划卖出日：非跌停则当日收盘卖；跌停则顺延至次日收盘卖（不再继续往后找）。"""
	if not is_sell_liquidity_blocked(row, off):
		return _close_sell_quote(row, off, code, t_day, code_dates, reason)
	next_off = off + 1
	if next_off > MAX_DATA_DAY:
		return None
	defer_reason = "%s(跌停顺延次日收盘)" % reason
	return _close_sell_quote(row, next_off, code, t_day, code_dates, defer_reason)


def _g0_hit(
	row: pd.Series,
	off: int,
	code: str,
	t_day: str,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
) -> bool:
	td = trade_date_at_offset(code, t_day, off, code_dates)
	return bool(td and (code, td) in g_zero)


def _try_g0_sell(
	row: pd.Series,
	off: int,
	code: str,
	t_day: str,
	code_dates: dict[str, list[str]],
	g_zero: set[tuple[str, str]],
	*,
	buy_off: int,
) -> tuple[float, str, str] | None:
	"""G=0 强平：买入日触发则 A 股 T+1 顺延至下一交易日收盘卖（默认）。"""
	if not _g0_hit(row, off, code, t_day, g_zero, code_dates):
		return None
	if G0_DEFER_BUY_DAY_TO_NEXT_CLOSE and off == buy_off:
		defer_off = off + 1
		if defer_off > MAX_DATA_DAY:
			return None
		return _try_plate_close_sell(
			row, defer_off, code, t_day, code_dates, G0_BUY_DAY_DEFER_REASON,
		)
	return _try_plate_close_sell(row, off, code, t_day, code_dates, "G0强平")


def _buy_px(row: pd.Series, buy_off: int, buy_kind: str) -> float | None:
	if buy_kind == "open":
		return _num(row.get(_day_col(buy_off, "开盘")))
	return _num(row.get(_day_col(buy_off, "收盘")))


def _row_ma(row: pd.Series, off: int, period: int) -> float | None:
	return _parse_float(row.get(_day_col(off, "MA%d" % period)))


def _ma_break_reason_at_close(row: pd.Series, off: int) -> str | None:
	"""尾盘收盘价跌破 MA5 或 MA10（数据源已预计算）。"""
	c = _num(row.get(_day_col(off, "收盘")))
	if c is None:
		return None
	tags: list[str] = []
	ma5 = _row_ma(row, off, 5)
	ma10 = _row_ma(row, off, 10)
	if ma5 is not None and c < ma5 - 1e-9:
		tags.append("MA5")
	if ma10 is not None and c < ma10 - 1e-9:
		tags.append("MA10")
	if not tags:
		return None
	return "破位%s尾盘" % "/".join(tags)


def rule_max_sell_off(rule_id: str) -> int | None:
	spec = rule_buy_spec(rule_id)
	if spec is None:
		return None
	buy_off, _ = spec
	return buy_off + rule_fixed_hold_days(rule_id)


def _simulate_fixed_sell(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
	*,
	buy_off: int,
	buy_kind: str,
	sell_off: int,
	rule_id: str,
	exit_mode: str = EXIT_MODE_TIME,
) -> dict | None:
	if is_buy_day_blocked(row, buy_off, buy_kind):
		return None
	buy_px = _buy_px(row, buy_off, buy_kind)
	if buy_px is None or sell_off > MAX_DATA_DAY:
		return None

	code = str(row["股票代码"])
	t_day = str(row["T日"])
	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []

	loop_start = buy_off if G0_DEFER_BUY_DAY_TO_NEXT_CLOSE else buy_off + 1
	for off in range(loop_start, MAX_DATA_DAY + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			break
		hold_lows.append(lo)

		res = _try_g0_sell(
			row, off, code, t_day, code_dates, g_zero, buy_off=buy_off,
		)
		if res:
			sell_px, sell_day, reason = res
			break

		if exit_mode == EXIT_MODE_MA_BREAK:
			br = _ma_break_reason_at_close(row, off)
			if br:
				res = _try_plate_close_sell(row, off, code, t_day, code_dates, br)
				if res:
					sell_px, sell_day, reason = res
					break
				continue

		if off == sell_off:
			hold_n = sell_off - buy_off
			base = "持%d天T+%d收盘" % (hold_n, sell_off)
			if exit_mode == EXIT_MODE_MA_BREAK:
				base = "未破位持%d天T+%d收盘" % (hold_n, sell_off)
			res = _try_plate_close_sell(row, sell_off, code, t_day, code_dates, base)
			if res:
				sell_px, sell_day, reason = res
				break

	if sell_px is None:
		return None

	buy_cal = (
		trade_date_at_offset(code, t_day, buy_off, code_dates)
		if buy_off > 0
		else t_day
	)
	return _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		buy_cal=buy_cal or t_day,
		reason=reason,
		rule_id=rule_id,
		hold_lows=hold_lows,
		t_day=t_day,
	)


def _simulate_from_buy_anchor(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
	*,
	buy_off: int,
	buy_kind: str,
	rule_id: str,
	stop_pct: float = STOP_PCT,
	stop_rel: int = STOP_MIN_DAY,
	fallback_rel: int = FROM_BUY_FALLBACK,
) -> dict | None:
	buy_px = _buy_px(row, buy_off, buy_kind)
	if buy_px is None:
		return None

	code = str(row["股票代码"])
	t_day = str(row["T日"])
	stop_line = buy_px * (1.0 - stop_pct / 100.0)
	first_stop_off = buy_off + stop_rel
	last_off = min(buy_off + fallback_rel, MAX_DATA_DAY)

	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []

	for off in range(buy_off + 1, last_off + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			return None
		hold_lows.append(lo)

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

	buy_cal = (
		trade_date_at_offset(code, t_day, buy_off, code_dates)
		if buy_off > 0
		else t_day
	)
	return _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		buy_cal=buy_cal or t_day,
		reason=reason,
		rule_id=rule_id,
		hold_lows=hold_lows,
		t_day=t_day,
	)


def _pack_trade(
	row: pd.Series,
	*,
	buy_px: float,
	sell_px: float,
	sell_day: str,
	buy_cal: str,
	reason: str,
	rule_id: str,
	hold_lows: list[float | None],
	t_day: str,
) -> dict | None:
	ret_pct = (sell_px / buy_px - 1.0) * 100.0
	shares = int(CAP_PER_STOCK / buy_px / 100.0) * 100
	if shares < 100:
		return None
	buy_amt = round(shares * buy_px, 2)
	sell_amt = round(shares * sell_px, 2)
	return {
		"策略": STRATEGY_NAME,
		"买卖规则": _rule_label(rule_id),
		"开仓日": t_day,
		"买入日": _norm_date(buy_cal) or buy_cal,
		"股票代码": str(row["股票代码"]),
		"股票名称": str(row.get("股票名称", "")),
		"监控日涨幅偏离值F": int(row["F"]) if pd.notna(row["F"]) else "",
		"买入价": round(buy_px, 4),
		"卖出日": sell_day,
		"卖出价": round(sell_px, 4),
		"卖出原因": reason,
		"收益率%": round(ret_pct, 4),
		"收益金额": round(sell_amt - buy_amt, 2),
		"买入股数": int(shares),
		"买入金额": buy_amt,
		"卖出金额": sell_amt,
		"持仓最大回撤%": _holding_mae_pct(buy_px, hold_lows),
		"T日涨跌幅%": _num(row.get("T日涨跌幅%")),
	}


def _holding_mae_pct(buy_px: float, lows: list[float | None]) -> float:
	worst = 0.0
	for lo in lows:
		if lo is None or lo <= 0:
			continue
		dd = (buy_px - lo) / buy_px * 100.0
		if dd > worst:
			worst = dd
	return round(worst, 4)


def simulate_trade(
	row: pd.Series,
	g_zero: set[tuple[str, str]],
	code_dates: dict[str, list[str]],
	*,
	exit_mode: str = EXIT_MODE_TIME,
) -> dict | None:
	rule = f_trade_rule(row.get("F"))
	if rule is None:
		return None
	if rule in FIXED_RULE_SPECS:
		boff, kind, sell_off = FIXED_RULE_SPECS[rule]
		return _simulate_fixed_sell(
			row, g_zero, code_dates,
			buy_off=boff, buy_kind=kind, sell_off=sell_off,
			rule_id=rule, exit_mode=exit_mode,
		)

	if is_buy_day_blocked(row, 0, "open"):
		return None
	buy_px = _num(row.get("T日_开盘"))
	if buy_px is None:
		return None
	code = str(row["股票代码"])
	t_day = str(row["T日"])
	stop_line = buy_px * (1.0 - STOP_PCT / 100.0)

	sell_px: float | None = None
	sell_day = ""
	reason = ""
	hold_lows: list[float | None] = []
	stop_active = False
	last_off = min(MAX_SELL_DAY, MAX_DATA_DAY)
	buy_off = 0

	if G0_DEFER_BUY_DAY_TO_NEXT_CLOSE:
		res = _try_g0_sell(
			row, 0, code, t_day, code_dates, g_zero, buy_off=buy_off,
		)
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

		res = _try_g0_sell(
			row, off, code, t_day, code_dates, g_zero, buy_off=buy_off,
		)
		if res:
			sell_px, sell_day, reason = res
			break

		if off >= STOP_MIN_DAY and lo is not None and lo <= stop_line + 1e-9:
			stop_active = True

		if stop_active:
			base = "止损%d%%(T+%d收盘)" % (int(STOP_PCT), off)
			res = _try_plate_close_sell(row, off, code, t_day, code_dates, base)
			if res:
				sell_px, sell_day, reason = res
				break
			continue

		if off == last_off:
			base = "未触发止损 T+%d收盘" % last_off
			res = _try_plate_close_sell(row, last_off, code, t_day, code_dates, base)
			if res:
				sell_px, sell_day, reason = res
				break

	if sell_px is None:
		return None

	return _pack_trade(
		row,
		buy_px=buy_px,
		sell_px=sell_px,
		sell_day=sell_day,
		buy_cal=t_day,
		reason=reason,
		rule_id="default",
		hold_lows=hold_lows,
		t_day=t_day,
	)


def _buy_filter_doc() -> dict:
	if BUY_FILTER_MODE == BUY_FILTER_PCT_THRESHOLD:
		return {
			"模式": "跌幅带不买且涨幅超阈值不买",
			"60/00": "[-10%,-8%]不买; 涨幅>+8%不买",
			"68/30": "[-30%,-15%]不买; 涨幅>+15%不买",
			"过滤时点": "T日信号池过滤一次; 实际买入日再过滤一次",
			"T日信号池": "T日收盘价/昨收",
			"收盘买": "买入日收盘价/昨收",
			"开盘买": "买入日开盘价/昨收",
		}
	return {
		"模式": "涨幅带不买",
		"60/00": "[8%,10%]",
		"68/30": "[15%,30%]",
		"收盘买": "买入日收盘价/昨收涨幅在带内不买",
		"开盘买": "买入日开盘价/昨收涨幅在带内不买",
		"T日信号": "T日收盘价/昨收涨幅在带内整行不买",
	}


def _buy_filter_summary() -> str:
	if BUY_FILTER_MODE == BUY_FILTER_PCT_THRESHOLD:
		return "T日信号池+实际买入日双重过滤(跌幅带+涨幅阈值); G=0强平贯穿"
	return "仅涨幅带过滤买入; 带外可买; G=0强平贯穿所有规则"


def run_backtest(
	df: pd.DataFrame,
	*,
	same_day_no_buy: bool = False,
	exit_mode: str = EXIT_MODE_TIME,
) -> tuple[pd.DataFrame, dict]:
	g_zero = build_g_zero(df)
	code_dates = build_code_trade_dates(df)
	blocked = build_f_block_keys(df)
	signals = collect_signals(df, skip_limit=True)
	skip_stats = {
		"总行数": len(df),
		"F阻断键数_T日加代码": len(blocked),
		"可买信号_行数": len(signals),
		"F跳过集合": sorted(SKIP_F),
		"信号规则": "同T日+代码任一行F在跳过集则整键不买; 其余G=1行可买; 不去重; 分F档买卖",
		"F分档规则": {
			"不买F_整键": sorted(SKIP_F),
			"不做F_行级": sorted(NO_TRADE_F),
			"F7": "T+2开盘买 持1天(T+3收盘卖)",
			"F10": "T+1开盘买 持1天(T+2收盘卖)",
			"F8_F30": "T+1开盘买 持3天(T+4收盘卖)",
			"F9_F27_F28": "T+1开盘买 持2天(T+3收盘卖)",
			"其他含25_26_29": "T开盘买 日历锚8%止损T+2起 T+6兜底",
			"买入流动性": _buy_filter_doc(),
		},
		"涨跌停跳过规则": _buy_filter_summary(),
		"G0强平": "买入日触发G=0则A股T+1顺延至下一交易日收盘卖; 其余G=0当日收盘卖",
		"卖出流动性": "卖出日收盘价/昨收处于跌幅带内视为跌停卖不出，顺延至次日收盘卖",
		"卖出模式": {
			"time": "持满计划天数收盘卖",
			"ma_break": "持仓期尾盘收盘<MA5或<MA10则卖,否则持满2天",
		}.get(exit_mode, exit_mode),
		"同日禁买": same_day_no_buy,
	}
	if same_day_no_buy:
		skip_stats["同日禁买说明"] = "任一持仓日或卖出日当天不再开新仓(按买入日排序撮合)"

	trades: list[dict] = []
	fail = defaultdict(int)
	busy_days: set[str] = set()

	plan_rows: list[tuple[str, int, pd.Series]] = []
	for idx, row in signals.iterrows():
		pb = planned_buy_calendar(row, code_dates)
		if not pb:
			fail["no_buy_date"] += 1
			continue
		plan_rows.append((pb, int(idx), row))
	plan_rows.sort(key=lambda x: (x[0], x[1]))

	for buy_planned, _, row in plan_rows:
		if same_day_no_buy and buy_planned in busy_days:
			fail["buy_day_busy"] += 1
			continue
		t = simulate_trade(row, g_zero, code_dates, exit_mode=exit_mode)
		if t is None:
			fail["sim_fail"] += 1
			continue
		if not same_day_no_buy:
			trades.append(t)
			continue
		code = str(row["股票代码"])
		buy_cal = str(t.get("买入日", buy_planned))
		sell_cal = _norm_date(t.get("卖出日", "")) or str(t.get("卖出日", ""))
		if buy_cal in busy_days:
			fail["buy_day_busy"] += 1
			continue
		for d in hold_calendar_days(code, buy_cal, sell_cal, code_dates):
			busy_days.add(d)
		trades.append(t)

	tdf = pd.DataFrame(trades)
	if tdf.empty:
		return tdf, {"说明": "无成交", "跳过统计": skip_stats, "失败": dict(fail)}

	hold_lens: list[int] = []
	for _, tr in tdf.iterrows():
		code = str(tr["股票代码"])
		buy_cal = _norm_date(tr.get("买入日", ""))
		sell_cal = _norm_date(tr.get("卖出日", ""))
		days = hold_calendar_days(code, buy_cal, sell_cal, code_dates)
		hold_lens.append(max(len(days) - 1, 0) if days else 0)
	tdf = tdf.copy()
	tdf["持有交易日数"] = hold_lens

	rets = tdf["收益率%"].astype(float).values
	buy_days = tdf["开仓日"].astype(str).tolist()
	ext = compute_extended_metrics(rets, buy_days)
	wins = int((rets > 0).sum())
	n = len(rets)
	nav = float(np.prod(1.0 + rets[np.argsort(buy_days)] / 100.0))

	reason_dist = tdf["卖出原因"].value_counts().to_dict()
	summary = {
		"策略": STRATEGY_NAME,
		"说明": "F7/F10/F8/F30/F9/F27/F28分档; F1-6整键不买; T日+买入日双重涨跌幅过滤; 无同日禁买; G0; 单票10万",
		"单票上限_元": CAP_PER_STOCK,
		"成交笔数": n,
		"胜率_pct": round(100.0 * wins / n, 4),
		"单笔平均收益_pct": round(float(np.mean(rets)), 4),
		"中位收益_pct": round(float(np.median(rets)), 4),
		"合计收益_线性加总_pct": round(float(np.sum(rets)), 4),
		"合计收益金额_元": round(float(tdf["收益金额"].sum()), 2),
		"净值_顺序复利": round(nav, 6),
		"单笔最差_pct": round(float(np.min(rets)), 4),
		"持仓回撤均_pct": round(float(tdf["持仓最大回撤%"].mean()), 4),
		"卖出原因分布": reason_dist,
		"跳过统计": skip_stats,
		"失败": dict(fail),
		**{k: ext.get(k) for k in ("盈亏比_均盈除以均亏绝对值", "最大回撤_链式净值_pct")},
	}
	return tdf, summary
