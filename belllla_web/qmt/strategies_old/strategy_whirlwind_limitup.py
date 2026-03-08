#coding:gbk
# 导入常用库
import numpy as np

"""
旋风冲锋策略 - 优化版
严格按照要求：买入条件必须是近20日内有过涨停(涨幅>=9.9%)
"""

def init(C):
    # 设置回测参数
    C.start_date = "20250101"
    C.end_date = "20251231"
    C.accountid = "test_account"
   
    # 滑点和手续费设置
    C.slippage = 0.001      # 滑点0.1%
    C.commission = 0.0003   # 手续费0.03%
    C.min_commission = 5    # 最低手续费5元
   
    # 策略参数
    C.max_stocks = 10        # 最多10只股票
    C.per_stock_amount = 100000  # 每只股票10万
    C.holding = {}           # 持仓状态
    C.buy_price = {}         # 买入价格记录
    C.buy_shares = {}        # 买入股数记录
    C.buy_date = {}          # 买入日期记录
   
    # 初始化股票池为空
    C.selected_stocks = []
   
    print(f'旋风冲锋策略（优化版）初始化完成')
    print(f'回测期间: {C.start_date} - {C.end_date}')
    print(f'滑点: {C.slippage*100:.1f}%, 手续费: {C.commission*100:.2f}%')
    print(f'买入条件: 近20日内必须有涨停(涨幅>=9.9%)')

