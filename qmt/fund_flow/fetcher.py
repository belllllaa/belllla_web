# -*- coding: utf-8 -*-
"""
东方财富 push2 全 A 股资金流与行情拉取（不剔除个股，全部 A 股）。
含简单重试与响应校验，接口异常时便于自动修复。
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# 尽量模拟浏览器，降低被东方财富限流/拒连概率（RemoteDisconnected 多为服务端主动断开）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

# 全部 A 股：沪主板+科创板+深主板+创业板
FS_ALL_A = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

# 请求字段：代码、名称、现价、涨跌幅、总市值、流通市值、主力净流入、小单净流入(散户)、成交额(用于占成交金额)
# 接口返回 diff 为「数组的数组」，顺序与本列表一致
FIELDS = "f12,f14,f2,f3,f20,f21,f62,f184,f6"
FIELD_INDEX = {"f12": 0, "f14": 1, "f2": 2, "f3": 3, "f20": 4, "f21": 5, "f62": 6, "f184": 7, "f6": 8}

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# 重试配置：东方财富有时会主动断开连接，多试几次、拉长间隔
MAX_RETRIES = 4
RETRY_DELAYS = (3, 6, 12, 20)


def _get_proxies() -> dict[str, str] | None:
    """从环境变量读取代理。如 HTTP_PROXY=http://127.0.0.1:7890"""
    url = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not url or not url.strip():
        return None
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("socks"):
        url = "http://" + url
    return {"http": url, "https": url}


def _request_with_retry(params: dict[str, Any], timeout: int = 30) -> dict | None:
    proxies = _get_proxies()
    if proxies:
        logger.info("使用代理: %s", proxies.get("https", proxies.get("http")))
    # 优先用 curl_cffi 模拟 Chrome TLS
    try:
        from curl_cffi import requests as curl_requests
        print("使用 curl_cffi 模拟浏览器请求…", flush=True)
        for i in range(MAX_RETRIES):
            try:
                if i > 0:
                    time.sleep(RETRY_DELAYS[i - 1])
                r = curl_requests.get(
                    CLIST_URL, params=params, headers=HEADERS, timeout=timeout,
                    impersonate="chrome", proxies=proxies,
                )
                r.raise_for_status()
                data = r.json()
                if data is not None:
                    return data
            except Exception as e:
                logger.warning("curl_cffi 请求异常，第 %s 次: %s", i + 1, e)
    except ImportError:
        pass  # 未安装 curl_cffi，用下面 requests

    for i in range(MAX_RETRIES):
        try:
            if i > 0:
                time.sleep(RETRY_DELAYS[i])
            r = requests.get(CLIST_URL, params=params, headers=HEADERS, timeout=timeout, proxies=proxies or {})
            r.raise_for_status()
            data = r.json()
            if data is None:
                logger.warning("API 返回空 body，第 %s 次重试", i + 1)
                continue
            return data
        except requests.RequestException as e:
            logger.warning("请求异常 %s，第 %s 次重试: %s", CLIST_URL, i + 1, e)
        except ValueError as e:
            logger.warning("JSON 解析失败，第 %s 次重试: %s", i + 1, e)
    return None


