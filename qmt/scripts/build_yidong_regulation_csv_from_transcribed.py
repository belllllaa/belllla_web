# -*- coding: utf-8 -*-
"""将 _yidong_crops/transcribed.csv 同步到 上游数据源/yidong_regulation_stocks_2026.csv（去完全重复行）。"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(_SCRIPT_DIR))

from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402

SRC = _SCRIPT_DIR / "_yidong_crops" / "transcribed.csv"
DST = Path(YIDONG_REGULATION_STOCKS_CSV)


def main() -> None:
	if not SRC.is_file():
		print("[错误] 请先由截图转录生成: %s" % SRC)
		return
	rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
	if not rows:
		print("[错误] 源 CSV 为空")
		return
	fields = list(rows[0].keys())
	seen: set[tuple] = set()
	out: list[dict] = []
	for r in rows:
		key = tuple(r.get(f, "") for f in fields)
		if key in seen:
			continue
		seen.add(key)
		out.append(r)
	DST.parent.mkdir(parents=True, exist_ok=True)
	with DST.open("w", encoding="utf-8-sig", newline="") as f:
		w = csv.DictWriter(f, fieldnames=fields)
		w.writeheader()
		w.writerows(out)
	print("[OK] %d 行（去重前 %d）-> %s" % (len(out), len(rows), DST))


if __name__ == "__main__":
	main()
