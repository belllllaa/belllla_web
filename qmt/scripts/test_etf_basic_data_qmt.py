# -*- coding: utf-8 -*-
"""
命令行探测 QMT / xtquant 读取 ETF 行情与基础数据是否正常。

运行（必须用迅投 QMT 安装目录自带的 python.exe，以确保能 import xtquant）：
  python qmt/scripts/test_etf_basic_data_qmt.py

可选参数（日期为 YYYYMMDD）：
  python qmt/scripts/test_etf_basic_data_qmt.py 20250401 20250428 510300.SH 159919.SZ

说明：
- 依赖行情服务：请先登录客户端并等待行情连接就绪。
- 若无历史数据，可在 QMT「数据管理」中补充下载；本脚本也会尝试 xtdata.download_history_data。
"""

from __future__ import annotations

import os
import sys
import traceback

# 允许从任意工作目录运行：python qmt/scripts/test_etf_basic_data_qmt.py
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# 默认：沪深主流宽基 ETF 各一只（可按需改成你关心的标的）
DEFAULT_ETFS = ("510300.SH", "159919.SZ")


def _p(title: str, detail: str = "") -> None:
    if detail:
        print("[ETF测试] %s %s" % (title, detail))
    else:
        print("[ETF测试] %s" % title)


def _summarize_df(name: str, df, rows: int = 5) -> None:
    try:
        import pandas as pd
    except ImportError:
        _p(name, "无 pandas，跳过摘要")
        return
    if df is None:
        _p(name, "-> None")
        return
    if hasattr(df, "empty") and df.empty:
        _p(name, "DataFrame 为空")
        return
    _p(name, "行数=%d 列=%s" % (len(df), list(df.columns)[:12]))
    try:
        tail = df.tail(rows)
        _p(name + " 尾部", "\n%s" % tail.to_string())
    except Exception as e:
        _p(name, "摘要失败: %s" % e)


def _summarize_tick(name: str, tick) -> None:
    if tick is None:
        _p(name, "-> None")
        return
    if isinstance(tick, dict):
        keys = list(tick.keys())
        _p(name, "dict 键数=%d 示例键=%s" % (len(keys), keys[:20]))
        for k in ("lastPrice", "last_price", "price", "bidPrice", "askPrice"):
            if k in tick:
                _p(name + " [%s]" % k, repr(tick[k]))
                break
        return
    _p(name, "类型=%s repr(前200)=%s" % (type(tick).__name__, repr(tick)[:200]))


def _summarize_instrument(name: str, info) -> None:
    if info is None:
        _p(name, "-> None")
        return
    if isinstance(info, dict):
        # 优先展示与定价/股本相关的常见键
        prefer = (
            "InstrumentName",
            "InstrumentID",
            "ExchangeID",
            "FloatVolume",
            "TotalVolume",
            "PriceTick",
            "contract_multiplier",
            "ExpireDate",
            "ProductName",
            "InstrumentType",
        )
        hit = {k: info[k] for k in prefer if k in info}
        if hit:
            _p(name, "节选: %s" % hit)
        else:
            kn = list(info.keys())[:25]
            _p(name, "键(前25): %s" % kn)
        return
    _p(name, "类型=%s" % type(info).__name__)


def _try_get_market_data_ex(xtdata, codes, period: str, start_time: str, end_time: str):
    get_ex = getattr(xtdata, "get_market_data_ex", None)
    if not callable(get_ex):
        _p("get_market_data_ex", "不存在")
        return
    field_list = ["open", "high", "low", "close", "volume"]
    kwargs = dict(
        field_list=field_list,
        stock_list=list(codes),
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=-1,
        dividend_type="front",
        fill_data=True,
    )
    try:
        raw = get_ex(**kwargs)
    except TypeError:
        kwargs.pop("count", None)
        try:
            raw = get_ex(**kwargs)
        except Exception as e:
            _p("get_market_data_ex(%s)" % period, "失败: %s" % e)
            return
    except Exception as e:
        _p("get_market_data_ex(%s)" % period, "失败: %s" % e)
        return

    if not raw:
        _p("get_market_data_ex(%s)" % period, "返回空")
        return

    try:
        import pandas as pd
    except ImportError:
        _p("get_market_data_ex(%s)" % period, "有返回但无 pandas，raw 键: %s" % list(raw.keys()))
        return

    for code in codes:
        node = raw.get(code)
        df = node if isinstance(node, pd.DataFrame) else None
        if df is None and isinstance(node, dict):
            df = pd.DataFrame(node)
        _summarize_df("K线 %s %s" % (period, code), df)


