# -*- coding: utf-8 -*-
"""异动监管：分F档买卖规则 — 导出买卖明细（上下半表）与汇总。

用法：
  python qmt/scripts/export_yidong_regulation_trades.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(_SCRIPT_DIR))

from dafengniu_paths import (  # noqa: E402
	YIDONG_REGULATION_STOCKS_CSV,
	YIDONG_REGULATION_TRADES_DETAIL_CSV,
	YIDONG_REGULATION_TRADES_SL8_T2_LOWER_CSV,
	YIDONG_REGULATION_TRADES_SL8_T2_SUMMARY_JSON,
	YIDONG_REGULATION_TRADES_SL8_T2_UPPER_CSV,
)
from yidong_regulation_backtest_core import (  # noqa: E402
	load_yidong,
	run_backtest,
)

DEFAULT_DETAIL = Path(YIDONG_REGULATION_TRADES_DETAIL_CSV)
OUT_UPPER = Path(YIDONG_REGULATION_TRADES_SL8_T2_UPPER_CSV)
OUT_LOWER = Path(YIDONG_REGULATION_TRADES_SL8_T2_LOWER_CSV)
OUT_SUMMARY = Path(YIDONG_REGULATION_TRADES_SL8_T2_SUMMARY_JSON)


def _split_half(df, out_upper: Path, out_lower: Path, out_all: Path | None) -> tuple[int, int]:
	df = df.sort_values(["开仓日", "股票代码"]).reset_index(drop=True)
	n = len(df)
	mid = n // 2
	upper = df.iloc[:mid]
	lower = df.iloc[mid:]
	upper.to_csv(out_upper, index=False, encoding="utf-8-sig")
	lower.to_csv(out_lower, index=False, encoding="utf-8-sig")
	if out_all is not None:
		df.to_csv(out_all, index=False, encoding="utf-8-sig")
	return len(upper), len(lower)


def main() -> int:
	ap = argparse.ArgumentParser(description="异动监管分F档买卖 明细导出")
	ap.add_argument("--csv", type=Path, default=Path(YIDONG_REGULATION_STOCKS_CSV))
	ap.add_argument("--out-all", type=Path, default=DEFAULT_DETAIL)
	ap.add_argument("--out-upper", type=Path, default=OUT_UPPER)
	ap.add_argument("--out-lower", type=Path, default=OUT_LOWER)
	ap.add_argument("--out-summary", type=Path, default=OUT_SUMMARY)
	args = ap.parse_args()

	df = load_yidong(args.csv)
	trades, summary = run_backtest(df)
	if trades.empty:
		print("无成交")
		return 1

	args.out_upper.parent.mkdir(parents=True, exist_ok=True)
	nu, nl = _split_half(trades, args.out_upper, args.out_lower, args.out_all)
	summary["明细拆分"] = {
		"排序": "开仓日, 股票代码",
		"上半笔数": nu,
		"下半笔数": nl,
		"全量文件": str(args.out_all),
		"上半文件": str(args.out_upper),
		"下半文件": str(args.out_lower),
	}
	args.out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

	print(json.dumps(summary, ensure_ascii=False, indent=2))
	print("---")
	print("全量 %d 笔 -> %s" % (len(trades), args.out_all))
	print("上半 %d 笔 -> %s" % (nu, args.out_upper))
	print("下半 %d 笔 -> %s" % (nl, args.out_lower))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
