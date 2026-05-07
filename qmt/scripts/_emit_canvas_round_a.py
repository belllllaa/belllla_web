# -*- coding: utf-8 -*-
"""从 Round A CSV 生成 Canvas TS 行片段。

CSV 由 dafengniu_sell_combo_scan 写出：首行「基准」，随后多行固定对照（方案标签为开盘 SL/TP），再为筛选后网格。
"""
import os

import pandas as pd

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CSV_PATH = os.path.join(ROOT, "实盘策略", "测试组合表格", "dafengniu_sell_combo_scan_round_A.csv")
OUT = os.path.normpath(
	os.path.join(
		os.path.expanduser("~"),
		".cursor",
		"projects",
		"c-Users-admin-Projects-belllla-web",
		"canvases",
		"_gen_round_a_rows.txt",
	)
)


def _fmt_row_ts(label: str, sl_s: str, tp_s: str, r: pd.Series) -> str:
	label_esc = str(label).replace("\\", "\\\\").replace("'", "\\'")
	return (
		"\t\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
		% (
			label_esc,
			sl_s,
			tp_s,
			str(int(r["成交笔数"])),
			str(r["收益合计_pct"]),
			str(r["胜率_pct"]),
			str(r["最大回撤_链式净值_pct"]),
			str(r["盈亏比_均盈除以均亏绝对值"]),
			str(r["夏普_笔收益"]),
			str(r["波动率_笔收益标准差_pct"]),
		)
	)


def main() -> None:
	df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
	if df.empty:
		raise SystemExit("[错误] Round A CSV 为空")
	chunks: list[str] = []
	for _, r in df.iterrows():
		label = str(r["方案标签"]).replace("\\", "\\\\").replace("'", "\\'")
		sl = "%.1f%%" % (float(r["止损_sl"]) * 100)
		tp = "%.1f%%" % (float(r["止盈_tp"]) * 100)
		chunks.append(_fmt_row_ts(label, sl, tp, r))
	os.makedirs(os.path.dirname(OUT), exist_ok=True)
	with open(OUT, "w", encoding="utf-8") as f:
		f.write("\n".join(chunks))
	print("[OK] %d rows -> %s" % (len(chunks), OUT))


if __name__ == "__main__":
	main()
