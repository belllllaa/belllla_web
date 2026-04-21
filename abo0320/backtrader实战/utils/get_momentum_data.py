"""
动量/多标的回测用日线数据：沪深300成分股，AkShare 拉取 A 股日线（默认前复权）。

输出：每只股票一个 CSV，列与课程一致（无表头）：Date + Open, High, Low, Close, Volume, OpenInterest(0)

默认区间：2023-01-01 至 2025-12-31（含）

依赖：
  pip install akshare pandas

网络：行情来自东方财富等接口。若出现 ProxyError，请检查系统/环境代理（或关闭无效代理）后重试。

用法：
  python get_momentum_data.py
  python get_momentum_data.py --output-dir ../data/csi300_daily --sleep 0.2
  python get_momentum_data.py --codes 600519,000858 --start 2023-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

try:
    import akshare as ak
except ImportError as e:
    raise SystemExit(
        "请先安装: pip install akshare pandas\n"
        f"原始错误: {e}"
    ) from e


def _date_to_ak(s: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    return pd.Timestamp(s).strftime("%Y%m%d")


def save_backtrader_csv(df: pd.DataFrame, output_path: str | Path) -> Path:
    """无表头 OHLCV+OpenInterest，首列日期，与 GenericCSVData 默认一致。"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    if "OpenInterest" not in df.columns:
        df["OpenInterest"] = 0
    cols = ["Open", "High", "Low", "Close", "Volume", "OpenInterest"]
    df = df[[c for c in cols if c in df.columns]]
    df.to_csv(out, date_format="%Y-%m-%d", header=False)
    return out.resolve()


def get_csi300_codes() -> pd.DataFrame:
    """沪深300成分：列含 品种代码、品种名称。"""
    df = ak.index_stock_cons(symbol="000300")
    return df


def fetch_stock_daily_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    retries: int = 4,
    sleep_s: float = 0.15,
) -> pd.DataFrame:
    """
    单只 A 股日线 -> 索引为日期，列 Open/High/Low/Close/Volume。
    adjust: qfq 前复权 / hfq 后复权 / '' 不复权
    """
    start_ak = _date_to_ak(start_date)
    end_ak = _date_to_ak(end_date)
    symbol = str(symbol).strip().zfill(6)

    last_err: Exception | None = None
    raw: pd.DataFrame | None = None
    for attempt in range(retries):
        try:
            raw = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_ak,
                end_date=end_ak,
                adjust=adjust,
            )
            break
        except Exception as e:
            last_err = e
            time.sleep(sleep_s * (2**attempt))
    else:
        raise RuntimeError(f"{symbol} 行情拉取失败: {last_err}") from last_err

    if raw is None or raw.empty:
        return pd.DataFrame()

    rename = {
        "开盘": "Open",
        "最高": "High",
        "最低": "Low",
        "收盘": "Close",
        "成交量": "Volume",
    }
    df = raw.rename(columns=rename)
    if "日期" not in df.columns:
        return pd.DataFrame()
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.set_index("日期").sort_index()
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            return pd.DataFrame()
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    return df[["Open", "High", "Low", "Close", "Volume"]]


