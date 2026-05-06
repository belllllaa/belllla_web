# -*- coding: utf-8 -*-
"""
买入分档 a/b/c/d + 统一卖出（锚定 D0 开盘），数据仅来自
qmt/实盘策略/dafengniu_open_window_metrics_qmt.csv（与 tmp_all_combo_filtered 相同过滤）。

CSV 仅有每日开/收、无高低价：日内低近似 low_i = min(Di_开盘, Di_收盘)。

昨收（用于 gap = D0开盘/昨收−1 及 D0 侧可卖判断）：
  **优先**：若 CSV 含任一下列且为有效正数，则作为真实 D0 前一日收盘：
    D0前收盘 / 昨收 / 前收盘 / PREV_CLOSE / prev_close
  **否则**：表内无 T-1 收盘时，仍用 D0_MA5 与 D0_收盘反推近似昨收（不推荐用于严肃回测）：
    prev_hat = (5*D0_MA5 - D0_收盘) / 4，gap = D0_开盘/prev_hat - 1
  若用作分档的昨收异常（<=0 或非有限）则跳过该样本。

卖出：开盘止损/止盈 7%，D1 收盘强弱（< D0开*1.005 则卖），D2/D3 转弱（收<=前收*1.005），最多 D3 收盘；跌停顺延逻辑同 tmp_all_combo_filtered。

用法：
  python qmt/scripts/dafengniu_buy_combo_backtest.py
  python qmt/scripts/dafengniu_buy_combo_backtest.py --grid
  python qmt/scripts/dafengniu_buy_combo_backtest.py --grid --step 0.05
  python qmt/scripts/dafengniu_buy_combo_backtest.py --grid-only-tier a
  # 单档网格：只扫该档三腿（或 d 单权重），a/b/c/d 其余固定为 buys_for_bucket 默认比例，卖出不变；输出 *_tier_a.csv
  python qmt/scripts/dafengniu_buy_combo_backtest.py --scan-a-hi 0.03 0.05 0.005
  python qmt/scripts/dafengniu_buy_combo_backtest.py --scan-a-gap-grid-default
  # 二维扫描 A 档 gap 下沿/上沿（默认 −5%%～+6.5%%，步长 0.5%%），写出 dafengniu_buy_a_gap_grid_scan.csv
"""
from __future__ import annotations

import argparse
import itertools
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
SRC = os.path.join(ROOT, "qmt", "实盘策略", "dafengniu_open_window_metrics_qmt.csv")
OUT = os.path.join(ROOT, "qmt", "实盘策略", "dafengniu_buy_combo_vs_sell_compare.csv")
OUT_GRID = os.path.join(ROOT, "qmt", "实盘策略", "dafengniu_buy_auto_weight_grid.csv")
OUT_A_GAP_HI_SCAN = os.path.join(ROOT, "qmt", "实盘策略", "dafengniu_buy_a_gap_hi_scan.csv")
OUT_A_GAP_GRID_SCAN = os.path.join(ROOT, "qmt", "实盘策略", "dafengniu_buy_a_gap_grid_scan.csv")

# gap 分界：D: g<=a_lo；A: a_lo<g<a_hi；B: a_hi<=g<b_hi；C: g>=b_hi（默认与旧版 −5%%/3%%/7%% 一致）
A_GAP_LO = -0.05
A_GAP_HI_DEFAULT = 0.03
B_GAP_HI = 0.07

# 真实 D0 前收盘：导出指标时优先写入其一，否则 gap 与昨收相关逻辑退回 MA5 近似
PREV_CLOSE_COLS = ("D0前收盘", "昨收", "前收盘", "PREV_CLOSE", "prev_close")
BASE_WA = (0.5, 0.3, 0.2)
BASE_WB = (0.5, 0.3, 0.2)
BASE_WC = (0.5, 0.2, 0.3)
BASE_WD = 0.5


def out_grid_tier_csv(tier: str) -> str:
	return os.path.join(ROOT, "qmt", "实盘策略", "dafengniu_buy_auto_weight_grid_tier_%s.csv" % tier.lower())


def _load_all_series_rows() -> tuple[list[dict], int, int]:
	"""全部过滤后行（不剔除 gap_bucket 为 None）；用于 gap 边界扫描。"""
	df0 = load_filtered_df()
	rows_raw: list[dict] = []
	bad_prev = 0
	for _, r in df0.iterrows():
		sx = csv_row_to_series(r)
		if sx is None:
			bad_prev += 1
			continue
		prev_c, o, lw, cl = sx
		d0o = float(o[0])
		g = d0o / float(prev_c) - 1.0
		row = row_from_lists(o, cl)
		rows_raw.append(
			{"prev_c": prev_c, "o": o, "lw": lw, "cl": cl, "row": row, "d0o": d0o, "g": g}
		)
	return rows_raw, len(df0), bad_prev


def _frange(a: float, b: float, step: float) -> list[float]:
	if step <= 0:
		raise ValueError("step must be positive")
	out: list[float] = []
	x = float(a)
	n = 0
	while x <= b + 1e-9 and n < 100000:
		out.append(round(x, 6))
		x = round(x + step, 10)
		n += 1
	return out


