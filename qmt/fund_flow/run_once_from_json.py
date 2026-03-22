# -*- coding: utf-8 -*-
"""
从浏览器保存的东方财富 API JSON 生成汇总表与每日宽表（直连失败时用手动导入）。

接口说明：该接口每页通常只返回约 100 条，全 A 约 5500+ 只需分页请求多份 JSON 再合并。

行业说明：所属行业目前由单独接口（akshare/东财行业板块）拉取，若你处网络被限会拿不到。
  - 若 JSON 里带行业：保存时在 URL 的 fields 参数中加上行业字段（如 f127），则解析时会自动填入所属行业。
  - 离线用法：在 output 目录放 industry_map.csv（列：代码,所属行业），网络失败时会用该表补全所属行业。

步骤：
1. 在浏览器中依次打开各页（只改 pn= 页码），每页复制全部 JSON 另存为本地文件：
   第1页: ...&pn=1&pz=5000&...  → 保存为 output/page1.json
   基址: https://push2.eastmoney.com/api/qt/clist/get?fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&pn=1&pz=5000&fid=f62&po=1&np=1&fltt=2&invt=2&fields=f12,f14,f2,f3,f20,f21,f62,f184,f6
2. 运行: py -m qmt.fund_flow.run_once_from_json --input qmt/fund_flow/output --date 2026-03-11
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_here = Path(__file__).resolve().parent
if __name__ == "__main__" and __package__ is None:
    _root = _here.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from qmt.fund_flow.clean import clean_fund_flow
from qmt.fund_flow.run_once import build_and_write_from_df
from qmt.fund_flow.industry_fetcher import fetch_industry_map

# 与 fetcher 一致：接口 diff 按此顺序
FIELD_INDEX = {"f12": 0, "f14": 1, "f2": 2, "f3": 3, "f20": 4, "f21": 5, "f62": 6, "f184": 7, "f6": 8}


def _num(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, str):
        # 接口有时返回 "1722113024.0JS:1722113024"，取前半数字
        v = v.split("JS:")[0].strip()
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _load_diffs_from_paths(paths: list[Path]) -> list:
    """从多个 JSON 文件加载并合并 data.data.diff 数组。"""
    all_diff = []
    for p in paths:
        if not p.exists():
            print(f"跳过不存在的文件: {p}")
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"JSON 解析失败 {p}: {e}")
            continue
        diff = None
        if isinstance(data.get("data"), dict) and "diff" in data["data"]:
            diff = data["data"]["diff"]
        elif isinstance(data.get("data"), list):
            diff = data["data"]
        if diff:
            all_diff.extend(diff)
            print(f"  已读 {p.name}: {len(diff)} 条")
    return all_diff


def _industry_from_item(item: dict) -> str:
    """从接口单项中取行业（若 URL 的 fields 含行业字段）。常见字段：f127/f100/hy/行业。"""
    for key in ("f127", "f100", "hy", "行业", "f124"):
        v = item.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _parse_diff_to_df(diff: list) -> pd.DataFrame:
    """将东方财富 diff 数组解析为与 fetcher 返回同结构的 DataFrame。若项中含行业字段则一并解析。"""
    rows = []
    for item in diff:
        if isinstance(item, (list, tuple)):
            if len(item) < 8:
                continue
            row = {
                "代码": str(item[FIELD_INDEX["f12"]] or "").strip().zfill(6),
                "名称": str(item[FIELD_INDEX["f14"]] or ""),
                "现价": _num(item[FIELD_INDEX["f2"]]),
                "涨跌幅": _num(item[FIELD_INDEX["f3"]]),
                "总市值": _num(item[FIELD_INDEX["f20"]]),
                "流通市值": _num(item[FIELD_INDEX["f21"]]),
                "主力净流入": _num(item[FIELD_INDEX["f62"]]),
                "散户净流入": _num(item[FIELD_INDEX["f184"]]),
                "成交额": _num(item[FIELD_INDEX["f6"]]) if len(item) > 8 else 0,
                "所属行业": "",
            }
        elif isinstance(item, dict):
            row = {
                "代码": str(item.get("f12", "") or "").strip().zfill(6),
                "名称": str(item.get("f14", "") or ""),
                "现价": _num(item.get("f2")),
                "涨跌幅": _num(item.get("f3")),
                "总市值": _num(item.get("f20")),
                "流通市值": _num(item.get("f21")),
                "主力净流入": _num(item.get("f62")),
                "散户净流入": _num(item.get("f184")),
                "成交额": _num(item.get("f6", 0)),
                "所属行业": _industry_from_item(item),
            }
        else:
            continue
        rows.append(row)
    return pd.DataFrame(rows)


def main_from_json(
    input_paths: list[str] | list[Path],
    snapshot_date: str,
    output_dir: str | Path | None = None,
) -> Path:
    if output_dir is None:
        output_dir = _here / "output"
    output_dir = Path(output_dir)
    paths = []
    for p in input_paths:
        p = Path(p)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.json")))
        else:
            paths.append(p)
    if not paths:
        raise FileNotFoundError("未找到任何 JSON 文件")
    print(f"正在从 {len(paths)} 个文件读取…")
    diff = _load_diffs_from_paths(paths)
    if not diff:
        raise RuntimeError("所有 JSON 中均无 data.diff 数据，请确认是东方财富 push2 接口的完整响应")
    raw = _parse_diff_to_df(diff)
    print(f"共解析 {len(raw)} 条，正在清洗并生成汇总…")
    df = clean_fund_flow(raw)
    # 所属行业：优先用 JSON 里带的（若保存时 URL 的 fields 含行业字段），再补网络/本地
    if "所属行业" not in df.columns:
        df["所属行业"] = ""
    df["所属行业"] = df["所属行业"].fillna("").astype(str).str.strip()
    industry_df = fetch_industry_map()
    if industry_df is not None:
        df = df.merge(industry_df, on="代码", how="left", suffixes=("", "_net"))
        if "所属行业_net" in df.columns:
            empty = df["所属行业"] == ""
            df.loc[empty, "所属行业"] = df.loc[empty, "所属行业_net"].fillna("")
            df = df.drop(columns=["所属行业_net"])
    else:
        pass  # 保持 JSON 解析出的所属行业（可能全为空）
    # 网络失败时尝试本地行业映射表（代码,所属行业），便于离线使用
    local_map = output_dir / "industry_map.csv"
    if local_map.exists() and df["所属行业"].str.strip().eq("").all():
        try:
            local_df = pd.read_csv(local_map, encoding="utf-8")
            if "代码" in local_df.columns and "所属行业" in local_df.columns:
                local_df["代码"] = local_df["代码"].astype(str).str.strip().str.zfill(6)
                df = df.drop(columns=["所属行业"]).merge(local_df[["代码", "所属行业"]], on="代码", how="left")
                df["所属行业"] = df["所属行业"].fillna("")
                print("  已从本地 industry_map.csv 填充所属行业", flush=True)
        except Exception as e:
            print(f"  读取 industry_map.csv 失败: {e}", flush=True)
    df["所属行业"] = df["所属行业"].fillna("")
    return build_and_write_from_df(df, snapshot_date, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="从浏览器保存的东方财富 API JSON 生成资金流汇总表与每日宽表",
    )
    parser.add_argument(
        "--input",
        "-i",
        nargs="+",
        required=True,
        metavar="FILE_OR_DIR",
        help="JSON 文件路径或目录（可多个，多页合并）。",
    )
    parser.add_argument(
        "--date",
        "-d",
        default="2026-03-11",
        metavar="YYYY-MM-DD",
        help="汇总日期，如 2026-03-11",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help="输出目录，默认 qmt/fund_flow/output",
    )
    args = parser.parse_args()
    main_from_json(args.input, args.date, args.output_dir)
