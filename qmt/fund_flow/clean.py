# -*- coding: utf-8 -*-
"""
资金流数据清洗：全部 A 股不剔除，仅做单位与格式统一。
汇总表：市值→亿元，流入→万元。
"""
from __future__ import annotations

import pandas as pd


def _to_yiyuan(v: float) -> float:
    """接口市值多为元，转为亿元。若数值已像亿元则不再除。"""
    if v is None or v != v:
        return 0.0
    v = float(v)
    if v == 0:
        return 0.0
    if v >= 1e4:
        return round(v / 1e8, 4)
    return round(v, 4)


def _to_wanyuan(v: float) -> float:
    """接口流入多为元，转为万元。若已像万元则不再除。"""
    if v is None or v != v:
        return 0.0
    v = float(v)
    if v == 0:
        return 0.0
    if abs(v) >= 1e4:
        return round(v / 1e4, 2)
    return round(v, 2)


def clean_fund_flow(df: pd.DataFrame) -> pd.DataFrame:
    """
    清洗资金流 DataFrame。
    - 代码统一为 6 位字符串
    - 总市值、流通市值 → 亿元
    - 主力净流入、散户净流入 → 万元
    - 不剔除任何个股
    """
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "代码" in out.columns:
        out["代码"] = out["代码"].astype(str).str.strip().str.zfill(6)
    for col in ["现价", "涨跌幅"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    if "总市值" in out.columns:
        out["总市值"] = out["总市值"].apply(_to_yiyuan)
    if "流通市值" in out.columns:
        out["流通市值"] = out["流通市值"].apply(_to_yiyuan)
    if "主力净流入" in out.columns:
        out["主力净流入"] = out["主力净流入"].apply(_to_wanyuan)
    if "散户净流入" in out.columns:
        out["散户净流入"] = out["散户净流入"].apply(_to_wanyuan)
    return out
