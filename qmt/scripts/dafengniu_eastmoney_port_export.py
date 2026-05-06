# -*- coding: utf-8 -*-
"""
使用东方财富数据端口（AkShare）导出大风牛信号特征。

输入支持两种格式：
1) code,open_date
2) 含 代码/开仓日YYYYMMDD/简称/入选日 的明细表
"""

from __future__ import annotations

import argparse
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

N_WINDOW = 6
# 防止个别远端连接长时间挂死
socket.setdefaulttimeout(20)


def yyyymmdd_shift(d8: str, delta_days: int) -> str:
    d = datetime.strptime(d8, "%Y%m%d").date() + timedelta(days=delta_days)
    return d.strftime("%Y%m%d")


def norm_d8(v) -> Optional[str]:
    s = str(v).strip()
    if "." in s:
        s = s.split(".", 1)[0]
    if len(s) >= 8 and s[:8].isdigit():
        return s[:8]
    return None


def code6(ts_code: str) -> str:
    s = str(ts_code).strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    return s.zfill(6)[:6]


def pick_open_pos(df: pd.DataFrame, open_d8: str):
    target = datetime.strptime(open_d8, "%Y%m%d").date()
    dd = pd.to_datetime(df["date"]).dt.date
    for i in range(len(dd)):
        if dd.iloc[i] == target:
            return i, None
    for i in range(len(dd)):
        if dd.iloc[i] >= target:
            return i, "first_trade_on_or_after_%s" % dd.iloc[i].isoformat()
    return None, "no_bar_on_or_after"


def fetch_stock_df_with_retry(symbol_ts: str, open_d8: str, retries: int = 3):
    import akshare as ak

    s6 = code6(symbol_ts)
    start = yyyymmdd_shift(open_d8, -220)
    end = yyyymmdd_shift(open_d8, 90)
    last_e = None
    for k in range(retries):
        try:
            raw = ak.stock_zh_a_hist(
                symbol=s6,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="qfq",
            )
            if raw is None or raw.empty:
                return None, "no_ak_data"
            df = pd.DataFrame(
                {
                    "date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
                    "open": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
                    "close": pd.to_numeric(raw.iloc[:, 3], errors="coerce"),
                    "high": pd.to_numeric(raw.iloc[:, 4], errors="coerce"),
                    "low": pd.to_numeric(raw.iloc[:, 5], errors="coerce"),
                }
            ).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            if df.empty:
                return None, "empty_df"
            return df, None
        except Exception as e:
            last_e = e
            time.sleep(0.8 * (k + 1))
    return None, str(last_e)[:120] if last_e else "fetch_fail"


def fetch_sse_df(start_d8: str, end_d8: str, retries: int = 3):
    import akshare as ak

    last_e = None
    for k in range(retries):
        try:
            raw = ak.index_zh_a_hist(
                symbol="000001",
                period="daily",
                start_date=start_d8,
                end_date=end_d8,
            )
            if raw is None or raw.empty:
                return None
            df = pd.DataFrame(
                {
                    "date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
                    "close": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
                }
            ).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            df["ma5"] = df["close"].rolling(5, min_periods=5).mean()
            return df
        except Exception as e:
            last_e = e
            time.sleep(1.0 * (k + 1))
    print("[WARN] SSE fetch failed:", last_e)
    return None


