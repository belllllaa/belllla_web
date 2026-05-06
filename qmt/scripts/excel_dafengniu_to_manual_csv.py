# -*- coding: utf-8 -*-
"""
从桌面《大疯牛(1).xlsx》整理出与实盘策略兼容的 manual_open CSV，并生成明细表。

约定（与 strategy_my_watchlist_intraday_atr_1m_live_signal._load_manual_hold_open_dates_csv 一致）：
  第 1 列：股票代码（QMT 风格 000001.SZ / 600000.SH）
  第 2 列：开仓日 YYYYMMDD（入选日的次一交易日，用 akshare 上交所交易日历）

Excel 约定：
  第 1 行为表头，第 2 行为说明行（跳过），数据从第 3 行起。
  前三列：入选时间、入选股票简称、股票代码。

同一代码多行：合并为一条，取最早的开仓日（便于与“持股天数”类逻辑一致）。

Excel 已知问题（《大疯牛》当前版）：
  表内分为两段：前一段「入选」序列号落在 46331～46387，按 Excel 日期实为 2026-11～2026-12，
  后一段从序列号 46027 起为 2026-01～2026-04。业务含义应为「先 2025 年末一段，再到 2026 年」，即
  前一段应为 2025-11～2025-12（年份多写了一年）。脚本默认把解析得到的「2026 年 11、12 月」的入选日整体减一年纠正。

用法：
  python qmt/scripts/excel_dafengniu_to_manual_csv.py
  python qmt/scripts/excel_dafengniu_to_manual_csv.py --excel "D:/xxx/大疯牛(1).xlsx"
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime

import pandas as pd

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
	sys.path.insert(0, _REPO_ROOT)


def _excel_serial_to_date(v: float) -> date | None:
	try:
		x = float(v)
	except (TypeError, ValueError):
		return None
	if 30000 < x < 60000:
		ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=x)
		return ts.date()
	return None


def _cell_to_select_date(val) -> date | None:
	if val is None or (isinstance(val, float) and pd.isna(val)):
		return None
	if isinstance(val, datetime):
		return val.date()
	if isinstance(val, pd.Timestamp):
		return val.date()
	if isinstance(val, date):
		return val
	try:
		x = float(val)
	except (TypeError, ValueError):
		return None
	d = _excel_serial_to_date(x)
	if d:
		return d
	if x >= 1e8:
		s = str(int(x))
		if len(s) >= 8:
			y, m, d2 = int(s[:4]), int(s[4:6]), int(s[6:8])
			try:
				return date(y, m, d2)
			except ValueError:
				return None
	return None


def _normalize_code_6(raw) -> str | None:
	if raw is None or (isinstance(raw, float) and pd.isna(raw)):
		return None
	s = str(raw).strip().replace("\t", "").strip()
	if not s:
		return None
	try:
		n = int(float(s))
	except (ValueError, TypeError):
		return None
	return str(n).zfill(6)


def _infer_exchange(code6: str) -> str:
	pre = code6[:2]
	if pre in ("60", "68", "69"):
		return "SH"
	if pre == "51" or pre == "52" or pre == "53" or pre == "54" or pre == "55" or pre == "56" or pre == "58":
		return "SH"
	if pre == "50" and code6[2] in "123456789":
		return "SH"
	if code6.startswith("6") or code6.startswith("5"):
		return "SH"
	return "SZ"


def _canonical_code(code6: str) -> str:
	return "%s.%s" % (code6, _infer_exchange(code6))


def _load_sse_trade_dates():
	import akshare as ak

	df = ak.tool_trade_date_hist_sina()
	dt = pd.to_datetime(df["trade_date"])
	return sorted(dt.dt.date.unique().tolist())


def _next_trade_day(cal: list[date], d: date) -> date | None:
	"""严格晚于自然日 d 的第一个交易日（入选日若为交易日，开仓日为下一交易日）。"""
	for td in cal:
		if td > d:
			return td
	return None


def _fix_dafengniu_trailing_segment_year(sd: date) -> date:
	"""将误记为 2026 年 11～12 月的「年末入选」纠正为 2025 年同期（见文件头说明）。"""
	if sd.year == 2026 and sd.month >= 11:
		try:
			return date(sd.year - 1, sd.month, sd.day)
		except ValueError:
			return sd
	return sd


def main():
	ap = argparse.ArgumentParser()
	default_xlsx = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "大疯牛(1).xlsx")
	ap.add_argument("--excel", default=default_xlsx, help="Excel 路径")
	ap.add_argument(
		"--out-dir",
		default=os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "实盘策略")),
		help="输出目录（默认 qmt/实盘策略）",
	)
	ap.add_argument(
		"--no-trailing-year-fix",
		action="store_true",
		help="关闭「2026 年末→2025 年末」年份纠正（仅在确认 Excel 已为正确公历年时使用）",
	)
	args = ap.parse_args()

	excel_path = os.path.abspath(args.excel)
	out_dir = os.path.normpath(args.out_dir)
	os.makedirs(out_dir, exist_ok=True)

	if not os.path.isfile(excel_path):
		print("[错误] 找不到 Excel: %s" % excel_path)
		sys.exit(1)

	df = pd.read_excel(excel_path, sheet_name=0, header=0, skiprows=[1])
	if df.shape[1] < 3:
		print("[错误] 列数不足 3")
		sys.exit(1)

	col_sel = df.iloc[:, 0]
	col_name = df.iloc[:, 1]
	col_code = df.iloc[:, 2]

	print("[信息] 正在拉取上交所交易日历（akshare）…")
	trade_cal = _load_sse_trade_dates()

	rows_detail = []
	open_by_code: dict[str, str] = {}

	for i in range(len(df)):
		sd = _cell_to_select_date(col_sel.iloc[i])
		if not args.no_trailing_year_fix and sd:
			sd = _fix_dafengniu_trailing_segment_year(sd)
		code6 = _normalize_code_6(col_code.iloc[i])
		if not sd or not code6:
			continue
		name = "" if pd.isna(col_name.iloc[i]) else str(col_name.iloc[i]).strip()
		nd = _next_trade_day(trade_cal, sd)
		if not nd:
			print("[警告] 第 %d 行：无法计算次一交易日，入选日=%s 代码=%s" % (i + 3, sd, code6))
			continue
		open_yyyymmdd = nd.strftime("%Y%m%d")
		cc = _canonical_code(code6)
		rows_detail.append(
			{
				"入选日": sd.isoformat(),
				"开仓日": nd.isoformat(),
				"开仓日YYYYMMDD": open_yyyymmdd,
				"代码": cc,
				"简称": name,
			}
		)
		prev = open_by_code.get(cc)
		if prev is None or open_yyyymmdd < prev:
			open_by_code[cc] = open_yyyymmdd

	detail_path = os.path.join(out_dir, "dafengniu_holdings_detail.csv")
	manual_path = os.path.join(out_dir, "dafengniu_manual_open_dates.csv")

	pd.DataFrame(rows_detail).to_csv(detail_path, index=False, encoding="utf-8-sig")

	with open(manual_path, "w", encoding="utf-8-sig", newline="") as f:
		w = csv.writer(f)
		w.writerow(["# 由 excel_dafengniu_to_manual_csv.py 生成；列：代码,开仓日YYYYMMDD；同代码合并取最早开仓日"])
		w.writerow(["code", "open_date"])
		for cc in sorted(open_by_code.keys()):
			w.writerow([cc, open_by_code[cc]])

	dup_n = len(rows_detail) - len(open_by_code)
	print("[完成] 明细行=%d 去重后代码数=%d（合并重复=%d）" % (len(rows_detail), len(open_by_code), dup_n))
	print("[输出] %s" % detail_path)
	print("[输出] %s" % manual_path)


if __name__ == "__main__":
	main()
