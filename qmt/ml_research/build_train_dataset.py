# -*- coding: utf-8 -*-
"""
从「推荐池 CSV」构建训练集并可选训练一个简单分类器。

约定：
  - CSV 含推荐日与股票代码（列名见 watchlist_csv.py）
  - 默认：推荐日之后第一个交易日开盘价买入；之后按日线先触及止盈/止损出场
  - 特征：仅使用推荐日及以前日线（收盘价视角），不含入场日开盘

运行（在仓库根目录 belllla_web，且使用 QMT 自带 Python 以加载 xtquant）：

  python -m qmt.ml_research.build_train_dataset --csv path/to/pool.csv --tp 0.08 --sl 0.04 --max-hold 60

输出：
  - 同目录生成 pool_ml_dataset.csv（或 --out 指定）
  - 若已安装 scikit-learn，打印简单时间切分验证指标
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from qmt.ml_research.daily_bars import get_daily_ohlcv_xtdata
from qmt.ml_research.entry_label import (
    normalize_daily_index,
    recommend_feature_end_entry_indices,
    simulate_long_tp_sl,
)
from qmt.ml_research.features import build_tabular_features
from qmt.ml_research.watchlist_csv import load_watchlist_csv


def _to_yyyymmdd(ts):
    t = pd.Timestamp(ts)
    return t.strftime("%Y%m%d")


def build_rows(wl: pd.DataFrame, tp_pct: float, sl_pct: float, max_hold_days: int):
    rows = []
    skipped = []
    for i, r in wl.iterrows():
        code = r["stock_code"]
        rec = r["recommend_date"]
        start = _to_yyyymmdd(rec - pd.Timedelta(days=500))
        end = _to_yyyymmdd(rec + pd.Timedelta(days=800))
        try:
            raw = get_daily_ohlcv_xtdata(code, start, end)
        except Exception as e:
            skipped.append((code, rec, "fetch:%s" % e))
            continue
        if raw is None or raw.empty:
            skipped.append((code, rec, "empty_bars"))
            continue
        df = normalize_daily_index(raw)
        if df is None or len(df) < 30:
            skipped.append((code, rec, "short_df"))
            continue
        dates = df.index.values
        fe, en = recommend_feature_end_entry_indices(dates, rec)
        if fe is None or en is None:
            skipped.append((code, rec, "no_entry"))
            continue
        sim = simulate_long_tp_sl(df, en, tp_pct, sl_pct, max_hold_days)
        if not sim:
            skipped.append((code, rec, "sim_fail"))
            continue
        feats = build_tabular_features(df, fe)
        if not feats:
            skipped.append((code, rec, "no_features"))
            continue
        out = {
            "stock_code": code,
            "recommend_date": rec,
            "entry_date": df.index[en],
            "outcome": sim["outcome"],
            "bars_held": sim["bars_held"],
        }
        out.update(feats)
        rows.append(out)
    ds = pd.DataFrame(rows)
    if skipped:
        print("[跳过 %d 条] 示例:" % len(skipped))
        for s in skipped[:8]:
            print(" ", s)
    return ds, skipped


def _train_simple(df: pd.DataFrame, drop_timeout: bool):
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.metrics import classification_report
        from sklearn.model_selection import train_test_split
    except ImportError:
        print("未安装 scikit-learn，跳过训练；可: pip install scikit-learn")
        return

    work = df.copy()
    if drop_timeout:
        work = work[work["outcome"] != "timeout"].copy()
    if len(work) < 30:
        print("有效样本不足 30，跳过训练")
        return

    work["y"] = (work["outcome"] == "tp_first").astype(int)
    feat_cols = [c for c in work.columns if c not in ("stock_code", "recommend_date", "entry_date", "outcome", "bars_held", "y")]
    X = work[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = work["y"].values

    order = work["recommend_date"].argsort()
    split = int(len(order) * 0.75)
    tr, te = order[:split], order[split:]
    if len(te) < 5:
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=42)
    else:
        X_tr, X_te = X.iloc[tr], X.iloc[te]
        y_tr, y_te = y[tr], y[te]

    clf = HistGradientBoostingClassifier(max_depth=4, max_iter=80, random_state=42)
    clf.fit(X_tr, y_tr)
    pred = clf.predict(X_te)
    print("\n=== 验证集 classification_report（正类=先触及止盈）===\n")
    print(classification_report(y_te, pred, digits=3))
    base = float(np.mean(y_te)) if len(y_te) else 0.0
    print("验证集 先止盈 基准占比: %.3f" % base)


def main():
    ap = argparse.ArgumentParser(description="CSV 推荐池 + xtquant 日线 -> 特征与标签")
    ap.add_argument("--csv", required=True, help="推荐池 CSV 路径")
    ap.add_argument("--tp", type=float, default=0.08, help="止盈比例，如 0.08=+8%%")
    ap.add_argument("--sl", type=float, default=0.04, help="止损比例，如 0.04=-4%%")
    ap.add_argument("--max-hold", type=int, default=60, help="最长持有交易日数")
    ap.add_argument("--out", default="", help="输出 CSV；默认与输入同目录 pool_ml_dataset.csv")
    ap.add_argument("--keep-timeout", action="store_true", help="保留未触及止盈止损的样本（outcome=timeout）")
    args = ap.parse_args()

    path = os.path.abspath(args.csv)
    wl = load_watchlist_csv(path)
    print("读取 %d 条推荐记录: %s" % (len(wl), path))

    ds, _ = build_rows(wl, args.tp, args.sl, args.max_hold)
    if ds.empty:
        print("无有效样本，结束")
        return 1

    out_path = args.out.strip()
    if not out_path:
        out_path = os.path.join(os.path.dirname(path), "pool_ml_dataset.csv")
    ds.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("已写入: %s  行数=%d" % (out_path, len(ds)))

    _train_simple(ds, drop_timeout=not args.keep_timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
