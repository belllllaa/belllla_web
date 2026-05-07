# -*- coding: utf-8 -*-
"""从 CSV 指定「文件行号」起，仅对「D0前收盘」为空的行补全（不覆盖已有值）。"""
from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_metrics_core import (  # noqa: E402
	akshare_hist_to_daily_df,
	prev_close_before_open_from_daily,
	yyyymmdd_shift,
)


def _d8_to_yyyy_mm_dd(d8: str) -> str:
	return "%s-%s-%s" % (d8[:4], d8[4:6], d8[6:8])


def _baostock_ts(sym: str) -> str:
	c = code6(sym)
	pfx = "sh" if c.startswith("6") else "sz"
	return "%s.%s" % (pfx, c)


def _prev_close_via_baostock(bs_mod, sym: str, od: str) -> float | None:
	start = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, -180))
	end = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, 15))
	rs = bs_mod.query_history_k_data_plus(
		_baostock_ts(sym),
		"date,close",
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
	bdf["date"] = pd.to_datetime(bdf["date"], errors="coerce")
	bdf["close"] = pd.to_numeric(bdf["close"], errors="coerce")
	pc, _e = prev_close_before_open_from_daily(bdf, od)
	return float(pc) if pc is not None and pc > 0 else None


def code6(sym: str) -> str:
	s = str(sym).strip().upper().replace("\u3000", "").strip()
	if "." in s:
		s = s.split(".")[0]
	return s.zfill(6)[:6]


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


def _empty_prev(v) -> bool:
	if v is None:
		return True
	try:
		if pd.isna(v):
			return True
	except Exception:
		pass
	s = str(v).strip()
	return s == "" or s.lower() == "nan"


_DEFAULT_CSV = os.path.normpath(
	os.path.join(_SCRIPT_DIR, "..", "实盘策略", "dafengniu_open_window_metrics_qmt.csv")
)


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--csv", "-c", default=_DEFAULT_CSV, help="默认指向 qmt/实盘策略/dafengniu_open_window_metrics_qmt.csv")
	ap.add_argument(
		"--start-file-line",
		type=int,
		default=140,
		help="从该「文件行号」起处理（含本行）。第 1 行为表头，第 2 行为首条数据。",
	)
	ap.add_argument("--sleep", type=float, default=0.35)
	ap.add_argument("--retries", type=int, default=4)
	ap.add_argument("--bs-only", action="store_true", help="仅用 Baostock（批量更稳，与 enrich 脚本一致前复权 adjustflag=2）")
	args = ap.parse_args()

	path = os.path.abspath(args.csv)
	df = pd.read_csv(path, encoding="utf-8-sig")
	if "D0前收盘" not in df.columns or "代码" not in df.columns or "开仓日" not in df.columns:
		print("CSV 需含列: 代码, 开仓日, D0前收盘")
		sys.exit(1)

	start_idx = max(0, int(args.start_file_line) - 2)
	ak = None
	if not args.bs_only:
		try:
			import akshare as ak
		except ImportError:
			pass
	bs_mod = None
	try:
		import baostock as bs

		if bs.login().error_code == "0":
			bs_mod = bs
	except Exception:
		bs_mod = None
	if ak is None and bs_mod is None:
		print("[错误] 请安装: python -m pip install akshare pandas  和/或  python -m pip install baostock pandas")
		sys.exit(1)

	n_done = 0
	n_skip = 0
	n_fail = 0
	for i in range(start_idx, len(df)):
		if not _empty_prev(df.loc[i, "D0前收盘"]):
			n_skip += 1
			continue
		od = open_date8(df.loc[i, "开仓日"])
		if not od:
			n_fail += 1
			continue
		sym = df.loc[i, "代码"]
		s6 = code6(sym)
		got = None
		if ak is not None:
			for attempt in range(max(1, args.retries)):
				try:
					raw = ak.stock_zh_a_hist(
						symbol=s6,
						period="daily",
						start_date=yyyymmdd_shift(od, -180),
						end_date=yyyymmdd_shift(od, 15),
						adjust="qfq",
					)
					dfd = akshare_hist_to_daily_df(raw)
					if dfd is None or dfd.empty:
						raise ValueError("empty")
					pc, _e = prev_close_before_open_from_daily(dfd, od)
					if pc is not None and pc > 0:
						got = round(float(pc), 4)
					break
				except Exception:
					if attempt + 1 >= max(1, args.retries):
						break
					time.sleep(0.6 * (attempt + 1))
		if got is None and bs_mod is not None:
			try:
				pc2 = _prev_close_via_baostock(bs_mod, sym, od)
				if pc2 is not None:
					got = round(float(pc2), 4)
			except Exception:
				pass
		if got is None:
			print("[失败] i=%d %s %s" % (i, s6, od))
			n_fail += 1
		else:
			df.loc[i, "D0前收盘"] = got
			n_done += 1
			print("[OK] i=%d %s D0=%s D0前收盘=%s" % (i, s6, od, got))
		if args.sleep > 0:
			time.sleep(args.sleep)

	for _t in ("标签_开仓起3交易日皆开盘高于收盘", "标签_窗口内最低较前收跌超9pct"):
		if _t in df.columns:
			df[_t] = pd.to_numeric(df[_t], errors="coerce").fillna(0).astype(int)

	for _col in list(df.columns):
		if "_MA5" in _col or "_MA10" in _col:

			def _fmt_ma(v):
				if v is None or v == "":
					return ""
				try:
					if pd.isna(v):
						return ""
				except Exception:
					pass
				try:
					return "%.2f" % float(v)
				except Exception:
					return v

			df[_col] = df[_col].map(_fmt_ma)

	df.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.4f")
	print("[完成] start_idx=%d 补全=%d 跳过已有=%d 失败=%d -> %s" % (start_idx, n_done, n_skip, n_fail, path))
	try:
		if bs_mod is not None:
			bs_mod.logout()
	except Exception:
		pass


if __name__ == "__main__":
	main()