def _try_download_history(xtdata, codes, end_time: str):
    dl = getattr(xtdata, "download_history_data", None)
    if not callable(dl):
        _p("download_history_data", "不存在，跳过预下载")
        return
    y = int(end_time[:4])
    start = "%d0101" % (y - 1)
    for code in codes:
        for period in ("1d", "1m"):
            try:
                dl(code, period, start, end_time)
                _p("download_history_data", "已请求 %s %s %s~%s" % (code, period, start, end_time))
            except Exception as e:
                _p("download_history_data", "%s %s: %s" % (code, period, e))


def _try_full_tick(xtdata, codes):
    fn = getattr(xtdata, "get_full_tick", None)
    if not callable(fn):
        _p("get_full_tick", "xtdata 上不存在（部分版本仅在 ContextInfo 提供）")
        return
    try:
        raw = fn(list(codes))
    except Exception as e:
        _p("get_full_tick", "异常: %s" % e)
        return
    if not raw:
        _p("get_full_tick", "空返回（检查行情连接 / 是否交易时段）")
        return
    if isinstance(raw, dict):
        for code in codes:
            _summarize_tick("tick %s" % code, raw.get(code))
    else:
        _summarize_tick("tick 整体", raw)


def _call_instrument(fn, code):
    """不同版本签名：列表 / 单码 / iscomplete。"""
    last_err = None
    for attempt in (
        lambda: fn([code]),
        lambda: fn([code], iscomplete=True),
        lambda: fn(code),
    ):
        try:
            return attempt()
        except TypeError as e:
            last_err = e
            continue
        except Exception as e:
            raise e
    if last_err:
        raise last_err
    return None


def _try_instrument_detail(xtdata, codes):
    candidates = (
        "get_instrument_detail",
        "get_instrumentdetail",
        "GetInstrumentDetail",
    )
    for name in candidates:
        fn = getattr(xtdata, name, None)
        if not callable(fn):
            continue
        for code in codes:
            try:
                info = _call_instrument(fn, code)
            except Exception as e:
                _p(name, "%s: %s" % (code, e))
                continue
            _summarize_instrument("%s(%s)" % (name, code), info)
        return
    _p("合约详情", "xtdata 上未发现 get_instrument_detail 类接口")


def main() -> int:
    argv = sys.argv[1:]
    end_time = "20250428"
    start_time = "20250401"
    codes = list(DEFAULT_ETFS)

    if argv:
        i = 0
        if len(argv[0]) == 8 and argv[0].isdigit():
            start_time = argv[0]
            i += 1
        if i < len(argv) and len(argv[i]) == 8 and argv[i].isdigit():
            end_time = argv[i]
            i += 1
        rest = [x for x in argv[i:] if "." in x]
        if rest:
            codes = rest

    _p("========== 参数 ==========")
    _p("标的", repr(codes))
    _p("日线区间", "%s ~ %s" % (start_time, end_time))

    try:
        from xtquant import xtdata
    except ImportError as e:
        _p("错误", "无法 import xtquant: %s" % e)
        _p("提示", "请使用迅投 QMT 安装目录下的 python.exe 运行本脚本。")
        return 1

    _p("========== 预下载（可选）==========")
    _try_download_history(xtdata, codes, end_time)

    _p("========== 日线 K 线（复用 daily_bars.get_daily_ohlcv_xtdata）==========")
    try:
        from qmt.ml_research.daily_bars import get_daily_ohlcv_xtdata

        for code in codes:
            df = get_daily_ohlcv_xtdata(code, start_time, end_time)
            _summarize_df("日线 %s" % code, df)
    except Exception as e:
        _p("daily_bars", "失败: %s\n%s" % (e, traceback.format_exc()))

    _p("========== 直接 get_market_data_ex ==========")
    _try_get_market_data_ex(xtdata, codes, "1d", start_time, end_time)
    _try_get_market_data_ex(xtdata, codes, "1m", start_time, end_time)

    _p("========== 全推 tick ==========")
    _try_full_tick(xtdata, codes)

    _p("========== 合约详情 ==========")
    _try_instrument_detail(xtdata, codes)

    _p("========== 完成 ==========")
    _p(
        "若某段为空或异常",
        "请先确认客户端已登录；数据管理中有对应周期历史；实盘全推 tick 需在交易时段与 Lv1 权限。",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
