# -*- coding: utf-8 -*-
"""为 dafengniu_open_window_metrics_qmt.csv 补列「D0前收盘」（开仓日对齐到的首根 K 线的前一交易日收盘价）。

数据源（见实现）：
  - 默认：先 AkShare 东财前复权；失败或未安装时再 Baostock 前复权（adjustflag=2）。
  - 仅批量、网络不稳时推荐加 --bs-only，只走 Baostock。

与 QMT 导出 `dividend_type=front_ratio` / AkShare `adjust=qfq` 同属前复权口径；数值可能与 QMT 有微小差异。

运行方式（在仓库根目录 belllla_web 下）：

  pip install pandas baostock
  pip install akshare

  # 推荐：只 Baostock，少断连
  python qmt/scripts/enrich_open_window_metrics_qmt_prev_close.py --bs-only --sleep 0.05

  # 默认：先 AkShare，再 Baostock
  python qmt/scripts/enrich_open_window_metrics_qmt_prev_close.py --sleep 0.35

  # 指定 CSV（克隆后若文件路径不同）
  python qmt/scripts/enrich_open_window_metrics_qmt_prev_close.py -c qmt/实盘策略/dafengniu_open_window_metrics_qmt.csv --bs-only

说明：会原地覆盖写入 --csv 指向的文件，请先备份。列「D0前收盘」插入在「开仓日」右侧。
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

from dafengniu_metrics_core import (  # noqa: E402
	akshare_hist_to_daily_df,
	prev_close_before_open_from_daily,
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


def _baostock_ts(sym: str) -> str:
	c = code6(sym)
	pfx = "sh" if c.startswith("6") else "sz"
	return "%s.%s" % (pfx, c)


def _prev_close_via_baostock(bs_mod, sym: str, od: str) -> float | None:
	start = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, -120))
	end = _d8_to_yyyy_mm_dd(yyyymmdd_shift(od, 10))
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
	return pc if pc is not None and pc > 0 else None


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--csv", "-c", default=_DEFAULT_CSV, help="metrics_qmt CSV 路径")
	ap.add_argument("--sleep", type=float, default=0.35, help="请求间隔（秒）")
	ap.add_argument(
		"--retries", type=int, default=4, help="单标的 AkShare 失败时的重试次数"
	)
	ap.add_argument("--bs-only", action="store_true", help="仅用 Baostock，跳过 AkShare（批量更稳）")
	ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 行（调试）")
	args = ap.parse_args()
	path = os.path.abspath(args.csv)
	if not os.path.isfile(path):
		print("[错误] 找不到: %s" % path)
		sys.exit(1)

	ak = None
	if not args.bs_only:
		try:
			import akshare as ak  # noqa: F401
		except ImportError:
			ak = None

	bs_mod = None
	try:
		import baostock as bs

		if bs.login().error_code == "0":
			bs_mod = bs
	except Exception:
		bs_mod = None

	if ak is None and bs_mod is None:
		print("[错误] 请至少安装 akshare 或 baostock 之一")
		sys.exit(1)

	df = pd.read_csv(path, encoding="utf-8-sig")
	if "代码" not in df.columns or "开仓日" not in df.columns:
		print("[错误] CSV 需包含列: 代码、开仓日")
		sys.exit(1)

	n = len(df) if args.limit <= 0 else min(len(df), args.limit)
	prevs: list = []

	for i in range(n):
		r = df.iloc[i]
		od = open_date8(r["开仓日"])
		if not od:
			prevs.append("")
			continue
		sym = r["代码"]
		s6 = code6(sym)
		got = None
		if ak is not None:
			for attempt in range(max(1, args.retries)):
				try:
					raw = ak.stock_zh_a_hist(
						symbol=s6,
						period="daily",
						start_date=yyyymmdd_shift(od, -120),
						end_date=yyyymmdd_shift(od, 10),
						adjust="qfq",
					)
					dfd = akshare_hist_to_daily_df(raw)
					if dfd is None or dfd.empty:
						raise ValueError("empty_hist")
					pc, _err = prev_close_before_open_from_daily(dfd, od)
					if pc is not None and pc > 0:
						got = round(pc, 4)
					break
				except Exception:
					if attempt + 1 >= max(1, args.retries):
						break
					time.sleep(0.8 * (attempt + 1))
		if got is None and bs_mod is not None:
			try:
				pc2 = _prev_close_via_baostock(bs_mod, sym, od)
				if pc2 is not None:
					got = round(float(pc2), 4)
			except Exception:
				pass
		prevs.append("" if got is None else got)
		if args.sleep > 0:
			time.sleep(args.sleep)
		if (i + 1) % 50 == 0:
			print("[进度] %d/%d" % (i + 1, n))

	if "D0前收盘" in df.columns:
		df = df.drop(columns=["D0前收盘"])
	idx = df.columns.get_loc("开仓日") + 1
	df.insert(idx, "D0前收盘", prevs + [""] * (len(df) - len(prevs)))

	# 与导出脚本一致：标签列整型
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

	os.makedirs(os.path.dirname(path), exist_ok=True)
	df.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.4f")
	filled = sum(1 for x in prevs if x != "" and x is not None)
	print("[完成] 写入 %s ；本批补全 D0前收盘 %d/%d 行" % (path, filled, len(prevs)))

	try:
		if bs_mod is not None:
			bs_mod.logout()
	except Exception:
		pass


if __name__ == "__main__":
	main()
