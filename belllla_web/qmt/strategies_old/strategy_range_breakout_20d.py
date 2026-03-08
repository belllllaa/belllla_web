#coding:gbk
"""
横盘突破策略（简化版 - 波动率版）

【策略诊断结论 - 选股截面 vs 买卖时序】
- 主要问题在「选股截面」：
  - 波动率<3%、箱体<6% 过严，选出的多为“极度平静”的股票，突破后弹性不足，容易继续横盘或一日游。
  - 真正“横盘蓄势后放量突破”的标的，横盘期往往已有一定波动（如日振幅2%~4%），箱体约6%~12%。
  - 涨幅>5% 可保留，用「跳空高开」补强：今日开盘 > 昨日收盘，算多头强势信号，过滤低开冲高的一日游。
- 次要问题在「买卖时序」：
  - 尾盘买入逻辑合理；可增加“突破质量”过滤（如站上MA20、突破日放量）减少假突破。
  - 最短持有过短会洗掉刚启动的标的，建议 min_hold_days=5；止损/MA拐头保留即可。

可调参数（init 内）：
  放宽横盘条件以提升弹性（如 5%、10%）
  当日涨幅下限（如 5%）
  是否要求跳空高开（开盘价 > 昨日收盘），与涨幅搭配可替代单纯提高涨幅门槛
  （可选先不用）use_trend_filter：是否要求收盘价在 MA20 之上
  （可选先不用）use_volume_filter：是否要求突破日成交量 > 20日均量（需接口支持 volume）
"""

import numpy as np
import time

def init(C):
    C.accountid = getattr(C, 'accountid', '')
    C.max_stocks = 10
    C.per_stock_amount = 10000
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.min_hold_days = 5
    print('横盘突破策略（简化版）初始化完成')
 