def download_csi300_pool(
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31",
    output_dir: str | Path | None = None,
    adjust: str = "qfq",
    sleep_s: float = 0.2,
    max_stocks: int | None = None,
) -> Path:
    """
    下载沪深300全部成分股日线，写入 output_dir。
    同时写入 universe.csv（代码、名称、文件名、行数）。
    """
    base = Path(__file__).resolve().parent.parent / "data" / "csi300_daily"
    out_dir = Path(output_dir) if output_dir else base
    if not out_dir.is_absolute():
        out_dir = (Path(__file__).resolve().parent.parent / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cons = get_csi300_codes()
    code_col = "品种代码" if "品种代码" in cons.columns else cons.columns[0]
    name_col = "品种名称" if "品种名称" in cons.columns else cons.columns[1]

    rows_manifest: list[dict] = []
    n_ok = 0
    n_fail = 0

    sub = cons
    if max_stocks is not None:
        sub = sub.head(max_stocks)

    print(f"沪深300成分股数量: {len(cons)}  将下载: {len(sub)}  区间: [{start_date}, {end_date}]  复权: {adjust}")
    print(f"输出目录: {out_dir}")

    for _, r in sub.iterrows():
        if pd.isna(r[code_col]):
            continue
        try:
            code = str(int(float(str(r[code_col]).strip()))).zfill(6)
        except (ValueError, TypeError):
            code = str(r[code_col]).strip().zfill(6)
        if not code:
            continue
        name = str(r.get(name_col, ""))
        path = out_dir / f"{code}.csv"
        try:
            df = fetch_stock_daily_ohlcv(code, start_date, end_date, adjust=adjust, sleep_s=sleep_s)
            time.sleep(sleep_s)
            if df.empty:
                print(f"  [空] {code} {name}")
                n_fail += 1
                rows_manifest.append({"code": code, "name": name, "file": path.name, "bars": 0, "ok": False})
                continue
            save_backtrader_csv(df, path)
            n_ok += 1
            rows_manifest.append(
                {"code": code, "name": name, "file": path.name, "bars": len(df), "ok": True}
            )
            print(f"  [ok] {code} {name}  bars={len(df)}")
        except Exception as e:
            n_fail += 1
            rows_manifest.append({"code": code, "name": name, "file": path.name, "bars": 0, "ok": False, "error": str(e)})
            print(f"  [fail] {code} {name}  {e}")

    man = pd.DataFrame(rows_manifest)
    man_path = out_dir / "universe.csv"
    man.to_csv(man_path, index=False, encoding="utf-8-sig")
    print(f"完成: 成功 {n_ok}  失败 {n_fail}  清单: {man_path}")
    return out_dir.resolve()


def download_single_symbol(
    symbol: str,
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31",
    output_path: str | Path | None = None,
    adjust: str = "qfq",
) -> Path | None:
    """单标的 CSV，默认写入 data/csi300_daily/{code}.csv（若未指定 -o）。"""
    code = str(symbol).strip().zfill(6)
    if output_path is None:
        base = Path(__file__).resolve().parent.parent / "data" / "csi300_daily"
        base.mkdir(parents=True, exist_ok=True)
        output_path = base / f"{code}.csv"
    else:
        output_path = Path(output_path)

    try:
        df = fetch_stock_daily_ohlcv(code, start_date, end_date, adjust=adjust)
    except RuntimeError as e:
        print(str(e))
        return None
    if df.empty:
        print(f"{code} 无数据")
        return None
    p = save_backtrader_csv(df, output_path)
    print(f"已保存: {p}  行数: {len(df)}")
    return p


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="沪深300（或指定代码）A股日线 OHLCV，供 Backtrader 使用")
    p.add_argument(
        "--codes",
        default=None,
        help="仅下载指定代码，逗号分隔，如 600519,000858；不传则下载全部沪深300",
    )
    p.add_argument("--start", default="2023-01-01", help="起始日期（含）")
    p.add_argument("--end", default="2025-12-31", help="结束日期（含）")
    p.add_argument(
        "--output-dir",
        default=None,
        help="股票池 CSV 目录，默认 backtrader实战/data/csi300_daily",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="单标的模式下的输出文件路径（与 --codes 单代码联用）",
    )
    p.add_argument(
        "--adjust",
        default="qfq",
        choices=("qfq", "hfq", "none"),
        help="复权：qfq 前复权（默认）/ hfq 后复权 / none 不复权",
    )
    p.add_argument("--sleep", type=float, default=0.2, help="请求间隔（秒），降低封 IP 风险")
    p.add_argument("--max-stocks", type=int, default=None, help="仅调试：最多下多少只")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    adj = "" if args.adjust == "none" else args.adjust

    if args.codes:
        parts = [x.strip() for x in args.codes.split(",") if x.strip()]
        if len(parts) == 1 and args.output:
            download_single_symbol(
                parts[0],
                start_date=args.start,
                end_date=args.end,
                output_path=args.output,
                adjust=adj,
            )
        else:
            base = Path(args.output_dir) if args.output_dir else None
            if base is None:
                base = Path(__file__).resolve().parent.parent / "data" / "csi300_daily"
            base = Path(base)
            if not base.is_absolute():
                base = (Path(__file__).resolve().parent.parent / base).resolve()
            base.mkdir(parents=True, exist_ok=True)
            for c in parts:
                p = base / f"{str(c).strip().zfill(6)}.csv"
                download_single_symbol(c, start_date=args.start, end_date=args.end, output_path=p, adjust=adj)
                time.sleep(args.sleep)
    else:
        download_csi300_pool(
            start_date=args.start,
            end_date=args.end,
            output_dir=args.output_dir,
            adjust=adj,
            sleep_s=args.sleep,
            max_stocks=args.max_stocks,
        )