def handlebar(C):
    # 获取当前K线日期
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
   
    # 检查是否在回测时间范围内
    if current_date_str < C.start_date or current_date_str > C.end_date:
        return
   
    # 每个交易日都重新筛选股票池 - 严格按照涨停条件
    C.selected_stocks = select_strict_limit_up_stocks(C, bar_date_str)
    print(f"{bar_date_str} 符合涨停条件的股票: {len(C.selected_stocks)}只")
   
    # 初始化新股票的持仓状态
    for stock in C.selected_stocks:
        if stock not in C.holding:
            C.holding[stock] = False
   
    # 先处理卖出逻辑（对所有持仓股票）
    for stock in list(C.holding.keys()):
        if C.holding.get(stock, False):
            try:
                # 获取当日数据
                data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period=C.period, count=10, subscribe=False)
                if stock not in data or len(data[stock]) < 2:
                    continue
               
                closes = list(data[stock]['close'])
                opens = list(data[stock]['open'])
                highs = list(data[stock]['high'])
                lows = list(data[stock]['low'])
                current_price = closes[-1]
               
                # 获取买入信息
                buy_price = C.buy_price.get(stock, current_price)
                buy_date = C.buy_date.get(stock, current_date_str)
               
                # 计算当日涨幅相关指标
                if len(opens) >= 1:
                    today_open = opens[-1]
                    today_high = highs[-1]
                    today_low = lows[-1]
                   
                    # 当日最高涨幅和最低涨幅
                    if today_open > 0:
                        today_high_return = (today_high - today_open) / today_open
                        today_low_return = (today_low - today_open) / today_open
                        today_current_return = (current_price - today_open) / today_open
                       
                        # 卖出条件检查
                        sell_condition = False
                        sell_reason = ""
                       
                        # 条件1: 跌停止损 - 当前涨幅<-9%
                        if today_current_return < -0.09:
                            sell_condition = True
                            sell_reason = "跌停止损"
                           
                        # 条件2: 大跌减亏
                        elif (today_low_return < -0.09 and today_current_return > -0.05) or \
                             (today_low_return < -0.07 and today_current_return > -0.03) or \
                             (today_low_return < -0.05 and today_current_return > -0.01):
                            sell_condition = True
                            sell_reason = "大跌减亏"
                           
                        # 条件3: 冲高回落
                        elif (today_high_return > 0.09 and today_current_return < 0.05) or \
                             (today_high_return > 0.07 and today_current_return < 0.03) or \
                             (today_high_return > 0.05 and today_current_return < 0.01):
                            sell_condition = True
                            sell_reason = "冲高回落"
                           
                        # 条件4: 炸板回落
                        elif today_high_return > 0.08 and today_current_return < 0.05:
                            sell_condition = True
                            sell_reason = "炸板回落"
                           
                        # 条件5: 破5日线清仓
                        elif len(closes) >= 5:
                            ma_5 = np.mean(closes[-5:])
                            if current_price < ma_5 * 0.99:
                                sell_condition = True
                                sell_reason = "破5日线"
                       
                        # 执行卖出
                        if sell_condition and stock in C.buy_shares:
                            shares = C.buy_shares[stock]
                            if shares >= 100:
                                # 计算实际卖出价格（考虑滑点）
                                actual_sell_price = current_price * (1 - C.slippage)
                                # 计算手续费
                                commission_fee = max(shares * actual_sell_price * C.commission, C.min_commission)
                               
                                passorder(24, 1101, C.accountid, stock, 5, -1, shares, C)
                                C.holding[stock] = False
                                profit = (actual_sell_price - buy_price) * shares - commission_fee
                                profit_pct = (actual_sell_price - buy_price) / buy_price
                                print(f"{bar_date_str} 卖出 {stock} {shares}股 @ {actual_sell_price:.3f} {sell_reason} 盈亏: {profit:.2f} ({profit_pct:.1%})")
                               
                                # 清理记录
                                for key in [C.buy_price, C.buy_shares, C.buy_date]:
                                    if stock in key:
                                        del key[stock]
                                C.draw_text(1, 1, '卖')
            except Exception as e:
                continue
   
    # 处理买入逻辑 - 开盘买入
    if not C.selected_stocks:
        return
       
    for stock in C.selected_stocks:
        try:
            # 获取60日数据
            data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period=C.period, count=60, subscribe=False)
           
            # 检查数据是否足够
            if stock not in data or len(data[stock]) < 60:
                continue
               
            closes = list(data[stock]['close'])
            opens = list(data[stock]['open'])
            highs = list(data[stock]['high'])
            lows = list(data[stock]['low'])
            current_open = opens[-1]  # 使用开盘价
           
            # 基本价格检查
            if current_open <= 0:
                continue
               
            # 严格执行买入条件：必须是近20日内有涨停(>=9.9%)
            has_valid_limit_up = check_strict_limit_up(closes, opens, highs, lows, 20)
           
            if not has_valid_limit_up:
                continue  # 不符合条件，跳过
               
            # 计算今日开盘涨幅
            prev_close = closes[-2] if len(closes) >= 2 else current_open
            today_open_return = (current_open - prev_close) / prev_close if prev_close > 0 else 0
           
            # 简化买入逻辑：只要是符合涨停条件的股票，且开盘涨幅在合理范围内就买入
            buy_condition = False
            if -0.03 <= today_open_return <= 0.08:  # 开盘涨幅在-3%到+8%之间
                buy_condition = True
               
            # 执行买入 - 开盘买入
            if not C.holding.get(stock, False) and buy_condition:
                current_holdings = sum(1 for holding in C.holding.values() if holding)
                if current_holdings < C.max_stocks:
                    target_shares = int(C.per_stock_amount / current_open)
                    shares = (target_shares // 100) * 100
                   
                    if shares >= 100 and shares <= 10000:
                        # 计算实际买入价格（考虑滑点）
                        actual_buy_price = current_open * (1 + C.slippage)
                        # 计算手续费
                        commission_fee = max(shares * actual_buy_price * C.commission, C.min_commission)
                       
                        passorder(23, 1101, C.accountid, stock, 5, -1, shares, C)
                        C.holding[stock] = True
                        C.buy_price[stock] = actual_buy_price
                        C.buy_shares[stock] = shares
                        C.buy_date[stock] = current_date_str
                        actual_investment = shares * actual_buy_price + commission_fee
                        print(f"{bar_date_str} 买入 {stock} {shares}股 @ {actual_buy_price:.3f} (投入:{actual_investment:.0f}元)")
                        C.draw_text(1, 1, '买')
                       
        except Exception as e:
            continue

def select_strict_limit_up_stocks(C, bar_date_str):
    """严格选股：只选择近20日内有真正涨停(>=9.9%)的股票"""
    selected_stocks = []
    try:
        # 获取更广泛的股票池
        all_stocks = []
       
        # 尝试获取中证800
        try:
            all_stocks = C.get_sector('000906.ZZ')
        except:
            pass
           
        # 如果获取不到，尝试沪深300
        if not all_stocks or len(all_stocks) == 0:
            try:
                all_stocks = C.get_sector('000300.SH')
            except:
                pass
               
        # 如果还是获取不到，使用预设池
        if not all_stocks or len(all_stocks) == 0:
            all_stocks = [
                '600036.SH', '000333.SZ', '601318.SH', '000651.SZ', '600104.SH',
                '000858.SZ', '601288.SH', '000002.SZ', '600519.SH', '002475.SZ',
                '601668.SH', '000725.SZ', '601857.SH', '002415.SZ', '601988.SH',
                '600030.SH', '000001.SZ', '601628.SH', '601328.SH', '601166.SH'
            ]
       
        # 严格筛选：必须近20日内有涨停(>=9.9%)
        valid_stocks = []
        for stock in all_stocks[:300]:  # 扩大到前300只
            try:
                data = C.get_market_data_ex(['close', 'high', 'open'], [stock], end_time=bar_date_str, period='1d', count=30, subscribe=False)
                if stock in data and len(data[stock]) >= 30:
                    closes = list(data[stock]['close'])
                    opens = list(data[stock]['open'])
                    highs = list(data[stock]['high'])
                   
                    # 严格检查近20日是否有涨停(>=9.9%)
                    has_strict_limit_up = False
                    for i in range(-21, -1):  # 近20个交易日
                        if abs(i) <= len(closes) and i < len(opens):
                            day_open = opens[i]
                            day_high = highs[i]
                            if day_open > 0:
                                daily_return = (day_high - day_open) / day_open
                                if daily_return >= 0.099:  # 严格9.9%标准
                                    has_strict_limit_up = True
                                    break
                   
                    if has_strict_limit_up:
                        valid_stocks.append(stock)
                        if len(valid_stocks) >= 30:  # 最多30只候选
                            break
            except:
                continue
               
        selected_stocks = valid_stocks
       
    except Exception as e:
        print(f"严格选股异常: {e}")
        # 回退到安全的预设池
        selected_stocks = [
            '600036.SH', '000333.SZ', '601318.SH', '000651.SZ', '600104.SH',
            '000858.SZ', '601288.SH', '000002.SZ', '600519.SH', '002475.SZ'
        ]
   
    return selected_stocks

def check_strict_limit_up(closes, opens, highs, lows, days):
    """严格检查近N日是否有涨停(涨幅>=9.9%)"""
    if len(closes) < days + 1:
        return False
       
    start_idx = max(0, len(closes) - days - 1)
    for i in range(start_idx, len(closes) - 1):  # 排除当天
        if opens[i] > 0:
            high_return = (highs[i] - opens[i]) / opens[i]
            if high_return >= 0.099:  # 严格9.9%标准
                return True
    return False

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    """时间戳转换函数"""
    import time
    try:
        return time.strftime(format_str, time.localtime(timetag/1000))
    except:
        return str(timetag)
