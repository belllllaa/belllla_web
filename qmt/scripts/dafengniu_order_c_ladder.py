# -*- coding: utf-8 -*-
"""ORDER-C 实盘约定（当前）：**资金等权**，五档只决定「首买 / 补仓① / 补仓②」占比；补仓回落 **全局统一**。

**1）可交易区间与分档**

- D0 开盘相对昨收的涨跌幅度 ``gap_pct``（%），仅在 **(-5, 8]** 内执行 ORDER-C（左开右闭与 `gap_pct_to_bin_index` 一致）。
- 将该区间划为 **五档**（见 `ORDER_C_LADDER_BIN_LABELS`）。落在哪一档，就用该档的 **`ORDER_C_LADDER_LEG_FRAC`**：
  三元组 ``(首买占比, 补仓①占比, 补仓②占比)``，三者之和为 1，表示把 **该笔当日分给这只票的总名义** 拆成三笔限价/计划的名额。

**2）资金（等权，不按档乘系数）**

- 日度总预算 **`ORDER_C_DAILY_BUDGET_YUAN`**（默认 60 万），当日最多 **`ORDER_C_MAX_STOCKS_PER_DAY`** 只（默认 3）。
- **预算按当日实际信号笔数等额划分**：`order_c_daily_budget_split_for_signals_yuan([gap...])` 返回每只 **60万÷n**（n=1..3），
  **与 gap 落在哪一档无关**（不做「优质档多给钱」）。
- 单笔总名义上通常取分配到的 cap，再乘该档三腿比例：
  `order_c_notional_three_legs_yuan(gap_pct, cap_yuan)`（默认 **不** 再乘 `ORDER_C_BIN_WEIGHTS`）。
- `ORDER_C_SLOT_CAP_YUAN`（60÷3=20 万）表示 **三只同日时每只满额** 的口径；仅一只信号当日可独占 **60 万**。

**3）补仓触发（与回测「全局统一·2%/3.0%」一致，日线近似）**

- 用 **D0 最低价相对 D0 开盘价** 的最大下探幅度（%）代表当日相对开盘的最大回落。
- **所有五档共用同一组阈值**：补仓①在相对开盘下探 ≥ **`ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT[0]`**（2%）时认为可在约定价位成交；
  补仓②在下探 ≥ **`ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT[1]`**（3%）时同理（具体成交价模型见 `dafengniu_order_c_ladder_backtest`）。
- 不按档切换不同的 T1/T2（不做「分档递增门槛」那一套）。

**4）与画布/扫描里 `ORDER_C_BIN_WEIGHTS` 的关系**

- `dafengniu_order_abc_position_canvas` 中的归一化权重仍可用于 **历史回测对比、Σ(w×r) 加权笔均**；
  **实盘 ORDER-C 名义分配以本模块「等权日预算」为准**，二者勿混为一谈。

用法：
  from dafengniu_order_c_ladder import (
      ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT,
      order_c_daily_budget_split_for_signals_yuan,
      order_c_notional_three_legs_yuan,
  )
  caps = order_c_daily_budget_split_for_signals_yuan([-1.2, 1.0, 6.0])  # 三只 → 各约 20 万
  y = order_c_notional_three_legs_yuan(-1.2, caps[0])  # 默认不按档权重缩小总名义
"""

from __future__ import annotations

import json
from typing import Any

# 与 `dafengniu_order_abc_position_canvas.ORDER_C_BIN_SLICE_LABELS` 顺序一致
ORDER_C_LADDER_BIN_LABELS: tuple[str, str, str, str, str] = (
	"(-5,-2]",
	"(-2,0]",
	"(0,2]",
	"(2,5]",
	"(5,8]",
)

# 每档：(首买, 补仓①, 补仓②) 占「该档总名义」的比例
ORDER_C_LADDER_LEG_FRAC: tuple[tuple[float, float, float], ...] = (
	(0.35, 0.35, 0.30),  # 深低开：分化大、中位数偏弱 → 首买保守，更多留给盘中下探
	(0.50, 0.30, 0.20),  # 中小低开：与实盘基准 0.5/0.3/0.2 一致
	(0.48, 0.30, 0.22),  # 小幅高开：日内略偏强 → 略提高首买
	(0.38, 0.34, 0.28),  # 中高开：易回吐 → 降首买、抬补仓
	(0.32, 0.38, 0.30),  # 强高开：样本内更易当日走弱 → 首买最小，补仓②略抬
)

for _t in ORDER_C_LADDER_LEG_FRAC:
	assert abs(sum(_t) - 1.0) < 1e-9, _t

