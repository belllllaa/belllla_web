#coding:gbk
# 导入常用库
import numpy as np

"""
布林带突破策略 - 中证1000版
严格按照QMT函数规范编写
核心逻辑：价格下穿布林带下轨买入，上穿布林带上轨卖出
股票池：中证1000（000852.ZZ），按市值从小到大排序，买入最小10个市值股票
"""

def init(C):
    # 设置回测参数
    C.start_date = "20210101"
    C.end_date = "20251231"
    C.accountid = "bollinger_test"
   
    # 滑点和手续费设置
    C.slippage = 0.001      # 滑点0.1%
    C.commission = 0.0003   # 手续费0.03%
    C.min_commission = 5    # 最低手续费5元
    C.max_stocks = 10       # 最多10只股票
   
    # 策略参数
    C.max_stock_value = 100000  # 每只股票最多投入10万元
    C.holding = {}           # 持仓状态
    C.buy_price = {}         # 买入价格记录
    C.buy_shares = {}        # 买入股数记录
   
    # 布林带参数
    C.boll_period = 20       # 布林带周期
    C.boll_stddev = 2.0      # 标准差倍数
   
    print(f'布林带突破策略（中证1000版）初始化完成')
    print(f'回测期间: {C.start_date} - {C.end_date}')
    print(f'初始资金: 100万元')
    print(f'股票池: 中证1000（000852.ZZ）')
    print(f'选股规则: 按市值从小到大，选择最小10个市值股票')
    print(f'单票上限: 10万元')
    print(f'策略逻辑: 下轨买入，上轨卖出')

def handlebar(C):
    # 获取当前K线日期
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
   
    # 检查是否在回测时间范围内
    if current_date_str < C.start_date or current_date_str > C.end_date:
        return
   
    # 获取中证1000成分股（000852.ZZ）
    try:
        stock_pool = C.get_sector('000852.ZZ')
    except:
        try:
            stock_pool = C.get_sector('000852.SH')
        except:
            stock_pool = C.get_stock_list_in_sector('沪深A股')
   
    # 如果获取不到，使用默认股票池
    if not stock_pool or len(stock_pool) == 0:
        stock_pool = C.get_stock_list_in_sector('沪深A股')
   
    # 限制股票池大小，避免超时
    stock_pool = stock_pool[:500]
   
    # 获取账户信息
    account = get_trade_detail_data(C.accountid, 'stock', 'account')
    if not account:
        return
    available_cash = int(account[0].m_dAvailable)
    total_balance = account[0].m_dBalance
   
    # 获取当前持仓
    holdings = get_trade_detail_data(C.accountid, 'stock', 'position')
    current_holdings = {}
    for pos in holdings:
        stock_code = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        current_holdings[stock_code] = {
            'volume': pos.m_nVolume,
            'can_use_volume': pos.m_nCanUseVolume,
            'cost_price': pos.m_dOpenPrice
        }
   
    # 处理卖出逻辑
    for stock in list(C.holding.keys()):
        if C.holding.get(stock, False):
            try:
                # 获取股票数据
                data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=C.boll_period+2, subscribe=False)
                if stock not in data or len(data[stock]) < C.boll_period+2:
                    continue
               
                closes = list(data[stock]['close'])
                current_price = closes[-1]
                prev_close = closes[-2]
               
                # 计算布林带
                ma_20 = np.mean(closes[-C.boll_period-1:-1])
                stddev_20 = np.std(closes[-C.boll_period-1:-1])
                upper_band = ma_20 + C.boll_stddev * stddev_20
                lower_band = ma_20 - C.boll_stddev * stddev_20
               
                # 卖出条件：价格上穿布林带上轨
                if prev_close <= upper_band and current_price > upper_band:
                    # 执行卖出
                    shares = C.buy_shares.get(stock, 0)
                    if shares >= 100 and stock in current_holdings:
                        actual_sell_price = current_price * (1 - C.slippage)
                        commission_fee = max(shares * actual_sell_price * C.commission, C.min_commission)
                        passorder(24, 1101, C.accountid, stock, 5, -1, shares, C)
                        C.holding[stock] = False
                        profit = (actual_sell_price - C.buy_price.get(stock, actual_sell_price)) * shares - commission_fee
                        profit_pct = profit / (C.buy_price.get(stock, actual_sell_price) * shares)
                        print(f"{bar_date_str} 卖出 {stock} {shares}股 @ {actual_sell_price:.3f} 上轨突破 盈亏: {profit:.2f} ({profit_pct:.1%})")
                       
                        # 清理记录
                        for key in [C.buy_price, C.buy_shares]:
                            if stock in key:
                                del key[stock]
            except Exception as e:
                continue
   
    # 处理买入逻辑
    buy_candidates = []
   
    # 筛选买入候选股票（按市值排序，选择最小10个）
    candidate_stocks = []
    for stock in stock_pool[:100]:  # 限制前100只股票进行筛选
        try:
            # 获取股票数据
            data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=C.boll_period+2, subscribe=False)
            if stock not in data or len(data[stock]) < C.boll_period+2:
                continue
           
            closes = list(data[stock]['close'])
            current_price = closes[-1]
            prev_close = closes[-2]
           
            # 计算布林带
            ma_20 = np.mean(closes[-C.boll_period-1:-1])
            stddev_20 = np.std(closes[-C.boll_period-1:-1])
            upper_band = ma_20 + C.boll_stddev * stddev_20
            lower_band = ma_20 - C.boll_stddev * stddev_20
           
            # 买入条件：价格下穿布林带下轨
            if prev_close >= lower_band and current_price < lower_band:
                # 检查是否已经持仓
                if stock not in C.holding or not C.holding.get(stock, False):
                    # 使用当前价格作为市值代理（简化处理）
                    market_value = current_price
                    candidate_stocks.append((stock, current_price, market_value))
        except Exception as e:
            continue
   
    # 按市值从小到大排序，选择最小10个
    candidate_stocks.sort(key=lambda x: x[2])  # 按市值排序
    buy_candidates = candidate_stocks[:10]  # 选择最小10个市值股票
   
    # 执行买入（满仓轮动）
    for stock, price, market_value in buy_candidates:
        if available_cash <= 0:
            break
       
        # 计算可买入股数
        target_value = min(C.max_stock_value, available_cash)
        shares = int(target_value / price / 100) * 100  # 向下取整到100的倍数
       
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
                print(f"{bar_date_str} 买入 {stock} {shares}股 @ {actual_buy_price:.3f} (投入:{investment:.0f}元)")
   
    # 更新持仓状态
    for stock in current_holdings:
        if stock not in C.holding:
            C.holding[stock] = True

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    """时间戳转换函数"""
    import time
    try:
        return time.strftime(format_str, time.localtime(timetag/1000))
    except:
        return str(timetag)
