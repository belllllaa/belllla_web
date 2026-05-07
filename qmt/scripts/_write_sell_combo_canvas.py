# -*- coding: utf-8 -*-
"""写入 dafengniu-sell-combo-scan.canvas.tsx：Round A 来自 _gen_round_a_rows.txt；B/D/E/F 来自扫描 CSV。"""
import os
import sys
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)
from dafengniu_paths import (
	SELL_COMBO_SCAN_ROUND_B_CSV,
	SELL_COMBO_SCAN_ROUND_C_CSV,
	SELL_COMBO_SCAN_ROUND_D_CSV,
	SELL_COMBO_SCAN_ROUND_E_CSV,
)

ROWS_TXT = Path(
	os.path.normpath(
		os.path.join(
			os.path.expanduser("~"),
			".cursor",
			"projects",
			"c-Users-admin-Projects-belllla-web",
			"canvases",
			"_gen_round_a_rows.txt",
		)
	)
)

CANVAS = Path(
	os.path.normpath(
		os.path.join(
			os.path.expanduser("~"),
			".cursor",
			"projects",
			"c-Users-admin-Projects-belllla-web",
			"canvases",
			"dafengniu-sell-combo-scan.canvas.tsx",
		)
	)
)


def _ts_str(s: object) -> str:
	return str(s).replace("\\", "\\\\").replace("'", "\\'")


def normalize_rows(raw: str) -> str:
	"""_emit_canvas_round_a.py 输出为双 tab，画布内统一为单 tab。"""
	lines = []
	for ln in raw.splitlines():
		if ln.startswith("\t\t"):
			lines.append("\t" + ln[2:])
		else:
			lines.append(ln)
	return "\n".join(lines) + ("\n" if raw else "")


ROUND_A_HEADER = """import { Callout, Divider, H1, H2, Stack, Table, Text } from 'cursor/canvas';

/** 数据来自 qmt/scripts/dafengniu_sell_combo_scan.py → 测试组合表格/dafengniu_sell_combo_scan_round_*.csv */

const ROUND_A_HEADERS = [
\t'方案',
\t'止损',
\t'止盈',
\t'N',
\t'合计%',
\t'胜率%',
\t'最大回撤%',
\t'盈亏比(均)',
\t'夏普',
\t'波动率%',
];

const ROUND_A_ROWS: string[][] = [
"""


