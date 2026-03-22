# -*- coding: utf-8 -*-
"""
在网络可用时拉取一次全 A 股 代码->所属行业，保存为 output/industry_map.csv。
之后 run_once_from_json 在网络失败时会自动用该文件补全「所属行业」列。
用法: py -m qmt.fund_flow.export_industry_map
"""
from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
if __name__ == "__main__" and __package__ is None:
    _root = _here.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from qmt.fund_flow.industry_fetcher import fetch_industry_map


def main() -> None:
    out_path = _here / "output" / "industry_map.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print("正在拉取行业映射…", flush=True)
    df = fetch_industry_map()
    if df is None or df.empty:
        print("拉取失败，未生成文件。", flush=True)
        return
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"已保存 {len(df)} 条到 {out_path}", flush=True)


if __name__ == "__main__":
    main()
