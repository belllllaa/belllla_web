# -*- coding: utf-8 -*-
"""
QMT ContextInfo 封装模块

封装 get_market_data_ex 常用调用、is_last_bar/is_new_bar 判断及统一日志输出。
"""


def get_market_df(ContextInfo, stock_list, fields=None, period="1d", count=-1,
                  start_time="", end_time="", dividend_type="follow", fill_data=True):
    """
    获取行情数据并返回 DataFrame 格式

    :param ContextInfo: QMT 上下文
    :param stock_list: 股票代码列表
    :param fields: 字段列表，空则取全部常用字段
    :param period: K线周期
    :param count: 数据条数，-1 表示不限制
    :param start_time: 起始时间
    :param end_time: 结束时间
    :param dividend_type: 除权方式
    :param fill_data: 是否填充缺失数据
    :return: dict { stock_code: DataFrame } 或单标的时返回单个 DataFrame
    """
    if fields is None:
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
        return {} if len(stock_list) > 1 else None

    # 转换为 DataFrame（若为 dict 结构则保持）
    try:
        import pandas as pd
        result = {}
        for code, val in data.items():
            if hasattr(val, "to_frame"):
                result[code] = val
            elif isinstance(val, dict):
                result[code] = pd.DataFrame(val)
            else:
                result[code] = val
        if len(stock_list) == 1 and stock_list[0] in result:
            return result[stock_list[0]]
        return result
    except ImportError:
        return data


def is_last_bar(ContextInfo):
    """是否为最后一根 K 线"""
    return ContextInfo.is_last_bar()


def is_new_bar(ContextInfo):
    """是否为新的 K 线"""
    return ContextInfo.is_new_bar()


def log(ContextInfo, msg, level="info"):
    """
    统一日志输出

    :param ContextInfo: QMT 上下文（可用于获取 barpos 等）
    :param msg: 日志内容
    :param level: info / warn / error
    """
    barpos = getattr(ContextInfo, "barpos", -1)
    prefix = f"[{level.upper()}] bar={barpos} "
    print(prefix + str(msg))
