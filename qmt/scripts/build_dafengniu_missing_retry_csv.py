# -*- coding: utf-8 -*-
"""
从 dafengniu_open_window_metrics_qmt.csv 生成“待重跑清单”：
1) 识别未成功行（_error 非空，或 D0_开盘缺失）
2) 新增列：上证T-1是否站上MA5（1/0，失败留空）
3) 输出总清单 + 2 份拆分清单，便于分批跑，降低远端断连风险
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd


def _find_col(df: pd.DataFrame, key: str) -> str:
    for c in df.columns:
        if key in str(c):
            return c
    raise KeyError("未找到包含关键字的列: %s" % key)


def _to_yyyymmdd_int(v) -> Optional[int]:
    s = str(v).strip()
    if not s:
        return None
    if "." in s:
        s = s.split(".", 1)[0]
    if len(s) >= 8 and s[:8].isdigit():
        return int(s[:8])
    return None


def _fetch_sse_t1_ma5_map(min_open: int, max_open: int) -> dict[int, int]:
    """
    返回 {open_date_yyyymmdd: 1/0}，含义：开仓日前一交易日，上证收盘是否 >= MA5。
    """
    import akshare as ak

    start = str(min_open - 20000)  # 粗略向前多取一段
    end = str(max_open + 20000)

    df = None
    last_err = None

    # 优先用 index_zh_a_hist；失败则尝试 stock_zh_index_daily_em
    try:
        raw = ak.index_zh_a_hist(
            symbol="000001",
            period="daily",
            start_date=start,
            end_date=end,
        )
        if raw is not None and not raw.empty:
            df = pd.DataFrame(
                {
                    "date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
                    "close": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
                }
            )
    except Exception as e:
        last_err = e

    if df is None or df.empty:
        try:
            raw2 = ak.stock_zh_index_daily_em(symbol="sh000001")
            if raw2 is not None and not raw2.empty:
                # 常见列：date, close
                date_col = "date" if "date" in raw2.columns else raw2.columns[0]
                close_col = "close" if "close" in raw2.columns else raw2.columns[2]
                df = pd.DataFrame(
                    {
                        "date": pd.to_datetime(raw2[date_col], errors="coerce"),
                        "close": pd.to_numeric(raw2[close_col], errors="coerce"),
                    }
                )
        except Exception as e:
            last_err = e

    if df is None or df.empty:
        raise RuntimeError("上证指数数据获取失败: %r" % (last_err,))

    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    df["ma5"] = df["close"].rolling(5, min_periods=5).mean()
    df["d8"] = df["date"].dt.strftime("%Y%m%d").astype(int)
    d8_list = df["d8"].tolist()
    d8_to_i = {d: i for i, d in enumerate(d8_list)}

    out: dict[int, int] = {}
    for od in range(min_open, max_open + 1):
        if od not in d8_to_i:
            continue
        i = d8_to_i[od]
        if i <= 0:
            continue
        t1 = df.iloc[i - 1]
        if pd.isna(t1["ma5"]) or pd.isna(t1["close"]):
            continue
        out[od] = 1 if float(t1["close"]) >= float(t1["ma5"]) else 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ref",
        default=r"qmt/实盘策略/dafengniu_open_window_metrics_qmt.csv",
        help="参考指标表（含 _error）",
    )
    ap.add_argument(
        "--out",
        default=r"qmt/实盘策略/dafengniu_missing_retry.csv",
        help="输出待重跑清单",
    )
    ap.add_argument(
        "--split",
        type=int,
        default=2,
        help="拆分份数，默认 2",
    )
    args = ap.parse_args()

    p_ref = Path(args.ref)
    p_out = Path(args.out)
    p_out.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(p_ref)
    code_col = _find_col(df, "代码")
    open_col = _find_col(df, "开仓")
    err_col = "_error"
    d0_open_col = _find_col(df, "D0_开盘")

    err_s = df[err_col].fillna("").astype(str).str.strip() if err_col in df.columns else pd.Series([""] * len(df))
    d0_s = pd.to_numeric(df[d0_open_col], errors="coerce")

    missing_mask = err_s.ne("") | d0_s.isna()
    miss = df.loc[missing_mask, [code_col, open_col]].copy()
    miss = miss.rename(columns={code_col: "代码", open_col: "开仓日"})
    miss["开仓日_int"] = miss["开仓日"].map(_to_yyyymmdd_int)
    miss = miss.dropna(subset=["开仓日_int"]).copy()
    miss["开仓日_int"] = miss["开仓日_int"].astype(int)
    miss = miss.sort_values(["开仓日_int", "代码"]).drop_duplicates(["代码", "开仓日_int"]).reset_index(drop=True)

    if miss.empty:
        miss["上证T-1是否站上MA5"] = []
        miss.to_csv(p_out, index=False, encoding="utf-8-sig")
        print("[完成] 未发现待重跑行 -> %s" % p_out)
        return

    sse_map = {}
    try:
        sse_map = _fetch_sse_t1_ma5_map(int(miss["开仓日_int"].min()), int(miss["开仓日_int"].max()))
    except Exception as e:
        print("[警告] 上证MA5列计算失败，先留空: %r" % (e,))

    miss["上证T-1是否站上MA5"] = miss["开仓日_int"].map(sse_map)
    miss = miss.drop(columns=["开仓日_int"])
    miss.to_csv(p_out, index=False, encoding="utf-8-sig")

    n = len(miss)
    k = max(1, int(args.split))
    chunk = (n + k - 1) // k
    stem = p_out.stem
    suf = p_out.suffix or ".csv"
    for i in range(k):
        part = miss.iloc[i * chunk : (i + 1) * chunk].copy()
        if part.empty:
            continue
        p_part = p_out.parent / ("%s_part%d%s" % (stem, i + 1, suf))
        part.to_csv(p_part, index=False, encoding="utf-8-sig")
        print("[输出] part%d 行数=%d -> %s" % (i + 1, len(part), p_part))

    print("[完成] 待重跑=%d -> %s" % (len(miss), p_out))


if __name__ == "__main__":
    main()

