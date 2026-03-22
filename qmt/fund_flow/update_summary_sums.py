# -*- coding: utf-8 -*-
"""
根据「每日资金流入汇总」sheet 计算并写回「汇总」sheet 的前3/5/10/20/60日主力净流入之和（不含当日）。
前N日 = 截止日 end_date 的前 N 个交易日的 M/D主力 之和，不含 end_date 当天。
用法: py -m qmt.fund_flow.update_summary_sums --path output/fund_flow_20260310.xlsx --end 2026-03-10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(_root))

import pandas as pd

from qmt.fund_flow.calendar_utils import get_trading_days
from qmt.fund_flow.excel_io import _date_to_col_prefix


def update_summary_sums(excel_path: str | Path, end_date: str, start_date: str = "2026-01-01") -> None:
    path = Path(excel_path)
    if not path.is_absolute():
        cand = Path(__file__).resolve().parent / path
        path = cand if cand.exists() else Path(__file__).resolve().parent.parent.parent / path
    if not path.exists():
        print(f"文件不存在: {path}")
        return
    daily = pd.read_excel(path, sheet_name="每日资金流入汇总")
    summary = pd.read_excel(path, sheet_name="汇总")
    # 读回时股票可能被 Excel 存成数字，统一为 6 位字符串
    if "股票" in daily.columns:
        daily["股票"] = daily["股票"].astype(str).str.replace(r"\.0$", "", regex=True)
        daily["股票"] = daily["股票"].str.zfill(6)
    if "股票代码" in summary.columns:
        summary["股票代码"] = summary["股票代码"].astype(str).str.replace(r"\.0$", "", regex=True)
        summary["股票代码"] = summary["股票代码"].str.zfill(6)
    if "股票" not in daily.columns or "股票代码" not in summary.columns:
        print("缺少 股票 / 股票代码 列")
        return
    ROLLING_DAYS = (3, 5, 10, 20, 40, 60)
    trading_days = get_trading_days(start_date, end_date)
    if len(trading_days) < 4:
        print("交易日不足，无法计算前3日")
        return
    code_ser = daily["股票"].astype(str).str.zfill(6)
    summary_codes = summary["股票代码"].astype(str).str.zfill(6)
    days_before = trading_days[:-1]  # 不含截止日当天
    all_cols = []
    for n in ROLLING_DAYS:
        if len(days_before) >= n:
            prev_n = [f"{_date_to_col_prefix(d)}主力" for d in days_before[-n:]]
            all_cols.extend(prev_n)
    for col in set(all_cols):
        if col not in daily.columns:
            daily[col] = None
    for n in ROLLING_DAYS:
        col_name = f"前{n}日主力净流入之和(亿)"
        if len(days_before) < n:
            summary[col_name] = None
            continue
        prev_n = [f"{_date_to_col_prefix(d)}主力" for d in days_before[-n:]]
        sum_wan = daily[prev_n].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
        sum_yi = (sum_wan / 1e4).round(4)  # 万元→亿元
        summary[col_name] = summary_codes.map(dict(zip(code_ser, sum_yi)))
    # 去掉旧的「前N日(万)」列，只保留(亿)
    drop_wan = [c for c in summary.columns if isinstance(c, str) and "前" in c and "日主力" in c and c.endswith("(万)")]
    if drop_wan:
        summary = summary.drop(columns=drop_wan)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="汇总", index=False)
        daily.to_excel(writer, sheet_name="每日资金流入汇总", index=False)
    print(f"已更新汇总表前3/5/10/20/40/60日主力净流入之和(亿): {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="output/fund_flow_20260310.xlsx", help="Excel 路径")
    parser.add_argument("--end", default="2026-03-10", help="截止日期")
    parser.add_argument("--start", default="2026-01-01", help="起始日期")
    args = parser.parse_args()
    update_summary_sums(args.path, args.end, args.start)
