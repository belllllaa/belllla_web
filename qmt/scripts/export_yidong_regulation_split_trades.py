# -*- coding: utf-8
"""异动监管分 F 档买卖 · 分板块导出资金明细（上：60/00，下：68/30）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(_SCRIPT_DIR))

from dafengniu_paths import (  # noqa: E402
	YIDONG_REGULATION_CAPITAL_SPLIT_SUMMARY_JSON,
	YIDONG_REGULATION_CAPITAL_TRADES_ALL_CSV,
	YIDONG_REGULATION_CAPITAL_TRADES_GROWTH_CSV,
	YIDONG_REGULATION_CAPITAL_TRADES_MAIN_CSV,
	YIDONG_REGULATION_CAPITAL_TRADES_OTHER_CSV,
	YIDONG_REGULATION_STOCKS_CSV,
)
from yidong_regulation_backtest import (  # noqa: E402
	board_group,
	summarize_capital,
	trades_to_capital_rows,
)
from yidong_regulation_backtest_core import (  # noqa: E402
	CAP_PER_STOCK,
	SKIP_F,
	STRATEGY_NAME,
	load_yidong,
	run_backtest,
)


def _core_tdf_to_trades(tdf: pd.DataFrame) -> list[dict]:
	out: list[dict] = []
	for _, r in tdf.iterrows():
		code = str(r["股票代码"])
		out.append(
			{
				"代码": code,
				"名称": r.get("股票名称", ""),
				"T日": r.get("开仓日", ""),
				"买入价": r["买入价"],
				"卖出价": r["卖出价"],
				"收益率%": r["收益率%"],
				"卖出原因": r.get("卖出原因", ""),
				"卖出日": r.get("卖出日", ""),
				"F": r.get("监控日涨幅偏离值F", ""),
				"板块": board_group(code),
				"持仓最大回撤%": r.get("持仓最大回撤%", ""),
				"买卖规则": r.get("买卖规则", ""),
			}
		)
	return out

OUT_MAIN = Path(YIDONG_REGULATION_CAPITAL_TRADES_MAIN_CSV)
OUT_GROWTH = Path(YIDONG_REGULATION_CAPITAL_TRADES_GROWTH_CSV)
OUT_OTHER = Path(YIDONG_REGULATION_CAPITAL_TRADES_OTHER_CSV)
OUT_ALL = Path(YIDONG_REGULATION_CAPITAL_TRADES_ALL_CSV)
OUT_SUMMARY = Path(YIDONG_REGULATION_CAPITAL_SPLIT_SUMMARY_JSON)

GROUP_LABEL = {
	"main_60_00": "上_主板(60/00开头)",
	"growth_68_30": "下_科创创业(68/30开头)",
	"other": "其他代码",
}


def main() -> None:
	ap = argparse.ArgumentParser(description="异动监管分板块资金回测导出")
	ap.add_argument("--csv", default=str(YIDONG_REGULATION_STOCKS_CSV))
	ap.add_argument("--cap", type=float, default=CAP_PER_STOCK)
	args = ap.parse_args()

	csv_path = Path(args.csv)
	df = load_yidong(csv_path)

	tdf, summary = run_backtest(df)
	trades = _core_tdf_to_trades(tdf)
	skip_stats = summary.get("跳过统计", {})
	skip_stats["成交笔数"] = len(tdf)
	skip_stats["可买信号"] = skip_stats.get("可买信号_行数", 0)
	skip_stats["表内行数"] = skip_stats.get("总行数", len(df))
	rows = trades_to_capital_rows(trades, cap_per_stock=float(args.cap))

	cols = [
		"序号",
		"板块",
		"股票代码",
		"股票名称",
		"买入日",
		"买入价",
		"卖出日",
		"卖出价",
		"卖出原因",
		"买入股数",
		"买入金额",
		"卖出金额",
		"单笔收益率%",
		"单笔收益金额",
		"F",
		"持仓最大回撤%",
		"资金占用%",
	]

	def _write(sub_rows: list[dict], path: Path) -> None:
		tdf = pd.DataFrame(sub_rows)
		if len(tdf):
			tdf = tdf[cols]
			tdf = tdf.sort_values(["买入日", "股票代码"]).reset_index(drop=True)
			tdf["序号"] = range(1, len(tdf) + 1)
		else:
			tdf = pd.DataFrame(columns=cols)
		path.parent.mkdir(parents=True, exist_ok=True)
		tdf.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.4f")

	by_group: dict[str, list[dict]] = {
		"main_60_00": [],
		"growth_68_30": [],
		"other": [],
	}
	for r in rows:
		g = r.get("板块", "other")
		by_group.setdefault(g, []).append(r)

	_write(rows, OUT_ALL)
	_write(by_group.get("main_60_00", []), OUT_MAIN)
	_write(by_group.get("growth_68_30", []), OUT_GROWTH)
	_write(by_group.get("other", []), OUT_OTHER)

	summaries = {
		"数据源": str(csv_path),
		"策略": STRATEGY_NAME,
		"F分档规则": summary.get("跳过统计", {}).get("F分档规则", {}),
		"过滤": {
			"F跳过": sorted(SKIP_F),
			"G": 1,
			"T日交易所涨跌停": True,
			"60/00开头_T日涨跌幅": "跳过 >8% 或 <-8%",
			"68/30开头_T日涨跌幅": "跳过 >15% 或 <-15%",
		},
		"单票上限_元": float(args.cap),
		"股数": "100股整数倍",
		"跳过统计_行级": skip_stats,
		"全量": summarize_capital(rows, "全量"),
		"上_主板60_00": summarize_capital(by_group.get("main_60_00", []), GROUP_LABEL["main_60_00"]),
		"下_科创创业68_30": summarize_capital(by_group.get("growth_68_30", []), GROUP_LABEL["growth_68_30"]),
		"其他": summarize_capital(by_group.get("other", []), GROUP_LABEL["other"]),
	}

	with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
		json.dump(summaries, f, ensure_ascii=False, indent=2)

	print("=== 过滤与信号 ===")
	print("表内行 %d | F/G/涨跌停/涨跌幅带跳过见 JSON | 可买信号 %d | 成交 %d"
	      % (skip_stats["表内行数"], skip_stats["可买信号"], skip_stats["成交笔数"]))
	for key in ("全量", "上_主板60_00", "下_科创创业68_30", "其他"):
		s = summaries[key]
		if s.get("成交笔数", 0) == 0:
			print("\n[%s] 无成交" % key)
			continue
		print(
			"\n[%s] %d笔 | 总买 %.0f | 总收益 %.0f (%.2f%%) | 胜率 %.1f%% | 均笔 %.2f%% | 金额回撤 %.0f | 净值回撤 %.2f%%"
			% (
				key,
				s["成交笔数"],
				s["总买入金额"],
				s["总收益金额"],
				s["总收益率_金额加权%"],
				s["胜率%"],
				s["平均每笔收益率%"],
				s["累计收益金额最大回撤"],
				s.get("链式净值最大回撤%") or 0,
			)
		)
	print("\n[OK] 上 -> %s" % OUT_MAIN)
	print("[OK] 下 -> %s" % OUT_GROWTH)
	print("[OK] 全量 -> %s" % OUT_ALL)
	print("[OK] 汇总 -> %s" % OUT_SUMMARY)
	if by_group.get("other"):
		print("[OK] 其他 -> %s" % OUT_OTHER)


if __name__ == "__main__":
	main()
