# -*- coding: utf-8 -*-
"""
QMT 行情数据获取封装

封装 get_market_data_ex，返回 DataFrame 格式，处理停牌、缺失数据等。
"""


def get_ohlcv_df(ContextInfo, stock_code, period="1d", count=-1,
                 start_time="", end_time="", dividend_type="front", fill_data=True):
    """
    获取 OHLCV 行情数据，返回 DataFrame

    :param ContextInfo: QMT 上下文
    :param stock_code: 股票代码或代码列表
    :param period: K线周期
    :param count: 数据条数
    :param start_time: 起始时间
    :param end_time: 结束时间
    :param dividend_type: 除权方式
    :param fill_data: 是否填充缺失数据
    :return: 单标的返回 DataFrame，多标的返回 dict { code: DataFrame }
    """
    if isinstance(stock_code, str):
        stock_list = [stock_code]
    else:
        stock_list = list(stock_code)

    fields = ["open", "high", "low", "close", "volume"]
    kwargs = {
        "fields": fields,
        "stock_code": stock_list,
        "period": period,
        "dividend_type": dividend_type,
        "fill_data": fill_data,
        "subscribe": True,
    }
    if count > 0:
        kwargs["count"] = count
    if start_time:
        kwargs["start_time"] = start_time
    if end_time:
        kwargs["end_time"] = end_time

    data = ContextInfo.get_market_data_ex(**kwargs)
    if not data:
        return None if len(stock_list) == 1 else {}

    try:
        import pandas as pd
        result = {}
        for code, val in data.items():
            if isinstance(val, dict):
                result[code] = pd.DataFrame(val)
            elif hasattr(val, "close") and hasattr(val, "open"):
                result[code] = pd.DataFrame({
                    "open": val.open, "high": val.high, "low": val.low,
                    "close": val.close, "volume": getattr(val, "volume", [])
                })
            elif hasattr(val, "to_frame"):
                result[code] = val.to_frame() if callable(val.to_frame) else val
            else:
                result[code] = val
        if len(stock_list) == 1 and stock_list[0] in result:
            return result[stock_list[0]]
        return result
    except ImportError:
        return data


def get_close_array(ContextInfo, stock_code, period="1d", count=-1,
                    start_time="", end_time="", dividend_type="front"):
    """
    获取收盘价数组，便于指标计算

    :return: numpy 数组
    """
    df = get_ohlcv_df(
        ContextInfo,
        stock_code,
        period=period,
        count=count,
        start_time=start_time,
        end_time=end_time,
        dividend_type=dividend_type,
    )
    if df is None:
        return None
    if hasattr(df, "columns") and "close" in df.columns:
        return df["close"].values
    if hasattr(df, "values"):
        return df.values.flatten()
    return None