# 日度资金：60 万 ÷ 每日最多 3 只 → 单笔满额 20 万（与画布示例一致）
ORDER_C_DAILY_BUDGET_YUAN: float = 600_000.0
ORDER_C_MAX_STOCKS_PER_DAY: int = 3
ORDER_C_SLOT_CAP_YUAN: float = ORDER_C_DAILY_BUDGET_YUAN / float(ORDER_C_MAX_STOCKS_PER_DAY)

# 与 `dafengniu_order_c_ladder_backtest.ORDER_C_ADOPTED_PROFILE_LABEL`「全局统一·2%/3.0%」一致（补仓① / 补仓② 阈值，单位：%）
ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT: tuple[float, float] = (2.0, 3.0)


def gap_pct_to_bin_index(gap_pct: float) -> int | None:
	"""ORDER-C 可交易区间 (-5,8] 内返回 0..4；否则 None。"""
	x = float(gap_pct)
	if x <= -5.0 or x > 8.0:
		return None
	if x <= -2.0:
		return 0
	if x <= 0.0:
		return 1
	if x <= 2.0:
		return 2
	if x <= 5.0:
		return 3
	return 4


def ladder_leg_fractions_for_gap_pct(gap_pct: float) -> tuple[float, float, float] | None:
	"""返回 (首买占比, 补仓①占比, 补仓②占比)，不在 ORDER-C 区间内则 None。"""
	j = gap_pct_to_bin_index(gap_pct)
	if j is None:
		return None
	return ORDER_C_LADDER_LEG_FRAC[j]


def order_c_total_cap_yuan(
	gap_pct: float,
	cap_max_yuan_per_stock: float = 200_000.0,
	*,
	use_bin_weight: bool = False,
) -> float:
	"""该笔「总名义」上限（元）。

	- ``use_bin_weight=False``（**实盘默认**）：恒为 ``cap_max_yuan_per_stock``（不与 gap 档相乘）。
	- ``use_bin_weight=True``：= ``cap_max × ORDER_C_BIN_WEIGHTS[j]``，仅用于与历史加权口径对比。
	"""
	j = gap_pct_to_bin_index(gap_pct)
	if j is None:
		return 0.0
	if not use_bin_weight:
		return float(cap_max_yuan_per_stock)
	from dafengniu_order_abc_position_canvas import ORDER_C_BIN_WEIGHTS

	return float(cap_max_yuan_per_stock) * float(ORDER_C_BIN_WEIGHTS[j])


def order_c_daily_budget_split_for_signals_yuan(
	gap_pcts: list[float],
	*,
	daily_budget_yuan: float = ORDER_C_DAILY_BUDGET_YUAN,
) -> list[float]:
	"""当日 1～3 笔信号时，将 **日预算等额划分**：第 i 笔分得 ``daily_budget / n``（``n=len(gap_pcts)``）。

	**与 gap 落在哪一档无关**（五档只用于 `ORDER_C_LADDER_LEG_FRAC` 与统计）。各笔之和恒等于 ``daily_budget``（最后一笔吸收舍入差）。
	参数 ``gap_pcts`` 仍传入以便调用方对齐信号顺序；不参与加权。
	"""
	n = len(gap_pcts)
	if n > ORDER_C_MAX_STOCKS_PER_DAY:
		raise ValueError("当日信号数不能超过 ORDER_C_MAX_STOCKS_PER_DAY")
	if n == 0:
		return []
	per = float(daily_budget_yuan) / float(n)
	out = [round(per, 2)] * n
	diff = round(float(daily_budget_yuan) - float(sum(out)), 2)
	if out and abs(diff) >= 0.005:
		out[-1] = round(out[-1] + diff, 2)
	return out


def order_c_notional_three_legs_yuan(
	gap_pct: float,
	cap_max_yuan_per_stock: float = 200_000.0,
	*,
	use_bin_weight: bool = False,
) -> tuple[float, float, float] | None:
	"""首买、补仓①、补仓② 名义金额（元）= 总名义 × 该档 ``ORDER_C_LADDER_LEG_FRAC``。

	``use_bin_weight=False``（默认）：总名义 = ``cap_max_yuan_per_stock``。
	``use_bin_weight=True``：总名义 = ``cap × ORDER_C_BIN_WEIGHTS``（对比/回测用）。
	"""
	legs = ladder_leg_fractions_for_gap_pct(gap_pct)
	if legs is None:
		return None
	total = float(
		order_c_total_cap_yuan(
			gap_pct,
			cap_max_yuan_per_stock,
			use_bin_weight=use_bin_weight,
		)
	)
	f0, f1, f2 = legs
	return (
		round(total * f0, 2),
		round(total * f1, 2),
		round(total * f2, 2),
	)


