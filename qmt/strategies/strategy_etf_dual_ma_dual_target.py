#coding:gbk
"""
策略二：双ETF 双均线(5/20) + 严格风控
目标：10万本金，年化>25%，胜率≥50%，回撤<年化1/3
逻辑：两只低波ETF各约5万，分别按5/20金叉买、死叉或单笔止损5%卖；分散标的降低回撤。
标的：510880.SH 红利ETF、512800.SH 银行ETF（或 510300 沪深300ETF 作替代）
"""

import numpy as np

def init(C):
    C.accountid = getattr(C, 'accountid', '')
    # 两只ETF，各约一半仓位
    C.symbols = ['510880.SH', '512800.SH']  # 红利ETF、银行ETF
    C.per_capital = 50000
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
    print('策略二：双ETF双均线(5/20)+止损 初始化完成，10万各5万')


def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    symbols = getattr(C, 'symbols', ['510880.SH', '512800.SH'])

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

        # ---------- 卖出 ----------
        if C.holding.get(symbol, False) and C.buy_shares.get(symbol, 0) >= 100:
            buy_price = C.buy_price.get(symbol, current_price)
            loss_pct = (current_price - buy_price) / buy_price
            if loss_pct <= getattr(C, 'stop_loss_pct', -0.05):
                passorder(24, 1101, C.accountid, symbol, 5, 0, C.buy_shares[symbol], "双ETF均线", 1, "", C)
                print(f"{bar_date_str} 卖出 {symbol} {C.buy_shares[symbol]}股 @ {current_price:.3f} 止损{loss_pct:.1%}")
                C.holding[symbol] = False
                C.buy_price[symbol] = 0.0
                C.buy_shares[symbol] = 0
                C.buy_date[symbol] = ''
                continue
            if ma5_prev >= ma20_prev and ma5_now < ma20_now:
                passorder(24, 1101, C.accountid, symbol, 5, 0, C.buy_shares[symbol], "双ETF均线", 1, "", C)
                print(f"{bar_date_str} 卖出 {symbol} {C.buy_shares[symbol]}股 @ {current_price:.3f} 死叉")
                C.holding[symbol] = False
                C.buy_price[symbol] = 0.0
                C.buy_shares[symbol] = 0
                C.buy_date[symbol] = ''
                continue

        # ---------- 买入：金叉且该标的当前空仓 ----------
        if not C.holding.get(symbol, False) and ma5_prev <= ma20_prev and ma5_now > ma20_now:
            per_cap = getattr(C, 'per_capital', 50000)
            shares = int(per_cap / current_price) // 100 * 100
            if shares >= 100:
                passorder(23, 1101, C.accountid, symbol, 5, 0, shares, "双ETF均线", 1, "", C)
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
