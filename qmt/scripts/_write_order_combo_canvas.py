# -*- coding: utf-8 -*-
"""写入 dafengniu-order-combo-scan.canvas.tsx：ORDER「A/B/C」、五档补仓切片与回落补仓回测表。

详见 `dafengniu_order_abc_position_canvas`、`dafengniu_order_c_ladder`、`dafengniu_order_c_ladder_backtest`
（含 ORDER-C 实盘约定等权 vs 档权重汇总表）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)

CANVAS = Path(
	os.path.normpath(
		os.path.join(
			os.path.expanduser("~"),
			".cursor",
			"projects",
			"c-Users-admin-Projects-belllla-web",
			"canvases",
			"dafengniu-order-combo-scan.canvas.tsx",
		)
	)
)


def build_canvas() -> str:
	from dafengniu_order_abc_position_canvas import abc_position_canvas_fragments
	from dafengniu_order_c_ladder import order_c_ladder_canvas_fragments
	from dafengniu_order_c_ladder_backtest import (
		ladder_backtest_canvas_fragments,
		order_c_adopted_summary_canvas_fragments,
	)
	from dafengniu_order_b_ladder_backtest import group_b_ladder_canvas_fragments

	abc_constants, abc_jsx = abc_position_canvas_fragments(require_ma5=True)
	ladder_constants, ladder_jsx = order_c_ladder_canvas_fragments()
	bt_constants, bt_jsx = ladder_backtest_canvas_fragments(require_sse_ma5=True)
	sum_constants, sum_jsx = order_c_adopted_summary_canvas_fragments(require_sse_ma5=True)
	b_ladder_constants, b_ladder_jsx = group_b_ladder_canvas_fragments(require_sse_ma5=True)
	return (
		"""import { Callout, Divider, H1, H2, Stack, Table, Text } from 'cursor/canvas';

/** ORDER：三组独立买扫 + 仓位（脚本 qmt/scripts/dafengniu_order_abc_position_canvas.py） */

"""
		+ abc_constants
		+ ladder_constants
		+ bt_constants
		+ sum_constants
		+ b_ladder_constants
		+ """
export default function DafengniuOrderComboScanCanvas() {
	return (
		<Stack gap={18}>
			<H1>ORDER：A / B / C — 买扫与仓位</H1>
			<Text tone="secondary" size="small">
				固定卖出与回测 D 一致：开盘 −10% / +6.5%，盘中同档；上证收盘破 MA5 尾盘；D1 弱 0.5%；最长 D3。
				固定门控：T−1 上证收 ≥ T−1 MA5。数据来源：dafengniu_sync_open_baostock.csv（与组合扫描同一套成交回放）。
			</Text>
			<Callout tone="info" title="更新画布">
				python qmt/scripts/_write_order_combo_canvas.py（仅需 baostock 同步 CSV，无需先跑 buy_combo_scan）
			</Callout>

			<Divider />
"""
		+ abc_jsx
		+ ladder_jsx
		+ bt_jsx
		+ sum_jsx
		+ b_ladder_jsx
		+ """
		</Stack>
	);
}
"""
	)


def main() -> None:
	body = build_canvas()
	CANVAS.parent.mkdir(parents=True, exist_ok=True)
	CANVAS.write_text(body, encoding="utf-8")
	print("[OK] %s (%d bytes)" % (CANVAS, CANVAS.stat().st_size))


if __name__ == "__main__":
	main()
