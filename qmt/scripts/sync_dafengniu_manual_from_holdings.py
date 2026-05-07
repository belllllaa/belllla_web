# -*- coding: utf-8 -*-
"""从股票池明细 CSV 增量同步到「简化开仓日」CSV。

数据源（手动维护、每日可追加）：
  qmt/实盘策略/大疯牛妖股数据/dafengniu_holdings_detail.csv
  列：入选日, 开仓日, 开仓日YYYYMMDD, 代码, 简称

目标（供策略/脚本读取）：
  qmt/实盘策略/大疯牛妖股数据/dafengniu_sync_open_dates.csv
  列：code,open_date（open_date 为 8 位 YYYYMMDD）

逻辑：以 (代码, 开仓日YYYYMMDD) 为键；明细中出现、且简化表中尚不存在的组合 → **追加**。
已存在于简化表的行不会删除或修改（仅从明细「增生」）。

用法：
  python qmt/scripts/sync_dafengniu_manual_from_holdings.py
  python qmt/scripts/sync_dafengniu_manual_from_holdings.py --dry-run
  python qmt/scripts/sync_dafengniu_manual_from_holdings.py --holdings path --manual path
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

from dafengniu_paths import HOLDINGS_DETAIL_CSV, SYNC_OPEN_DATES_CSV  # noqa: E402

_DEFAULT_HOLDINGS = HOLDINGS_DETAIL_CSV
_DEFAULT_MANUAL = SYNC_OPEN_DATES_CSV


def _norm_code(v) -> str:
	s = str(v).strip().upper().replace("\u3000", "").strip()
	return s


def _norm_open_yyyymmdd(row: pd.Series) -> str | None:
	"""优先 开仓日YYYYMMDD；否则从 开仓日 解析。"""
	if "开仓日YYYYMMDD" in row.index:
		raw = row["开仓日YYYYMMDD"]
		if raw is not None and str(raw).strip() not in ("", "nan"):
			s = str(raw).strip().replace(".0", "")
			if "e" in s.lower() or "E" in s:
				try:
					s = "%.0f" % float(s)
				except ValueError:
					pass
			s = "".join(c for c in s if c.isdigit())
			if len(s) >= 8:
				return s[:8]
	if "开仓日" in row.index:
		raw = row["开仓日"]
		if pd.notna(raw) and str(raw).strip():
			ts = pd.to_datetime(raw, errors="coerce")
			if pd.notna(ts):
				return ts.strftime("%Y%m%d")
	return None


def _manual_keys(df: pd.DataFrame) -> set[tuple[str, str]]:
	out: set[tuple[str, str]] = set()
	for _, r in df.iterrows():
		c = _norm_code(r.get("code", ""))
		od = r.get("open_date", "")
		if od is None or (isinstance(od, float) and pd.isna(od)):
			continue
		sod = str(od).strip().replace(".0", "")
		sod = "".join(c for c in sod if c.isdigit())
		if len(sod) >= 8:
			sod = sod[:8]
		else:
			continue
		if c:
			out.add((c, sod))
	return out


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--holdings", "-H", default=_DEFAULT_HOLDINGS)
	ap.add_argument("--manual", "-M", default=_DEFAULT_MANUAL)
	ap.add_argument("--dry-run", action="store_true")
	args = ap.parse_args()

	hp = os.path.abspath(args.holdings)
	mp = os.path.abspath(args.manual)
	if not os.path.isfile(hp):
		print("[错误] 找不到股票池: %s" % hp)
		sys.exit(1)

	hold = pd.read_csv(hp, encoding="utf-8-sig")
	required = ("代码",)
	for col in required:
		if col not in hold.columns:
			print("[错误] 股票池缺少列: %s，实际: %s" % (col, list(hold.columns)))
			sys.exit(1)

	new_rows: list[dict] = []
	seen_hold: set[tuple[str, str]] = set()

	if os.path.isfile(mp):
		man = pd.read_csv(mp, encoding="utf-8-sig")
		if "code" not in man.columns or "open_date" not in man.columns:
			print("[错误] 简化表需含 code, open_date，实际: %s" % list(man.columns))
			sys.exit(1)
		existing = _manual_keys(man)
	else:
		man = pd.DataFrame(columns=["code", "open_date"])
		existing = set()

	for _, row in hold.iterrows():
		code = _norm_code(row.get("代码", ""))
		if not code:
			continue
		od = _norm_open_yyyymmdd(row)
		if not od:
			print("[跳过] 无法解析开仓日: 代码=%s 行=%s" % (code, row.to_dict()))
			continue
		key = (code, od)
		if key in seen_hold:
			continue
		seen_hold.add(key)
		if key not in existing:
			new_rows.append({"code": code, "open_date": od})

	if not new_rows:
		print("[完成] 无新增：(明细中全部 (代码,开仓日) 已在简化表中)。")
		return

	add = pd.DataFrame(new_rows)
	add = add.sort_values(["open_date", "code"]).reset_index(drop=True)
	print("[新增] %d 条:" % len(add))
	print(add.to_string(index=False))

	if args.dry_run:
		print("[dry-run] 未写入 %s" % mp)
		return

	out = pd.concat([man, add], ignore_index=True)
	out = out.drop_duplicates(subset=["code", "open_date"], keep="first")
	out = out.sort_values(["open_date", "code"]).reset_index(drop=True)
	os.makedirs(os.path.dirname(mp), exist_ok=True)
	out.to_csv(mp, index=False, encoding="utf-8-sig")
	print("[写入] %s 共 %d 行（含表头以上共 %d 条记录）" % (mp, len(out) + 1, len(out)))


if __name__ == "__main__":
	main()
