# -*- coding: utf-8 -*-
"""
检查 fund_flow_*.xlsx 数据完整性：汇总表列、每日表列与填充率。
用法: py -m qmt.fund_flow.verify_excel [--path output/fund_flow_20260310.xlsx]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(_root))

import pandas as pd


def _resolve_path(p: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path
    base = Path(__file__).resolve().parent
    if (base / path).exists():
        return (base / path).resolve()
    return (base.parent.parent / path).resolve()


def verify(excel_path: str | Path) -> bool:
    path = _resolve_path(str(excel_path))
    if not path.exists():
        print(f"文件不存在: {path}")
        return False
    print(f"检查: {path}\n")
    ok = True

    # 汇总 sheet
    try:
        summary = pd.read_excel(path, sheet_name="汇总")
    except Exception as e:
        print(f"读取「汇总」失败: {e}")
        return False
    required = ["股票代码", "股票名称", "最新价", "涨跌幅", "主力净流入(万)", "散户净流入(万)", "流通市值(亿)"]
    missing = [c for c in required if c not in summary.columns]
    if missing:
        print(f"汇总表缺少列: {missing}")
        ok = False
    else:
        print(f"汇总表: {len(summary)} 行, 必要列齐全")
        # 检查关键列非空
        for col in ["股票代码", "最新价", "主力净流入(万)"]:
            non_null = summary[col].notna().sum()
            print(f"  - {col} 非空: {non_null}/{len(summary)}")
    print()

    # 每日 sheet
    try:
        daily = pd.read_excel(path, sheet_name="每日资金流入汇总")
    except Exception as e:
        print(f"读取「每日资金流入汇总」失败: {e}")
        return False
    if "股票" not in daily.columns:
        print("每日表缺少「股票」列")
        ok = False
    else:
        main_cols = [c for c in daily.columns if c.endswith("主力")]
        retail_cols = [c for c in daily.columns if c.endswith("散户")]
        pct_cols = [c for c in daily.columns if c.endswith("涨跌幅")]
        print(f"每日表: {len(daily)} 行")
        print(f"  - 主力列数: {len(main_cols)}, 散户列数: {len(retail_cols)}, 涨跌幅列数: {len(pct_cols)}")
        if main_cols:
            first_main, last_main = main_cols[0], main_cols[-1]
            print(f"  - {first_main} 非空: {daily[first_main].notna().sum()}/{len(daily)}")
            print(f"  - {last_main} 非空: {daily[last_main].notna().sum()}/{len(daily)}")
    print()
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="output/fund_flow_20260310.xlsx", help="Excel 路径")
    args = parser.parse_args()
    success = verify(args.path)
    sys.exit(0 if success else 1)
