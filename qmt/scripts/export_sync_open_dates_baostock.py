# -*- coding: utf-8 -*-
"""根据 dafengniu_sync_open_dates.csv（code, open_date），用 Baostock 前复权日线导出扩展行情表。

约定：
  · 开仓日 open_date = D0（若当日休市，对齐到其后首个交易日，与 metrics_core 一致）。
  · **D前1**：D0 的前一个交易日的开盘、收盘及当日 MA5/MA10。
  · **D0…D5**：连续 6 个交易日的 OHLC + MA5 + MA10（列为 Dk_MA10,Dk_MA5,Dk_开盘,Dk_收盘,Dk_最低,Dk_最高）。
  · MA 为收盘价在全样本上的 rolling（min_periods 与 metrics_core 一致）。
  · **上证**：上证指数（Baostock `sh.000001`）在 **股票 D0 当日**（与上面对齐后的首个成交日同一日历日）的收盘、MA5、MA10；
    **破位**指当日收盘价 **低于** 对应均线（跌破）。
  · **衍生**：`D0开盘涨跌%` = (D0 开盘 − D前1 收盘) / D前1 收盘 × 100；
    `Dk_高收回撤%`（k=1…5）= (Dk 最高 − Dk 收盘) / Dk 最高 × 100（日内最高相对收盘的回撤幅度）。

依赖：pandas、baostock

用法：
  python qmt/scripts/export_sync_open_dates_baostock.py
  python qmt/scripts/export_sync_open_dates_baostock.py --in path/to/sync.csv --out path/to/out.csv
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_paths import SYNC_OPEN_BAOSTOCK_CSV, SYNC_OPEN_DATES_CSV  # noqa: E402
from dafengniu_metrics_core import (  # noqa: E402
	N_WINDOW_DAYS,
	_norm_date_series,
	_pick_open_positions,
	yyyymmdd_shift,
)

_DEFAULT_IN = SYNC_OPEN_DATES_CSV
_DEFAULT_OUT = SYNC_OPEN_BAOSTOCK_CSV

# 上证指数（Baostock）
_SSE_TS = "sh.000001"


def code6(sym: str) -> str:
	s = str(sym).strip().upper().replace("\u3000", "").strip()
	if "." in s:
		s = s.split(".")[0]
	return s.zfill(6)[:6]


def _baostock_ts(sym: str) -> str:
	c = code6(sym)
	pfx = "sh" if c.startswith("6") else "sz"
	return "%s.%s" % (pfx, c)


def _d8_to_yyyy_mm_dd(d8: str) -> str:
	return "%s-%s-%s" % (d8[:4], d8[4:6], d8[6:8])


def open_date8(x) -> str:
	s = str(x).strip()
	if "." in s and s.replace(".", "").isdigit():
		try:
			v = int(float(s))
			return "%08d" % v if v >= 0 else ""
		except ValueError:
			pass
	s = s.split(".")[0]
	if len(s) >= 8 and s[:8].isdigit():
		return s[:8]
	return ""


def fetch_daily(bs_mod, sym: str, od: str) -> pd.DataFrame | None:
	if not od or len(od) != 8:
		return None
	start = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, -260))
	try:
		od_dt = datetime.strptime(od, "%Y%m%d").date()
	except ValueError:
		return None
	end_dt = max(od_dt + timedelta(days=180), datetime.now().date() + timedelta(days=14))
	end = end_dt.strftime("%Y-%m-%d")
	rs = bs_mod.query_history_k_data_plus(
		_baostock_ts(sym),
		"date,open,high,low,close",
		start_date=start,
		end_date=end,
		frequency="d",
		adjustflag="2",
	)
	if rs.error_code != "0":
		return None
	rows = []
	while rs.error_code == "0" and rs.next():
		rows.append(rs.get_row_data())
	if not rows:
		return None
	bdf = pd.DataFrame(rows, columns=rs.fields)
	for col in ("open", "high", "low", "close"):
		bdf[col] = pd.to_numeric(bdf[col], errors="coerce")
	bdf["date"] = pd.to_datetime(bdf["date"], errors="coerce")
	bdf = bdf.dropna(subset=["date"])
	return bdf if not bdf.empty else None


def fetch_sse_index_daily(bs_mod, min_od: str, max_od: str) -> pd.DataFrame | None:
	"""拉取上证指数日线（前复权 adjustflag=2），区间覆盖 [min_od,max_od] 及前推足够历史以计算 MA10。"""
	if not min_od or len(min_od) != 8 or not max_od or len(max_od) != 8:
		return None
	start = _d8_to_yyyy_mm_dd(yyyymmdd_shift(min_od, -260))
	try:
		max_dt = datetime.strptime(max_od, "%Y%m%d").date()
	except ValueError:
		return None
	end_dt = max(max_dt + timedelta(days=180), datetime.now().date() + timedelta(days=14))
	end = end_dt.strftime("%Y-%m-%d")
	rs = bs_mod.query_history_k_data_plus(
		_SSE_TS,
		"date,open,high,low,close",
		start_date=start,
		end_date=end,
		frequency="d",
		adjustflag="2",
	)
	if rs.error_code != "0":
		return None
	rows = []
	while rs.error_code == "0" and rs.next():
		rows.append(rs.get_row_data())
	if not rows:
		return None
	bdf = pd.DataFrame(rows, columns=rs.fields)
	for col in ("open", "high", "low", "close"):
		bdf[col] = pd.to_numeric(bdf[col], errors="coerce")
	bdf["date"] = pd.to_datetime(bdf["date"], errors="coerce")
	bdf = bdf.dropna(subset=["date"])
	return bdf if not bdf.empty else None


def _prep_work(bdf: pd.DataFrame) -> pd.DataFrame:
	work = bdf.sort_values("date").reset_index(drop=True)
	for col in ("open", "high", "low", "close"):
		work[col] = pd.to_numeric(work[col], errors="coerce")
	work["date"] = _norm_date_series(work["date"])
	work["ma5"] = work["close"].rolling(5, min_periods=5).mean()
	work["ma10"] = work["close"].rolling(10, min_periods=10).mean()
	return work


def _cell_ma(v) -> float | str:
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return ""
	try:
		x = float(v)
	except (TypeError, ValueError):
		return ""
	if pd.isna(x):
		return ""
	return round(x, 2)


def _cell_px(v) -> float | str:
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return ""
	try:
		x = float(v)
	except (TypeError, ValueError):
		return ""
	if pd.isna(x):
		return ""
	return round(x, 4)


def _cell_pct_open_vs_prev(prev_close, open_px) -> float | str:
	"""D0 开盘相对前一交易日收盘价的涨跌幅（%%）。"""
	try:
		p = float(prev_close)
		o = float(open_px)
	except (TypeError, ValueError):
		return ""
	if pd.isna(p) or pd.isna(o) or p == 0:
		return ""
	return round((o - p) / p * 100.0, 2)


def _cell_pct_high_close_drawdown(high_px, close_px) -> float | str:
	"""单日 (最高 − 收盘) / 最高 × 100 %%。"""
	try:
		h = float(high_px)
		c = float(close_px)
	except (TypeError, ValueError):
		return ""
	if pd.isna(h) or pd.isna(c) or h <= 0:
		return ""
	return round((h - c) / h * 100.0, 2)


def _sse_d0_columns(idx_work: pd.DataFrame | None, d0_bar_date) -> dict:
	"""股票 D0 对应交易日在上证指数上的收盘、MA 及是否跌破 MA5/MA10。"""
	empty = {
		"上证_D0_收盘": "",
		"上证_D0_MA5": "",
		"上证_D0_MA10": "",
		"上证_D0破位MA5": "",
		"上证_D0破位MA10": "",
	}
	if idx_work is None or idx_work.empty:
		return empty
	try:
		target_d = pd.Timestamp(d0_bar_date).normalize().date()
	except (TypeError, ValueError):
		return empty
	dd = _norm_date_series(idx_work["date"]).dt.date
	mask = dd == target_d
	if not mask.any():
		return empty
	row = idx_work.loc[mask].iloc[-1]
	c = row.get("close")
	m5 = row.get("ma5")
	m10 = row.get("ma10")
	out = dict(empty)
	out["上证_D0_收盘"] = _cell_px(c)
	out["上证_D0_MA5"] = _cell_ma(m5)
	out["上证_D0_MA10"] = _cell_ma(m10)

	def _break_below(px, ma) -> str:
		if px is None or ma is None:
			return ""
		try:
			a, b = float(px), float(ma)
		except (TypeError, ValueError):
			return ""
		if pd.isna(a) or pd.isna(b):
			return ""
		return "是" if a < b else "否"

	out["上证_D0破位MA5"] = _break_below(c, m5)
	out["上证_D0破位MA10"] = _break_below(c, m10)
	return out


def _norm_code(v: str) -> str:
	return str(v).strip()


def row_from_work(work: pd.DataFrame, idx: int, prefix: str, include_hilo: bool) -> dict:
	r = work.iloc[idx]
	out: dict = {}
	out["%s_MA10" % prefix] = _cell_ma(r.get("ma10"))
	out["%s_MA5" % prefix] = _cell_ma(r.get("ma5"))
	out["%s_开盘" % prefix] = _cell_px(r.get("open"))
	out["%s_收盘" % prefix] = _cell_px(r.get("close"))
	if include_hilo:
		out["%s_最低" % prefix] = _cell_px(r.get("low"))
		out["%s_最高" % prefix] = _cell_px(r.get("high"))
	return out


def build_one_row(bs_mod, code: str, od: str, sleep: float, idx_work: pd.DataFrame | None) -> dict:
	out: dict = {"代码": _norm_code(code), "开仓日": od}
	out.update(_sse_d0_columns(None, None))
	bdf = fetch_daily(bs_mod, code, od)
	if bdf is None or bdf.empty:
		out["_error"] = "no_data"
		return out

	work = _prep_work(bdf)
	try:
		target = datetime.strptime(od, "%Y%m%d").date()
	except ValueError:
		out["_error"] = "bad_date"
		return out

	pos, hint = _pick_open_positions(work, target)
	if pos is None:
		out["_error"] = hint or "no_position"
		return out

	out.update(_sse_d0_columns(idx_work, work.iloc[pos]["date"]))

	if hint:
		out["日期对齐说明"] = hint

	# D前1：仅开盘、收盘 + MA（不含高低）
	if pos > 0:
		rp = work.iloc[pos - 1]
		out["D前1_MA10"] = _cell_ma(rp.get("ma10"))
		out["D前1_MA5"] = _cell_ma(rp.get("ma5"))
		out["D前1_开盘"] = _cell_px(rp.get("open"))
		out["D前1_收盘"] = _cell_px(rp.get("close"))
	else:
		out["D前1_MA10"] = ""
		out["D前1_MA5"] = ""
		out["D前1_开盘"] = ""
		out["D前1_收盘"] = ""

	n_avail = len(work) - pos
	take = min(N_WINDOW_DAYS, max(0, n_avail))

	for k in range(N_WINDOW_DAYS):
		pfx = "D%d" % k
		if k >= take:
			for suffix in ("MA10", "MA5", "开盘", "收盘", "最低", "最高"):
				out["%s_%s" % (pfx, suffix)] = ""
			continue
		idx = pos + k
		out.update(row_from_work(work, idx, pfx, include_hilo=True))

	# 衍生：D0 开盘涨跌%、D1–D5 高收回撤%
	if pos > 0 and take > 0:
		out["D0开盘涨跌%"] = _cell_pct_open_vs_prev(work.iloc[pos - 1]["close"], work.iloc[pos]["open"])
	else:
		out["D0开盘涨跌%"] = ""

	for k in range(1, N_WINDOW_DAYS):
		col_dd = "D%d_高收回撤%%" % k
		if k >= take:
			out[col_dd] = ""
			continue
		i2 = pos + k
		out[col_dd] = _cell_pct_high_close_drawdown(work.iloc[i2]["high"], work.iloc[i2]["close"])

	if pos + N_WINDOW_DAYS > len(work):
		out["_error"] = "partial_d5"
	elif "_error" not in out:
		out["_error"] = ""

	if sleep > 0:
		time.sleep(sleep)
	return out


def ordered_columns() -> list[str]:
	head = (
		["代码", "开仓日"]
		+ ["D前1_MA10", "D前1_MA5", "D前1_开盘", "D前1_收盘"]
		+ [
			x
			for k in range(N_WINDOW_DAYS)
			for x in (
				"D%d_MA10" % k,
				"D%d_MA5" % k,
				"D%d_开盘" % k,
				"D%d_收盘" % k,
				"D%d_最低" % k,
				"D%d_最高" % k,
			)
		]
		+ ["D0开盘涨跌%"]
		+ ["D%d_高收回撤%%" % k for k in range(1, N_WINDOW_DAYS)]
		+ [
			"上证_D0_收盘",
			"上证_D0_MA5",
			"上证_D0_MA10",
			"上证_D0破位MA5",
			"上证_D0破位MA10",
		]
		+ ["日期对齐说明", "_error"]
	)
	return head


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in", "-i", dest="inp", default=_DEFAULT_IN)
	ap.add_argument("--out", "-o", default=_DEFAULT_OUT)
	ap.add_argument("--sleep", type=float, default=0.06)
	ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 行（调试）")
	args = ap.parse_args()

	inp = os.path.abspath(args.inp)
	outp = os.path.abspath(args.out)
	if not os.path.isfile(inp):
		print("[错误] 找不到: %s" % inp)
		sys.exit(1)

	try:
		import baostock as bs
	except ImportError:
		print("[错误] pip install baostock pandas")
		sys.exit(1)

	lg = bs.login()
	if lg.error_code != "0":
		print("[错误] baostock 登录: %s" % lg.error_msg)
		sys.exit(1)

	df_in = pd.read_csv(inp, encoding="utf-8-sig")
	if "code" in df_in.columns:
		code_col = "code"
	elif "代码" in df_in.columns:
		code_col = "代码"
	else:
		print("[错误] 需要列 code 或 代码")
		sys.exit(1)
	if "open_date" not in df_in.columns:
		print("[错误] 需要列 open_date")
		sys.exit(1)

	all_ods: list[str] = []
	for _, r in df_in.iterrows():
		od = open_date8(r["open_date"])
		if od:
			all_ods.append(od)

	idx_work: pd.DataFrame | None = None
	if all_ods:
		min_od = min(all_ods)
		max_od = max(all_ods)
		idx_bdf = fetch_sse_index_daily(bs, min_od, max_od)
		if idx_bdf is None or idx_bdf.empty:
			print("[警告] 上证指数数据拉取失败，上证相关列为空")
		else:
			idx_work = _prep_work(idx_bdf)

	rows_out: list[dict] = []
	n = 0
	for _, r in df_in.iterrows():
		code = r[code_col]
		od = open_date8(r["open_date"])
		if not od:
			continue
		row = build_one_row(bs, str(code), od, args.sleep, idx_work)
		rows_out.append(row)
		n += 1
		if args.limit and n >= args.limit:
			break
		if n % 50 == 0:
			print("[进度] %d" % n)

	cols = ordered_columns()
	out_df = pd.DataFrame(rows_out)
	for c in cols:
		if c not in out_df.columns:
			out_df[c] = ""
	out_df = out_df[[c for c in cols]]
	out_df = out_df.fillna("")

	os.makedirs(os.path.dirname(outp), exist_ok=True)
	out_df.to_csv(outp, index=False, encoding="utf-8-sig", float_format="%.4f")
	print("[完成] %s 行数 %d -> %s" % (inp, len(out_df), outp))
	bs.logout()


if __name__ == "__main__":
	main()
