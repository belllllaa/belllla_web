# -*- coding: utf-8 -*-
"""
单独补全历史脚本：从指定起始日到截止日，按股、按日补全「每日资金流入汇总」中的主力/散户/涨跌幅（万元、%）。

- 用途：首次建表后补全历史；或每日表被误删/历史列丢失时，先由 run_once 生成带当日列的宽表，再运行本脚本补全历史区间。
- 与当日脚本解耦：不依赖历次 run_once 记录，只依赖当前 daily_fund_flow_wide.xlsx 的表结构（可由 run_once 生成）。
- 数据源：akshare 按股拉取（近约 100 个交易日）；运行较慢（每股约 0.2s）。--start/--end 需与 akshare 能返回的日期重叠。
- 宽表列名仅含月/日（如 1/2、3/10），不含年份，故 --start/--end 应限定在同一年（如 2026），否则多年度会共用同一列导致混年。

用法: py -m qmt.fund_flow.fill_daily_history --path output/daily_fund_flow_wide.xlsx [--start 2026-01-01] [--end 今日]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(_root))

from qmt.fund_flow.calendar_utils import get_trading_days
from qmt.fund_flow.excel_io import _date_to_col_prefix, write_daily_wide_workbook


def _market(code: str) -> str:
    return "sh" if str(code).startswith("6") or str(code).startswith("5") else "sz"


def fill_daily_history(
    excel_path: str | Path,
    end_date: str,
    start_date: str = "2026-01-01",
    limit: int | None = None,
    debug: bool = False,
) -> None:
    import pandas as pd
    try:
        import akshare as ak
    except ImportError:
        print("请安装 akshare: pip install akshare")
        return
    path = Path(excel_path)
    if not path.is_absolute():
        base = Path(__file__).resolve().parent  # qmt/fund_flow
        root = base.parent.parent               # 项目根
        candidates = [
            base / path,
            root / path,
            root / "qmt" / "fund_flow" / path,
        ]
        if path.name == "daily_fund_flow_wide.xlsx":
            candidates.append(root / "qmt" / "fund_flow" / "output" / path.name)
        for cand in candidates:
            if cand.exists():
                path = cand
                break
        else:
            path = base / path
    if not path.exists():
        print(f"文件不存在: {path}")
        print("请先运行: py -m qmt.fund_flow.run_once  生成 output/daily_fund_flow_wide.xlsx")
        return
    print(f"目标文件: {path.resolve()}")
    daily = pd.read_excel(path, sheet_name="每日资金流入汇总")
    if daily.empty or "股票" not in daily.columns:
        print("每日 sheet 无「股票」列")
        return
    # 读回时股票可能被 Excel 存成数字（如 1 而非 000001），统一为 6 位字符串
    daily["股票"] = daily["股票"].astype(str).str.replace(r"\.0$", "", regex=True)
    daily["股票"] = daily["股票"].str.zfill(6)
    trading_days = get_trading_days(start_date, end_date)
    if not trading_days:
        print(f"日期区间 {start_date} ～ {end_date} 内无交易日，请检查 --start/--end（需 start ≤ end 且为交易日）。")
        return

    def _resolve_date_col(prefix: str, suffix: str) -> str | None:
        """解析列名：Excel 可能把 1/2 存成 0.5，需用实际列名写入。"""
        want = f"{prefix}{suffix}"
        if want in daily.columns:
            return want
        for c in daily.columns:
            if not str(c).endswith(suffix):
                continue
            head = str(c)[: -len(suffix)]
            if head == prefix:
                return c
            try:
                if abs(float(head) - (int(prefix.split("/")[0]) / int(prefix.split("/")[1]))) < 1e-9:
                    return c
            except (ValueError, ZeroDivisionError):
                pass
        return None

    # 若宽表是逐日 append 生成的，可能缺少部分日期列，先补全列再填数（一次性合并避免碎片化）
    extra = {}
    for d in trading_days:
        prefix = _date_to_col_prefix(d)
        for suffix, default in [("主力", None), ("散户", None), ("涨跌幅", None)]:
            col = f"{prefix}{suffix}"
            if col not in daily.columns and _resolve_date_col(prefix, suffix) is None:
                extra[col] = default
    if extra:
        daily = pd.concat([daily, pd.DataFrame(extra, index=daily.index)], axis=1)
    # 涨跌幅列需存字符串（如 "1.23%"），统一转为 object 避免写入时报 dtype 错误
    for c in daily.columns:
        if "涨跌幅" in str(c):
            daily[c] = daily[c].astype(object)
    stocks = daily["股票"].astype(str).str.zfill(6).tolist()
    if limit is not None and limit > 0:
        stocks = stocks[: int(limit)]
        print(f"仅处理前 {len(stocks)} 只股票（--limit {limit}）")
    n_stocks = len(stocks)
    print(f"补全区间: {start_date} ～ {end_date}，共 {len(trading_days)} 个交易日", flush=True)
    print(f"开始补全，共 {n_stocks} 只股票，每 10 只打印一次进度…", flush=True)
    filled = 0
    last_skip_code = None
    first_stock_date_range_printed = False
    skip_no_col, skip_row_empty, skip_nan, skip_no_idx = 0, 0, 0, 0
    t0 = time.perf_counter()
    for i, code in enumerate(stocks):
        if (i + 1) % 10 == 0 or i == 0:
            elapsed = time.perf_counter() - t0
            print(f"进度 {i+1}/{n_stocks} （已用时 {elapsed:.0f}s）…", flush=True)
        try:
            df = ak.stock_individual_fund_flow(stock=code, market=_market(code))
            if df is None or df.empty:
                if debug and i == 0:
                    print(f"  [debug] 首只股票 {code} akshare 返回空或 None", flush=True)
                time.sleep(0.15)
                continue
            # 列名可能是 日期、主力净流入-净额、小单净流入-净额 等（兼容带「元」等后缀）
            date_col = "日期" if "日期" in df.columns else (df.columns[0] if len(df.columns) else None)
            if date_col is None:
                if debug and i == 0:
                    print(f"  [debug] 首只股票 {code} 无列: columns={list(df.columns)}", flush=True)
                time.sleep(0.15)
                continue
            main_col = None
            retail_col = None
            change_col = None
            for c in df.columns:
                cstr = str(c)
                if "主力" in cstr and "净" in cstr and "占比" not in cstr:
                    main_col = c
                if "小单" in cstr and "净" in cstr and "占比" not in cstr:
                    retail_col = c
                if change_col is None and ("涨跌幅" in cstr or cstr.strip() == "涨跌幅"):
                    change_col = c
            if main_col is None or retail_col is None:
                if debug and i == 0:
                    print(f"  [debug] 首只股票 {code} 未识别主力/散户列: 全部列={list(df.columns)}", flush=True)
                time.sleep(0.15)
                continue
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
            # 统一为字符串便于比较（避免 Excel 读回为 datetime 等）
            df[date_col] = df[date_col].astype(str).str.strip()
            df[date_col] = df[date_col].replace("nan", pd.NA).replace("NaT", pd.NA)
            if not first_stock_date_range_printed:
                dates_in_df = df[date_col].dropna().tolist()
                if dates_in_df:
                    print(f"  [诊断] akshare 首只股票日期范围: {min(dates_in_df)} ～ {max(dates_in_df)}，请求区间 {start_date} ～ {end_date}", flush=True)
                    overlap = set(trading_days) & set(dates_in_df)
                    print(f"  [诊断] 与请求区间交集的交易日数: {len(overlap)}（共请求 {len(trading_days)} 天）", flush=True)
                    if len(overlap) == 0:
                        print("  [诊断] 交集为 0 会导致写入为 0，请用 --start/--end 与 akshare 返回的日期范围对齐（如 --end 今天）。", flush=True)
                    if debug:
                        date_col_in_daily = sum(1 for d in trading_days if f"{_date_to_col_prefix(d)}主力" in daily.columns)
                        print(f"  [debug] 宽表中已有日期列数（与请求区间一致）: {date_col_in_daily}", flush=True)
                        print(f"  [debug] 主力列={main_col!r} 散户列={retail_col!r} 日期列={date_col!r}", flush=True)
                        if overlap:
                            print(f"  [debug] 交集示例日期: {sorted(overlap)[:5]}", flush=True)
                    first_stock_date_range_printed = True
            for d in trading_days:
                prefix = _date_to_col_prefix(d)
                col_main = _resolve_date_col(prefix, "主力")
                col_retail = _resolve_date_col(prefix, "散户")
                col_change = _resolve_date_col(prefix, "涨跌幅")
                if col_main is None or col_retail is None:
                    skip_no_col += 1
                    continue
                d_str = str(d).strip()
                row = df[df[date_col].astype(str).str.strip() == d_str]
                if row.empty:
                    skip_row_empty += 1
                    continue
                # 每日 sheet 单位：万元；akshare 可能返回空或非数字，安全转换
                raw_main = pd.to_numeric(row[main_col].iloc[0], errors="coerce")
                raw_retail = pd.to_numeric(row[retail_col].iloc[0], errors="coerce")
                if pd.isna(raw_main) or pd.isna(raw_retail):
                    skip_nan += 1
                    continue
                # akshare 净额多为“元”；若数值已很小(<1e7)可能是万元，不再除
                if float(raw_main) >= 1e7 or float(raw_retail) >= 1e7:
                    main_val = round(float(raw_main) / 1e4, 2)
                    retail_val = round(float(raw_retail) / 1e4, 2)
                else:
                    main_val = round(float(raw_main), 2)
                    retail_val = round(float(raw_retail), 2)
                idx = daily.index[daily["股票"].astype(str).str.zfill(6) == code].tolist()
                if not idx:
                    skip_no_idx += 1
                    continue
                daily.loc[idx[0], col_main] = main_val
                daily.loc[idx[0], col_retail] = retail_val
                if change_col and col_change and col_change in daily.columns and change_col in row.columns:
                    try:
                        pct = row[change_col].iloc[0]
                        pct = float(pct) if pd.notna(pct) else None
                        daily.loc[idx[0], col_change] = f"{pct:.2f}%" if pct is not None else None
                    except (TypeError, ValueError):
                        daily.loc[idx[0], col_change] = None
                filled += 1
        except KeyboardInterrupt:
            print("\n已中断（Ctrl+C），当前进度未保存，请重新运行以完成全量补全。", flush=True)
            raise
        except Exception as e:
            last_skip_code = code
            if debug and i < 3:
                print(f"  [debug] 股票 {code} 异常: {e}", flush=True)
            # 单只请求失败或数据异常时跳过，继续下一只
            if (i + 1) % 500 == 0:
                tip = f"  已跳过部分个股（如 {type(e).__name__}）"
                if last_skip_code:
                    tip += f"，其中包含 {last_skip_code}"
                print(f"{tip}，继续…", flush=True)
        time.sleep(0.18)
    # 仅当该文件内有「汇总」sheet 时，才读汇总并更新前3/5/10/20/40/60日主力之和(亿)后写回；否则只写回每日 sheet
    ROLLING_DAYS = (3, 5, 10, 20, 40, 60)
    has_summary = "汇总" in pd.ExcelFile(path).sheet_names
    if has_summary:
        summary = pd.read_excel(path, sheet_name="汇总")
        has_rolling = any(
            "日主力净流入之和" in str(c) for c in summary.columns
        )
        if has_rolling:
            days_before = trading_days[:-1]
            code_to_sum = daily["股票"].astype(str).str.zfill(6)
            summary_codes = summary["股票代码"].astype(str).str.zfill(6)
            all_cols = []
            for n in ROLLING_DAYS:
                if len(days_before) >= n:
                    all_cols.extend([f"{_date_to_col_prefix(d)}主力" for d in days_before[-n:]])
            for col in set(all_cols):
                if col not in daily.columns:
                    daily[col] = None
            for n in ROLLING_DAYS:
                col_name = f"前{n}日主力净流入之和(亿)"
                if len(days_before) < n:
                    if col_name in summary.columns:
                        summary[col_name] = None
                    continue
                prev_n = [f"{_date_to_col_prefix(d)}主力" for d in days_before[-n:]]
                sum_wan = daily[prev_n].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
                sum_yi = (sum_wan / 1e4).round(4)  # 万元→亿元
                summary[col_name] = summary_codes.map(dict(zip(code_to_sum, sum_yi)))
            drop_wan = [c for c in summary.columns if isinstance(c, str) and "前" in c and "日主力" in c and c.endswith("(万)")]
            if drop_wan:
                summary = summary.drop(columns=drop_wan)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="汇总", index=False)
            daily.to_excel(writer, sheet_name="每日资金流入汇总", index=False)
    else:
        write_daily_wide_workbook(daily_wide_df=daily, output_path=path)
    print("")
    print("=" * 50)
    print("【全量历史补全已完成】")
    print(f"  共处理 {n_stocks} 只股票，写入 {filled} 个单元格，已保存至: {path.resolve()}")
    print("  每日 sheet 已补全历史主力/散户/涨跌幅（单位：万元、%）。")
    if has_summary:
        print("  汇总表前3/5/10/20/40/60日主力之和(亿)已更新。")
    if filled == 0 or debug:
        print(f"  [统计] 跳过: 缺列={skip_no_col} 无匹配行={skip_row_empty} 空值={skip_nan} 无股票行={skip_no_idx}", flush=True)
    if filled == 0:
        print("  提示：若写入为 0，请确认 --start/--end 与 akshare 返回的日期有交集（akshare 通常返回近约 100 个交易日）。可尝试 --end 设为今天。")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="output/daily_fund_flow_wide.xlsx", help="每日宽表 Excel 路径（默认 output/daily_fund_flow_wide.xlsx）")
    parser.add_argument("--end", default=None, help="截止日期（默认今天）")
    parser.add_argument("--start", default="2026-01-01", help="起始日期，建议与 run_once 宽表同年（如 2026），避免多年度共用 M/D 列")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 只股票，用于测试")
    parser.add_argument("--debug", action="store_true", help="打印首只股票的接口返回详情，便于排查写入为 0 的问题")
    args = parser.parse_args()
    end_date = args.end or date.today().strftime("%Y-%m-%d")
    fill_daily_history(args.path, end_date, args.start, limit=args.limit, debug=args.debug)