def _make_grid_samples():
	"""从指标 CSV 构造 gap 分档样本列表。"""
	df0 = load_filtered_df()
	samples = []
	bad_prev = 0
	for _, r in df0.iterrows():
		sx = csv_row_to_series(r)
		if sx is None:
			bad_prev += 1
			continue
		prev_c, o, lw, cl = sx
		d0o = float(o[0])
		g = d0o / float(prev_c) - 1.0
		row = row_from_lists(o, cl)
		bkt = gap_bucket(g)
		if bkt is None:
			continue
		samples.append(
			{
				"prev_c": prev_c,
				"o": o,
				"lw": lw,
				"cl": cl,
				"row": row,
				"d0o": d0o,
				"g": g,
				"bkt": bkt,
			}
		)
	return df0, samples, bad_prev

EXCLUDE_CODES = {
	"001217", "603628", "600478", "603132", "002805", "000505",
	"601155", "300638", "603986", "300394", "300548", "002565",
	"603920", "600151", "000547", "601698", "603698", "002149",
	"000818", "601330",
}

EXCLUDE_PICK_CODE_MMDD = {
	("1105", "002636"), ("1105", "001217"),
	("1112", "002317"), ("1112", "001298"),
	("1114", "600478"), ("1114", "001332"),
	("1117", "000620"), ("1117", "603132"),
	("1118", "002153"), ("1118", "605136"),
	("1119", "002805"), ("1119", "603129"),
	("1120", "002246"), ("1120", "000505"),
	("1121", "000892"), ("1121", "000070"), ("1121", "000681"),
	("1124", "002153"), ("1124", "688195"), ("1124", "605598"),
	("1125", "600105"), ("1125", "002728"), ("1125", "002759"),
	("1126", "002249"), ("1126", "600246"), ("1126", "600103"),
	("1203", "300638"), ("1203", "002353"), ("1203", "002565"),
	("1204", "603986"), ("1204", "603933"), ("1204", "600151"),
	("1210", "601869"), ("1210", "003031"), ("1210", "300548"),
	("1211", "002544"), ("1211", "002202"), ("1211", "600105"),
	("1212", "002149"), ("1212", "603929"), ("1212", "002565"),
	("1215", "600879"), ("1215", "600151"), ("1215", "002565"),
	("1215", "002565"), ("1216", "600879"), ("1216", "603920"),
	("1216", "002565"),
	("0114", "002131"), ("0114", "002465"), ("0114", "601698"),
	("0115", "002446"), ("0115", "000681"), ("0115", "601208"),
	("0116", "603698"), ("0116", "000547"), ("0116", "002565"),
	("0119", "605376"), ("0119", "603286"), ("0119", "600391"),
	("0130", "002455"), ("0130", "002149"), ("0130", "000818"),
	("0202", "002606"), ("0202", "002491"), ("0202", "600785"),
	("0203", "002165"), ("0203", "002342"), ("0203", "600481"),
	("0224", "603256"), ("0224", "601869"), ("0224", "603124"),
	("0303", "601975"), ("0303", "600635"), ("0303", "002506"),
	("0304", "000533"), ("0304", "002167"), ("0304", "002877"),
	("0305", "601179"), ("0305", "600875"), ("0305", "300303"),
	("0309", "600821"), ("0309", "000533"), ("0309", "688158"),
	("0313", "601611"), ("0313", "603659"), ("0313", "603366"),
	("0316", "603929"), ("0316", "002636"), ("0316", "601975"),
	("0316", "002565"), ("0317", "000572"), ("0317", "600408"),
	("0318", "603757"), ("0318", "603881"), ("0318", "001287"),
	("0319", "600996"), ("0319", "605389"), ("0319", "000617"),
	("0320", "002150"), ("0320", "002428"), ("0320", "603026"),
	("0323", "603529"), ("0323", "002218"), ("0323", "000703"),
	("0324", "000065"), ("0324", "601330"), ("0324", "601975"),
	("0326", "600163"), ("0326", "002109"), ("0326", "002192"),
	("0331", "002565"), ("0331", "002342"), ("0331", "600528"),
	("0402", "600339"), ("0402", "603477"), ("0402", "000155"),
	("0403", "003031"), ("0403", "605589"), ("0403", "600056"),
	("0407", "605589"), ("0407", "300821"), ("0407", "000703"),
	("0424", "001339"), ("0424", "002290"), ("0424", "600633"),
	("0427", "600418"), ("0427", "603501"), ("0427", "603486"),
	("0428", "600744"), ("0428", "603629"), ("0428", "603259"),
	("0428", "600770"),
}

SL = -0.07
TP = 0.07
STRONG_TH = 0.005
MAX_DAY = 3
WEAKEN = 0.005


def _code6_from_any(v: str) -> str:
	s = str(v).strip().upper()
	if "." in s:
		s = s.split(".", 1)[0]
	return s.zfill(6)[:6]


def _prev_trading_day_guess(d8: str) -> str:
	dt = datetime.strptime(str(int(d8)), "%Y%m%d")
	dt -= timedelta(days=1)
	while dt.weekday() >= 5:
		dt -= timedelta(days=1)
	return dt.strftime("%m%d")


