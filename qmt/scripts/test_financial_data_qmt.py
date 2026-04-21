# -*- coding: utf-8 -*-
"""
检查 QMT / xtquant 的 get_financial_data 是否能拉到数据（与防御选股同一字段列表）。

运行方式（推荐在迅投 QMT 安装目录自带的 python.exe 下执行）：
  python qmt/scripts/test_financial_data_qmt.py

可选参数：
  python test_financial_data_qmt.py 20250410 000001.SZ 600519.SH

说明：
- 需已安装 xtquant（随 QMT 客户端）；普通系统 Python 往往没有该模块。
- 财务数据需在 QMT「数据管理」中已下载。
- 本脚本不加载整份策略文件，仅使用与 strategy_sideways_breakout_sz_ma240 相同的字段常量。
"""

from __future__ import print_function

import os
import sys

# 与 qmt/回测策略/strategy_sideways_breakout_sz_ma240.py 中 FINANCIAL_FIELDS 保持一致
FINANCIAL_FIELDS = (
    "PERSHAREINDEX.equity_roe",
    "PERSHAREINDEX.net_roe",
    "PERSHAREINDEX.gear_ratio",
    "PERSHAREINDEX.sales_gross_profit",
    "PERSHAREINDEX.gross_profit",
    "ASHARECASHFLOW.cash_pay_dist_dpcp_int_exp",
    "CAPITALSTRUCTURE.total_capital",
)


def _describe_raw(raw):
    t = type(raw).__name__
    print("  [raw] 类型:", t)
    if raw is None:
        return
    if isinstance(raw, dict):
        print("  [raw] dict 键数量:", len(raw))
        for i, k in enumerate(raw.keys()):
            if i >= 10:
                print("  ... 其余键省略")
                break
            v = raw[k]
            print("    键 %r -> 值类型 %s" % (k, type(v).__name__))
            if hasattr(v, "shape"):
                print("      shape:", getattr(v, "shape", None))
            if hasattr(v, "__len__") and not isinstance(v, (str, bytes)):
                try:
                    print("      len:", len(v))
                except Exception:
                    pass
        return
    if hasattr(raw, "shape"):
        print("  [raw] shape:", raw.shape)
    if hasattr(raw, "columns"):
        cols = list(raw.columns)[:15]
        print("  [raw] columns(前15):", cols)
    if hasattr(raw, "__len__"):
        try:
            print("  [raw] len:", len(raw))
        except Exception:
            pass


def main():
    argv = sys.argv[1:]
    end_time = "20250410"
    stocks = ["000001.SZ", "600519.SH", "601398.SH"]
    if argv:
        if argv[0].isdigit() and len(argv[0]) >= 8:
            end_time = argv[0][:8]
            argv = argv[1:]
        if argv:
            stocks = argv

    print("=" * 60)
    print("财务拉取测试  end_time=%s  stocks=%s" % (end_time, stocks))
    print("=" * 60)
    print("字段数:", len(FINANCIAL_FIELDS))

    try:
        from xtquant import xtdata
    except ImportError as e:
        print("[错误] 无法 import xtquant:", e)
        print("请使用迅投 QMT 安装目录下的 python.exe 运行本脚本。")
        return 1

    get_fd = getattr(xtdata, "get_financial_data", None)
    if not callable(get_fd):
        print("[错误] xtdata 无 get_financial_data")
        return 1

    y = int(end_time[:4])
    start_time = "%d0101" % (y - 5)
    print("时间范围: start_time=%s end_time=%s  report_type=announce_time" % (start_time, end_time))

    dl = getattr(xtdata, "download_financial_data", None) or getattr(xtdata, "download_financial_data2", None)
    if callable(dl):
        try:
            dl(stocks)
            print("已尝试 download_financial_data(股票列表)")
        except Exception as ex:
            print("(提示) 预下载调用异常（可忽略）:", ex)

    try:
        raw = get_fd(
            list(FINANCIAL_FIELDS),
            list(stocks),
            "announce_time",
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        print("[错误] get_financial_data 调用失败:", e)
        return 1

    print("\n--- 原始返回 ---")
    _describe_raw(raw)

    print("\n--- 判断 ---")
    if raw is None:
        print("  返回为 None：未拉到数据或接口无返回。")
    elif isinstance(raw, dict) and len(raw) == 0:
        print("  空 dict：字段或股票无数据，或日期范围内无披露。")
    else:
        print("  有返回对象，请结合上方类型/shape/键名核对是否与策略解析逻辑一致。")

    print("\n完成。若要在本机验证「策略内 _parse_financial_to_metrics」：在 QMT 回测/研究里")
    print("  对同一 raw 调用策略中的解析函数即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
