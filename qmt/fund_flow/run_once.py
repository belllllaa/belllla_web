# -*- coding: utf-8 -*-
"""
一次性拉取全 A 股资金流并写入 Excel（截止到指定日期）。
用法: 在 qmt 目录下: python fund_flow/run_once.py
或在项目根目录: python -m qmt.fund_flow.run_once
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# 允许以 script 直接运行（在 qmt 或项目根）
_here = Path(__file__).resolve().parent
if __name__ == "__main__" and __package__ is None:
    _root = _here.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

try:
    from qmt.fund_flow.fetcher import fetch_all_a_fund_flow
    from qmt.fund_flow.clean import clean_fund_flow
    from qmt.fund_flow.excel_io import (
        write_daily_wide_workbook,
        write_summary_workbook,
        _date_to_col_prefix,
        append_daily_fund_flow,
    )
    from qmt.fund_flow.calendar_utils import get_trading_days
    from qmt.fund_flow.industry_fetcher import fetch_industry_map
except ImportError:
    from .fetcher import fetch_all_a_fund_flow
    from .clean import clean_fund_flow
    from .excel_io import (
        write_daily_wide_workbook,
        write_summary_workbook,
        _date_to_col_prefix,
        append_daily_fund_flow,
    )
    from .calendar_utils import get_trading_days
    from .industry_fetcher import fetch_industry_map


def build_and_write_from_df(
    df: pd.DataFrame,
    snapshot_date: str,
    output_dir: str | Path,
) -> Path:
    """
    用已清洗的 df（需含 代码、名称、现价、涨跌幅、主力净流入、散户净流入、流通市值、所属行业，可选 成交额）
    生成汇总表与每日宽表并写入。供 run_once 与 run_once_from_json 复用。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    daily_path = output_dir / "daily_fund_flow_wide.xlsx"
    summary_path = output_dir / f"fund_flow_summary_{snapshot_date.replace('-', '')}.xlsx"

    # 汇总表：股票代码在首列（强制 6 位字符串，000 开头不丢）
    summary = pd.DataFrame()
    summary["股票代码"] = df["代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    summary["股票名称"] = df["名称"]
    summary["最新价"] = df["现价"]

    # 涨跌幅数值 → 字符串
    pct = df["涨跌幅"]
    summary["当日净流入(万)"] = df["主力净流入"] + df["散户净流入"]
    # 占成交金额% = 当日净流入(万)*1e4/成交额(元)*100
    ratio = None
    if "成交额" in df.columns:
        amt = df["成交额"].fillna(0)
        ratio = summary["当日净流入(万)"].astype(float) * 1e4 / amt.replace(0, float("nan")) * 100
    # 数值转成 "数字%"
    summary["涨跌幅"] = pct.map(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    if ratio is not None:
        summary["占成交金额"] = ratio.map(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    else:
        summary["占成交金额"] = ""

    summary["主力净流入(万)"] = df["主力净流入"]
    summary["散户净流入(万)"] = df["散户净流入"]
    summary["所属行业"] = df["所属行业"]
    # 流通市值先保留为浮点，稍后再整体取整
    summary["流通市值(亿)"] = df["流通市值"]
    summary["主力-散户净流入(万)"] = df["主力净流入"] - df["散户净流入"]

    # 每日资金流入汇总：表头 股票、股票名称，M/D主力、M/D散户、M/D涨跌幅；主力/散户单位万元
    trading_days = get_trading_days("2026-01-01", snapshot_date)
    code_str = df["代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    daily_cols = {"股票": code_str, "股票名称": df["名称"]}
    for d in trading_days:
        prefix = _date_to_col_prefix(d)
        col_main, col_retail, col_pct = f"{prefix}主力", f"{prefix}散户", f"{prefix}涨跌幅"
        if d == snapshot_date:
            # df 中主力/散户净流入已是“万元”，直接写入
            daily_cols[col_main] = df["主力净流入"].round(2)
            daily_cols[col_retail] = df["散户净流入"].round(2)
            daily_cols[col_pct] = df["涨跌幅"].map(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
        else:
            daily_cols[col_main] = None
            daily_cols[col_retail] = None
            daily_cols[col_pct] = None
    daily_wide = pd.DataFrame(daily_cols)

    # 先更新 / 创建每日宽表文件
    if not daily_path.exists():
        write_daily_wide_workbook(daily_wide_df=daily_wide, output_path=daily_path)
        print(f"已创建每日宽表: {daily_path}")
    else:
        # 仅追加当日列，避免重写以往历史；传入 名称 以便新股能补全股票名称
        daily_add = df[["代码", "名称", "主力净流入", "散户净流入", "涨跌幅"]].copy()
        append_daily_fund_flow(existing_path=daily_path, daily_df=daily_add, snapshot_date=snapshot_date)
        print(f"已更新每日宽表当日列: {daily_path}")

    # 读取最新每日宽表，计算前3/5/10/20/40/60日主力净流入之和；每日表为万元，汇总表统一为亿元（万/1e4=亿）
    ROLLING_DAYS = (3, 5, 10, 20, 40, 60)
    daily_wide_latest = pd.read_excel(daily_path, sheet_name="每日资金流入汇总")
    if trading_days:
        days_before = trading_days[:-1]  # 不含当日
        code_series = daily_wide_latest["股票"].astype(str).str.zfill(6)
        summary_codes = summary["股票代码"].astype(str).str.zfill(6)

        def _rolling_sum_wan(n: int) -> pd.Series:
            if len(days_before) < n:
                return pd.Series([None] * len(daily_wide_latest))
            use_days = days_before[-n:]
            cols = [f"{_date_to_col_prefix(d)}主力" for d in use_days]
            for c in cols:
                if c not in daily_wide_latest.columns:
                    daily_wide_latest[c] = None
            return daily_wide_latest[cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)

        for n in ROLLING_DAYS:
            col_name = f"前{n}日主力净流入之和(亿)"
            s_wan = _rolling_sum_wan(n)
            s_yi = (s_wan / 1e4).round(4)  # 万元→亿元
            summary[col_name] = summary_codes.map(dict(zip(code_series, s_yi)))
    else:
        for n in ROLLING_DAYS:
            summary[f"前{n}日主力净流入之和(亿)"] = None

    # 流通市值(亿) 取整
    if "流通市值(亿)" in summary.columns:
        summary["流通市值(亿)"] = (
            pd.to_numeric(summary["流通市值(亿)"], errors="coerce").round(0).astype("Int64")
        )

    write_summary_workbook(summary_df=summary, output_path=summary_path)
    print(f"已写入当日汇总: {summary_path}")
    return summary_path


def main(snapshot_date: str = "2026-03-10", output_dir: str | Path | None = None) -> Path:
    """
    拉取全 A 股资金流，清洗后写入一个 Excel（汇总 + 每日资金流入汇总），截止到 snapshot_date。
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "output"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("正在拉取全 A 股资金流与行情…")
    raw = fetch_all_a_fund_flow(pz=100)
    if raw.empty:
        raise RuntimeError("拉取失败，未获取到数据")
    print(f"拉取到 {len(raw)} 条")

    df = clean_fund_flow(raw)
    industry_df = fetch_industry_map()
    if industry_df is not None:
        df = df.merge(industry_df, on="代码", how="left")
        df["所属行业"] = df["所属行业"].fillna("")
    else:
        df["所属行业"] = ""
    return build_and_write_from_df(df, snapshot_date, output_dir)


def _parse_date(s: str) -> str:
    """'今天' -> 今日 YYYY-MM-DD；'昨天' -> 昨日 YYYY-MM-DD；否则按 YYYY-MM-DD 解析。"""
    today = date.today()
    s = s.strip().lower()
    if s in ("今天", "今日", "today"):
        return today.strftime("%Y-%m-%d")
    if s in ("昨天", "昨日", "yesterday"):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="拉取全 A 股资金流并写入汇总表与每日宽表")
    parser.add_argument(
        "--date",
        dest="dates",
        action="append",
        default=None,
        metavar="DATE",
        help="汇总日期，可多次指定。支持: 今天/昨天 或 YYYY-MM-DD（如 2026-03-11）。不传则跑今天。",
    )
    args = parser.parse_args()
    if args.dates:
        dates = [_parse_date(d) for d in args.dates]
    else:
        dates = [_parse_date("今天")]
    for d in dates:
        print(f"正在拉取并生成 {d} 的汇总…")
        main(snapshot_date=d)
