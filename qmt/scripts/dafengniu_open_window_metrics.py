# -*- coding: utf-8 -*-
"""
读取 dafengniu_sync_open_dates.csv（默认 qmt/实盘策略/大疯牛妖股数据/；否则回落 dafengniu_manual_open_dates.csv），
对每个标的拉取日线（AkShare 前复权），计算开仓日（含）起连续 6 个交易日：
开盘价、收盘价、MA5、MA10；并输出两项标签：
  - 开仓日起连续 3 个交易日每日开盘 > 收盘
  - 开窗内任一交易日：最低价相对前一交易日收盘价跌幅 ≤ -9%

用法：
  python qmt/scripts/dafengniu_open_window_metrics.py
  python qmt/scripts/dafengniu_open_window_metrics.py --input path/to.csv --out path/out.csv --sleep 0.25

依赖：pandas、akshare（不需启动 QMT）。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_paths import MANUAL_OPEN_DATES_LEGACY_CSV, SYNC_OPEN_DATES_CSV  # noqa: E402
from dafengniu_metrics_core import (  # noqa: E402
	akshare_hist_to_daily_df,
	compute_window_metrics_from_daily,
	yyyymmdd_shift,
)

_DEFAULT_IN = SYNC_OPEN_DATES_CSV if os.path.isfile(SYNC_OPEN_DATES_CSV) else MANUAL_OPEN_DATES_LEGACY_CSV
_DEFAULT_OUT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "实盘策略", "dafengniu_open_window_metrics.csv"))


def load_manual_pairs(path: str) -> list[tuple[str, str]]:
	out = []
	if not os.path.isfile(path):
		return out
	for enc in ("utf-8-sig", "gbk", "utf-8"):
		try:
			with open(path, "r", encoding=enc, newline="") as f:
				for row in csv.reader(f):
					if len(row) < 2:
						continue
					a = row[0].strip()
					b = row[1].strip()
					if not a or a.startswith("#"):
						continue
					al = a.lower()
					if al in ("code", "symbol", "stock", "stock_code", "ts_code"):
						continue
					if len(b) >= 8 and b[:8].isdigit():
						out.append((a.strip(), b[:8]))
			return out
		except Exception:
			out = []
			continue
	return out


def code6(sym: str) -> str:
	s = sym.strip().upper().replace("\u3000", "").strip()
	if "." in s:
		s = s.split(".")[0]
	return s.zfill(6)[:6]


def fetch_ak_daily(symbol6: str, start: str, end: str):
	import akshare as ak

	return ak.stock_zh_a_hist(
		symbol=symbol6,
		period="daily",
		start_date=start,
		end_date=end,
		adjust="qfq",
	)


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--input", "-i", default=_DEFAULT_IN, help="manual_open_dates CSV")
	ap.add_argument("--out", "-o", default=_DEFAULT_OUT, help="输出 CSV")
	ap.add_argument("--sleep", type=float, default=0.2, help="请求间隔秒（减轻限频）")
	ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 条（调试）")
	ap.add_argument("--prepend-calendar", type=int, default=120, help="开仓日前多取自然日跨度（用于 MA）")
	ap.add_argument("--append-calendar", type=int, default=40, help="开仓日后多取自然日跨度")
	args = ap.parse_args()

	path_in = os.path.abspath(args.input)
	if not os.path.isfile(path_in):
		print("[错误] 找不到输入 CSV: %s" % path_in)
		sys.exit(1)

	pairs = load_manual_pairs(path_in)
	if not pairs:
		print("[错误] 输入无有效行")
		sys.exit(1)

	if args.limit > 0:
		pairs = pairs[: args.limit]

	rows_out = []
	err_n = 0

	for idx, (sym, od) in enumerate(pairs):
		s6 = code6(sym)
		start = yyyymmdd_shift(od, -abs(args.prepend_calendar))
		end = yyyymmdd_shift(od, abs(args.append_calendar))
		try:
			raw = fetch_ak_daily(s6, start, end)
			df = akshare_hist_to_daily_df(raw)
			if df is None or df.empty:
				err_n += 1
				rows_out.append(
					{
						"代码": sym,
						"开仓日": od,
						"_error": "no_ak_data",
					}
				)
				continue
			m, err = compute_window_metrics_from_daily(df, od, sym)
			if m is None:
				err_n += 1
				rows_out.append({"代码": sym, "开仓日": od, "_error": err or "compute_fail"})
				continue
			rows_out.append(m.row)
		except Exception as e:
			err_n += 1
			rows_out.append({"代码": sym, "开仓日": od, "_error": str(e)[:80]})
		if args.sleep > 0:
			time.sleep(args.sleep)
		if (idx + 1) % 50 == 0:
			print("[进度] %d/%d" % (idx + 1, len(pairs)))

	import pandas as pd

	out_df = pd.DataFrame(rows_out)
	for _tag in ("标签_开仓起3交易日皆开盘高于收盘", "标签_窗口内最低较前收跌超9pct"):
		if _tag in out_df.columns:
			out_df[_tag] = pd.to_numeric(out_df[_tag], errors="coerce").fillna(0).astype(int)
	out_path = os.path.abspath(args.out)
	os.makedirs(os.path.dirname(out_path), exist_ok=True)
	out_df.to_csv(out_path, index=False, encoding="utf-8-sig", float_format="%.4f")
	print("[完成] 行数=%d 失败/异常=%d -> %s" % (len(rows_out), err_n, out_path))


if __name__ == "__main__":
	main()
