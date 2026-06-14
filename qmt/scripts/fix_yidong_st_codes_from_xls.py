# -*- coding: utf-8
"""用上游 xls 覆盖 CSV 中「股票名称以 ST 开头」行的股票代码，并清空行情列后增量补 Baostock。

匹配键：上榜日 + 股票名称（xls 同键多行取最后一行）。
非 ST 行不改动代码与行情。

用法：
  python qmt/scripts/fix_yidong_st_codes_from_xls.py
  python qmt/scripts/fix_yidong_st_codes_from_xls.py --no-enrich
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(_SCRIPT_DIR))

from convert_26_yidong_xls_to_csv import (  # noqa: E402
	BASE_COLS,
	ENRICH_COLS,
	_code6,
)
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV, YIDONG_REGULATION_XLS  # noqa: E402

COL_RENAME = {"上榜日=T": "上榜日"}
DROP_XLS_JUNK = ("T日收盘价", "T+1日开盘价", "T+2")


def _is_st_name(name) -> bool:
	return str(name).strip().upper().startswith("ST")


def _read_xls_all(xls_path: Path) -> pd.DataFrame:
	df = pd.read_excel(xls_path, sheet_name="Sheet1", engine="xlrd", header=0)
	df = df.rename(columns=COL_RENAME)
	df = df.drop(columns=[c for c in DROP_XLS_JUNK if c in df.columns], errors="ignore")
	if "上榜日" in df.columns:
		df["上榜日"] = pd.to_datetime(df["上榜日"], errors="coerce").dt.strftime("%Y-%m-%d")
	df["股票代码"] = df["股票代码"].map(_code6)
	return df


def _xls_name_lookup(xdf: pd.DataFrame) -> pd.DataFrame:
	"""(上榜日, 股票名称) -> 最新一行基础字段。"""
	base = [c for c in BASE_COLS if c in xdf.columns]
	sub = xdf[base].copy()
	sub = sub[sub["股票代码"].astype(str).str.len() == 6]
	sub = sub.drop_duplicates(subset=["上榜日", "股票名称"], keep="last")
	return sub.set_index(["上榜日", "股票名称"])


def _best_enrich_rows(df: pd.DataFrame) -> pd.DataFrame:
	price_cols = [c for c in ENRICH_COLS if c in df.columns]

	def _score(row: pd.Series) -> int:
		return sum(1 for c in price_cols if str(row.get(c, "")).strip() not in ("", "nan"))

	out = df.copy()
	out["_score"] = out.apply(_score, axis=1)
	out = out.sort_values("_score", ascending=False)
	return out.drop_duplicates(subset=["上榜日", "股票代码"], keep="first").drop(columns="_score")


def fix_st_codes(csv_path: Path, xls_path: Path) -> dict:
	xdf = _read_xls_all(xls_path)
	lookup = _xls_name_lookup(xdf)

	csv = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
	csv["股票代码"] = csv["股票代码"].map(_code6)
	for c in ENRICH_COLS:
		if c not in csv.columns:
			csv[c] = ""

	st_mask = csv["股票名称"].map(_is_st_name)
	changed = 0
	cleared = 0
	not_in_xls = 0

	for idx in csv.index[st_mask]:
		name = str(csv.at[idx, "股票名称"]).strip()
		date = str(csv.at[idx, "上榜日"]).strip()
		key = (date, name)
		if key not in lookup.index:
			not_in_xls += 1
			continue
		row = lookup.loc[key]
		new_code = _code6(row["股票代码"])
		if len(new_code) != 6:
			continue
		old_code = _code6(csv.at[idx, "股票代码"])
		if old_code != new_code:
			changed += 1
		for c in BASE_COLS:
			if c in row.index and c in csv.columns:
				v = row[c]
				csv.at[idx, c] = "" if pd.isna(v) else str(v).strip()
		csv.at[idx, "股票代码"] = new_code
		# 代码或基础字段变更后清空行情，强制重拉
		for c in ENRICH_COLS:
			if c in csv.columns and str(csv.at[idx, c]).strip() not in ("", "nan"):
				cleared += 1
			csv.at[idx, c] = ""
		if "T日" in csv.columns:
			csv.at[idx, "T日"] = ""
		if "T日对齐说明" in csv.columns:
			csv.at[idx, "T日对齐说明"] = ""

	# 修正后可能 (上榜日, 代码) 重复：保留行情列最多的一行
	before = len(csv)
	csv = _best_enrich_rows(csv)
	deduped = before - len(csv)

	base = [
		"上榜日",
		"T日",
		"T日对齐说明",
		"股票名称",
		"股票代码",
		"监控日涨幅偏离值",
		"当日是否成功卡异动",
		"累计触发异动次数",
	]
	ordered = base + [c for c in ENRICH_COLS if c in csv.columns and c not in base]
	rest = [c for c in csv.columns if c not in ordered]
	csv = csv[[c for c in ordered + rest if c in csv.columns]]
	csv = csv.sort_values(["上榜日", "股票代码"], ascending=[False, True]).reset_index(drop=True)
	csv = csv.fillna("")

	csv_path.parent.mkdir(parents=True, exist_ok=True)
	csv.to_csv(csv_path, index=False, encoding="utf-8-sig")

	return {
		"ST行数": int(st_mask.sum()),
		"代码覆盖变更": changed,
		"清空行情单元约": cleared,
		"xls无匹配": not_in_xls,
		"去重删除行": deduped,
		"写回总行": len(csv),
	}


def main() -> None:
	ap = argparse.ArgumentParser(description="ST 股代码按上游 xls 覆盖并增量补行情")
	ap.add_argument("--xls", default=str(YIDONG_REGULATION_XLS))
	ap.add_argument("--csv", default=str(YIDONG_REGULATION_STOCKS_CSV))
	ap.add_argument("--no-enrich", action="store_true")
	args = ap.parse_args()

	xls_path = Path(args.xls)
	csv_path = Path(args.csv)
	if not xls_path.is_file():
		raise SystemExit("[错误] 找不到 xls: %s" % xls_path)
	if not csv_path.is_file():
		raise SystemExit("[错误] 找不到 csv: %s" % csv_path)

	stats = fix_st_codes(csv_path, xls_path)
	print(
		"[OK] ST 行 %d | 代码变更 %d | 去重删 %d | xls 无匹配 %d | 写回 %d 行 -> %s"
		% (
			stats["ST行数"],
			stats["代码覆盖变更"],
			stats["去重删除行"],
			stats["xls无匹配"],
			stats["写回总行"],
			csv_path,
		)
	)

	if not args.no_enrich:
		subprocess.run(
			[sys.executable, str(_SCRIPT_DIR / "enrich_yidong_regulation_baostock.py"), "--csv", str(csv_path)],
			check=False,
		)


if __name__ == "__main__":
	main()
