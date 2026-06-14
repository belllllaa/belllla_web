# -*- coding: utf-8
"""异动监管回测：T 收盘买 + 止损 8% T+2 起 + G0 + T+6 兜底。"""

from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pandas as pd

from dafengniu_benchmark_ref_trades import compute_extended_metrics
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV

SKIP_F = {1, 2, 3, 10, 30}
MAX_SELL_DAY = 7
DEFAULT_CAP = 100_000.0


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
	s = str(v).strip()[:10]
	return s if len(s) == 10 else ""


def _code6(v) -> str:
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return ""
	if isinstance(v, (int, float)) and not isinstance(v, bool):
		n = int(round(float(v)))
		return "" if n <= 0 else str(n).zfill(6)[:6]
	s = str(v).strip().split(".")[0]
	digits = re.sub(r"\D", "", s)
	if not digits:
		return ""
	n = int(digits)
	return "" if n <= 0 else str(n).zfill(6)[:6]


def board_group(code: str) -> str:
	"""upper=主板60/00；lower=科创创业68/30；other=其余。"""
	c = _code6(code)
	if not c:
		return "other"
	if c.startswith(("60", "00")):
		return "main_60_00"
	if c.startswith(("68", "30")):
		return "growth_68_30"
	return "other"


def _load(path) -> pd.DataFrame:
	df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
	df["股票代码"] = df["股票代码"].map(_code6)
	df["T日"] = df["T日"].map(_norm_date)
	if "上榜日" in df.columns:
		df["上榜日"] = df["上榜日"].map(_norm_date)
	else:
		df["上榜日"] = df["T日"]
	df["F"] = pd.to_numeric(df["监控日涨幅偏离值"], errors="coerce")
	df["G"] = pd.to_numeric(df["当日是否成功卡异动"], errors="coerce")
	df["T日涨跌幅%"] = pd.to_numeric(df.get("T日涨跌幅%"), errors="coerce")
	return df


def _limit_threshold(code: str, name: str) -> float:
	nm = str(name).upper()
	if "ST" in nm:
		return 4.9
	if code.startswith(("300", "301", "688")):
		return 19.9
	if code.startswith(("8", "43", "92")):
		return 29.9
	return 9.9


def _is_limit_up_down(r: pd.Series) -> bool:
	chg = r.get("T日涨跌幅%")
	if pd.isna(chg):
		return False
	lim = _limit_threshold(r["股票代码"], r.get("股票名称", ""))
	return float(chg) >= lim or float(chg) <= -lim


def _t_day_pct_band_skip(r: pd.Series) -> bool:
	"""60/00：|T涨跌幅|>8% 不买；68/30：|T涨跌幅|>15% 不买。"""
	chg = r.get("T日涨跌幅%")
	if pd.isna(chg):
		return False
	chg = float(chg)
	code = r["股票代码"]
	if code.startswith(("60", "00")):
		return chg > 8.0 or chg < -8.0
	if code.startswith(("68", "30")):
		return chg > 15.0 or chg < -15.0
	return False


_SSE_CAL: list | None = None


def _get_sse_cal() -> list:
	global _SSE_CAL
	if _SSE_CAL is None:
		from excel_dafengniu_to_manual_csv import _load_sse_trade_dates

		_SSE_CAL = _load_sse_trade_dates()
	return _SSE_CAL


def _build_g_zero(df: pd.DataFrame) -> set[tuple[str, str]]:
	out: set[tuple[str, str]] = set()
	for _, r in df.iterrows():
		if r["G"] != 0:
			continue
		c = r["股票代码"]
		for d in (r["T日"], r["上榜日"]):
			if d:
				out.add((c, d))
	return out


def _date_at_offset(t0: str, off: int, cal: list) -> str:
	if not t0 or off < 0:
		return ""
	try:
		t = datetime.strptime(t0[:10], "%Y-%m-%d").date()
	except ValueError:
		return ""
	i0 = None
	for j, td in enumerate(cal):
		if td >= t:
			i0 = j
			break
	if i0 is None:
		return ""
	j = i0 + off
	if j >= len(cal):
		return ""
	return cal[j].strftime("%Y-%m-%d")


def _px(r: pd.Series, off: int, kind: str) -> float | None:
	prefix = "T日" if off == 0 else "T+%d日" % off
	col = "%s_%s" % (prefix, "开盘" if kind == "open" else "收盘")
	return _num(r.get(col))


def _pxhlc(r: pd.Series, off: int) -> tuple[float | None, float | None, float | None, float | None]:
	prefix = "T日" if off == 0 else "T+%d日" % off
	return (
		_num(r.get("%s_开盘" % prefix)),
		_num(r.get("%s_最高" % prefix)),
		_num(r.get("%s_最低" % prefix)),
		_num(r.get("%s_收盘" % prefix)),
	)


def _has_prices(r: pd.Series, sell_day: int, sell_kind: str) -> bool:
	if _px(r, 0, "close") is None:
		return False
	if _px(r, sell_day, sell_kind) is None:
		return False
	return True


