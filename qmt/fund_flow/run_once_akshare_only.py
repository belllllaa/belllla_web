# -*- coding: utf-8 -*-
"""
仅通过 akshare 拉取「今日个股资金流排名」，生成与 run_once 相同格式的汇总表与每日宽表。
东方财富直连/浏览器分页都失败时可用此方式（akshare 走不同请求路径，有时能通）。
注意：akshare 该接口通常最多返回约 200 条，非全市场 5000+。
用法: py -m qmt.fund_flow.run_once_akshare_only --date 2026-03-11
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_here = Path(__file__).resolve().parent
if __name__ == "__main__" and __package__ is None:
    _root = _here.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from qmt.fund_flow.fetcher import _fetch_via_akshare
from qmt.fund_flow.clean import clean_fund_flow
from qmt.fund_flow.run_once import build_and_write_from_df
from qmt.fund_flow.industry_fetcher import fetch_industry_map


def _parse_date(s: str) -> str:
    today = date.today()
    s = s.strip().lower()
    if s in ("今天", "今日", "today"):
        return today.strftime("%Y-%m-%d")
    if s in ("昨天", "昨日", "yesterday"):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def main(snapshot_date: str, output_dir: str | Path | None = None) -> Path:
    output_dir = Path(output_dir or _here / "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("仅通过 akshare 拉取今日个股资金流排名（约 200 条）…", flush=True)
    raw = _fetch_via_akshare()
    if raw is None or raw.empty:
        raise RuntimeError("akshare 拉取失败，未获取到数据")
    print(f"拉取到 {len(raw)} 条", flush=True)

    df = clean_fund_flow(raw)
    industry_df = fetch_industry_map()
    if industry_df is not None:
        df = df.merge(industry_df, on="代码", how="left")
        df["所属行业"] = df["所属行业"].fillna("")
    else:
        df["所属行业"] = ""

    return build_and_write_from_df(df, snapshot_date, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="仅用 akshare 拉取资金流并生成汇总（约 200 条）")
    parser.add_argument("--date", "-d", default="今天", help="汇总日期，如 2026-03-11 或 今天")
    parser.add_argument("--output-dir", "-o", default=None, help="输出目录")
    args = parser.parse_args()
    d = _parse_date(args.date)
    print(f"汇总日期: {d}", flush=True)
    main(d, args.output_dir)
    print("完成。", flush=True)
