#coding:gbk
"""
策略三：银行股池 双均线(5/20) + 单笔止损5%
目标：10万本金，年化>25%，胜率≥50%，回撤<年化1/3
逻辑：3只大盘银行股各约1/3仓位，分别金叉买、死叉或亏损5%卖。参考：银行股双均线回测年化约57%、回撤约7%。
标的：招商银行、工商银行、农业银行（600036/601398/601288）
"""

import numpy as np

def init(C):
    C.accountid = getattr(C, 'accountid', '')
    C.symbols = ['600036.SH', '601398.SH', '601288.SH']
    C.capital_total = 100000
    C.per_capital = 100000 // 3
    C.ma_fast = 5
    C.ma_slow = 20
    C.stop_loss_pct = -0.05
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    for s in C.symbols:
        C.holding[s] = False
        C.buy_price[s] = 0.0
        C.buy_shares[s] = 0
        C.buy_date[s] = ''
    print('策略三：银行股双均线(5/20)+止损 初始化完成，10万/3只')


def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    symbols = getattr(C, 'symbols', ['600036.SH', '601398.SH', '601288.SH'])

    for symbol in symbols:
        try:
            data = C.get_market_data_ex(['close', 'open'], [symbol], end_time=bar_date_str, period=C.period, count=25, subscribe=False)
        except Exception:
            data = C.get_market_data_ex(['close', 'open'], [symbol], end_time=bar_date_str, period='1d', count=25, subscribe=False)

        if symbol not in data or len(data[symbol]) < getattr(C, 'ma_slow', 20) + 1:
            continue

        closes = list(data[symbol]['close'])
        opens = list(data[symbol]['open'])
        current_price = float(closes[-1])
        today_open = float(opens[-1])
        if today_open <= 0:
            continue

        ma_fast = getattr(C, 'ma_fast', 5)
        ma_slow = getattr(C, 'ma_slow', 20)
        ma5_now = np.mean(closes[-ma_fast:])
        ma5_prev = np.mean(closes[-ma_fast-1:-1])
        ma20_now = np.mean(closes[-ma_slow:])
        ma20_prev = np.mean(closes[-ma_slow-1:-1])

        if C.holding.get(symbol, False) and C.buy_shares.get(symbol, 0) >= 100:
            buy_price = C.buy_price.get(symbol, current_price)
            loss_pct = (current_price - buy_price) / buy_price
            if loss_pct <= getattr(C, 'stop_loss_pct', -0.05):
                passorder(24, 1101, C.accountid, symbol, 5, 0, C.buy_shares[symbol], "银行双均线", 1, "", C)
                print(f"{bar_date_str} 卖出 {symbol} {C.buy_shares[symbol]}股 @ {current_price:.3f} 止损{loss_pct:.1%}")
                C.holding[symbol] = False
                C.buy_price[symbol] = 0.0
                C.buy_shares[symbol] = 0
                C.buy_date[symbol] = ''
                continue
            if ma5_prev >= ma20_prev and ma5_now < ma20_now:
                passorder(24, 1101, C.accountid, symbol, 5, 0, C.buy_shares[symbol], "银行双均线", 1, "", C)
                print(f"{bar_date_str} 卖出 {symbol} {C.buy_shares[symbol]}股 @ {current_price:.3f} 死叉")
                C.holding[symbol] = False
                C.buy_price[symbol] = 0.0
                C.buy_shares[symbol] = 0
                C.buy_date[symbol] = ''
                continue

        if not C.holding.get(symbol, False) and ma5_prev <= ma20_prev and ma5_now > ma20_now:
            per_cap = getattr(C, 'per_capital', 33000)
            shares = int(per_cap / current_price) // 100 * 100
            if shares >= 100:
                passorder(23, 1101, C.accountid, symbol, 5, 0, shares, "银行双均线", 1, "", C)
                C.holding[symbol] = True
                C.buy_price[symbol] = current_price
                C.buy_shares[symbol] = shares
                C.buy_date[symbol] = current_date_str
                print(f"{bar_date_str} 买入 {symbol} {shares}股 @ {current_price:.3f} 金叉")


def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    import time
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)
