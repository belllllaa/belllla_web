# 模式二参考代码：QMT 回测样板

以下两个策略为模式二（回测优先）的完整参考代码，可直接在 QMT 中加载回测。

---

## 1. 布林带突破策略 - 中证1000版

**文件**: [strategies/strategy_bollinger_csi1000.py](../../../strategies/strategy_bollinger_csi1000.py)

**逻辑**: 价格下穿布林带下轨买入，上穿上轨卖出。股票池为中证1000，按市值从小到大选最小10只。

```python
#coding:gbk
import numpy as np

"""
布林带突破策略 - 中证1000版
核心逻辑：价格下穿布林带下轨买入，上穿布林带上轨卖出
股票池：中证1000（000852.ZZ），按市值从小到大排序，买入最小10个市值股票
"""

def init(C):
    C.start_date = "20210101"
    C.end_date = "20251231"
    C.accountid = "bollinger_test"
    C.slippage = 0.001      # 滑点0.1%
    C.commission = 0.0003   # 手续费0.03%
    C.min_commission = 5    # 最低手续费5元
    C.max_stocks = 10
    C.max_stock_value = 100000  # 每只股票最多投入10万元
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.boll_period = 20       # 布林带周期
    C.boll_stddev = 2.0      # 标准差倍数

def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    if current_date_str < C.start_date or current_date_str > C.end_date:
        return
   
    # 获取中证1000成分股
    try:
        stock_pool = C.get_sector('000852.ZZ')
    except:
        try:
            stock_pool = C.get_sector('000852.SH')
        except:
            stock_pool = C.get_stock_list_in_sector('沪深A股')
    if not stock_pool or len(stock_pool) == 0:
        stock_pool = C.get_stock_list_in_sector('沪深A股')
    stock_pool = stock_pool[:500]
   
    # 获取账户与持仓
    account = get_trade_detail_data(C.accountid, 'stock', 'account')
    if not account:
        return
    available_cash = int(account[0].m_dAvailable)
    holdings = get_trade_detail_data(C.accountid, 'stock', 'position')
    current_holdings = {}
    for pos in holdings:
        stock_code = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        current_holdings[stock_code] = {'volume': pos.m_nVolume, 'can_use_volume': pos.m_nCanUseVolume, 'cost_price': pos.m_dOpenPrice}
   
    # 卖出逻辑：价格上穿布林带上轨
    for stock in list(C.holding.keys()):
        if C.holding.get(stock, False):
            try:
                data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=C.boll_period+2, subscribe=False)
                if stock not in data or len(data[stock]) < C.boll_period+2:
                    continue
                closes = list(data[stock]['close'])
                current_price = closes[-1]
                prev_close = closes[-2]
                ma_20 = np.mean(closes[-C.boll_period-1:-1])
                stddev_20 = np.std(closes[-C.boll_period-1:-1])
                upper_band = ma_20 + C.boll_stddev * stddev_20
                lower_band = ma_20 - C.boll_stddev * stddev_20
                if prev_close <= upper_band and current_price > upper_band:
                    shares = C.buy_shares.get(stock, 0)
                    if shares >= 100 and stock in current_holdings:
                        passorder(24, 1101, C.accountid, stock, 5, -1, shares, C)
                        C.holding[stock] = False
                        for key in [C.buy_price, C.buy_shares]:
                            if stock in key:
                                del key[stock]
            except Exception:
                continue
   
    # 买入逻辑：价格下穿布林带下轨，按市值排序选最小10只
    candidate_stocks = []
    for stock in stock_pool[:100]:
        try:
            data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=C.boll_period+2, subscribe=False)
            if stock not in data or len(data[stock]) < C.boll_period+2:
                continue
            closes = list(data[stock]['close'])
            current_price = closes[-1]
            prev_close = closes[-2]
            ma_20 = np.mean(closes[-C.boll_period-1:-1])
            stddev_20 = np.std(closes[-C.boll_period-1:-1])
            upper_band = ma_20 + C.boll_stddev * stddev_20
            lower_band = ma_20 - C.boll_stddev * stddev_20
            if prev_close >= lower_band and current_price < lower_band:
                if stock not in C.holding or not C.holding.get(stock, False):
                    candidate_stocks.append((stock, current_price, current_price))
        except Exception:
            continue
    candidate_stocks.sort(key=lambda x: x[2])
    buy_candidates = candidate_stocks[:10]
   
    for stock, price, _ in buy_candidates:
        if available_cash <= 0:
            break
        target_value = min(C.max_stock_value, available_cash)
        shares = int(target_value / price / 100) * 100
        if shares >= 100:
            actual_buy_price = price * (1 + C.slippage)
            commission_fee = max(shares * actual_buy_price * C.commission, C.min_commission)
            investment = shares * actual_buy_price + commission_fee
            if investment <= available_cash:
                passorder(23, 1101, C.accountid, stock, 5, -1, shares, C)
                C.holding[stock] = True
                C.buy_price[stock] = actual_buy_price
                C.buy_shares[stock] = shares
                available_cash -= investment
   
    for stock in current_holdings:
        if stock not in C.holding:
            C.holding[stock] = True

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    import time
    try:
        return time.strftime(format_str, time.localtime(timetag/1000))
    except:
        return str(timetag)
```

---

## 2. 旋风冲锋策略 - 涨停板样板

**文件**: [strategies/strategy_whirlwind_limitup.py](../../../strategies/strategy_whirlwind_limitup.py)

**逻辑**: 买入条件为近20日内有过涨停(>=9.9%)，开盘涨幅 -3%~+8% 时买入。卖出：跌停止损、大跌减亏、冲高回落、炸板回落、破5日线。

**关键函数**:
- `select_strict_limit_up_stocks(C, bar_date_str)` - 严格选股：近20日有涨停
- `check_strict_limit_up(closes, opens, highs, lows, days)` - 检查涨停条件
- `timetag_to_datetime(timetag, format_str)` - 时间戳转换

**注意**: 需在 init 中设置 `C.period = '1d'`（若 QMT 未自动注入）。

完整代码见 [strategy_whirlwind_limitup.py](../../../strategies/strategy_whirlwind_limitup.py)。

---

## 通用模式二代码要点

| 要点 | 说明 |
|------|------|
| 编码 | `#coding:gbk` |
| 时间 | `timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')` |
| 股票池 | `C.get_sector('000852.ZZ')` / `C.get_stock_list_in_sector('沪深A股')` |
| 账户 | `get_trade_detail_data(C.accountid, 'stock', 'account')` |
| 持仓 | `get_trade_detail_data(C.accountid, 'stock', 'position')` |
| 行情 | `C.get_market_data_ex(['close','high','open'], [stock], end_time=..., period='1d', count=N, subscribe=False)` |
| 下单 | `passorder(23, 1101, C.accountid, stock, 5, -1, shares, C)` 买入；`passorder(24, ...)` 卖出 |
| 滑点手续费 | 在 init 中设置 C.slippage、C.commission、C.min_commission |
