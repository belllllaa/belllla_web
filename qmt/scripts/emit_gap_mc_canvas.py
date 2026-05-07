# -*- coding: utf-8 -*-
"""从 dafengniu_gap_mc_2k.json（或指定 JSON）生成 Cursor Canvas TSX（嵌入全量 combinations）。"""
from __future__ import annotations

import json
import os
import sys

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
JSON_PATH = os.path.join(_REPO, "qmt", "scripts", "output", "dafengniu_gap_mc_2k.json")
_CANVAS_DIR = os.path.join(
	os.environ.get("USERPROFILE", "C:\\Users\\admin"),
	".cursor",
	"projects",
	"c-Users-admin-Projects-belllla-web",
	"canvases",
)
CANVAS_PATH = os.path.join(_CANVAS_DIR, "dafengniu-gap-mc-2k.canvas.tsx")


def main() -> None:
	json_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else JSON_PATH
	canvas_path = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else CANVAS_PATH
	with open(json_path, "r", encoding="utf-8") as f:
		d = json.load(f)
	comb = d.get("combinations") or []
	if len(comb) < int(d.get("n_valid_results", 0) or 0):
		raise SystemExit("JSON 缺少 combinations 全量数组，请先运行 qmt/scripts/dafengniu_gap_mc_1k_backtest.py 生成 JSON")

	comb_js = json.dumps(comb, ensure_ascii=False, indent=2)
	bm = json.dumps(d.get("baseline_metrics") or {}, ensure_ascii=False, separators=(",", ":"))
	su = json.dumps(d.get("summary") or {}, ensure_ascii=False, separators=(",", ":"))
	best = json.dumps(d.get("best") or {}, ensure_ascii=False, separators=(",", ":"))
	seed = int(d.get("seed", 42))
	csv_note = str(d.get("csv", ""))
	n = len(comb)
	gb = d.get("gap_edge_bounds_pct") or {}
	lo, hi = gb.get("lo"), gb.get("hi")
	if lo is not None and hi is not None:
		bounds_note = f"三档分界均在 [{lo}%, {hi}%] 内随机（贴近涨跌幅、兼顾流动性）"
	else:
		bounds_note = "三档分界在涨跌幅合理区间内随机"

	body = """import { Callout, Divider, Grid, H1, H2, Stack, Stat, Table, Text } from 'cursor/canvas';

type ComboRow = {
	e_d_pct: number;
	e_ab_pct: number;
	e_bc_pct: number;
	n: number;
	win_rate_pct: number;
	mean_return_pct: number;
	sum_return_pct: number;
	nav_chain: number;
};

const SEED = __SEED__;
const CSV_NOTE = __CSV__;
const BASELINE = __BM__ as ComboRow & { label?: string };
const SUMMARY = __SU__;
const BEST = __BEST__ as ComboRow;
const COMBINATIONS: ComboRow[] = __COMB__;

export default function DafengniuGapMcCanvas() {
	const baseRow = [
		'基准',
		`${BASELINE.e_d_pct}%`,
		`${BASELINE.e_ab_pct}%`,
		`${BASELINE.e_bc_pct}%`,
		String(BASELINE.n),
		`${BASELINE.win_rate_pct}%`,
		`${BASELINE.mean_return_pct}%`,
		`${BASELINE.sum_return_pct}%`,
		String(BASELINE.nav_chain),
	];
	const bestRow = [
		'排序#1',
		`${BEST.e_d_pct}%`,
		`${BEST.e_ab_pct}%`,
		`${BEST.e_bc_pct}%`,
		String(BEST.n),
		`${BEST.win_rate_pct}%`,
		`${BEST.mean_return_pct}%`,
		`${BEST.sum_return_pct}%`,
		String(BEST.nav_chain),
	];
	const allRows = COMBINATIONS.map((r, i) => [
		String(i + 1),
		`${r.e_d_pct}%`,
		`${r.e_ab_pct}%`,
		`${r.e_bc_pct}%`,
		String(r.n),
		`${r.win_rate_pct}%`,
		`${r.mean_return_pct}%`,
		`${r.sum_return_pct}%`,
		String(r.nav_chain),
	]);

	return (
		<Stack gap={18}>
			<H1>dafengniu gap 蒙特卡洛 __N__ 组</H1>
			<Text tone="secondary" size="small">{`样本：固定卖出；D/A 直接买，B/C 需 D0 最低触价；__BOUNDS__；seed=${String(SEED)}`}</Text>
			<Text tone="secondary" size="small">{CSV_NOTE}</Text>
			<Callout tone="info" title="极值（全 __N__ 组内）">
				{`最高胜率 ${SUMMARY.max_win_rate}% · 最高均笔 ${SUMMARY.max_mean_return}% · 最高链式净值 ${SUMMARY.max_nav}`}
			</Callout>
			<Grid columns={3} gap={12}>
				<Stat value={`${SUMMARY.max_win_rate}%`} label="最高胜率" />
				<Stat value={`${SUMMARY.max_mean_return}%`} label="最高均笔收益" />
				<Stat value={String(SUMMARY.max_nav)} label="最高链式净值" />
			</Grid>
			<Divider />
			<H2>基准与当前排序第一</H2>
			<Table
				headers={['类型', 'e_d', 'e_ab', 'e_bc', 'N', '胜率', '均笔%', '合计%', '净值']}
				rows={[baseRow, bestRow]}
			/>
			<Divider />
			<H2>全部 __N__ 组（已按合计%、胜率降序）</H2>
			<Text tone="secondary" size="small">表列：序号为三档分界在样本上的回测排序。</Text>
			<Table
				headers={['#', 'e_d%', 'e_ab%', 'e_bc%', 'N', '胜率', '均笔%', '合计%', '净值']}
				rows={allRows}
			/>
		</Stack>
	);
}
"""
	body = (
		body.replace("__SEED__", str(seed))
		.replace("__CSV__", json.dumps(csv_note, ensure_ascii=False))
		.replace("__BM__", bm)
		.replace("__SU__", su)
		.replace("__BEST__", best)
		.replace("__COMB__", comb_js)
		.replace("__N__", str(n))
		.replace("__BOUNDS__", bounds_note)
	)

	os.makedirs(os.path.dirname(canvas_path), exist_ok=True)
	with open(canvas_path, "w", encoding="utf-8") as f:
		f.write(body)
	print("[canvas]", canvas_path, "rows", n)


if __name__ == "__main__":
	main()
