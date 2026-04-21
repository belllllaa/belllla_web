"""
纳指（FRED: NASDAQCOM）日线：不依赖 pandas_datareader，避免与 Py3.14/pandas 的兼容问题。
"""
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent

print("正在从美联储经济数据库(FRED)获取纳指数据...")

ticker = "NASDAQCOM"
start_date = "1998-08-06"
end_date = "2026-03-11"

# FRED 公开 CSV（无需 API Key）；日期在本地再筛一遍
url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={ticker}"

try:
    nasdaq_data = pd.read_csv(
        url, parse_dates=["observation_date"], index_col="observation_date"
    )
    nasdaq_data = nasdaq_data.loc[start_date:end_date]
    nasdaq_data.dropna(inplace=True)
    nasdaq_data.index.name = "Date"
    nasdaq_data.rename(columns={ticker: "Nasdaq_Close"}, inplace=True)

    out = _SCRIPT_DIR / "nasdaq_fred_prices.csv"
    nasdaq_data.to_csv(out)
    print(f"获取成功！共 {len(nasdaq_data)} 条数据，已保存为: {out}")
except Exception as e:
    print(f"FRED 数据获取失败: {e}")
