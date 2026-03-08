# -*- coding: utf-8 -*-
"""
每日 PEG 选股：用东方财富机构预测的未来三年复合增长率计算 PEG，筛出 PEG<0.5 且市值最小的前 5 只。

PEG = PE / 未来三年复合增长率（%）
例如今年 2025 则用 2025、2026、2027 三年预测 EPS 计算 2025→2027 的复合增长率（CAGR）。

数据来源（通过 akshare）：
- 机构预测：东方财富 盈利预测（一致预期 EPS），取 2025/2026/2027 年预测每股收益
- 行情与估值：东方财富 沪深京 A 股实时行情（市盈率-动态、总市值）

使用：每日收盘后运行一次即可。
  pip install akshare pandas
  python scripts/peg_top5_eastmoney.py

说明：
- 三年复合增长率 = (EPS_2027/EPS_2025)^(1/2)-1，再乘以 100 得到百分比。
- 若请求行情时报代理/网络错误，可检查本机代理或稍后重试（东方财富接口有时会限流）。
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

# 请求东方财富时禁用代理，避免代理导致连接失败
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

def _find_eps_column(df, year):
    """在盈利预测表中找到某年预测每股收益列名。"""
    for c in df.columns:
        if str(year) in c and ("收益" in c or "EPS" in c.upper()):
            return c
    return None


def _get_three_year_cagr(df_forecast):
    """从盈利预测表取 2025/2026/2027 预测每股收益，算 2025→2027 三年复合增长率（%）。"""
    import pandas as pd
    col_25 = _find_eps_column(df_forecast, 2025)
    col_26 = _find_eps_column(df_forecast, 2026)
    col_27 = _find_eps_column(df_forecast, 2027)
    if not all([col_25, col_27]):  # 至少需要 2025 与 2027
        return None
    eps25 = pd.to_numeric(df_forecast[col_25], errors="coerce")
    eps27 = pd.to_numeric(df_forecast[col_27], errors="coerce")
    # 三年复合：2025→2027 共 2 年，CAGR = (EPS_2027/EPS_2025)^(1/2)-1
    ratio = eps27 / eps25
    ratio = ratio.replace([float("inf"), -float("inf")], float("nan"))
    cagr = ratio ** 0.5 - 1.0
    cagr = cagr.replace([float("inf"), -float("inf")], float("nan"))
    growth_pct = cagr * 100
    return growth_pct


def main():
    try:
        import akshare as ak
        import pandas as pd
    except ImportError:
        print("请先安装: pip install akshare pandas")
        sys.exit(1)

    print("正在获取东方财富 盈利预测（机构一致预期）…")
    df_forecast = ak.stock_profit_forecast_em()
    if df_forecast is None or df_forecast.empty:
        print("未获取到盈利预测数据")
        sys.exit(1)

    # 代码列名可能是 "代码" 或 "股票代码"
    code_col = "代码" if "代码" in df_forecast.columns else "股票代码"
    if code_col not in df_forecast.columns:
        print("盈利预测表中未找到代码列", list(df_forecast.columns))
        sys.exit(1)

    growth = _get_three_year_cagr(df_forecast)
    if growth is None:
        print("无法从盈利预测表解析 2025/2027 预测收益列（需有 2025、2027 年列）", list(df_forecast.columns))
        sys.exit(1)

    df_forecast = df_forecast.copy()
    df_forecast["growth_pct"] = growth
    # 只保留增长率有效且为正的（PEG 才有意义）
    df_forecast = df_forecast[df_forecast["growth_pct"].notna() & (df_forecast["growth_pct"] > 0)]
    df_forecast["代码"] = df_forecast[code_col].astype(str).str.strip()

    print("正在获取沪深京 A 股实时行情（含市盈率、总市值）…")
    df_spot = None
    for attempt in range(2):
        try:
            df_spot = ak.stock_zh_a_spot_em()
            break
        except Exception as e:
            if attempt == 0:
                print("  请求行情失败，5 秒后重试…", str(e)[:80])
                time.sleep(5)
            else:
                _fallback_without_spot(df_forecast)
                print("\n提示：完整结果需行情接口可用，请关闭 VPN/代理或在网络稳定时重试。")
                return 1
    if df_spot is None or df_spot.empty:
        print("未获取到行情数据")
        _fallback_without_spot(df_forecast)
        return 1

    df_spot["代码"] = df_spot["代码"].astype(str).str.strip()
    # 合并：仅保留有机构预测且增长率>0 的股票
    merged = df_spot.merge(
        df_forecast[["代码", "growth_pct"]].drop_duplicates("代码"),
        on="代码",
        how="inner",
    )

    # 市盈率-动态：负或无效的排除
    pe_col = "市盈率-动态"
    if pe_col not in merged.columns:
        print("行情表中无 市盈率-动态 列", list(merged.columns))
        sys.exit(1)
    merged[pe_col] = pd.to_numeric(merged[pe_col], errors="coerce")
    merged = merged[merged[pe_col].notna() & (merged[pe_col] > 0)]

    # PEG = PE / 增长率(%)，例如 PE=20、增长率=40% -> PEG=0.5
    merged["PEG"] = merged[pe_col] / merged["growth_pct"]
    merged = merged[merged["PEG"].notna() & merged["PEG"].between(0.0001, 0.5)]

    # 按总市值升序，取前 5
    merged["总市值"] = pd.to_numeric(merged["总市值"], errors="coerce")
    merged = merged[merged["总市值"].notna() & (merged["总市值"] > 0)]
    top5 = merged.nsmallest(5, "总市值")

    if top5.empty:
        print("当前无满足 PEG<0.5 且市值有效的股票")
        sys.exit(0)

    print("\n" + "=" * 60)
    print("PEG<0.5 且市值最小的前 5 只（PEG=PE/未来三年复合增长率，东方财富）")
    print("生成时间:", datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 60)
    for i, row in top5.iterrows():
        print(
            f"  {row['代码']}  {row['名称']}  "
            f"市值:{row['总市值']/1e8:.2f}亿  "
            f"PE:{row[pe_col]:.1f}  三年CAGR:{row['growth_pct']:.1f}%  PEG:{row['PEG']:.3f}"
        )
    print("=" * 60)
    return 0


def _fallback_without_spot(df_forecast):
    """行情接口失败时：仅按三年CAGR 输出前5（无PE/市值/PEG），证明盈利预测与CAGR 已跑通。"""
    name_col = "名称" if "名称" in df_forecast.columns else "股票简称"
    if name_col not in df_forecast.columns:
        name_col = df_forecast.columns[2] if len(df_forecast.columns) > 2 else "代码"
    top = df_forecast.nlargest(5, "growth_pct")
    print("\n" + "=" * 60)
    print("（仅盈利预测）三年CAGR 最高的 5 只（未获取行情，无 PE/市值/PEG）")
    print("生成时间:", datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 60)
    for _, row in top.iterrows():
        print(f"  {row['代码']}  {row.get(name_col, '')}  三年CAGR:{row['growth_pct']:.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main() or 0)
