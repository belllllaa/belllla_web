# -*- coding: utf-8 -*-
"""dafengniu 开仓窗口指标：开仓日（含）起连续 6 个交易日（开仓+之后 5 日）OHLC、MA5/MA10，及两项标签逻辑。

供 dafengniu_open_window_metrics.py（AkShare）与 QMT 策略共用同一套口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd


N_WINDOW_DAYS = 6  # 开仓日 + 其后 5 个交易日
DROP_RATIO = -0.09  # 最低价相对前一交易日收盘价跌幅阈值（≤ -9%）


def _norm_date_series(s: pd.Series) -> pd.Series:
	return pd.to_datetime(s).dt.normalize()


@dataclass
class WindowMetrics:
	open_date: str  # YYYYMMDD
	row: dict

	def to_flat_dict(self) -> dict:
		return dict(self.row)


def _pick_open_positions(d: pd.DataFrame, target: datetime.date) -> tuple[int | None, str | None]:
	"""返回开仓日在行情表中的整数行位置（iloc）；若不存在则找首个 >= target 的交易日。"""
	if d is None or d.empty or "date" not in d.columns:
		return None, "empty"
	dd = _norm_date_series(d["date"]).dt.date
	for i in range(len(dd)):
		if dd.iloc[i] == target:
			return i, None
	for i in range(len(dd)):
		if dd.iloc[i] >= target:
			return i, "first_trade_on_or_after_%s" % dd.iloc[i].isoformat()
	return None, "no_bar_on_or_after"


def prev_close_before_open_from_daily(
	d: pd.DataFrame,
	open_yyyymmdd: str,
) -> tuple[float | None, str | None]:
	"""仅求开仓日（或对齐到的首个成交日）前一交易日的收盘价；不要求后视 6 日完整窗口。"""
	if d is None or d.empty:
		return None, "empty"
	try:
		target = datetime.strptime(open_yyyymmdd, "%Y%m%d").date()
	except ValueError:
		return None, "bad_open_date"
	work = d.sort_values("date").reset_index(drop=True)
	if "close" not in work.columns or "date" not in work.columns:
		return None, "missing_col"
	work["close"] = pd.to_numeric(work["close"], errors="coerce")
	work["date"] = _norm_date_series(work["date"])
	pos, hint = _pick_open_positions(work, target)
	if pos is None:
		return None, hint or "no_position"
	if pos <= 0:
		return None, hint or "no_prev_bar"
	pc = work.iloc[pos - 1]["close"]
	if pd.isna(pc):
		return None, "nan_prev_close"
	return float(pc), None


def compute_window_metrics_from_daily(
	d: pd.DataFrame,
	open_yyyymmdd: str,
	code: str,
) -> tuple[WindowMetrics | None, str | None]:
	"""
	d 列：date, open, high, low, close（均为数值；date 可 datetime）
	按日期升序；需包含开仓日前至少 9 个交易日以保证 MA10，窗口内 MA 与行情一致。
	"""
	if d is None or d.empty:
		return None, "empty"
	try:
		target = datetime.strptime(open_yyyymmdd, "%Y%m%d").date()
	except ValueError:
		return None, "bad_open_date"

	work = d.sort_values("date").reset_index(drop=True)
	for col in ("open", "high", "low", "close"):
		if col not in work.columns:
			return None, "missing_%s" % col
		work[col] = pd.to_numeric(work[col], errors="coerce")

	work["date"] = _norm_date_series(work["date"])
	work["ma5"] = work["close"].rolling(5, min_periods=5).mean()
	work["ma10"] = work["close"].rolling(10, min_periods=10).mean()

	pos, hint = _pick_open_positions(work, target)
	if pos is None:
		return None, hint or "no_position"

	if pos + N_WINDOW_DAYS > len(work):
		return None, "short_tail"

	win = work.iloc[pos : pos + N_WINDOW_DAYS]

	# 标签1：开仓日起连续 3 个交易日，每日开盘 > 收盘（实体阴线）
	tag_3_oc = True
	for j in range(min(3, len(win))):
		o = win.iloc[j]["open"]
		c = win.iloc[j]["close"]
		if pd.isna(o) or pd.isna(c) or not (float(o) > float(c)):
			tag_3_oc = False
			break

	# 标签2：窗口内任一交易日，最低价相对「前一交易日收盘价」跌幅 ≤ -9%
	tag_dd9 = False
	for j in range(len(win)):
		row_idx = pos + j
		if row_idx <= 0:
			continue
		prev_c = work.iloc[row_idx - 1]["close"]
		low_j = work.iloc[row_idx]["low"]
		if pd.isna(prev_c) or pd.isna(low_j) or float(prev_c) <= 0:
			continue
		if float(low_j) / float(prev_c) - 1.0 <= DROP_RATIO + 1e-12:
			tag_dd9 = True
			break

	row: dict = {"代码": code, "开仓日": open_yyyymmdd}
	if hint:
		row["日期对齐说明"] = hint

	for k in range(N_WINDOW_DAYS):
		prefix = "D%d" % k
		if k >= len(win):
			row["%s_开盘" % prefix] = ""
			row["%s_收盘" % prefix] = ""
			row["%s_MA5" % prefix] = ""
			row["%s_MA10" % prefix] = ""
			continue
		r = win.iloc[k]
		row["%s_开盘" % prefix] = r["open"]
		row["%s_收盘" % prefix] = r["close"]
		row["%s_MA5" % prefix] = r["ma5"]
		row["%s_MA10" % prefix] = r["ma10"]

	if pos > 0:
		pc = work.iloc[pos - 1]["close"]
		if pd.notna(pc):
			row["D0前收盘"] = round(float(pc), 4)
		else:
			row["D0前收盘"] = ""
	else:
		row["D0前收盘"] = ""

	row["标签_开仓起3交易日皆开盘高于收盘"] = 1 if tag_3_oc else 0
	row["标签_窗口内最低较前收跌超9pct"] = 1 if tag_dd9 else 0

	return WindowMetrics(open_date=open_yyyymmdd, row=row), None


def akshare_hist_to_daily_df(raw: pd.DataFrame) -> pd.DataFrame | None:
	"""AkShare stock_zh_a_hist 原始表 -> 标准列。"""
	if raw is None or raw.empty:
		return None
	cols = list(raw.columns)
	if len(cols) < 6:
		return None
	# 列序：日期 代码 开盘 收盘 最高 最低 …
	out = pd.DataFrame(
		{
			"date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
			"open": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
			"close": pd.to_numeric(raw.iloc[:, 3], errors="coerce"),
			"high": pd.to_numeric(raw.iloc[:, 4], errors="coerce"),
			"low": pd.to_numeric(raw.iloc[:, 5], errors="coerce"),
		}
	)
	out = out.dropna(subset=["date"])
	return out


def yyyymmdd_shift(d8: str, delta_days: int) -> str:
	d = datetime.strptime(d8, "%Y%m%d").date() + timedelta(days=delta_days)
	return d.strftime("%Y%m%d")