def _fetch_via_akshare() -> pd.DataFrame:
    """
    备用：用 akshare 的「今日个股资金流排名」拉取，数据源同为东方财富，走 akshare 的请求有时更稳。
    返回列与 fetch_all_a_fund_flow 一致；流通市值/总市值/成交额 无则填 0。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("未安装 akshare，无法使用备用接口")
        return pd.DataFrame()
    # akshare 底层也连东方财富，同样可能被断开；重试 3 次并加延迟
    for attempt in range(3):
        try:
            if attempt > 0:
                delay = (5, 15)[min(attempt - 1, 1)]
                print(f"  备用接口第 {attempt + 1} 次重试（{delay}s 后）…", flush=True)
                time.sleep(delay)
            df = ak.stock_individual_fund_flow_rank(indicator="今日")
            break
        except Exception as e:
            logger.warning("akshare 资金流排名拉取失败（第 %s 次）: %s", attempt + 1, e)
            if attempt == 2:
                return pd.DataFrame()
    else:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    # 列名可能为：代码、名称、最新价、涨跌幅、主力净流入-净额、小单净流入-净额 等
    out = pd.DataFrame()
    out["代码"] = df["代码"].astype(str).str.strip().str.zfill(6)
    out["名称"] = df["名称"].astype(str)
    out["现价"] = pd.to_numeric(df.get("最新价", df.get("现价", 0)), errors="coerce").fillna(0)
    # 涨跌幅可能为 "1.23%" 或数值
    pct = df["涨跌幅"].astype(str).str.replace("%", "", regex=False)
    out["涨跌幅"] = pd.to_numeric(pct, errors="coerce").fillna(0)
    out["总市值"] = pd.to_numeric(df.get("总市值", 0), errors="coerce").fillna(0)
    out["流通市值"] = pd.to_numeric(df.get("流通市值", 0), errors="coerce").fillna(0)
    main_col = [c for c in df.columns if "主力" in c and "净额" in c]
    retail_col = [c for c in df.columns if "小单" in c and "净额" in c]
    out["主力净流入"] = df[main_col[0]].astype(float) if main_col else 0.0
    out["散户净流入"] = df[retail_col[0]].astype(float) if retail_col else 0.0
    out["成交额"] = pd.to_numeric(df.get("成交额", 0), errors="coerce").fillna(0)
    print(f"已通过 akshare 备用接口拉取 {len(out)} 条", flush=True)
    return out


def fetch_all_a_fund_flow(pz: int = 500) -> pd.DataFrame:
    """
    分页拉取全部 A 股当日资金流与行情。
    返回列：代码、名称、现价、涨跌幅、总市值、流通市值、主力净流入、散户净流入。
    直连东方财富失败时自动尝试 akshare 备用接口（今日资金流排名）。
    """
    all_rows: list[dict[str, Any]] = []
    pn = 1
    while True:
        params = {
            "fid": "f62",
            "po": "1",
            "pz": pz,
            "pn": pn,
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": FS_ALL_A,
            "fields": FIELDS,
        }
        data = _request_with_retry(params)
        if data is None:
            if pn == 1:
                print("直连东方财富失败，正在尝试 akshare 备用接口…", flush=True)
                fallback = _fetch_via_akshare()
                if not fallback.empty:
                    return fallback
                return pd.DataFrame()
            break

        # 兼容不同结构：data.diff 或 data.data.diff 等
        diff = None
        if isinstance(data.get("data"), dict) and "diff" in data["data"]:
            diff = data["data"]["diff"]
        elif isinstance(data.get("data"), list):
            diff = data["data"]
        if not diff:
            logger.warning("未找到列表数据，响应键: %s", list(data.keys()) if data else None)
            if pn == 1:
                return pd.DataFrame()
            break

        for item in diff:
            # 东方财富 diff 常为按 fields 顺序的数组，少数为 dict
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
                }
            elif isinstance(item, dict):
                row = {
                    "代码": str(item.get("f12", "")).strip().zfill(6),
                    "名称": item.get("f14", ""),
                    "现价": _num(item.get("f2")),
                    "涨跌幅": _num(item.get("f3")),
                    "总市值": _num(item.get("f20")),
                    "流通市值": _num(item.get("f21")),
                    "主力净流入": _num(item.get("f62")),
                    "散户净流入": _num(item.get("f184")),
                    "成交额": _num(item.get("f6", 0)),
                }
            else:
                continue
            all_rows.append(row)

        # 接口常限制每页约 100 条，持续翻页直到本页条数不足一页
        if len(diff) == 0:
            break
        if len(diff) < pz:
            break
        pn += 1
        time.sleep(0.8)  # 页间延迟，减轻被限流

    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    return df


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = fetch_all_a_fund_flow()
    print("rows:", len(df))
    if not df.empty:
        print(df.head())
