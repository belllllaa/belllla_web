"""导出「扩展网格」单组参数的逐笔明细（与 tmp_all_combo_filtered.py 同过滤、同 settle 逻辑）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)
from dafengniu_paths import GRID_EXT_TRADES_CSV, OPEN_WINDOW_METRICS_QMT_CSV  # noqa: E402

SRC = Path(OPEN_WINDOW_METRICS_QMT_CSV)
OUT = Path(GRID_EXT_TRADES_CSV)
# 同步写一份到脚本目录（纯 ASCII 路径，避免 IDE 用错误 URI 打不开「实盘策略」下文件）
OUT_ASCII = Path(__file__).resolve().parent / "dafengniu_grid_ext_sl7_tp7_th05_d0_D3_w0_trades.csv"

SL = -0.07
TP = 0.07
TH = 0.005
STRONG_REF = "d0"
MAX_DAY = 3
WEAKEN_CUT = 0.00

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


def _code6_from_any(v):
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


def load_filtered_df():
    df = pd.read_csv(SRC)
    for c in [f"D{i}_开盘" for i in range(6)] + [f"D{i}_收盘" for i in range(6)]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    need = [f"D{i}_开盘" for i in range(6)] + [f"D{i}_收盘" for i in range(6)]
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


def is_limit_down_locked(o, c, prev_c):
    if prev_c is None or prev_c <= 0:
        return False
    return abs(float(o) - float(c)) < 1e-12 and (float(o) / float(prev_c) - 1.0) <= -0.095


def sellable_open(i, row):
    prev_c = row[f"D{i-1}_收盘"] if i >= 1 else None
    return not is_limit_down_locked(row[f"D{i}_开盘"], row[f"D{i}_收盘"], prev_c)


def sellable_close(i, row):
    prev_c = row[f"D{i-1}_收盘"] if i >= 1 else None
    return not is_limit_down_locked(row[f"D{i}_开盘"], row[f"D{i}_收盘"], prev_c)


def settle_after_signal(row, sig_day, pref="close"):
    if pref == "open":
        if sellable_open(sig_day, row):
            return sig_day, float(row[f"D{sig_day}_开盘"])
    else:
        if sellable_close(sig_day, row):
            return sig_day, float(row[f"D{sig_day}_收盘"])
    for j in range(sig_day + 1, 6):
        if sellable_close(j, row):
            return j, float(row[f"D{j}_收盘"])
    return None, None


def _try_exit(row, sig_day: int, pref: str):
    d, p = settle_after_signal(row, sig_day, pref)
    if d is None:
        return None, None, None, None
    return int(d), float(p), int(sig_day), pref


def simulate_row(row) -> dict | None:
    d0 = float(row["D0_开盘"])
    o = [float(row[f"D{i}_开盘"]) for i in range(6)]
    c = [float(row[f"D{i}_收盘"]) for i in range(6)]
    code = row.get("代码", "")
    kday = row.get("开仓日", "")

    rule = ""
    d = p = sd = sp = None

    if o[1] <= d0 * (1.0 + SL):
        rule = "D1开盘止损"
        d, p, sd, sp = _try_exit(row, 1, "open")
    elif o[1] >= d0 * (1.0 + TP):
        rule = "D1开盘止盈"
        d, p, sd, sp = _try_exit(row, 1, "open")
    else:
        if STRONG_REF == "d0":
            d1_strong = c[1] >= d0 * (1.0 + TH)
        else:
            d1_strong = c[1] >= c[0] * (1.0 + TH)
        if not d1_strong:
            rule = "D1收盘不强"
            d, p, sd, sp = _try_exit(row, 1, "close")
        else:
            sold = False
            for i in range(2, MAX_DAY + 1):
                if o[i] <= d0 * (1.0 + SL):
                    rule = f"D{i}开盘止损"
                    d, p, sd, sp = _try_exit(row, i, "open")
                    sold = True
                    break
                if o[i] >= d0 * (1.0 + TP):
                    rule = f"D{i}开盘止盈"
                    d, p, sd, sp = _try_exit(row, i, "open")
                    sold = True
                    break
                if c[i] <= c[i - 1] * (1.0 + WEAKEN_CUT):
                    rule = f"D{i}收盘转弱"
                    d, p, sd, sp = _try_exit(row, i, "close")
                    sold = True
                    break
            if not sold:
                rule = f"D{MAX_DAY}到期收盘"
                d, p, sd, sp = _try_exit(row, MAX_DAY, "close")

    if d is None or p is None:
        return None

    ret = p / d0 - 1.0
    sig_o = float(row[f"D{sd}_开盘"])
    sig_c = float(row[f"D{sd}_收盘"])
    return {
        "代码": code,
        "开仓日": kday,
        "D0开盘_买入价": round(d0, 4),
        "触发规则": rule,
        "信号D": sd,
        "信号日开盘": round(sig_o, 4),
        "信号日收盘": round(sig_c, 4),
        "信号口径": sp,
        "成交D": d,
        "卖出价_可成交": round(p, 4),
        "若信号日即成交": "是" if d == sd else "否",
        "单笔收益率": round(ret, 6),
        "单笔收益率pct": round(ret * 100, 4),
    }


def main():
    base = load_filtered_df()
    records = []
    uns = 0
    for _, r in base.iterrows():
        rec = simulate_row(r)
        if rec is None:
            uns += 1
            continue
        records.append(rec)

    out_df = pd.DataFrame(records)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(OUT, index=False, encoding="utf-8-sig")
    out_df.to_csv(OUT_ASCII, index=False, encoding="utf-8-sig")
    print("filtered_rows", len(base))
    print("trades", len(records), "unsellable_dropped", uns)
    print("csv", OUT)
    print("csv_ascii", OUT_ASCII)
    if len(records):
        a = np.asarray([float(x["单笔收益率"]) for x in records], dtype=float)
        print("mean_ret", float(a.mean()), "winrate", float((a > 0).mean()), "sum_linear", float(a.sum()), "prod_nav", float(np.prod(1 + a)))


if __name__ == "__main__":
    main()
