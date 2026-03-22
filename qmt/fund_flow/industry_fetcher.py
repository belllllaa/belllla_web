# -*- coding: utf-8 -*-
"""
获取全 A 股所属行业（同花顺 + 东方财富），用于汇总表「所属行业」列。
多源合并，减少行业缺失。
"""
from __future__ import annotations

import time
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def fetch_industry_map() -> Optional[pd.DataFrame]:
    """
    返回 DataFrame 两列：代码, 所属行业。
    先取同花顺行业，再取东方财富行业成份补全缺失。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("未安装 akshare，跳过行业获取")
        return None

    # 1) 同花顺行业
    df_ths = _fetch_industry_ths(ak)
    # 2) 东方财富行业成份（akshare），补全同花顺未覆盖的代码
    df_em = _fetch_industry_em_akshare(ak)
    # 3) 合并：同花顺优先，东财填漏
    out = []
    seen = set()
    if df_ths is not None and not df_ths.empty:
        for _, row in df_ths.iterrows():
            code = str(row["代码"]).strip().zfill(6)
            if code not in seen and code.isdigit():
                seen.add(code)
                out.append({"代码": code, "所属行业": row["所属行业"]})
    if df_em is not None and not df_em.empty:
        for _, row in df_em.iterrows():
            code = str(row["代码"]).strip().zfill(6)
            if code not in seen and code.isdigit():
                seen.add(code)
                out.append({"代码": code, "所属行业": row["所属行业"]})
    if out:
        return pd.DataFrame(out)
    return _fetch_industry_eastmoney()


def _fetch_industry_ths(ak) -> Optional[pd.DataFrame]:
    """同花顺行业：行业列表 + 各行业成份股 -> 代码, 所属行业"""
    out = []
    try:
        industries = ak.stock_board_industry_summary_ths()
    except Exception:
        industries = getattr(ak, "stock_board_industry_name_ths", lambda: None)()
    if industries is None or (hasattr(industries, "empty") and industries.empty):
        return None
    if hasattr(industries, "iterrows"):
        names = industries.get("板块名称", industries.get("name", pd.Series()))
        if names.empty and len(industries) > 0:
            names = industries.iloc[:, 0]
    else:
        names = industries if isinstance(industries, (list, tuple)) else []
    for name in names:
        name = str(name).strip() if name else ""
        if not name:
            continue
        try:
            cons = ak.stock_board_industry_cons_ths(symbol=name)
            if cons is None or cons.empty:
                continue
            code_col = "代码" if "代码" in cons.columns else "code"
            if code_col not in cons.columns:
                continue
            for c in cons[code_col]:
                out.append({"代码": str(c).strip().zfill(6), "所属行业": name})
        except Exception as e:
            logger.debug("同花顺行业 %s: %s", name, e)
        time.sleep(0.08)
    return pd.DataFrame(out).drop_duplicates(subset=["代码"], keep="first") if out else None


def _fetch_industry_em_akshare(ak) -> Optional[pd.DataFrame]:
    """东方财富行业板块（akshare）：行业列表 + 各行业成份股，补全缺失"""
    out = []
    try:
        name_df = ak.stock_board_industry_name_em()
        if name_df is None or name_df.empty:
            return None
        name_col = "板块名称" if "板块名称" in name_df.columns else "name"
        if name_col not in name_df.columns and len(name_df.columns) > 0:
            name_col = name_df.columns[0]
        names = name_df[name_col].dropna().unique().tolist()
        for name in names:
            name = str(name).strip() if name else ""
            if not name:
                continue
            try:
                cons = ak.stock_board_industry_cons_em(symbol=name)
                if cons is None or cons.empty:
                    continue
                code_col = "代码" if "代码" in cons.columns else "code"
                if code_col not in cons.columns:
                    continue
                for c in cons[code_col]:
                    out.append({"代码": str(c).strip().zfill(6), "所属行业": name})
            except Exception as e:
                logger.debug("东财行业 %s: %s", name, e)
            time.sleep(0.08)
    except Exception as e:
        logger.warning("akshare 东财行业获取失败: %s", e)
        return None
    return pd.DataFrame(out).drop_duplicates(subset=["代码"], keep="first") if out else None


def _fetch_industry_eastmoney() -> Optional[pd.DataFrame]:
    """东方财富行业板块：先取行业列表，再取各行业成分，建 代码->行业 映射。"""
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        "Referer": "https://quote.eastmoney.com/",
    }
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    # 行业板块列表 m:90+t:2
    params = {"fid": "f62", "po": "1", "pz": "200", "pn": "1", "np": "1", "fltt": "2", "invt": "2", "fs": "m:90+t:2", "fields": "f12,f14"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        data = r.json()
        if not data or not isinstance(data.get("data"), dict):
            return None
        diff = data["data"].get("diff") or []
        if not diff:
            return None
        out = []
        for item in diff:
            if isinstance(item, (list, tuple)):
                if len(item) < 2:
                    continue
                bk_code = str(item[0]).strip()
                bk_name = str(item[1]).strip()
            else:
                bk_code = str(item.get("f12", "")).strip()
                bk_name = str(item.get("f14", "")).strip()
            if not bk_code or not bk_name:
                continue
            time.sleep(0.1)
            p2 = {"fid": "f12", "po": "1", "pz": "500", "pn": "1", "np": "1", "fltt": "2", "invt": "2", "fs": f"b:{bk_code}", "fields": "f12,f14"}
            r2 = requests.get(url, params=p2, headers=headers, timeout=15)
            d2 = r2.json()
            if not d2 or not isinstance(d2.get("data"), dict):
                continue
            for row in (d2["data"].get("diff") or []):
                code = str(row[0] if isinstance(row, (list, tuple)) else row.get("f12", "")).strip().zfill(6)
                if code and code.isdigit():
                    out.append({"代码": code, "所属行业": bk_name})
        if not out:
            return None
        return pd.DataFrame(out).drop_duplicates(subset=["代码"], keep="first")
    except Exception as e:
        logger.warning("东方财富行业获取失败: %s", e)
        return None