def load_filtered_df() -> pd.DataFrame:
	df = pd.read_csv(SRC)
	for c in [f"D{i}_开盘" for i in range(6)] + [f"D{i}_收盘" for i in range(6)] + ["D0_MA5"]:
		if c in df.columns:
			df[c] = pd.to_numeric(df[c], errors="coerce")
	for c in PREV_CLOSE_COLS:
		if c in df.columns:
			df[c] = pd.to_numeric(df[c], errors="coerce")
	need = [f"D{i}_开盘" for i in range(6)] + [f"D{i}_收盘" for i in range(6)] + ["D0_MA5"]
	df = df.dropna(subset=need).copy()
	df = df[(df["D0_开盘"] - df["D0_收盘"]).abs() > 0.10].copy()
	code_col = "代码" if "代码" in df.columns else None
	if code_col:
		df = df[~df[code_col].map(_code6_from_any).isin(EXCLUDE_CODES)].copy()
	open_col = "开仓日" if "开仓日" in df.columns else None
	if code_col and open_col:
		_code6_s = df[code_col].map(_code6_from_any)
		_pick_mmdd_s = df[open_col].map(_prev_trading_day_guess)
		_pair = list(zip(_pick_mmdd_s, _code6_s))
		df = df[[p not in EXCLUDE_PICK_CODE_MMDD for p in _pair]].copy()
	return df


def csv_row_to_series(r: pd.Series) -> tuple[float, list[float], list[float], list[float]] | None:
	"""prev_effective（昨收·用于 gap 与 D0 前参考价）, o[6], low_proxy[6], c[6]；失败返回 None。"""
	c0 = float(r["D0_收盘"])
	ma5 = float(r["D0_MA5"])
	prev_close: float | None = None
	for col in PREV_CLOSE_COLS:
		if col not in r.index:
			continue
		raw = r[col]
		if raw is None or (isinstance(raw, float) and np.isnan(raw)):
			continue
		try:
			v = float(raw)
		except (TypeError, ValueError):
			continue
		if np.isfinite(v) and v > 0:
			prev_close = v
			break
	if prev_close is not None:
		prev_effective = prev_close
	else:
		prev_hat = (5.0 * ma5 - c0) / 4.0
		if not np.isfinite(prev_hat) or prev_hat <= 0:
			return None
		prev_effective = prev_hat
	o = [float(r[f"D{i}_开盘"]) for i in range(6)]
	cl = [float(r[f"D{i}_收盘"]) for i in range(6)]
	lw = [min(o[i], cl[i]) for i in range(6)]
	return float(prev_effective), o, lw, cl


def is_limit_down_locked(o, c, prev_c) -> bool:
	if prev_c is None or float(prev_c) <= 0:
		return False
	return abs(float(o) - float(c)) < 1e-12 and (float(o) / float(prev_c) - 1.0) <= -0.095


def row_from_lists(o, c):
	row = {}
	for i in range(6):
		row[f"D{i}_开盘"] = o[i]
		row[f"D{i}_收盘"] = c[i]
	return row


def prev_close_before_day(i: int, prev_before_d0: float, cl: list[float]) -> float | None:
	if i == 0:
		return prev_before_d0
	return cl[i - 1]


def sellable_open(i: int, row: dict, prev_before_d0: float, cl: list[float]) -> bool:
	pc = prev_close_before_day(i, prev_before_d0, cl)
	return not is_limit_down_locked(row[f"D{i}_开盘"], row[f"D{i}_收盘"], pc)


def sellable_close(i: int, row: dict, prev_before_d0: float, cl: list[float]) -> bool:
	pc = prev_close_before_day(i, prev_before_d0, cl)
	return not is_limit_down_locked(row[f"D{i}_开盘"], row[f"D{i}_收盘"], pc)


def settle_after_signal(row: dict, sig_day: int, pref: str, prev_before_d0: float, cl: list[float]):
	if pref == "open":
		if sellable_open(sig_day, row, prev_before_d0, cl):
			return sig_day, float(row[f"D{sig_day}_开盘"])
	else:
		if sellable_close(sig_day, row, prev_before_d0, cl):
			return sig_day, float(row[f"D{sig_day}_收盘"])
	for j in range(sig_day + 1, 6):
		if sellable_close(j, row, prev_before_d0, cl):
			return j, float(row[f"D{j}_收盘"])
	return None, None


