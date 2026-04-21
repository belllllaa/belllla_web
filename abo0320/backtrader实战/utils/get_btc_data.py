"""
BTC 日线：优先从 Binance 公开 API 拉取（避免 Yahoo Finance 限流）。
标的为 BTCUSDT，与课程中 Yahoo 的 BTC-USD 日线高度接近，均用于回测学习。
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
# 若本地无法访问 api.binance.com，可换节点或自行代理后再试
USER_AGENT = "Mozilla/5.0 (compatible; get_btc_data/1.0)"


def _fetch_binance_daily_btcusdt(start_date: str, end_date: str) -> pd.DataFrame:
    """拉取 [start_date, end_date) 区间的 Binance 日线 K 线。"""
    start_ms = int(pd.Timestamp(start_date, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_date, tz="UTC").timestamp() * 1000)

    all_rows = []
    current = start_ms
    while current < end_ms:
        params = urllib.parse.urlencode(
            {
                "symbol": "BTCUSDT",
                "interval": "1d",
                "startTime": current,
                "endTime": end_ms - 1,
                "limit": 1000,
            }
        )
        url = f"{BINANCE_KLINES}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                chunk = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Binance 请求失败: {e}") from e

        if not chunk:
            break

        for k in chunk:
            open_t = int(k[0])
            if open_t >= end_ms:
                continue
            all_rows.append(
                {
                    "ts": open_t,
                    "Open": float(k[1]),
                    "High": float(k[2]),
                    "Low": float(k[3]),
                    "Close": float(k[4]),
                    "Volume": float(k[5]),
                }
            )

        last_open = int(chunk[-1][0])
        if last_open >= end_ms - 86400_000:
            break
        current = last_open + 86400_000
        time.sleep(0.25)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows).drop_duplicates(subset=["ts"]).sort_values("ts")
    idx = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.drop(columns=["ts"])
    df.index = idx
    return df


def download_btc_data():
    """
    下载 BTC 历史数据并清洗为 Backtrader 可直接读取的 CSV 格式
    """
    symbol = "BTC-USD"
    start_date = "2020-01-01"
    end_date = "2026-01-01"
    output_file = "btc_daily_2020_2026.csv"

    print(f"正在从 Binance 拉取 BTCUSDT 日线（对应课程 {symbol} 区间）...")
    print(f"区间: [{start_date}, {end_date})")

    try:
        df = _fetch_binance_daily_btcusdt(start_date, end_date)
    except RuntimeError as e:
        print(str(e))
        return

    if df.empty:
        print("下载失败：数据为空（可检查网络或 Binance 是否可达）。")
        return

    df["OpenInterest"] = 0
    cols = ["Open", "High", "Low", "Close", "Volume", "OpenInterest"]
    df = df[cols]

    # GenericCSVData 默认 headers=False：不写表头，首列为日期
    df.to_csv(output_file, date_format="%Y-%m-%d", header=False)
    print(f"成功，已保存: {output_file}")
    print(f"行数: {len(df)}")


if __name__ == "__main__":
    download_btc_data()