def build_footer() -> str:
	dfb = pd.read_csv(SELL_COMBO_SCAN_ROUND_B_CSV, encoding="utf-8-sig")
	dfc = pd.read_csv(SELL_COMBO_SCAN_ROUND_C_CSV, encoding="utf-8-sig")
	dfd = pd.read_csv(SELL_COMBO_SCAN_ROUND_D_CSV, encoding="utf-8-sig")
	dfe = pd.read_csv(SELL_COMBO_SCAN_ROUND_E_CSV, encoding="utf-8-sig")
	if len(dfb) < 1 or len(dfc) < 1 or len(dfd) < 1 or len(dfe) < 1:
		raise SystemExit("Round B/C/D/E CSV 无数据，请先运行: python qmt/scripts/dafengniu_sell_combo_scan.py")
	b_lines: list[str] = []
	for _, rb in dfb.iterrows():
		b_lines.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				_ts_str(rb["方案标签"]),
				"%.1f%%" % (float(rb["止损_sl"]) * 100),
				"%.1f%%" % (float(rb["止盈_tp"]) * 100),
				str(int(rb["成交笔数"])),
				str(rb["收益合计_pct"]),
				str(rb["胜率_pct"]),
				str(rb["最大回撤_链式净值_pct"]),
				str(rb["盈亏比_均盈除以均亏绝对值"]),
				str(rb["夏普_笔收益"]),
				str(rb["波动率_笔收益标准差_pct"]),
			)
		)
	b_block = "\n".join(b_lines)
	c_lines: list[str] = []
	for _, rc in dfc.iterrows():
		c_lines.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				_ts_str(rc["方案标签"]),
				"%.1f%%" % (float(rc["止损_sl"]) * 100),
				"%.1f%%" % (float(rc["止盈_tp"]) * 100),
				_ts_str(rc["sse_tail_exit"]),
				str(int(rc["开盘平仓笔数"])),
				str(int(rc["盘中平仓笔数"])),
				str(int(rc["上证破MA5笔数"])),
				str(int(rc["D1弱转弱到期笔数"])),
				str(int(rc["成交笔数"])),
				str(rc["收益合计_pct"]),
				str(rc["夏普_笔收益"]),
				str(rc["胜率_pct"]),
				str(rc["最大回撤_链式净值_pct"]),
				str(rc["波动率_笔收益标准差_pct"]),
				str(rc["盈亏比_均盈除以均亏绝对值"]),
			)
		)
	c_block = "\n".join(c_lines)
	d_lines: list[str] = []
	for _, rd in dfd.iterrows():
		md = int(rd["max_day"])
		d_lines.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', 'D%d', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				_ts_str(rd["方案标签"]),
				"%.1f%%" % (float(rd["止损_sl"]) * 100),
				"%.1f%%" % (float(rd["止盈_tp"]) * 100),
				"%.1f%%" % (float(rd["止损_sl_盘中"]) * 100),
				"%.1f%%" % (float(rd["止盈_tp_盘中"]) * 100),
				_ts_str(rd["sse_tail_exit"]),
				str(rd["D1_weak"]),
				md,
				str(int(rd["成交笔数"])),
				str(rd["收益合计_pct"]),
				str(rd["夏普_笔收益"]),
				str(rd["胜率_pct"]),
				str(rd["最大回撤_链式净值_pct"]),
				str(rd["波动率_笔收益标准差_pct"]),
				str(rd["盈亏比_均盈除以均亏绝对值"]),
			)
		)
	d_block = "\n".join(d_lines)
	e_lines: list[str] = []
	for _, er in dfe.iterrows():
		e_lines.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% (
				_ts_str(er["方案标签"]),
				"%.1f%%" % (float(er["止损_sl"]) * 100),
				"%.1f%%" % (float(er["止盈_tp"]) * 100),
				_ts_str(er["sse_tail_exit"]),
				str(int(er["开盘成交数"])),
				str(int(er["破位成交数"])),
				str(int(er["D1弱转弱到期笔数"])),
				str(int(er["成交笔数"])),
				str(er["收益合计_pct"]),
				str(er["夏普_笔收益"]),
				str(er["胜率_pct"]),
				str(er["最大回撤_链式净值_pct"]),
				str(er["波动率_笔收益标准差_pct"]),
				str(er["盈亏比_均盈除以均亏绝对值"]),
			)
		)
	e_block = "\n".join(e_lines)
	return (
		"""
];

const ROUND_B_HEADERS = [
\t'方案',
\t'止损',
\t'止盈',
\t'N',
\t'合计%',
\t'胜率%',
\t'最大回撤%',
\t'盈亏比(均)',
\t'夏普',
\t'波动率%',
];

const ROUND_B_ROWS: string[][] = [
"""
		+ b_block
		+ """
];

const ROUND_C_HEADERS = [
\t'方案',
\t'止损',
\t'止盈',
\t'尾盘',
\t'N开盘',
\t'N盘中',
\t'N上证MA5',
\t'N弱转到期',
\t'N',
\t'合计%',
\t'夏普',
\t'胜率%',
\t'最大回撤%',
\t'波动率%',
\t'盈亏比(均)',
];

const ROUND_C_ROWS: string[][] = [
"""
		+ c_block
		+ """
];

const ROUND_D_HEADERS = [
\t'方案',
\t'开盘SL',
\t'开盘TP',
\t'盘中SL',
\t'盘中TP',
\t'尾盘',
\t'D1弱',
\t'最长',
\t'N',
\t'合计%',
\t'夏普',
\t'胜率%',
\t'最大回撤%',
\t'波动率%',
\t'盈亏比(均)',
];

const ROUND_D_ROWS: string[][] = [
"""
		+ d_block
		+ """
];

const ROUND_E_HEADERS = [
\t'方案',
\t'止损',
\t'止盈',
\t'尾盘',
\t'N开盘',
\t'N破位',
\t'N弱转到期',
\t'N',
\t'合计%',
\t'夏普',
\t'胜率%',
\t'最大回撤%',
\t'波动率%',
\t'盈亏比(均)',
];

const ROUND_E_ROWS: string[][] = [
"""
		+ e_block
		+ """
];

export default function DafengniuSellComboScanCanvas() {
\treturn (
\t\t<Stack gap={18}>
\t\t\t<H1>卖出规则组合扫描（第一轮 A / B / C / D / E）</H1>
\t\t\t<Text tone="secondary" size="small">
\t\t\t\t固定买入与 MA5 门控；扫描脚本：python qmt/scripts/dafengniu_sell_combo_scan.py。CSV：
\t\t\t\tqmt/实盘策略/测试组合表格/dafengniu_sell_combo_scan_round_*.csv。
\t\t\t\tB：仅统计盘中平仓笔（旧版轮次 D）。C：全路径主表（旧版轮次 B）。D：异质开盘/盘中单行（旧版轮次 F）。E：与 C 同参但跳过盘中触价。
\t\t\t</Text>
\t\t\t<Callout tone="info" title="更新画布">
\t\t\t\tpython qmt/scripts/dafengniu_sell_combo_scan.py（或 --round A|B|C|D|E|all）→ python qmt/scripts/_emit_canvas_round_a.py → python qmt/scripts/_write_sell_combo_canvas.py
\t\t\t</Callout>

\t\t\t<H2>A：仅统计开盘平仓笔；基准 + 固定对照，其下为筛选网格</H2>
\t\t\t<Table headers={ROUND_A_HEADERS} rows={ROUND_A_ROWS} />

\t\t\t<Divider />

\t\t\t<H2>B：仅统计盘中止损/止盈（开盘未先触发；开盘与盘中同档 SL·TP）</H2>
\t\t\t<Table headers={ROUND_B_HEADERS} rows={ROUND_B_ROWS} />

\t\t\t<Divider />

\t\t\t<H2>C：全路径；多档 SL/TP；N开盘·N盘中·N上证MA5·N弱转到期 为归因笔数（四项之和等于 N）</H2>
\t\t\t<Table headers={ROUND_C_HEADERS} rows={ROUND_C_ROWS} />

\t\t\t<Divider />

\t\t\t<H2>D：异质开盘/盘中 SL·TP（3×3 交叉；另 −8% 开盘×固定盘中 −10%/6.5%；破 MA5·0.50%·D3）</H2>
\t\t\t<Table headers={ROUND_D_HEADERS} rows={ROUND_D_ROWS} />

\t\t\t<Divider />

\t\t\t<H2>E：无盘中触价；N开盘·N破位(上证收低于 MA5)·N弱转到期 三项之和等于 N</H2>
\t\t\t<Table headers={ROUND_E_HEADERS} rows={ROUND_E_ROWS} />
\t\t</Stack>
\t);
}
"""
	)


if __name__ == "__main__":
	if not ROWS_TXT.is_file():
		raise SystemExit("missing %s — run qmt/scripts/_emit_canvas_round_a.py first" % ROWS_TXT)
	body = normalize_rows(ROWS_TXT.read_text(encoding="utf-8"))
	CANVAS.parent.mkdir(parents=True, exist_ok=True)
	CANVAS.write_text(ROUND_A_HEADER + body + build_footer(), encoding="utf-8")
	print("[OK] %s (%d bytes)" % (CANVAS, CANVAS.stat().st_size))