def simulate_unified_sell(
	d0_anchor: float,
	row: dict,
	o: list[float],
	cl: list[float],
	prev_before_d0: float,
) -> tuple[float | None, int | None]:
	if d0_anchor <= 0:
		return None, None
	if o[1] <= d0_anchor * (1.0 + SL):
		d, p = settle_after_signal(row, 1, "open", prev_before_d0, cl)
		return (p, d) if d is not None else (None, None)
	if o[1] >= d0_anchor * (1.0 + TP):
		d, p = settle_after_signal(row, 1, "open", prev_before_d0, cl)
		return (p, d) if d is not None else (None, None)
	if cl[1] < d0_anchor * (1.0 + STRONG_TH):
		d, p = settle_after_signal(row, 1, "close", prev_before_d0, cl)
		return (p, d) if d is not None else (None, None)
	for i in range(2, MAX_DAY + 1):
		if o[i] <= d0_anchor * (1.0 + SL):
			d, p = settle_after_signal(row, i, "open", prev_before_d0, cl)
			return (p, d) if d is not None else (None, None)
		if o[i] >= d0_anchor * (1.0 + TP):
			d, p = settle_after_signal(row, i, "open", prev_before_d0, cl)
			return (p, d) if d is not None else (None, None)
		if cl[i] <= cl[i - 1] * (1.0 + WEAKEN):
			d, p = settle_after_signal(row, i, "close", prev_before_d0, cl)
			return (p, d) if d is not None else (None, None)
	d, p = settle_after_signal(row, MAX_DAY, "close", prev_before_d0, cl)
	return (p, d) if d is not None else (None, None)


def gap_bucket(
	g: float,
	a_lo: float | None = None,
	a_hi: float | None = None,
	b_hi: float | None = None,
) -> str | None:
	if not np.isfinite(g):
		return None
	al = A_GAP_LO if a_lo is None else a_lo
	ah = A_GAP_HI_DEFAULT if a_hi is None else a_hi
	bh = B_GAP_HI if b_hi is None else b_hi
	if g <= al:
		return "d"
	if g < ah:
		return "a"
	if g < bh:
		return "b"
	return "c"


def _add_pyramid_legs(
	base: float, lows: list[float], legs: list[tuple[float, float]]
) -> list[tuple[float, float]]:
	rest = [(float(w), float(base) * float(m)) for w, m in legs]
	rest.sort(key=lambda x: -x[1])
	remaining = {i: rest[i] for i in range(len(rest))}
	out: list[tuple[float, float]] = []
	for day in range(6):
		lx = float(lows[day])
		for idx in sorted(list(remaining.keys())):
			w, px = remaining[idx]
			if lx <= px + 1e-12:
				out.append((w, px))
				del remaining[idx]
		if not remaining:
			break
	return out


def buys_for_bucket(
	rule: str,
	o0: float,
	g: float,
	lw: list[float],
	a_lo: float | None = None,
	a_hi: float | None = None,
	b_hi: float | None = None,
) -> list[tuple[float, float]] | None:
	al = A_GAP_LO if a_lo is None else a_lo
	ah = A_GAP_HI_DEFAULT if a_hi is None else a_hi
	bh = B_GAP_HI if b_hi is None else b_hi
	if rule == "a":
		if not (al < g < ah):
			return None
		out = [(0.5, float(o0))]
		out += _add_pyramid_legs(o0, lw, [(0.3, 0.95), (0.2, 0.92)])
		return out
	if rule == "b":
		if not (ah <= g < bh):
			return None
		b = o0 * 0.97
		if min(float(x) for x in lw) > b + 1e-12:
			return None
		out = [(0.5, b)]
		out += _add_pyramid_legs(b, lw, [(0.3, 0.95), (0.2, 0.92)])
		return out
	if rule == "c":
		if g < bh:
			return None
		b = o0 * 0.96
		if min(float(x) for x in lw) > b + 1e-12:
			return None
		out = [(0.5, b)]
		out += _add_pyramid_legs(b, lw, [(0.2, 0.97), (0.3, 0.95)])
		return out
	if rule == "d":
		if g > al:
			return None
		return [(0.5, float(o0))]
	return None


def weighted_avg_cost(fills: list[tuple[float, float]]) -> float:
	num = sum(w * p for w, p in fills)
	den = sum(w for w, _ in fills)
	return float(num / den) if den > 0 else 0.0


def pack_metrics(name: str, rets: list[float], skip: int) -> dict:
	a = np.asarray(rets, dtype=float)
	if len(a) == 0:
		return {
			"策略": name,
			"样本": 0,
			"胜率": np.nan,
			"盈亏比": np.nan,
			"单笔平均收益": np.nan,
			"总收益_线性": np.nan,
			"净值_顺序复利": np.nan,
			"跳过_无买或无效": skip,
		}
	pos = a[a > 0]
	neg = -a[a <= 0]
	pl = float(pos.mean() / neg.mean()) if len(pos) > 0 and len(neg) > 0 and neg.mean() > 0 else np.nan
	return {
		"策略": name,
		"样本": int(len(a)),
		"胜率": float((a > 0).mean()),
		"盈亏比": pl,
		"单笔平均收益": float(a.mean()),
		"总收益_线性": float(a.sum()),
		"净值_顺序复利": float(np.prod(1 + a)),
		"跳过_无买或无效": skip,
	}