def _sell_day_offset(t: dict, sse_cal: list) -> int | None:
	r = t.get("卖出原因", "")
	m = re.search(r"T\+(\d+)", r)
	if m:
		return int(m.group(1))
	if "G0" in r:
		t0 = t.get("T日", "")
		sd = t.get("卖出日", "")
		for d in range(1, MAX_SELL_DAY + 1):
			if _date_at_offset(t0, d, sse_cal) == sd:
				return d
	return None


def _holding_mae_pct(r: pd.Series, entry: float, end_d: int) -> float | None:
	if entry <= 0 or end_d < 1:
		return None
	lows: list[float] = []
	for d in range(1, end_d + 1):
		_, _, low, _ = _pxhlc(r, d)
		if low is not None:
			lows.append(low)
	if not lows:
		return None
	return round(max(0.0, (entry - min(lows)) / entry * 100.0), 4)


def _cumulative_max_dd_pct(trades: list[dict]) -> float | None:
	if not trades:
		return None
	s = sorted(trades, key=lambda x: x.get("T日", ""))
	eq = 100.0 + pd.Series([t["收益率%"] for t in s]).cumsum()
	peak = eq.cummax()
	dd_pts = peak - eq
	pmax = float(peak.max())
	if pmax <= 0:
		return 0.0
	return round(float(dd_pts.max()) / pmax * 100.0, 2)


def enrich_trade_drawdown(r: pd.Series, t: dict, sse_cal: list) -> dict:
	end_d = _sell_day_offset(t, sse_cal)
	if end_d is not None:
		mae = _holding_mae_pct(r, float(t["买入价"]), end_d)
		if mae is not None:
			t["持仓最大回撤%"] = mae
	return t


def build_f_block_keys(df: pd.DataFrame) -> set[tuple[str, str]]:
	blocked: set[tuple[str, str]] = set()
	for _, r in df.iterrows():
		if pd.isna(r["F"]) or int(r["F"]) not in SKIP_F:
			continue
		t, c = r["T日"], r["股票代码"]
		if t and c:
			blocked.add((str(t), str(c)))
	return blocked


def _eligible(
	r: pd.Series,
	blocked: set[tuple[str, str]],
	*,
	skip_limit: bool = True,
) -> bool:
	if r["G"] != 1:
		return False
	if (str(r["T日"]), str(r["股票代码"])) in blocked:
		return False
	if not r["T日"] or _px(r, 0, "close") is None:
		return False
	if skip_limit and _is_limit_up_down(r):
		return False
	if _t_day_pct_band_skip(r):
		return False
	return True


def simulate_stop_loss(
	r: pd.Series,
	g_zero: set[tuple[str, str]],
	sse_cal: list,
	*,
	stop_pct: float = 8.0,
	max_day: int = MAX_SELL_DAY,
	fallback_day: int = 6,
	min_day: int = 2,
	sell_kind: str = "close",
) -> dict | None:
	if fallback_day < 1 or fallback_day > MAX_SELL_DAY:
		return None
	if not _has_prices(r, fallback_day, sell_kind):
		return None
	entry = _px(r, 0, "close")
	if entry is None or entry <= 0:
		return None
	code = r["股票代码"]
	t0 = r["T日"]
	stop_px = entry * (1.0 - stop_pct / 100.0)

	exit_px = None
	exit_reason = None
	exit_date = ""

	for d in range(1, max_day + 1):
		dt = _date_at_offset(t0, d, sse_cal)
		if not dt:
			return None
		if (code, dt) in g_zero:
			exit_px = _px(r, d, "close")
			exit_reason = "G0强平"
			exit_date = dt
			if exit_px is None:
				return None
			break
		if d < min_day:
			continue
		_, _, low, close = _pxhlc(r, d)
		if low is not None and low <= stop_px:
			exit_px = close if close is not None else stop_px
			exit_reason = "止损%.0f%%(T+%d收盘)" % (stop_pct, d)
			exit_date = dt
			break

	if exit_px is None:
		dt = _date_at_offset(t0, fallback_day, sse_cal)
		if not dt:
			return None
		exit_px = _px(r, fallback_day, sell_kind)
		exit_reason = "未触发止损 T+%d%s" % (
			fallback_day,
			"开盘" if sell_kind == "open" else "收盘",
		)
		exit_date = dt
		if exit_px is None:
			return None

	ret_pct = (exit_px / entry - 1.0) * 100.0
	return {
		"代码": code,
		"名称": r.get("股票名称", ""),
		"T日": t0,
		"买入价": round(entry, 4),
		"卖出价": round(exit_px, 4),
		"收益率%": round(ret_pct, 4),
		"卖出原因": exit_reason,
		"卖出日": exit_date,
		"F": int(r["F"]) if not pd.isna(r["F"]) else "",
		"板块": board_group(code),
	}


def _collect_signals(df: pd.DataFrame, *, skip_limit: bool = True) -> list[tuple[str, pd.Series]]:
	blocked = build_f_block_keys(df)
	out: list[tuple[str, pd.Series]] = []
	for _, r in df.iterrows():
		if not _eligible(r, blocked, skip_limit=skip_limit):
			continue
		out.append((str(r["T日"]), r))
	out.sort(key=lambda x: (x[0], str(x[1]["股票代码"])))
	return out


