# -*- coding: utf-8 -*-
"""F1-F30 各档：固定买入×持有1~3天 + 原规则(default) 扫描，找最优组合并对比组合回测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT))
from dafengniu_paths import YIDONG_REGULATION_STOCKS_CSV  # noqa: E402
from dafengniu_benchmark_ref_trades import compute_extended_metrics  # noqa: E402
from yidong_regulation_backtest_core import (  # noqa: E402
	FIXED_RULE_SPECS,
	MAX_DATA_DAY,
	MAX_SELL_DAY,
	STOP_MIN_DAY,
	STOP_PCT,
	_day_col,
	_num,
	_pack_trade,
	_try_plate_close_sell,
	build_code_trade_dates,
	build_g_zero,
	is_buy_day_blocked,
	is_limit_skip_row,
	load_yidong,
	run_backtest,
	_simulate_fixed_sell,
	trade_date_at_offset,
)

CSV = Path(YIDONG_REGULATION_STOCKS_CSV)
OUT_JSON = _SCRIPT.parent / "实盘策略" / "测试组合表格" / "yidong_f1_30_hold_optimal.json"
MIN_N = 8

BUYS = [
	("T收盘", 0, "close"),
	("T+1开盘", 1, "open"),
	("T+1收盘", 1, "close"),
	("T+2开盘", 2, "open"),
]
HOLDS = (1, 2, 3)


def collect_f_rows(df: pd.DataFrame, f: int) -> pd.DataFrame:
	mask = (
		df["F"].eq(f)
		& df["G"].eq(1)
		& df["T日_收盘"].astype(str).str.strip().ne("")
		& ~df.apply(is_limit_skip_row, axis=1)
	)
	return df.loc[mask].copy().reset_index(drop=True)


def _simulate_default(row, g0, cd):
	if is_buy_day_blocked(row, 0, "close"):
		return None
	buy_px = _num(row.get("T日_收盘"))
	if buy_px is None:
		return None
	code = str(row["股票代码"])
	t_day = str(row["T日"])
	stop_line = buy_px * (1.0 - STOP_PCT / 100.0)
	sell_px = None
	sell_day = ""
	reason = ""
	hold_lows: list = []
	stop_active = False
	last_off = min(MAX_SELL_DAY, MAX_DATA_DAY)
	for off in range(1, MAX_DATA_DAY + 1):
		c = _num(row.get(_day_col(off, "收盘")))
		lo = _num(row.get(_day_col(off, "最低")))
		if c is None:
			break
		hold_lows.append(lo)
		td = trade_date_at_offset(code, t_day, off, cd)
		if td and (code, td) in g0:
			res = _try_plate_close_sell(row, off, code, t_day, cd, "G0强平")
			if res:
				sell_px, sell_day, reason = res
				break
			continue
		if off >= STOP_MIN_DAY and lo is not None and lo <= stop_line + 1e-9:
			stop_active = True
		if stop_active:
			res = _try_plate_close_sell(
				row, off, code, t_day, cd, "止损%d%%(T+%d收盘)" % (int(STOP_PCT), off)
			)
			if res:
				sell_px, sell_day, reason = res
				break
			continue
		if off == last_off:
			res = _try_plate_close_sell(row, last_off, code, t_day, cd, "未触发止损 T+6收盘")
			if res:
				sell_px, sell_day, reason = res
				break
	if sell_px is None:
		return None
	return _pack_trade(
		row, buy_px=buy_px, sell_px=sell_px, sell_day=sell_day, buy_cal=t_day,
		reason=reason, rule_id="default", hold_lows=hold_lows, t_day=t_day,
	)


def _metrics(rows: list[dict]) -> dict | None:
	if len(rows) < MIN_N:
		return None
	rets = np.array([float(x["收益率%"]) for x in rows], dtype=float)
	buy_days = [str(x.get("买入日", x.get("开仓日", ""))) for x in rows]
	ext = compute_extended_metrics(rets, buy_days)
	n = len(rets)
	pos = rets[rets > 0]
	neg = rets[rets < 0]
	return {
		"笔数": n,
		"胜率_pct": round(100.0 * (rets > 0).mean(), 2),
		"平均收益_pct": round(float(rets.mean()), 4),
		"中位收益_pct": round(float(np.median(rets)), 4),
		"收益标准差_pct": round(float(rets.std(ddof=1)) if n > 1 else 0.0, 4),
		"收益方差": round(float(rets.var(ddof=1)) if n > 1 else 0.0, 6),
		"单笔最大收益_pct": round(float(rets.max()), 4),
		"单笔最小收益_pct": round(float(rets.min()), 4),
		"合计收益_pct": round(float(rets.sum()), 2),
		"合计金额_元": round(sum(float(x.get("收益金额", 0)) for x in rows), 2),
		"盈亏比_均盈除均亏": ext.get("盈亏比_均盈除以均亏绝对值"),
		"链式回撤_pct": ext.get("最大回撤_链式净值_pct"),
	}


def _run_fixed(sub, g0, cd, buy_off, kind, hold) -> dict | None:
	rows = []
	sell_off = buy_off + hold
	for _, r in sub.iterrows():
		t = _simulate_fixed_sell(
			r, g0, cd, buy_off=buy_off, buy_kind=kind,
			sell_off=sell_off, rule_id="scan",
		)
		if t:
			rows.append(t)
	return _metrics(rows)


def scan_one_f(df, g0, cd, f: int) -> dict:
	sub = collect_f_rows(df, f)
	out: dict = {"F": f, "样本行数": len(sub), "候选": [], "最优": None}
	if len(sub) < MIN_N:
		out["备注"] = "样本不足"
		return out

	candidates: list[tuple[str, dict]] = []

	for hold in HOLDS:
		for label, boff, kind in BUYS:
			sell_off = boff + hold
			if sell_off > MAX_DATA_DAY:
				continue
			m = _run_fixed(sub, g0, cd, boff, kind, hold)
			if not m:
				continue
			tag = "%s→T+%d收 持%d天" % (label, sell_off, hold)
			entry = {"规则": tag, "买入": label, "持有天": hold, **m}
			out["候选"].append(entry)
			candidates.append((tag, m))

	rows_def = []
	for _, r in sub.iterrows():
		t = _simulate_default(r, g0, cd)
		if t:
			rows_def.append(t)
	md = _metrics(rows_def)
	if md:
		entry = {"规则": "原规则(T收+8%止损+T+6)", "买入": "T收盘", "持有天": None, **md}
		out["候选"].append(entry)
		candidates.append((entry["规则"], md))

	if not candidates:
		out["备注"] = "无有效成交"
		return out

	best_entry = max(out["候选"], key=lambda x: x["合计金额_元"])
	out["最优"] = best_entry
	return out


def _summary_from_trades(tdf: pd.DataFrame) -> dict:
	rets = tdf["收益率%"].astype(float).values
	buy_days = tdf["开仓日"].astype(str).tolist()
	ext = compute_extended_metrics(rets, buy_days)
	n = len(rets)
	return {
		"成交笔数": n,
		"胜率_pct": round(100.0 * (rets > 0).mean(), 2),
		"平均收益_pct": round(float(rets.mean()), 4),
		"中位收益_pct": round(float(np.median(rets)), 4),
		"收益标准差_pct": round(float(rets.std(ddof=1)) if n > 1 else 0.0, 4),
		"收益方差": round(float(rets.var(ddof=1)) if n > 1 else 0.0, 6),
		"单笔最大收益_pct": round(float(rets.max()), 4),
		"单笔最小收益_pct": round(float(rets.min()), 4),
		"合计收益_pct": round(float(rets.sum()), 2),
		"合计金额_元": round(float(tdf["收益金额"].sum()), 2),
		"盈亏比_均盈除均亏": ext.get("盈亏比_均盈除以均亏绝对值"),
		"链式回撤_pct": ext.get("最大回撤_链式净值_pct"),
	}


def run_portfolio_with_f_rules(df, f_rule_map: dict[int, str]) -> tuple[pd.DataFrame, dict]:
	"""f_rule_map: F -> rule_id (fix_* or default)."""
	import yidong_regulation_backtest_core as core

	orig = core.f_trade_rule

	def patched(f_val):
		if pd.isna(f_val):
			return "default"
		f = int(f_val)
		if f in core.SKIP_F or f in core.NO_TRADE_F:
			return None
		return f_rule_map.get(f, "default")

	core.f_trade_rule = patched
	tdf, summ = run_backtest(df, same_day_no_buy=False)
	core.f_trade_rule = orig
	summ["组合指标"] = _summary_from_trades(tdf) if not tdf.empty else {}
	return tdf, summ


def _rule_id_from_scan(best: dict) -> str:
	"""把扫描最优标签映射为 core rule_id。"""
	rule = best.get("规则", "")
	if "原规则" in rule:
		return "default"
	buy = best.get("买入", "")
	hold = best.get("持有天")
	if hold is None:
		return "default"
	sell_off = {"T收盘": 0, "T+1开盘": 1, "T+1收盘": 1, "T+2开盘": 2}.get(buy, 0) + hold
	kind = "o" if "开盘" in buy else "c"
	boff = {"T收盘": 0, "T+1开盘": 1, "T+1收盘": 1, "T+2开盘": 2}.get(buy, 0)
	rid = "fix_t%d%s_t%d%c" % (boff, kind, sell_off, "c")
	return rid if rid in FIXED_RULE_SPECS else "default"


def build_user_preset_map() -> dict[int, str]:
	return {
		6: "fix_t0c_t1c",
		4: "fix_t2o_t3c",
		7: "fix_t2o_t3c",
		2: "fix_t1o_t3c",
		3: "fix_t1o_t3c",
		8: "fix_t1o_t3c",
		9: "fix_t1o_t3c",
		10: "fix_t1o_t3c",
		30: "fix_t1o_t3c",
	}


def main() -> None:
	df = load_yidong(CSV)
	g0 = build_g_zero(df)
	cd = build_code_trade_dates(df)

	print("=" * 100)
	print("F1-F30 单档扫描 | G=1 | 现行买入过滤(跌幅带+涨幅阈值) | G0强平 | 单票10万")
	print("=" * 100)

	per_f: list[dict] = []
	optimal_map: dict[int, str] = {}

	for f in range(1, 31):
		res = scan_one_f(df, g0, cd, f)
		per_f.append(res)
		if res.get("最优"):
			optimal_map[f] = _rule_id_from_scan(res["最优"])
			b = res["最优"]
			print(
				"F%2d | 样本%3d | 最优: %-28s | %3d笔 | 胜率%5.1f%% | 均%6.2f%% | "
				"σ%5.2f | 最大%6.1f%% 最小%6.1f%% | 盈亏比%4.2f | 回撤%6.1f%% | 金额%8.0f"
				% (
					f, res["样本行数"], b["规则"], b["笔数"], b["胜率_pct"], b["平均收益_pct"],
					b["收益标准差_pct"], b["单笔最大收益_pct"], b["单笔最小收益_pct"],
					b["盈亏比_均盈除均亏"] or 0, b["链式回撤_pct"] or 0, b["合计金额_元"],
				)
			)
		else:
			print("F%2d | 样本%3d | %s" % (f, res["样本行数"], res.get("备注", "—")))

	print("\n" + "=" * 100)
	print("组合回测对比")
	print("=" * 100)

	_, s_user = run_portfolio_with_f_rules(df, build_user_preset_map())
	print("\n【用户指定分档】")
	u = s_user.get("组合指标", {})
	for k, v in u.items():
		print("  %s: %s" % (k, v))

	_, s_opt = run_portfolio_with_f_rules(df, optimal_map)
	print("\n【各F扫描最优拼接】")
	o = s_opt.get("组合指标", {})
	for k, v in o.items():
		print("  %s: %s" % (k, v))

	# 汇总 rule 分组
	from collections import defaultdict

	groups: dict[str, list[int]] = defaultdict(list)
	for f, rid in sorted(optimal_map.items()):
		groups[rid].append(f)

	print("\n【各F最优规则分组】")
	for rid, flist in sorted(groups.items()):
		print("  %s: F=%s" % (rid, ",".join(str(x) for x in flist)))

	payload = {
		"扫描说明": "每F独立扫描固定持满+原规则; 最优按合计金额",
		"单F结果": per_f,
		"最优拼接_map": {str(k): v for k, v in optimal_map.items()},
		"用户指定组合": u,
		"最优拼接组合": o,
	}
	OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
	OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
	print("\nJSON ->", OUT_JSON)


if __name__ == "__main__":
	main()