def buys_auto_weighted(
	bkt: str | None,
	o0: float,
	g: float,
	lw: list[float],
	wa: tuple[float, float, float],
	wb: tuple[float, float, float],
	wc: tuple[float, float, float],
	wd: float,
	a_lo: float | None = None,
	a_hi: float | None = None,
	b_hi: float | None = None,
) -> list[tuple[float, float]] | None:
	"""样本已按 gap 归入 a/b/c/d；各档独立三腿权重，触发倍数与原分档一致。"""
	al = A_GAP_LO if a_lo is None else a_lo
	ah = A_GAP_HI_DEFAULT if a_hi is None else a_hi
	bh = B_GAP_HI if b_hi is None else b_hi
	if bkt == "a":
		w1, w2, w3 = wa
		if not (al < g < ah):
			return None
		out = [(w1, float(o0))]
		out += _add_pyramid_legs(o0, lw, [(w2, 0.95), (w3, 0.92)])
		return out
	if bkt == "b":
		w1, w2, w3 = wb
		if not (ah <= g < bh):
			return None
		b = o0 * 0.97
		if min(float(x) for x in lw) > b + 1e-12:
			return None
		out = [(w1, b)]
		out += _add_pyramid_legs(b, lw, [(w2, 0.95), (w3, 0.92)])
		return out
	if bkt == "c":
		w1, w2, w3 = wc
		if g < bh:
			return None
		b = o0 * 0.96
		if min(float(x) for x in lw) > b + 1e-12:
			return None
		out = [(w1, b)]
		out += _add_pyramid_legs(b, lw, [(w2, 0.97), (w3, 0.95)])
		return out
	if bkt == "d":
		if g > al:
			return None
		return [(wd, float(o0))]
	return None


def _gen_abc_triples(
	step: float,
	w1_lo: float,
	w1_hi: float,
	w2_lo: float,
	w2_hi: float,
	min_w3: float,
) -> list[tuple[float, float, float]]:
	out = []
	w1 = w1_lo
	while w1 <= w1_hi + 1e-9:
		w2 = w2_lo
		while w2 <= w2_hi + 1e-9:
			w3 = 1.0 - w1 - w2
			if w3 >= min_w3 - 1e-9 and w3 <= 1.0 + 1e-9:
				out.append((round(w1, 4), round(w2, 4), round(w3, 4)))
			w2 = round(w2 + step, 6)
		w1 = round(w1 + step, 6)
	# \u53bb\u91cd
	seen = set()
	uniq = []
	for t in out:
		if t not in seen:
			seen.add(t)
			uniq.append(t)
	return uniq


def _gen_d_weights(step: float, lo: float, hi: float) -> list[float]:
	out = []
	x = lo
	while x <= hi + 1e-9:
		out.append(round(x, 4))
		x = round(x + step, 6)
	return out


def _fmt_weights(wa, wb, wc, wd) -> str:
	return "A%s|B%s|C%s|D%.2f" % (wa, wb, wc, wd)


def main_grid(step: float = 0.05, wide: bool = False):
	"""分档自动归类 + 统一卖：a/b/c 三腿权重笛卡尔积 × d 单权重；卖出规则不变。
	wide=False：中等搜索（较快）；wide=True：宽边界（组合数≈57³×13，需更久）。"""
	import time as _time

	df0, samples, bad_prev = _make_grid_samples()
	print("filtered_rows", len(df0))
	print("strategy_samples(with_bucket)", len(samples), "bad_prev", bad_prev)

	if wide:
		tr = _gen_abc_triples(step, 0.30, 0.70, 0.10, 0.45, 0.10)
		dw = _gen_d_weights(step, 0.20, 0.80)
	else:
		tr = _gen_abc_triples(step, 0.35, 0.65, 0.10, 0.40, 0.10)
		dw = _gen_d_weights(step, 0.25, 0.75)
	print("grid_wide", wide, "triple_abc_count", len(tr), "d_weights", len(dw))
	combo_n = len(tr) ** 3 * len(dw)
	print("grid_total_combos", combo_n)

	rows_out = []
	t0 = _time.time()
	done = 0
	for wa, wb, wc in itertools.product(tr, tr, tr):
		for wd in dw:
			rets: list[float] = []
			skip = 0
			for s in samples:
				bf = buys_auto_weighted(s["bkt"], s["d0o"], s["g"], s["lw"], wa, wb, wc, wd)
				if not bf:
					skip += 1
					continue
				avg_c = weighted_avg_cost(bf)
				px_e, _ = simulate_unified_sell(s["d0o"], s["row"], s["o"], s["cl"], s["prev_c"])
				if px_e is None:
					skip += 1
					continue
				rets.append(float(px_e) / float(avg_c) - 1.0)
			m = pack_metrics(_fmt_weights(wa, wb, wc, wd), rets, skip)
			m["权重A"] = str(wa)
			m["权重B"] = str(wb)
			m["权重C"] = str(wc)
			m["权重D"] = wd
			rows_out.append(m)
			done += 1
			if done % 2000 == 0:
				print("grid_progress", done, "/", combo_n, "elapsed_s", int(_time.time() - t0), flush=True)

	out_df = pd.DataFrame(rows_out)
	out_df = out_df.sort_values("单笔平均收益", ascending=False)
	out_df.to_csv(OUT_GRID, index=False, encoding="utf-8-sig", float_format="%.6f")
	print("elapsed_s", int(_time.time() - t0))
	print("wrote", OUT_GRID, "rows", len(out_df))
	print(out_df.head(12).to_string(index=False))