def run_stop_loss_trades(
	df: pd.DataFrame,
	*,
	skip_limit: bool = True,
	stop_pct: float = 8.0,
	min_day: int = 2,
	fallback_day: int = 6,
) -> tuple[list[dict], dict]:
	g_zero = _build_g_zero(df)
	sse_cal = _get_sse_cal()
	blocked = build_f_block_keys(df)
	stats = {
		"表内行数": len(df),
		"F阻断键数_T日加代码": len(blocked),
		"行级F在跳过集": 0,
		"G非1": 0,
		"T涨跌停": 0,
		"T涨跌幅带": 0,
		"无行情": 0,
	}
	for _, r in df.iterrows():
		if pd.isna(r["F"]) or int(r["F"]) in SKIP_F:
			stats["行级F在跳过集"] += 1
		elif r["G"] != 1:
			stats["G非1"] += 1
		elif skip_limit and _is_limit_up_down(r):
			stats["T涨跌停"] += 1
		elif _t_day_pct_band_skip(r):
			stats["T涨跌幅带"] += 1

	trades: list[dict] = []
	for _, r in _collect_signals(df, skip_limit=skip_limit):
		t = simulate_stop_loss(
			r,
			g_zero,
			sse_cal,
			stop_pct=stop_pct,
			min_day=min_day,
			fallback_day=fallback_day,
		)
		if t:
			trades.append(enrich_trade_drawdown(r, t, sse_cal))
		else:
			stats["无行情"] += 1
	stats["可买信号"] = len(_collect_signals(df, skip_limit=skip_limit))
	stats["成交笔数"] = len(trades)
	return trades, stats


def trades_to_capital_rows(
	trades: list[dict],
	cap_per_stock: float = DEFAULT_CAP,
) -> list[dict]:
	rows: list[dict] = []
	for i, t in enumerate(trades, 1):
		buy_px = float(t["买入价"])
		sell_px = float(t["卖出价"])
		shares = int(cap_per_stock / buy_px / 100.0) * 100
		if shares < 100:
			continue
		buy_amt = round(shares * buy_px, 2)
		sell_amt = round(shares * sell_px, 2)
		pnl = round(sell_amt - buy_amt, 2)
		ret_pct = (sell_px / buy_px - 1.0) * 100.0
		rows.append(
			{
				"序号": i,
				"板块": t.get("板块", ""),
				"股票代码": t.get("代码", ""),
				"股票名称": t.get("名称", ""),
				"开仓日": t.get("T日", ""),
				"买入日": t.get("T日", ""),
				"买入价": buy_px,
				"卖出日": t.get("卖出日", ""),
				"卖出价": sell_px,
				"卖出原因": t.get("卖出原因", ""),
				"买入股数": shares,
				"买入金额": buy_amt,
				"卖出金额": sell_amt,
				"单笔收益率%": round(ret_pct, 4),
				"单笔收益金额": pnl,
				"F": t.get("F", ""),
				"持仓最大回撤%": t.get("持仓最大回撤%", ""),
				"资金占用%": round(buy_amt / cap_per_stock * 100.0, 2),
			}
		)
	return rows


def summarize_capital(rows: list[dict], label: str) -> dict:
	if not rows:
		return {"标签": label, "成交笔数": 0}
	df = pd.DataFrame(rows)
	rets = df["单笔收益率%"].astype(float).values
	days = df["买入日"].astype(str).tolist()
	ext = compute_extended_metrics(rets, days)
	wins = int((df["单笔收益金额"] > 0).sum())
	eq = df.sort_values("买入日")["单笔收益金额"].cumsum()
	peak = eq.cummax()
	dd_amt = float((peak - eq).max()) if len(eq) else 0.0
	return {
		"标签": label,
		"策略": "止损8%_T+2起",
		"成交笔数": len(df),
		"盈利笔数": wins,
		"亏损笔数": int((df["单笔收益金额"] < 0).sum()),
		"胜率%": round(100.0 * wins / len(df), 2),
		"总买入金额": round(float(df["买入金额"].sum()), 2),
		"总卖出金额": round(float(df["卖出金额"].sum()), 2),
		"总收益金额": round(float(df["单笔收益金额"].sum()), 2),
		"总收益率_金额加权%": round(
			100.0 * float(df["单笔收益金额"].sum()) / float(df["买入金额"].sum()), 4
		),
		"平均每笔收益金额": round(float(df["单笔收益金额"].mean()), 2),
		"平均每笔收益率%": round(float(df["单笔收益率%"].mean()), 4),
		"最大单笔盈利": round(float(df["单笔收益金额"].max()), 2),
		"最大单笔亏损": round(float(df["单笔收益金额"].min()), 2),
		"累计收益金额最大回撤": round(dd_amt, 2),
		"链式净值最大回撤%": ext.get("最大回撤_链式净值_pct"),
		"笔收益波动率%": ext.get("波动率_笔收益标准差_pct"),
		"盈亏比": ext.get("盈亏比_均盈除以均亏绝对值"),
	}
