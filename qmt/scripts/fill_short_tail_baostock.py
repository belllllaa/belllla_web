# -*- coding: utf-8 -*-
"""用 Baostock 前复权日线补全 / 修正 dafengniu_open_window_metrics_qmt.csv 中的窗口指标。

CSV 语义（与首行列名一致）：
  · **D0 = 开仓日**对应的交易日（若当日休市，则对齐到「开仓日起首个有成交的交易日」，与 QMT 导出一致）。
  · **D0…D5** 为开仓日起连续 6 个交易日；每日字段顺序为：
      ``Dk_MA10, Dk_MA5, Dk_开盘, Dk_收盘``（k=0…5）。
    **D0** 另有两列：**D0_最低、D0_最高**（开仓日当天 Baostock 日线 low/high）。
  · **MA5 / MA10**：为该交易日收盘价在全序列上的滚动均线（需开仓日前足够历史日以保证 MA10）。

补数策略：
  1. 优先 ``allow_incomplete_window=False``，必须凑满 **连续 6 个交易日**；Baostock 请求区间覆盖开仓日至「今天」以后若干自然日。
  2. 若仍 short_tail（最新行情尚未披露够 6 日），再退回不完整窗口，尾部 D 列为空，并将 ``_error`` 设为 ``partial_6d``。

其它 CSV 行默认不改；可用 ``--incomplete`` 只修复 ``D5_收盘`` 仍为空的行。

用法：
  python qmt/scripts/fill_short_tail_baostock.py --mode short_tail
  python qmt/scripts/fill_short_tail_baostock.py --mode incomplete
  python qmt/scripts/fill_short_tail_baostock.py --mode both
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_metrics_core import (  # noqa: E402
	compute_window_metrics_from_daily,
	_norm_date_series,
	_pick_open_positions,
	yyyymmdd_shift,
)

_DEFAULT_CSV = os.path.normpath(
	os.path.join(_SCRIPT_DIR, "..", "实盘策略", "dafengniu_open_window_metrics_qmt.csv")
)


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


def fetch_daily_baostock(bs_mod, sym: str, od: str) -> pd.DataFrame | None:
	if not od or len(od) != 8:
		return None
	start = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, -260))
	try:
		od_dt = datetime.strptime(od, "%Y%m%d").date()
	except ValueError:
		return None
	today = datetime.now().date()
	# 覆盖长假 + 尽量拉到 Baostock 最新交易日
	end_dt = max(od_dt + timedelta(days=180), today + timedelta(days=14))
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
	if bdf.empty:
		return None
	return bdf


def _fmt_ma(v):
	"""与 QMT 导出一致：MA 保留 2 位小数；缺失为 NaN。"""
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return np.nan
	try:
		x = float(v)
	except (TypeError, ValueError):
		return np.nan
	if pd.isna(x):
		return np.nan
	return round(x, 2)


def _fmt_px(v):
	if v is None or v == "":
		return np.nan
	try:
		x = float(v)
	except (TypeError, ValueError):
		return v
	if pd.isna(x):
		return np.nan
	return round(x, 4)


def compute_metrics_pair(bdf: pd.DataFrame, od: str, sym: str):
	"""先试完整 6 日，失败再不完整。"""
	wm, err = compute_window_metrics_from_daily(bdf, od, sym, allow_incomplete_window=False)
	if wm is not None:
		return wm, False, None
	if err == "short_tail":
		wm2, err2 = compute_window_metrics_from_daily(bdf, od, sym, allow_incomplete_window=True)
		return wm2, True, err2
	return None, True, err


def apply_metrics_to_row(df_csv: pd.DataFrame, i: int, wm_row: dict, d0_lo: float | None, d0_hi: float | None) -> None:
	for k, v in wm_row.items():
		if k not in df_csv.columns:
			continue
		if k in ("标签_开仓起3交易日皆开盘高于收盘", "标签_窗口内最低较前收跌超9pct"):
			df_csv.at[i, k] = int(v) if v is not None and str(v) != "" else 0
			continue
		if "_MA5" in k or "_MA10" in k:
			df_csv.at[i, k] = _fmt_ma(v)
			continue
		if k in ("代码", "开仓日"):
			continue
		if k == "D0前收盘":
			df_csv.at[i, k] = _fmt_px(v)
			continue
		if k.startswith("D") and ("_开盘" in k or "_收盘" in k):
			df_csv.at[i, k] = _fmt_px(v)
			continue

	if "D0_最低" in df_csv.columns and d0_lo is not None:
		df_csv.at[i, "D0_最低"] = round(float(d0_lo), 4)
	if "D0_最高" in df_csv.columns and d0_hi is not None:
		df_csv.at[i, "D0_最高"] = round(float(d0_hi), 4)


def _indices_short_tail(df: pd.DataFrame) -> list:
	if "_error" not in df.columns:
		return []
	idx = []
	for i in df.index:
		v = df.at[i, "_error"]
		if pd.isna(v) or v == "":
			continue
		if str(v).strip() == "short_tail":
			idx.append(i)
	return idx


def _indices_incomplete(df: pd.DataFrame) -> list:
	"""D5_收盘缺失视为窗口未写满（含 partial 尾部）。"""
	if "D5_收盘" not in df.columns:
		return []
	s = df["D5_收盘"]
	miss = s.isna() | (s.astype(str).str.strip() == "")
	return list(df.index[miss])


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--csv", "-c", default=_DEFAULT_CSV)
	ap.add_argument("--sleep", type=float, default=0.06)
	ap.add_argument(
		"--mode",
		choices=("short_tail", "incomplete", "both"),
		default="both",
		help="short_tail: 仅 _error=short_tail；incomplete: 仅 D5_收盘为空；both: 二者并集",
	)
	args = ap.parse_args()
	path = os.path.abspath(args.csv)
	if not os.path.isfile(path):
		print("[错误] 找不到: %s" % path)
		sys.exit(1)

	try:
		import baostock as bs
	except ImportError:
		print("[错误] 请安装: pip install baostock pandas")
		sys.exit(1)

	lg = bs.login()
	if lg.error_code != "0":
		print("[错误] baostock 登录失败: %s" % lg.error_msg)
		sys.exit(1)

	df = pd.read_csv(path, encoding="utf-8-sig")
	if "_error" in df.columns:
		df["_error"] = df["_error"].astype(object)

	idx_set: set[int] = set()
	if args.mode in ("short_tail", "both"):
		idx_set.update(_indices_short_tail(df))
	if args.mode in ("incomplete", "both"):
		idx_set.update(_indices_incomplete(df))
	idxs = sorted(idx_set)

	if not idxs:
		print("[完成] 无需处理的行（mode=%s）。" % args.mode)
		bs.logout()
		return

	print("[信息] 待处理行数: %d mode=%s" % (len(idxs), args.mode))

	for n_done, i in enumerate(idxs, start=1):
		sym = df.at[i, "代码"]
		od = open_date8(df.at[i, "开仓日"])
		if not od:
			print("[跳过] row=%s 开仓日无效 %s" % (i, df.at[i, "开仓日"]))
			continue

		bdf = fetch_daily_baostock(bs, sym, od)
		if bdf is None or bdf.empty:
			print("[失败] row=%s %s %s 无 Baostock 数据" % (i, sym, od))
			continue

		wm, _, err = compute_metrics_pair(bdf, od, str(sym).strip())
		if wm is None:
			print("[失败] row=%s %s %s compute: %s" % (i, sym, od, err))
			continue

		try:
			target = datetime.strptime(od, "%Y%m%d").date()
		except ValueError:
			continue
		work = bdf.sort_values("date").reset_index(drop=True)
		for col in ("open", "high", "low", "close"):
			work[col] = pd.to_numeric(work[col], errors="coerce")
		work["date"] = _norm_date_series(work["date"])
		pos, _hint = _pick_open_positions(work, target)
		d0_lo = d0_hi = None
		if pos is not None and pos < len(work):
			try:
				d0_lo = float(work.iloc[pos]["low"])
				d0_hi = float(work.iloc[pos]["high"])
			except (TypeError, ValueError):
				pass

		apply_metrics_to_row(df, i, wm.row, d0_lo, d0_hi)

		d5v = df.at[i, "D5_收盘"] if "D5_收盘" in df.columns else np.nan
		if "_error" in df.columns:
			df.at[i, "_error"] = "partial_6d" if pd.isna(d5v) else ""

		st = "partial" if pd.isna(d5v) else "full"
		print("[更新] row=%s %s %s (%s)" % (i, sym, od, st))

		if args.sleep > 0:
			time.sleep(args.sleep)
		if n_done % 5 == 0:
			print("[进度] %d/%d" % (n_done, len(idxs)))

	df.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.4f")
	print("[完成] 已写回 %s" % path)
	bs.logout()


if __name__ == "__main__":
	main()
