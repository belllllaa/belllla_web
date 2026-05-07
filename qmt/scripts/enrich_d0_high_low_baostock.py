# -*- coding: utf-8 -*-
"""为 dafengniu_open_window_metrics_qmt.csv 增加 D0_最低、D0_最高（Baostock 日线，adjustflag=2 前复权）。

用法：
  python qmt/scripts/enrich_d0_high_low_baostock.py
  python qmt/scripts/enrich_d0_high_low_baostock.py -c path/to.csv --sleep 0.06

依赖：pandas、baostock
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_metrics_core import yyyymmdd_shift  # noqa: E402

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


def d0_high_low_baostock(bs_mod, sym: str, od: str) -> tuple[float | None, float | None]:
	"""开仓日 D0 的前复权 high、low。"""
	if not od or len(od) != 8:
		return None, None
	start = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, -30))
	end = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, 30))
	rs = bs_mod.query_history_k_data_plus(
		_baostock_ts(sym),
		"date,high,low",
		start_date=start,
		end_date=end,
		frequency="d",
		adjustflag="2",
	)
	if rs.error_code != "0":
		return None, None
	rows = []
	while rs.error_code == "0" and rs.next():
		rows.append(rs.get_row_data())
	if not rows:
		return None, None
	bdf = pd.DataFrame(rows, columns=rs.fields)
	bdf["date"] = pd.to_datetime(bdf["date"], errors="coerce").dt.strftime("%Y%m%d")
	target = od
	row = bdf.loc[bdf["date"] == target]
	if row.empty:
		return None, None
	try:
		h = float(row.iloc[0]["high"])
		l = float(row.iloc[0]["low"])
	except (TypeError, ValueError, KeyError):
		return None, None
	if h <= 0 or l <= 0:
		return None, None
	return h, l


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--csv", "-c", default=_DEFAULT_CSV)
	ap.add_argument("--sleep", type=float, default=0.06)
	args = ap.parse_args()
	path = os.path.abspath(args.csv)
	if not os.path.isfile(path):
		print("[错误] 找不到: %s" % path)
		sys.exit(1)

	try:
		import baostock as bs
	except ImportError:
		print("[错误] 请安装: python -m pip install baostock pandas")
		sys.exit(1)

	lg = bs.login()
	if lg.error_code != "0":
		print("[错误] baostock 登录失败: %s" % lg.error_msg)
		sys.exit(1)

	df = pd.read_csv(path, encoding="utf-8-sig")
	for col in ("D0_最低", "D0_最高"):
		if col in df.columns:
			df = df.drop(columns=[col])

	insert_at = list(df.columns).index("D0_收盘") + 1
	lows: list = []
	highs: list = []
	for i in range(len(df)):
		od = open_date8(df.iloc[i]["开仓日"])
		sym = df.iloc[i]["代码"]
		lo, hi = (None, None)
		if od:
			try:
				hi, lo = d0_high_low_baostock(bs, sym, od)
			except Exception as e:
				print("[异常] row=%d %s %s %s" % (i, sym, od, e))
		lows.append("" if lo is None else round(float(lo), 4))
		highs.append("" if hi is None else round(float(hi), 4))
		if args.sleep > 0:
			time.sleep(args.sleep)
		if (i + 1) % 40 == 0:
			print("[进度] %d/%d" % (i + 1, len(df)))

	df.insert(insert_at, "D0_最低", lows)
	df.insert(insert_at + 1, "D0_最高", highs)

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
	print("[完成] 已写入 %s 列 D0_最低、D0_最高（insert 于 D0_收盘 后）" % path)
	bs.logout()


if __name__ == "__main__":
	main()
