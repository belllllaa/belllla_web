#coding:gbk
"""
策略一：沪深300ETF 双均线趋势（5/20）+ 止损
目标：10万本金，年化>25%，胜率≥50%，回撤<年化1/3（约8%）
逻辑：MA5上穿MA20买入，MA5下穿MA20或单笔亏损>5%卖出；仅做一只标的，简单清晰。
标的：510300.SH（华泰柏瑞沪深300ETF）
"""

import numpy as np

def init(C):
    C.accountid = getattr(C, 'accountid', '')
    # 单标的：沪深300ETF
    C.symbol = '510300.SH'
    C.capital = 100000
    C.ma_fast = 5
    C.ma_slow = 20
    C.stop_loss_pct = -0.05   # 单笔亏损5%止损
    C.holding = False
    C.buy_price = 0.0
    C.buy_shares = 0
    C.buy_date = ''
    print('策略一：沪深300ETF双均线(5/20)+止损 初始化完成，本金10万')


def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    symbol = getattr(C, 'symbol', '510300.SH')

    try:
        data = C.get_market_data_ex(['close', 'open', 'high', 'low'], [symbol], end_time=bar_date_str, period=C.period, count=25, subscribe=False)
    except Exception:
        data = C.get_market_data_ex(['close', 'open', 'high', 'low'], [symbol], end_time=bar_date_str, period='1d', count=25, subscribe=False)

    if symbol not in data or len(data[symbol]) < C.ma_slow + 1:
        return

    closes = list(data[symbol]['close'])
    opens = list(data[symbol]['open'])
    current_price = float(closes[-1])
    prev_close = float(closes[-2])
    today_open = float(opens[-1])
    if today_open <= 0:
        return

    ma5_now = np.mean(closes[-C.ma_fast:])
    ma5_prev = np.mean(closes[-C.ma_fast-1:-1])
    ma20_now = np.mean(closes[-C.ma_slow:])
    ma20_prev = np.mean(closes[-C.ma_slow-1:-1])

    # ---------- 卖出 ----------
    if C.holding and C.buy_shares >= 100:
        buy_price = getattr(C, 'buy_price', current_price)
        loss_pct = (current_price - buy_price) / buy_price
        # 止损
        if loss_pct <= C.stop_loss_pct:
            passorder(24, 1101, C.accountid, symbol, 5, 0, C.buy_shares, "ETF双均线", 1, "", C)
            print(f"{bar_date_str} 卖出 {symbol} {C.buy_shares}股 @ {current_price:.3f} 止损{loss_pct:.1%}")
            C.holding = False
            C.buy_price = 0.0
            C.buy_shares = 0
            C.buy_date = ''
            return
        # 死叉：MA5 下穿 MA20
        if ma5_prev >= ma20_prev and ma5_now < ma20_now:
            passorder(24, 1101, C.accountid, symbol, 5, 0, C.buy_shares, "ETF双均线", 1, "", C)
            print(f"{bar_date_str} 卖出 {symbol} {C.buy_shares}股 @ {current_price:.3f} 死叉")
            C.holding = False
            C.buy_price = 0.0
            C.buy_shares = 0
            C.buy_date = ''
            return

    # ---------- 买入：金叉 MA5 上穿 MA20，且当前空仓 ----------
    if not C.holding and ma5_prev <= ma20_prev and ma5_now > ma20_now:
        capital = getattr(C, 'capital', 100000)
        shares = int(capital / current_price) // 100 * 100
        if shares >= 100:
            passorder(23, 1101, C.accountid, symbol, 5, 0, shares, "ETF双均线", 1, "", C)
            C.holding = True
            C.buy_price = current_price
            C.buy_shares = shares
            C.buy_date = current_date_str
            print(f"{bar_date_str} 买入 {symbol} {shares}股 @ {current_price:.3f} 金叉")

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    import time
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)
