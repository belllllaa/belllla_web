# -*- coding: utf-8 -*-
"""26异动监管测.xls → yidong_regulation_stocks_2026.csv（支持合并保留 Baostock 行情列）。"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(_SCRIPT_DIR))

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV, YIDONG_REGULATION_XLS  # noqa: E402

DEFAULT_XLS = Path(YIDONG_REGULATION_XLS)
DEFAULT_CSV = Path(YIDONG_REGULATION_STOCKS_CSV)

COL_RENAME = {"上榜日=T": "上榜日"}
DROP_XLS_JUNK = ("T日收盘价", "T+1日开盘价", "T+2")

BASE_COLS = (
	"上榜日",
	"股票名称",
	"股票代码",
	"监控日涨幅偏离值",
	"当日是否成功卡异动",
	"累计触发异动次数",
)

def _enrich_cols() -> tuple[str, ...]:
	from enrich_yidong_regulation_baostock import all_enrich_cols

	return tuple(all_enrich_cols())


ENRICH_COLS = _enrich_cols()


def _code6(v) -> str:
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return ""
	if isinstance(v, (int, float)) and not isinstance(v, bool):
		n = int(round(float(v)))
		return "" if n <= 0 else str(n).zfill(6)[:6]
	s = str(v).strip().split(".")[0]
	if not s or s.lower() == "nan":
		return ""
	digits = re.sub(r"\D", "", s)
	if not digits:
		return ""
	n = int(digits)
	return "" if n <= 0 else str(n).zfill(6)[:6]


def _read_xls(xls_path: Path) -> pd.DataFrame:
	df = pd.read_excel(xls_path, sheet_name="Sheet1", engine="xlrd", header=0)
	if df.empty:
		raise ValueError("Sheet1 为空")
	df = df.rename(columns=COL_RENAME)
	df = df.drop(columns=[c for c in DROP_XLS_JUNK if c in df.columns], errors="ignore")
	if "上榜日" in df.columns:
		df["上榜日"] = pd.to_datetime(df["上榜日"], errors="coerce").dt.strftime("%Y-%m-%d")
	if "股票代码" in df.columns:
		df["股票代码"] = df["股票代码"].map(_code6)
	# 同上榜日+代码多行：保留最后一行（源表最新）
	df = df.drop_duplicates(subset=["上榜日", "股票代码"], keep="last")
	return df


def _best_enrich_rows(old: pd.DataFrame) -> pd.DataFrame:
	"""旧 CSV 同键多行时，保留行情列填得最多的一行。"""
	price_cols = [c for c in ENRICH_COLS if c in old.columns]

	def _score(row: pd.Series) -> int:
		return sum(1 for c in price_cols if str(row.get(c, "")).strip() not in ("", "nan"))

	old = old.copy()
	old["_score"] = old.apply(_score, axis=1)
	old = old.sort_values("_score", ascending=False)
	return old.drop_duplicates(subset=["上榜日", "股票代码"], keep="first").drop(columns="_score")


def merge_update(xls_path: Path, csv_path: Path) -> tuple[int, int, int]:
	"""用 xls 更新基础字段，保留已有 Baostock 行情列；返回 (总行, 新增键, 更新键)。"""
	xdf = _read_xls(xls_path)
	base = [c for c in BASE_COLS if c in xdf.columns]
	xdf = xdf[base].copy()

	new_n = upd_n = 0
	if csv_path.is_file():
		old = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
		old["股票代码"] = old["股票代码"].map(_code6)
		old = _best_enrich_rows(old)
		old_keys = set(zip(old["上榜日"], old["股票代码"]))
		x_keys = set(zip(xdf["上榜日"], xdf["股票代码"]))
		new_n = len(x_keys - old_keys)
		upd_n = len(x_keys & old_keys)

		keep_cols = ["上榜日", "股票代码"] + [c for c in ENRICH_COLS if c in old.columns]
		enrich = old[keep_cols]
		out = xdf.merge(enrich, on=["上榜日", "股票代码"], how="left")
	else:
		out = xdf

	for c in ENRICH_COLS:
		if c not in out.columns:
			out[c] = ""

	ordered = list(base) + [c for c in ENRICH_COLS if c in out.columns]
	out = out[ordered]
	out = out.sort_values(["上榜日", "股票代码"], ascending=[False, True]).reset_index(drop=True)
	out = out.fillna("")

	csv_path.parent.mkdir(parents=True, exist_ok=True)
	out.to_csv(csv_path, index=False, encoding="utf-8-sig")
	return len(out), new_n, upd_n


def convert(xls_path: Path, csv_path: Path) -> int:
	"""全量覆盖（不保留行情列）。"""
	df = _read_xls(xls_path)
	for col in df.columns:
		if df[col].dtype in ("float64", "float32"):
			df[col] = df[col].where(df[col].notna(), None)
	csv_path.parent.mkdir(parents=True, exist_ok=True)
	df.to_csv(csv_path, index=False, encoding="utf-8-sig")
	return len(df)


def main() -> None:
	ap = argparse.ArgumentParser(description="26异动监管测.xls → yidong_regulation_stocks_2026.csv")
	ap.add_argument("--xls", default=str(DEFAULT_XLS))
	ap.add_argument("--csv", default=str(DEFAULT_CSV))
	ap.add_argument(
		"--overwrite",
		action="store_true",
		help="全量覆盖 CSV（不保留 Baostock 行情列）；默认合并更新",
	)
	args = ap.parse_args()

	xls_path = Path(args.xls)
	csv_path = Path(args.csv)
	if not xls_path.is_file():
		print("[错误] 找不到: %s" % xls_path)
		raise SystemExit(1)

	if args.overwrite:
		n = convert(xls_path, csv_path)
		print("[OK] 全量覆盖 %d 行 -> %s" % (n, csv_path))
	else:
		n, new_n, upd_n = merge_update(xls_path, csv_path)
		print(
			"[OK] 合并 %d 行（新增键 %d | 更新键 %d）-> %s"
			% (n, new_n, upd_n, csv_path)
		)


if __name__ == "__main__":
	main()