def main_grid_single_tier(tier: str, step: float = 0.05, wide: bool = False):
	"""只扫描一档买入权重，其余档固定为 BASE_*；卖出与全网格相同。组合数≈len(tr) 或 len(dw)。"""
	import time as _time

	tier = tier.lower()
	if tier not in ("a", "b", "c", "d"):
		raise ValueError("tier must be a|b|c|d, got %s" % tier)

	df0, samples, bad_prev = _make_grid_samples()
	print("filtered_rows", len(df0))
	print("strategy_samples(with_bucket)", len(samples), "bad_prev", bad_prev)
	print("grid_mode", "single_tier", tier)

	if wide:
		tr = _gen_abc_triples(step, 0.30, 0.70, 0.10, 0.45, 0.10)
		dw = _gen_d_weights(step, 0.20, 0.80)
	else:
		tr = _gen_abc_triples(step, 0.35, 0.65, 0.10, 0.40, 0.10)
		dw = _gen_d_weights(step, 0.25, 0.75)

	bwa, bwb, bwc, bwd = BASE_WA, BASE_WB, BASE_WC, BASE_WD
	if tier == "a":
		combo_iter = ((tx, bwb, bwc, bwd) for tx in tr)
		combo_n = len(tr)
	elif tier == "b":
		combo_iter = ((bwa, tx, bwc, bwd) for tx in tr)
		combo_n = len(tr)
	elif tier == "c":
		combo_iter = ((bwa, bwb, tx, bwd) for tx in tr)
		combo_n = len(tr)
	else:
		combo_iter = ((bwa, bwb, bwc, wx) for wx in dw)
		combo_n = len(dw)

	print("grid_wide", wide, "triple_abc_count", len(tr), "d_weights", len(dw), "grid_total_combos", combo_n)

	rows_out = []
	t0 = _time.time()
	done = 0
	prog_every = 2000 if combo_n > 2000 else max(1, min(500, combo_n // 10 or 1))

	for wa, wb, wc, wd in combo_iter:
		rets: list[float] = []
		skip = 0
		for s in samples:
			bf = buys_auto_weighted(s["bkt"], s["d0o"], s["g"], s["lw"], wa, wb, wc, wd)
			if not bf:
				skip += 1
				continue
			avg_c = weighted_avg_cost(bf)
			px_e, _ = simulate_unified_sell(s["d0o"], s["row"], s["o"], s["cl"], s["prev_c"])
			if px_e is None:
				skip += 1
				continue
			rets.append(float(px_e) / float(avg_c) - 1.0)
		tag = "单档%s网格|余档固定|统一卖" % tier.upper()
		m = pack_metrics("%s|%s" % (tag, _fmt_weights(wa, wb, wc, wd)), rets, skip)
		m["权重A"] = str(wa)
		m["权重B"] = str(wb)
		m["权重C"] = str(wc)
		m["权重D"] = wd
		rows_out.append(m)
		done += 1
		if done % prog_every == 0:
			print("grid_progress", done, "/", combo_n, "elapsed_s", int(_time.time() - t0), flush=True)

	out_path = out_grid_tier_csv(tier)
	out_df = pd.DataFrame(rows_out)
	out_df = out_df.sort_values("单笔平均收益", ascending=False)
	out_df.to_csv(out_path, index=False, encoding="utf-8-sig", float_format="%.6f")
	print("elapsed_s", int(_time.time() - t0))
	print("wrote", out_path, "rows", len(out_df))
	print(out_df.head(12).to_string(index=False))


def main_scan_a_gap_hi(hi_min: float, hi_max: float, step: float, a_lo: float | None = None):
	"""只扫 A 档 gap 上沿 a_hi：D/A/B/C 分区随 a_hi 联动，B 右界与 C 起点仍为 B_GAP_HI；各档仓位与倍数不变。"""
	import time as _time

	al = A_GAP_LO if a_lo is None else float(a_lo)
	bh = B_GAP_HI
	rows_raw, n_f, bad_prev = _load_all_series_rows()
	print("filtered_rows", n_f, "usable", len(rows_raw), "bad_prev", bad_prev)

	out_metrics: list[dict] = []
	t0 = _time.time()
	x = float(hi_min)
	n_skip_bounds = 0
	while x <= hi_max + 1e-9:
		a_hi = round(x, 6)
		if a_hi <= al + 1e-9:
			n_skip_bounds += 1
			x = round(x + step, 10)
			continue
		if a_hi >= bh - 1e-9:
			n_skip_bounds += 1
			x = round(x + step, 10)
			continue
		rets: list[float] = []
		skip = 0
		cnt_a = cnt_b = cnt_c = cnt_d = 0
		for s in rows_raw:
			bkt = gap_bucket(s["g"], a_lo=al, a_hi=a_hi, b_hi=bh)
			if bkt is None:
				skip += 1
				continue
			if bkt == "a":
				cnt_a += 1
			elif bkt == "b":
				cnt_b += 1
			elif bkt == "c":
				cnt_c += 1
			else:
				cnt_d += 1
			bf = buys_for_bucket(
				bkt, s["d0o"], s["g"], s["lw"], a_lo=al, a_hi=a_hi, b_hi=bh
			)
			if not bf:
				skip += 1
				continue
			avg_c = weighted_avg_cost(bf)
			px_e, _ = simulate_unified_sell(s["d0o"], s["row"], s["o"], s["cl"], s["prev_c"])
			if px_e is None:
				skip += 1
				continue
			rets.append(float(px_e) / float(avg_c) - 1.0)
		label = "调A上沿|lo=%.4f hi=%.4f|b_hi=%.4f|分档买+统一卖" % (al, a_hi, bh)
		m = pack_metrics(label, rets, skip)
		m["A_gap_lo"] = al
		m["A_gap_hi"] = a_hi
		m["B_C分界_b_hi"] = bh
		m["落入A计数"] = cnt_a
		m["落入B计数"] = cnt_b
		m["落入C计数"] = cnt_c
		m["落入D计数"] = cnt_d
		out_metrics.append(m)
		x = round(x + step, 10)

	print("scan_skip_invalid_bounds", n_skip_bounds, "elapsed_s", int(_time.time() - t0))
	out_df = pd.DataFrame(out_metrics)
	out_df = out_df.sort_values("单笔平均收益", ascending=False)
	out_df.to_csv(OUT_A_GAP_HI_SCAN, index=False, encoding="utf-8-sig", float_format="%.6f")
	print("wrote", OUT_A_GAP_HI_SCAN, "rows", len(out_df))
	print(out_df.to_string(index=False))


def main_scan_a_gap_grid(
	lo_min: float,
	lo_max: float,
	lo_step: float,
	hi_min: float,
	hi_max: float,
	hi_step: float,
	b_hi: float | None = None,
):
	"""二维扫描 A 档 gap 下沿 a_lo 与上沿 a_hi（须 a_lo<a_hi<b_hi）；B=[a_hi,b_hi)，C>=b_hi；D<=a_lo。"""
	import time as _time

	bh = B_GAP_HI if b_hi is None else float(b_hi)
	rows_raw, n_f, bad_prev = _load_all_series_rows()
	print("filtered_rows", n_f, "usable", len(rows_raw), "bad_prev", bad_prev)

	lo_list = _frange(lo_min, lo_max, lo_step)
	hi_list = _frange(hi_min, hi_max, hi_step)
	combo_n = len(lo_list) * len(hi_list)
	print(
		"gap_grid lo_points",
		len(lo_list),
		"hi_points",
		len(hi_list),
		"cartesian",
		combo_n,
		"b_hi",
		bh,
	)

	out_metrics: list[dict] = []
	t0 = _time.time()
	done = 0
	skipped_bounds = 0
	for al in lo_list:
		for a_hi in hi_list:
			if a_hi <= al + 1e-9:
				skipped_bounds += 1
				done += 1
				continue
			if a_hi >= bh - 1e-9:
				skipped_bounds += 1
				done += 1
				continue
			rets: list[float] = []
			skip = 0
			cnt_a = cnt_b = cnt_c = cnt_d = 0
			for s in rows_raw:
				bkt = gap_bucket(s["g"], a_lo=al, a_hi=a_hi, b_hi=bh)
				if bkt is None:
					skip += 1
					continue
				if bkt == "a":
					cnt_a += 1
				elif bkt == "b":
					cnt_b += 1
				elif bkt == "c":
					cnt_c += 1
				else:
					cnt_d += 1
				bf = buys_for_bucket(
					bkt, s["d0o"], s["g"], s["lw"], a_lo=al, a_hi=a_hi, b_hi=bh
				)
				if not bf:
					skip += 1
					continue
				avg_c = weighted_avg_cost(bf)
				px_e, _ = simulate_unified_sell(s["d0o"], s["row"], s["o"], s["cl"], s["prev_c"])
				if px_e is None:
					skip += 1
					continue
				rets.append(float(px_e) / float(avg_c) - 1.0)
			label = "gap网格|lo=%.4f hi=%.4f|b_hi=%.4f|分档买+统一卖" % (al, a_hi, bh)
			m = pack_metrics(label, rets, skip)
			m["A_gap_lo"] = al
			m["A_gap_hi"] = a_hi
			m["B_C分界_b_hi"] = bh
			m["落入A计数"] = cnt_a
			m["落入B计数"] = cnt_b
			m["落入C计数"] = cnt_c
			m["落入D计数"] = cnt_d
			out_metrics.append(m)
			done += 1
			if done % 500 == 0:
				print(
					"gap_grid_progress",
					done,
					"/",
					combo_n,
					"elapsed_s",
					int(_time.time() - t0),
					flush=True,
				)

	print(
		"gap_grid_skip_invalid_lo_hi",
		skipped_bounds,
		"evaluated",
		len(out_metrics),
		"elapsed_s",
		int(_time.time() - t0),
	)
	out_df = pd.DataFrame(out_metrics)
	out_df = out_df.sort_values("单笔平均收益", ascending=False)
	out_df.to_csv(OUT_A_GAP_GRID_SCAN, index=False, encoding="utf-8-sig", float_format="%.6f")
	print("wrote", OUT_A_GAP_GRID_SCAN, "rows", len(out_df))
	print(out_df.head(20).to_string(index=False))


def main():
	df0 = load_filtered_df()
	print("filtered_rows", len(df0))

	rows_out = []
	per_rule: dict[str, list[float]] = {"a": [], "b": [], "c": [], "d": []}
	per_rule_skip: dict[str, int] = {"a": 0, "b": 0, "c": 0, "d": 0}
	bench: list[float] = []
	bench_skip = 0
	matched_all: list[float] = []
	matched_skip = 0
	bad_prev = 0

	for _, r in df0.iterrows():
		sx = csv_row_to_series(r)
		if sx is None:
			bad_prev += 1
			bench_skip += 1
			matched_skip += 1
			continue
		prev_c, o, lw, cl = sx
		d0o = float(o[0])
		g = d0o / float(prev_c) - 1.0
		row = row_from_lists(o, cl)
		bkt = gap_bucket(g)

		d0b, p0b = settle_after_signal(row, 1, "close", prev_c, cl)
		if d0b is not None:
			bench.append(float(p0b) / d0o - 1.0)
		else:
			bench_skip += 1

		if bkt is not None:
			bf = buys_for_bucket(bkt, d0o, g, lw)
			if not bf:
				matched_skip += 1
				per_rule_skip[bkt] += 1
			else:
				avg_c = weighted_avg_cost(bf)
				px_e, _ = simulate_unified_sell(d0o, row, o, cl, prev_c)
				if px_e is None:
					matched_skip += 1
					per_rule_skip[bkt] += 1
				else:
					rr = float(px_e) / float(avg_c) - 1.0
					per_rule[bkt].append(rr)
					matched_all.append(rr)

	print("bad_prev_or_series", bad_prev)
	for rule in ("a", "b", "c", "d"):
		rows_out.append(pack_metrics("分档%s+统一卖(7/7/强0.5/转弱0.5/D3)|CSV近似低|按档内" % rule.upper(), per_rule[rule], per_rule_skip[rule]))
	rows_out.append(pack_metrics("分档自动归类+统一卖|落入a/b/c/d且成交", matched_all, matched_skip))
	rows_out.append(pack_metrics("基准_D0开盘买_D1收盘卖(可成交口径)", bench, bench_skip))

	out_df = pd.DataFrame(rows_out)
	out_df.to_csv(OUT, index=False, encoding="utf-8-sig", float_format="%.6f")
	print(out_df.to_string(index=False))
	print("wrote", OUT)


if __name__ == "__main__":
	ap = argparse.ArgumentParser(description="dafengniu buy combo backtest (CSV-only)")
	ap.add_argument("--grid", action="store_true", help="分档自动归类：a/b/c 三腿 × d 权重全组合网格（默认中等规模）")
	ap.add_argument(
		"--grid-only-tier",
		choices=("a", "b", "c", "d"),
		default=None,
		help="只扫描该档权重，其余档固定为默认分档比例；写出 dafengniu_buy_auto_weight_grid_tier_<档>.csv（远快于全笛卡尔积）",
	)
	ap.add_argument(
		"--grid-wide",
		action="store_true",
		help="与 --grid 或 --grid-only-tier 同用：扩大 a/b/c 与 d 的取值范围，组合更多、耗时更长",
	)
	ap.add_argument("--step", type=float, default=0.05, help="权重网格步长（默认 0.05）")
	ap.add_argument(
		"--scan-a-hi",
		nargs=3,
		type=float,
		metavar=("MIN", "MAX", "STEP"),
		default=None,
		help="扫描 A 档 gap 上沿：MIN、MAX、步长 STEP（须满足 a_lo<a_hi<B_GAP_HI）；写出 dafengniu_buy_a_gap_hi_scan.csv",
	)
	ap.add_argument(
		"--a-lo",
		type=float,
		default=None,
		help="与 --scan-a-hi 同用：A 下沿与 D 分界（默认 -0.05）",
	)
	ap.add_argument(
		"--scan-a-gap-grid",
		nargs=6,
		type=float,
		metavar=("LO_MIN", "LO_MAX", "LO_STEP", "HI_MIN", "HI_MAX", "HI_STEP"),
		default=None,
		help="二维扫描 A gap 下沿/上沿，写出 dafengniu_buy_a_gap_grid_scan.csv（须 a_lo<a_hi<b_hi=0.07）",
	)
	ap.add_argument(
		"--scan-a-gap-grid-default",
		action="store_true",
		help="在 −5%%～+6.5%% 上以步长 0.25%% 扫描 a_lo×a_hi（约千余组有效组合，较密）",
	)
	args = ap.parse_args()
	if args.scan_a_gap_grid_default:
		main_scan_a_gap_grid(-0.05, 0.065, 0.0025, -0.05, 0.065, 0.0025)
	elif args.scan_a_gap_grid is not None:
		g = args.scan_a_gap_grid
		main_scan_a_gap_grid(g[0], g[1], g[2], g[3], g[4], g[5])
	elif args.scan_a_hi is not None:
		main_scan_a_gap_hi(args.scan_a_hi[0], args.scan_a_hi[1], args.scan_a_hi[2], a_lo=args.a_lo)
	elif args.grid_only_tier:
		main_grid_single_tier(args.grid_only_tier, args.step, wide=args.grid_wide)
	elif args.grid:
		main_grid(args.step, wide=args.grid_wide)
	else:
		main()