def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    
    # 获取股票池 - 使用改进版本，确保获取3000+只股票
    all_stocks = get_stock_pool(C, bar_date_str)
   
    print(f"[{bar_date_str}] 股票池大小: {len(all_stocks)} 只股票")
    
    # 卖出逻辑
    for stock in list(C.holding.keys()):
        if not C.holding.get(stock, False):
            continue
        
        try:
            buy_date = C.buy_date.get(stock, current_date_str)
            days_held = _trading_days_diff(buy_date, current_date_str)
            in_min_hold = days_held < getattr(C, 'min_hold_days', 5)
            
            data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period=C.period, count=25, subscribe=False)
            if stock not in data or len(data[stock]) < 2:
                continue
            
            closes = list(data[stock]['close'])
            opens = list(data[stock]['open'])
            highs = list(data[stock]['high'])
            lows = list(data[stock]['low'])
            current_price = closes[-1]
            buy_price = C.buy_price.get(stock, current_price)
            today_open = opens[-1]
            today_high = highs[-1]
            today_low = lows[-1]
            
            if today_open <= 0:
                continue
            
            today_high_return = (today_high - today_open) / today_open
            today_low_return = (today_low - today_open) / today_open
            today_current_return = (current_price - today_open) / today_open
            
            sell_condition = False
            sell_reason = ""
            
            ma_10_prev = None
            ma_10_today = None
            if len(closes) >= 12:
                ma_10_prev = np.mean(closes[-11:-1])
                ma_10_today = np.mean(closes[-10:])
            
            total_loss = (current_price - buy_price) / buy_price
            if total_loss < -0.10:
                sell_condition = True
                sell_reason = "总亏损10%止损"
            elif today_current_return < -0.09:
                sell_condition = True
                sell_reason = "跌停"
            elif today_low_return < -0.09 and today_current_return < -0.05:
                sell_condition = True
                sell_reason = "大跌"
            elif not in_min_hold and ma_10_prev is not None and len(closes) >= 12:
                if current_price < ma_10_prev:
                    sell_condition = True
                    sell_reason = f"破10日线({current_price:.3f}<{ma_10_prev:.3f})"
            elif not in_min_hold and ma_10_prev is not None and ma_10_today is not None and len(closes) >= 12:
                if ma_10_today < ma_10_prev * 0.998 and current_price < ma_10_today:
                    sell_condition = True
                    sell_reason = "MA10拐头向下"
            
            if sell_condition and stock in C.buy_shares:
                shares = C.buy_shares[stock]
                if shares >= 100:
                    passorder(24, 1101, C.accountid, stock, 5, 0, shares, "横盘突破", 1, "", C)
                    C.holding[stock] = False
                    profit = (current_price - buy_price) * shares
                    profit_pct = (current_price - buy_price) / buy_price
                    print(f"{bar_date_str} 卖出 {stock} {shares}股 @ {current_price:.3f} {sell_reason} 盈亏: {profit:.2f} ({profit_pct:.1%})")
                    
                    for key in [C.buy_price, C.buy_shares, C.buy_date]:
                        if stock in key:
                            del key[stock]
                    C.draw_text(1, 1, '卖')
        
        except Exception as e:
            print(f"卖出异常 {stock}: {e}")
    
    # 买入逻辑
    current_holdings = sum(1 for h in C.holding.values() if h)
    if current_holdings < C.max_stocks:
        # 统计各阶段筛选结果
        total_stocks = min(3500, len(all_stocks))
        passed_sector_filter = 0
        passed_data_filter = 0
        passed_price_filter = 0
        passed_sideways_filter = 0
        passed_breakout_filter = 0
        final_selected = 0
        
        for stock in all_stocks[:total_stocks]:
            if current_holdings >= C.max_stocks:
                break
                
            if C.holding.get(stock, False):
                continue
            
            if _is_chinext_star_bse_or_st(stock):
                continue
            passed_sector_filter += 1
            
            try:
                data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period='1d', count=25, subscribe=False)
                if stock not in data or len(data[stock]['close']) < 22:
                    continue
                passed_data_filter += 1
                
                closes = list(data[stock]['close'])
                highs = list(data[stock]['high'])
                lows = list(data[stock]['low'])
                opens = list(data[stock]['open'])
                current_close = closes[-1]
                today_open = opens[-1]
                yesterday_close=closes[-2]
                
                if current_close <= 0 or today_open <= 0:
                    continue
                
                # 价格>5元筛选
                if current_close <= 5.0:
                    continue
                passed_price_filter += 1
                
                # 1. 检查横盘条件（波动率 + 箱体）
                vol_ratio, box_ratio = calculate_sideways_metrics(highs, lows, closes, 20)
                
                # 波动率 < 5% 且 价格箱体 < 10%
                if vol_ratio < 0.05 and box_ratio < 0.10:
                    passed_sideways_filter += 1
                    
                    # 2. 检查今日突破：涨幅>5%且非一字板,跳空
                    today_return = (current_close - today_open) / today_open
                    today_high = highs[-1]
                    is_yiziban = (abs(today_open - today_high) < 1e-6)
                    strong_gap_up = today_open > yesterday_close
                    if today_return > 0.05 and strong_gap_up and not is_yiziban :
                        passed_breakout_filter += 1
					                        
                        # 执行买入
                        target_shares = int(C.per_stock_amount / current_close)
                        shares = (target_shares // 100) * 100
                        if shares < 100 or shares > 10000:
                            continue
                        
                        passorder(23, 1101, C.accountid, stock, 5, 0, shares, "横盘突破", 1, "", C)
                        C.holding[stock] = True
                        C.buy_price[stock] = current_close
                        C.buy_shares[stock] = shares
                        C.buy_date[stock] = current_date_str
                        print(f"{bar_date_str} 买入 {stock} {shares}股 @ {current_close:.3f} 横盘突破")
                        C.draw_text(1, 1, '买')
                        
                        current_holdings += 1
                        final_selected += 1
                        
                        if current_holdings >= C.max_stocks:
                            break
                
            except Exception as e:
                print(f"买入异常 {stock}: {e}")
        
'''       # 打印详细的筛选统计
        print(f"[{bar_date_str}] 筛选统计:")
        print(f"  总分析股票: {total_stocks}")
        print(f"  通过板块过滤: {passed_sector_filter}")
        print(f"  通过数据获取: {passed_data_filter}")
        print(f"  通过价格>5元: {passed_price_filter}")
        print(f"  通过横盘条件: {passed_sideways_filter}")
        print(f"  通过突破条件: {passed_breakout_filter}")
        print(f"  实际买入数量: {final_selected}")
'''

def calculate_sideways_metrics(highs, lows, closes, period=20):
    """
    计算横盘指标：
    - vol_ratio: 20日波动率 = 标准差 / 20日均价
    - box_ratio: 价格箱体 = (20日最高价 - 20日最低价) / 20日均价
    使用过去 period 日（不含今日）的数据。
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return float('inf'), float('inf')

    # 过去 period 日（不含今日）的收盘价
    recent_closes = closes[-period-1:-1]
    mean_price = np.mean(recent_closes)
    if mean_price <= 0:
        return float('inf'), float('inf')

    # 1) 波动率：标准差 / 均价
    std = np.std(recent_closes)
    vol_ratio = std / mean_price

    # 2) 价格箱体：(20日最高价 - 20日最低价) / 20日均价
    recent_highs = highs[-period-1:-1]
    recent_lows = lows[-period-1:-1]
    if not recent_highs or not recent_lows:
        return float('inf'), float('inf')

    box_high = max(recent_highs)
    box_low = min(recent_lows)
    if box_low <= 0:
        box_ratio = float('inf')
    else:
        box_ratio = (box_high - box_low) / mean_price

    return vol_ratio, box_ratio

def get_stock_pool(C, current_date_str):
    """获取股票池 - 改进版本，确保获取3000+只股票"""
    all_stocks = []
    
    try:
        # 方法2: 组合多个指数成分股
        index_stocks = []
        indices = ['000001.SH', '399001.SZ', '000300.SH', '000905.SH', '000852.SH', '000903.SH']
        
        for index_code in indices:
            try:
                if hasattr(C, 'get_index_constituent'):
                    stocks = C.get_index_constituent(index_code)
                    if stocks:
                        index_stocks.extend(stocks)
                elif hasattr(C, 'get_sector'):
                    stocks = C.get_sector(index_code)
                    if stocks:
                        index_stocks.extend(stocks)
            except Exception:
                continue
        
        if index_stocks:
            all_stocks = list(set(index_stocks))
            print(f"方法2成功: 组合指数成分股 {len(all_stocks)} 只")
            return all_stocks
    except Exception as e:
        print(f"组合指数成分股失败: {e}") 
    return all_stocks

def _is_chinext_star_bse_or_st(stock_code):
    """剔除ST股、创业板、科创板、北交所"""
    if not stock_code or len(stock_code) < 6:
        return False
    code = stock_code.split('.')[0]
    suffix = (stock_code.split('.')[-1] or '').upper()
    if suffix == 'BJ':
        return True
    if code.startswith('300'):
        return True
    if code.startswith('688') or code.startswith('689'):
        return True
    if 'ST' in stock_code.upper():
        return True
    return False

def _trading_days_diff(date_start, date_end):
    from datetime import datetime
    try:
        d1 = datetime.strptime(str(date_start), '%Y%m%d')
        d2 = datetime.strptime(str(date_end), '%Y%m%d')
        return max(0, (d2 - d1).days)
    except Exception:
        return 0

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)  