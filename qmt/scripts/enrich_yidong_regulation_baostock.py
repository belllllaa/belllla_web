# -*- coding: utf-8
"""yidong_regulation_stocks_2026.csv：Baostock 增量补全 T-1~T+10 行情（不覆盖已有单元格）。"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(_SCRIPT_DIR))

from dafengniu_metrics_core import _pick_open_positions  # noqa: E402
from export_sync_open_dates_baostock import (  # noqa: E402
	_cell_ma,
	_cell_px,
	_prep_work,
	_sse_bar_row,
	code6,
	fetch_daily,
	fetch_sse_index_daily,
	open_date8,
)

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402

DEFAULT_CSV = Path(YIDONG_REGULATION_STOCKS_CSV)

DAY_OFFSETS = list(range(-1, 11))  # T-1 … T+10


def _date8_from_cell(v) -> str:
	s = str(v).strip()[:10].replace("-", "")
	return s if len(s) == 8 and s.isdigit() else open_date8(v)


def _day_label(off: int) -> str:
	if off < 0:
		return "T%d日" % off
	if off == 0:
		return "T日"
	return "T+%d日" % off


def _is_empty(v) -> bool:
	if v is None or (isinstance(v, float) and pd.isna(v)):
		return True
	s = str(v).strip()
	return not s or s.lower() == "nan"


def _day_price_cols() -> list[str]:
	out: list[str] = []
	for off in DAY_OFFSETS:
		p = _day_label(off)
		out.extend(
			[
				"%s_开盘" % p,
				"%s_收盘" % p,
				"%s_最高" % p,
				"%s_最低" % p,
				"%s_MA3" % p,
				"%s_MA5" % p,
				"%s_MA8" % p,
				"%s_MA10" % p,
			]
		)
	return out


def _meta_cols() -> list[str]:
	return ["T日", "T日对齐说明", "T日涨跌幅%"]


def _sse_cols() -> list[str]:
	return ["上证_T日_收盘", "上证_T日_MA5", "上证_T日_MA10"]


def all_enrich_cols() -> list[str]:
	return _meta_cols() + _day_price_cols() + _sse_cols()


def fetch_need_cols() -> list[str]:
	"""判断是否需要拉取行情（不含可选的 T日对齐说明）。"""
	return ["T日", "T日涨跌幅%"] + _day_price_cols() + _sse_cols()


def _prep_stock_work(bdf: pd.DataFrame) -> pd.DataFrame:
	work = _prep_work(bdf)
	work["ma3"] = work["close"].rolling(3, min_periods=3).mean()
	work["ma8"] = work["close"].rolling(8, min_periods=8).mean()
	return work


def _pct_chg_vs_prev_close(prev_close, close_px) -> float | str:
	try:
		p = float(prev_close)
		c = float(close_px)
	except (TypeError, ValueError):
		return ""
	if p <= 0 or pd.isna(p) or pd.isna(c):
		return ""
	return round((c - p) / p * 100.0, 4)


def _enrich_one(
	stock_work: pd.DataFrame | None,
	sse_work: pd.DataFrame | None,
	t8: str,
) -> tuple[dict, str | None]:
	out: dict = {c: "" for c in all_enrich_cols()}

	if not t8 or len(t8) != 8:
		return out, "bad_t_date"
	if stock_work is None or stock_work.empty:
		return out, "no_stock_bars"

	pos, hint = _pick_open_positions(stock_work, datetime.strptime(t8, "%Y%m%d").date())
	if pos is None:
		return out, hint or "no_t_bar"

	t_row = stock_work.iloc[pos]
	out["T日"] = pd.Timestamp(t_row["date"]).strftime("%Y-%m-%d")
	if hint:
		out["T日对齐说明"] = hint

	for off in DAY_OFFSETS:
		p = _day_label(off)
		idx = pos + off
		if idx < 0 or idx >= len(stock_work):
			continue
		row = stock_work.iloc[idx]
		out["%s_开盘" % p] = _cell_px(row.get("open"))
		out["%s_收盘" % p] = _cell_px(row.get("close"))
		out["%s_最高" % p] = _cell_px(row.get("high"))
		out["%s_最低" % p] = _cell_px(row.get("low"))
		out["%s_MA3" % p] = _cell_ma(row.get("ma3"))
		out["%s_MA5" % p] = _cell_ma(row.get("ma5"))
		out["%s_MA8" % p] = _cell_ma(row.get("ma8"))
		out["%s_MA10" % p] = _cell_ma(row.get("ma10"))

	prev_c = out.get("T-1日_收盘", "")
	t_c = out.get("T日_收盘", "")
	out["T日涨跌幅%"] = _pct_chg_vs_prev_close(prev_c, t_c)

	sse_cells = _sse_bar_row(sse_work, t_row["date"])
	if sse_cells is not None:
		c, m5, m10 = sse_cells
		out["上证_T日_收盘"] = c
		out["上证_T日_MA5"] = m5
		out["上证_T日_MA10"] = m10

	return out, None


def _row_needs_fetch(row: pd.Series, cols: list[str]) -> bool:
	return any(_is_empty(row.get(c, "")) for c in cols)


def _merge_fill_missing(base: dict, patch: dict, cols: list[str]) -> None:
	for c in cols:
		if c not in patch:
			continue
		if _is_empty(base.get(c)):
			base[c] = patch[c]


def _fetch_stock_extended(bs_mod, code: str, max_t8: str) -> pd.DataFrame:
	raw = fetch_daily(bs_mod, code, max_t8)
	if raw is None or raw.empty:
		return pd.DataFrame()
	return _prep_stock_work(raw)


def main() -> None:
	ap = argparse.ArgumentParser(description="Baostock 增量补全异动监管 T-1~T+10（不覆盖已有）")
	ap.add_argument("--csv", default=str(DEFAULT_CSV))
	ap.add_argument("--sleep", type=float, default=0.04, help="每票首次拉取间隔(秒)")
	ap.add_argument(
		"--force",
		action="store_true",
		help="强制全表重拉并覆盖行情列（默认仅补空）",
	)
	args = ap.parse_args()

	csv_path = Path(args.csv)
	if not csv_path.is_file():
		print("[错误] 找不到: %s" % csv_path)
		sys.exit(1)

	df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
	if df.empty:
		print("[错误] CSV 为空")
		sys.exit(1)

	enrich_cols = all_enrich_cols()
	need_cols = fetch_need_cols()
	for c in enrich_cols:
		if c not in df.columns:
			df[c] = ""

	df["股票代码"] = df["股票代码"].map(code6)
	df["_t8"] = df["上榜日"].map(_date8_from_cell)

	if args.force:
		need_mask = pd.Series(True, index=df.index)
	else:
		need_mask = df.apply(lambda r: _row_needs_fetch(r, need_cols), axis=1)

	n_need = int(need_mask.sum())
	print("待补行 %d / %d" % (n_need, len(df)))
	if n_need == 0:
		print("[OK] 无需补全 -> %s" % csv_path)
		return

	try:
		import baostock as bs
	except ImportError:
		print("[错误] pip install baostock pandas")
		sys.exit(1)

	lg = bs.login()
	if lg.error_code != "0":
		print("[错误] baostock 登录失败: %s" % lg.error_msg)
		sys.exit(1)

	sub = df.loc[need_mask]
	valid_t8 = [x for x in sub["_t8"].tolist() if x]
	min_t8 = min(valid_t8)
	max_t8 = max(valid_t8)

	need_sse = args.force or any(
		_is_empty(row.get(c)) for _, row in sub.iterrows() for c in _sse_cols()
	)
	sse_work = None
	if need_sse:
		sse_raw = fetch_sse_index_daily(bs, min_t8, max_t8)
		sse_work = _prep_work(sse_raw) if sse_raw is not None else None
		if sse_work is None:
			print("[警告] 上证指数拉取失败，上证列将为空")

	codes_need = sorted(sub["股票代码"].dropna().unique())
	stock_cache: dict[str, pd.DataFrame] = {}
	for i, code in enumerate(codes_need, 1):
		sub_valid = [x for x in sub.loc[sub["股票代码"] == code, "_t8"] if x]
		if not sub_valid:
			continue
		c_max = max(sub_valid)
		stock_cache[code] = _fetch_stock_extended(bs, code, c_max)
		if args.sleep > 0:
			time.sleep(args.sleep)
		if i % 20 == 0:
			print("  … 股票 %d/%d" % (i, len(codes_need)))

	bs.logout()

	row_cache: dict[tuple[str, str], dict] = {}
	fail = 0
	filled_cells = 0
	for idx, row in df.iterrows():
		merged = row.to_dict()
		if not need_mask.loc[idx] and not args.force:
			continue
		code = row["股票代码"]
		t8 = row["_t8"]
		key = (code, t8)
		if key not in row_cache:
			cells, err = _enrich_one(stock_cache.get(code), sse_work, t8)
			if err:
				fail += 1
			row_cache[key] = cells
		patch = row_cache[key]
		before = sum(1 for c in enrich_cols if not _is_empty(merged.get(c)))
		if args.force:
			for c in enrich_cols:
				if c in patch and not _is_empty(patch[c]):
					merged[c] = patch[c]
		else:
			_merge_fill_missing(merged, patch, enrich_cols)
		after = sum(1 for c in enrich_cols if not _is_empty(merged.get(c)))
		filled_cells += after - before
		df.loc[idx] = merged

	out_df = df.drop(columns=["_t8"], errors="ignore")
	for old in ("T日收盘价", "T+1日开盘价", "T+2"):
		if old in out_df.columns:
			out_df = out_df.drop(columns=[old], errors="ignore")

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
	ordered = base + [c for c in enrich_cols if c not in base and c in out_df.columns]
	rest = [c for c in out_df.columns if c not in ordered]
	out_df = out_df.loc[:, ~out_df.columns.duplicated()]
	ordered = [c for c in ordered if c in out_df.columns]
	out_df = out_df[ordered + [c for c in rest if c in out_df.columns]]
	out_df = out_df.replace("nan", "").fillna("")

	out_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
	filled_t = (out_df["T日_收盘"].astype(str).str.strip() != "").sum()
	filled_t7 = (out_df.get("T+7日_收盘", pd.Series([""] * len(out_df))).astype(str).str.strip() != "").sum()
	filled_t10 = (out_df.get("T+10日_收盘", pd.Series([""] * len(out_df))).astype(str).str.strip() != "").sum()
	print(
		"[OK] %d 行 | 本次待补 %d | 新填单元约 %d | T收盘 %d | T+7收盘 %d | T+10收盘 %d | 失败键 %d -> %s"
		% (len(out_df), n_need, filled_cells, filled_t, filled_t7, filled_t10, fail, csv_path)
	)


if __name__ == "__main__":
	main()
