# -*- coding: utf-8 -*-
"""
根据 holdings 明细导出“信号分析特征表”。

输入默认：
  qmt/实盘策略/大疯牛妖股数据/dafengniu_holdings_detail.csv

输出默认：
  qmt/实盘策略/大疯牛妖股数据/dafengniu_signal_features.csv

导出字段（核心）：
  - 代码, 简称, 入选日, 开仓日
  - D0~D5_开盘, D0~D5_收盘
  - 开仓起6日最高价
  - 盈亏比_D0开盘买_D2收盘卖
  - 开仓日前一交易日_上证站上MA5 (1/0)
  - 开仓日开盘相对前一日收盘涨跌幅
  - _error

说明：
  - 保留同代码不同开仓日（不去重）
  - 若开仓日非交易日，按“首个 >= 开仓日的交易日”对齐
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
	sys.path.insert(0, _SCRIPT_DIR)
from dafengniu_paths import HOLDINGS_DETAIL_CSV, SIGNAL_FEATURES_CSV  # noqa: E402

N_WINDOW = 6


def yyyymmdd_shift(d8: str, delta_days: int) -> str:
    d = datetime.strptime(d8, "%Y%m%d").date() + timedelta(days=delta_days)
    return d.strftime("%Y%m%d")


def _norm_d8(v) -> Optional[str]:
    s = str(v).strip()
    if not s:
        return None
    if "." in s:
        s = s.split(".", 1)[0]
    if len(s) >= 8 and s[:8].isdigit():
        return s[:8]
    return None


def _pick_open_pos(df: pd.DataFrame, open_d8: str) -> Tuple[Optional[int], Optional[str]]:
    try:
        target = datetime.strptime(open_d8, "%Y%m%d").date()
    except ValueError:
        return None, "bad_open_date"
    dd = pd.to_datetime(df["date"]).dt.date
    for i in range(len(dd)):
        if dd.iloc[i] == target:
            return i, None
    for i in range(len(dd)):
        if dd.iloc[i] >= target:
            return i, "first_trade_on_or_after_%s" % dd.iloc[i].isoformat()
    return None, "no_bar_on_or_after"


def _code6(ts_code: str) -> str:
    s = str(ts_code).strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    return s.zfill(6)[:6]


def fetch_stock_daily_df(symbol_ts: str, open_d8: str, pre_days: int = 180, post_days: int = 90) -> Optional[pd.DataFrame]:
    import akshare as ak

    s6 = _code6(symbol_ts)
    start = yyyymmdd_shift(open_d8, -abs(pre_days))
    end = yyyymmdd_shift(open_d8, abs(post_days))
    raw = ak.stock_zh_a_hist(symbol=s6, period="daily", start_date=start, end_date=end, adjust="qfq")
    if raw is None or raw.empty:
        return None
    # 列序：日期, 股票代码, 开盘, 收盘, 最高, 最低, ...
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
            "open": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
            "close": pd.to_numeric(raw.iloc[:, 3], errors="coerce"),
            "high": pd.to_numeric(raw.iloc[:, 4], errors="coerce"),
            "low": pd.to_numeric(raw.iloc[:, 5], errors="coerce"),
        }
    ).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return out if not out.empty else None


def fetch_sse_daily_df(start_d8: str, end_d8: str) -> Optional[pd.DataFrame]:
    import akshare as ak

    # 上证指数（000001）
    raw = ak.index_zh_a_hist(symbol="000001", period="daily", start_date=start_d8, end_date=end_d8)
    if raw is None or raw.empty:
        return None
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
            "close": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
        }
    ).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    out["ma5"] = out["close"].rolling(5, min_periods=5).mean()
    out["d8"] = out["date"].dt.strftime("%Y%m%d")
    return out if not out.empty else None


def calc_sse_t1_above_ma5(sse_df: pd.DataFrame, open_d8: str) -> Optional[int]:
    pos, _ = _pick_open_pos(sse_df.rename(columns={"close": "open"}).assign(open=1.0), open_d8)
    # 只用 date 定位，借用 _pick_open_pos；上面 open 列只是占位
    if pos is None or pos <= 0:
        return None
    r = sse_df.iloc[pos - 1]
    if pd.isna(r["close"]) or pd.isna(r["ma5"]):
        return None
    return 1 if float(r["close"]) >= float(r["ma5"]) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "-i", default=HOLDINGS_DETAIL_CSV, help="源明细CSV")
    ap.add_argument("--out", "-o", default=SIGNAL_FEATURES_CSV, help="输出CSV")
    ap.add_argument("--sleep", type=float, default=0.15, help="单票间隔秒")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前N行（调试）")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.out)
    if not in_path.is_file():
        raise FileNotFoundError("输入不存在: %s" % in_path)

    src = pd.read_csv(in_path)
    col_pick = [c for c in src.columns if "入选日" in str(c)]
    col_open = [c for c in src.columns if "开仓日YYYYMMDD" in str(c)]
    col_code = [c for c in src.columns if "代码" in str(c)]
    col_name = [c for c in src.columns if "简称" in str(c)]
    if not col_open or not col_code:
        raise RuntimeError("源CSV缺少关键列（代码/开仓日YYYYMMDD）")

    pick_col = col_pick[0] if col_pick else None
    open_col = col_open[0]
    code_col = col_code[0]
    name_col = col_name[0] if col_name else None

    work = src.copy()
    work["开仓日"] = work[open_col].map(_norm_d8)
    work["代码"] = work[code_col].astype(str).str.strip().str.upper()
    work["简称"] = work[name_col].astype(str).str.strip() if name_col else ""
    work["入选日"] = work[pick_col].astype(str).str.strip() if pick_col else ""
    work = work.dropna(subset=["开仓日"])
    work = work[work["代码"] != ""].reset_index(drop=True)

    if args.limit > 0:
        work = work.iloc[: int(args.limit)].copy()

    if work.empty:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame().to_csv(out_path, index=False, encoding="utf-8-sig")
        print("[完成] 无可处理记录")
        return

    min_d8 = str(work["开仓日"].min())
    max_d8 = str(work["开仓日"].max())
    sse_start = yyyymmdd_shift(min_d8, -240)
    sse_end = yyyymmdd_shift(max_d8, 30)

    sse_df = None
    try:
        sse_df = fetch_sse_daily_df(sse_start, sse_end)
    except Exception:
        sse_df = None

    import time

    rows = []
    for i, r in work.iterrows():
        code = r["代码"]
        od = r["开仓日"]
        name = r["简称"]
        pick = r["入选日"]
        out = {
            "代码": code,
            "简称": name,
            "开仓日": od,
            "入选日": pick,
        }
        try:
            df = fetch_stock_daily_df(code, od)
            if df is None or df.empty:
                out["_error"] = "no_ak_data"
                rows.append(out)
                continue

            pos, hint = _pick_open_pos(df, od)
            if pos is None:
                out["_error"] = hint or "no_position"
                rows.append(out)
                continue
            if pos + N_WINDOW > len(df):
                out["_error"] = "short_tail"
                rows.append(out)
                continue

            win = df.iloc[pos : pos + N_WINDOW].copy().reset_index(drop=True)
            prev_close = float(df.iloc[pos - 1]["close"]) if pos > 0 and pd.notna(df.iloc[pos - 1]["close"]) else None

            for k in range(N_WINDOW):
                out["D%d_开盘" % k] = float(win.iloc[k]["open"]) if pd.notna(win.iloc[k]["open"]) else ""
                out["D%d_收盘" % k] = float(win.iloc[k]["close"]) if pd.notna(win.iloc[k]["close"]) else ""

            highs = pd.to_numeric(win["high"], errors="coerce")
            out["开仓起6日最高价"] = float(highs.max()) if highs.notna().any() else ""

            d0_open = pd.to_numeric(win.iloc[0]["open"], errors="coerce")
            d2_close = pd.to_numeric(win.iloc[2]["close"], errors="coerce")
            if pd.notna(d0_open) and pd.notna(d2_close) and float(d0_open) > 0:
                out["盈亏比_D0开盘买_D2收盘卖"] = float(d2_close) / float(d0_open) - 1.0
            else:
                out["盈亏比_D0开盘买_D2收盘卖"] = ""

            if pd.notna(d0_open) and prev_close is not None and float(prev_close) > 0:
                out["开仓日开盘相对前一日收盘涨跌幅"] = float(d0_open) / float(prev_close) - 1.0
            else:
                out["开仓日开盘相对前一日收盘涨跌幅"] = ""

            sse_flag = calc_sse_t1_above_ma5(sse_df, od) if sse_df is not None else None
            out["开仓日前一交易日_上证站上MA5"] = sse_flag if sse_flag is not None else ""

            if hint:
                out["日期对齐说明"] = hint
            out["_error"] = ""
        except Exception as e:
            out["_error"] = str(e)[:120]
        rows.append(out)

        if args.sleep > 0:
            time.sleep(float(args.sleep))
        if (i + 1) % 50 == 0:
            print("[进度] %d/%d" % (i + 1, len(work)))

    out_df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig", float_format="%.4f")
    print("[完成] rows=%d -> %s" % (len(out_df), out_path))


if __name__ == "__main__":
    main()