def parse_input(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = list(df.columns)
    if "code" in cols and "open_date" in cols:
        out = pd.DataFrame(
            {
                "代码": df["code"].astype(str).str.strip().str.upper(),
                "开仓日": df["open_date"].map(norm_d8),
                "简称": "",
                "入选日": "",
            }
        )
        return out.dropna(subset=["开仓日"]).reset_index(drop=True)

    code_col = next((c for c in cols if "代码" in str(c)), None)
    open_col = next((c for c in cols if "开仓日YYYYMMDD" in str(c) or str(c) == "开仓日"), None)
    name_col = next((c for c in cols if "简称" in str(c)), None)
    pick_col = next((c for c in cols if "入选日" in str(c)), None)
    if code_col is None or open_col is None:
        raise RuntimeError("输入CSV缺少代码/开仓日字段")
    out = pd.DataFrame(
        {
            "代码": df[code_col].astype(str).str.strip().str.upper(),
            "开仓日": df[open_col].map(norm_d8),
            "简称": df[name_col].astype(str).str.strip() if name_col else "",
            "入选日": df[pick_col].astype(str).str.strip() if pick_col else "",
        }
    )
    return out.dropna(subset=["开仓日"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "-i", required=True)
    ap.add_argument("--out", "-o", required=True)
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.out)
    work = parse_input(in_path)
    if args.limit > 0:
        work = work.iloc[: int(args.limit)].copy()
    if work.empty:
        print("[ERROR] 输入无有效行")
        return

    sse = fetch_sse_df(
        yyyymmdd_shift(str(work["开仓日"].min()), -260),
        yyyymmdd_shift(str(work["开仓日"].max()), 30),
    )

    rows = []
    ok = 0
    err = 0
    for i, r in work.iterrows():
        code = r["代码"]
        od = r["开仓日"]
        one = {"代码": code, "简称": r["简称"], "开仓日": od, "入选日": r["入选日"]}
        try:
            df, e = fetch_stock_df_with_retry(code, od, retries=3)
            if df is None:
                one["_error"] = e or "fetch_fail"
                rows.append(one)
                err += 1
                continue
            pos, hint = pick_open_pos(df, od)
            if pos is None:
                one["_error"] = hint or "no_position"
                rows.append(one)
                err += 1
                continue
            if pos + N_WINDOW > len(df):
                one["_error"] = "short_tail"
                rows.append(one)
                err += 1
                continue
            win = df.iloc[pos : pos + N_WINDOW].reset_index(drop=True)
            prev_close = float(df.iloc[pos - 1]["close"]) if pos > 0 and pd.notna(df.iloc[pos - 1]["close"]) else None

            for k in range(N_WINDOW):
                one[f"D{k}_开盘"] = float(win.iloc[k]["open"]) if pd.notna(win.iloc[k]["open"]) else ""
                one[f"D{k}_收盘"] = float(win.iloc[k]["close"]) if pd.notna(win.iloc[k]["close"]) else ""

            one["开仓起6日最高价"] = float(pd.to_numeric(win["high"], errors="coerce").max())
            d0_open = pd.to_numeric(win.iloc[0]["open"], errors="coerce")
            d2_close = pd.to_numeric(win.iloc[2]["close"], errors="coerce")
            if pd.notna(d0_open) and pd.notna(d2_close) and float(d0_open) > 0:
                one["盈亏比_D0开盘买_D2收盘卖"] = float(d2_close) / float(d0_open) - 1.0
            else:
                one["盈亏比_D0开盘买_D2收盘卖"] = ""

            if prev_close is not None and prev_close > 0 and pd.notna(d0_open):
                one["开仓日开盘相对前一日收盘涨跌幅"] = float(d0_open) / prev_close - 1.0
            else:
                one["开仓日开盘相对前一日收盘涨跌幅"] = ""

            sse_flag = ""
            if sse is not None and not sse.empty:
                spos, _ = pick_open_pos(sse.rename(columns={"close": "open"}).assign(open=1.0), od)
                if spos is not None and spos > 0:
                    t1 = sse.iloc[spos - 1]
                    if pd.notna(t1["close"]) and pd.notna(t1["ma5"]):
                        sse_flag = 1 if float(t1["close"]) >= float(t1["ma5"]) else 0
            one["开仓日前一交易日_上证站上MA5"] = sse_flag

            one["日期对齐说明"] = hint or ""
            one["_error"] = ""
            ok += 1
        except Exception as ex:
            one["_error"] = str(ex)[:120]
            err += 1
        rows.append(one)

        if (i + 1) % 20 == 0:
            print(f"[进度] {i+1}/{len(work)} ok={ok} err={err}")
        if args.sleep > 0:
            time.sleep(float(args.sleep))

    out = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig", float_format="%.4f")
    print(f"[完成] rows={len(out)} ok={ok} err={err} -> {out_path}")


if __name__ == "__main__":
    main()