def order_c_ladder_canvas_fragments() -> tuple[str, str]:
	"""生成写入 `dafengniu-order-combo-scan.canvas.tsx` 的常量与 JSX 片段。"""
	def esc(x: object) -> str:
		if x is None:
			return "—"
		return str(x).replace("\\", "\\\\").replace("'", "\\'")

	slot = float(ORDER_C_SLOT_CAP_YUAN)
	t1, t2 = ORDER_C_ADOPTED_PULLBACK_UNIFORM_PCT
	intro = (
		"**实盘约定**：**资金等权** —— 当日 n 笔 ORDER-C 信号（n=1～3）分配 **60万÷n**，与 gap 落在哪一档无关。"
		"五档仅决定 **`ORDER_C_LADDER_LEG_FRAC`**（首买 / 补仓① / 补仓② 占该笔总名义的比例）。"
		"补仓触发阈值 **五档共用**：相对 D0 开盘价最大下探 ≥ **%.1f%%** 视为补仓①可成交，≥ **%.1f%%** 为补仓②（日线近似，与回测「全局统一·2%%/3.0%%」一致）。"
		"示例金额列：按 **满额三只口径 20 万/笔** × 各档三腿比例（单只独占当日时可分得 60 万，同公式乘以更大 cap）。"
		"组合扫描画布里的 `ORDER_C_BIN_WEIGHTS` 仍用于历史加权笔均，**不等于** 本条实盘分钱规则。"
	) % (t1, t2)
	dyn_intro = (
		"等额分预算示例：`order_c_daily_budget_split_for_signals_yuan` —— **1 笔→60 万**，**2 笔→各 30 万**，"
		"**3 笔→各 20 万**（合计恒 60 万）。再对各笔用 `order_c_notional_three_legs_yuan(gap, cap)` 拆三腿（默认不按档系数缩放总名义）。"
	)

	rows: list[list[str]] = []
	for i, lb in enumerate(ORDER_C_LADDER_BIN_LABELS):
		f0, f1, f2 = ORDER_C_LADDER_LEG_FRAC[i]
		ex_open = round(slot * f0, 0)
		ex_a1 = round(slot * f1, 0)
		ex_a2 = round(slot * f2, 0)
		rows.append(
			[
				lb,
				"等额 60万÷n",
				"%.0f%%" % (f0 * 100,),
				"%.0f%%" % (f1 * 100,),
				"%.0f%%" % (f2 * 100,),
				"%d" % int(ex_open),
				"%d" % int(ex_a1),
				"%d" % int(ex_a2),
			]
		)

	lines = []
	for r in rows:
		lines.append(
			"\t['%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'],"
			% tuple(esc(c) for c in r)
		)

	constants = (
		"""
const ORDER_C_LADDER_INTRO = """
		+ json.dumps(intro, ensure_ascii=False)
		+ """;

const ORDER_C_LADDER_DYNAMIC_INTRO = """
		+ json.dumps(dyn_intro, ensure_ascii=False)
		+ """;

const ORDER_C_LADDER_HEADERS = [
\t'开盘涨跌分档',
\t'日预算(实盘)',
\t'首买%',
\t'补仓①%',
\t'补仓②%',
\t'示例首买¥(单笔20万)',
\t'示例补仓①¥',
\t'示例补仓②¥',
];

const ORDER_C_LADDER_ROWS: string[][] = [
"""
		+ "\n".join(lines)
		+ """
];
"""
	)

	jsx = """

\t\t\t<H2>ORDER-C：五档优化买入（首买 + 两档补仓）</H2>
\t\t\t<Text tone="secondary" size="small">{ORDER_C_LADDER_INTRO}</Text>
\t\t\t<Text tone="secondary" size="small">{ORDER_C_LADDER_DYNAMIC_INTRO}</Text>
\t\t\t<Table headers={ORDER_C_LADDER_HEADERS} rows={ORDER_C_LADDER_ROWS} />
"""

	return constants, jsx


def ladder_snapshot_for_docs() -> dict[str, Any]:
	"""便于脚本打印自查。"""
	out: dict[str, Any] = {"bins": []}
	probes = (-3.0, -1.0, 1.0, 3.0, 6.0)
	for i, lb in enumerate(ORDER_C_LADDER_BIN_LABELS):
		yuan = order_c_notional_three_legs_yuan(
			probes[i], ORDER_C_SLOT_CAP_YUAN, use_bin_weight=False
		)
		out["bins"].append(
			{
				"label": lb,
				"leg_frac": ORDER_C_LADDER_LEG_FRAC[i],
				"example_yuan_open_add1_add2": yuan,
			}
		)
	return out
