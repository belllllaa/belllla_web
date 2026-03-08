#coding:gbk
"""
横盘突破策略 - 中证2000版本
- 股票池：中证2000成分股
- 过去20交易日（不含今日）横盘震荡，平均振幅在2%-4%之间
- 今日涨幅大于9%
- 今日不是一字板（开盘价 != 最高价）
- 今日价格在MA60和MA20之上，且MA60向上
- 股票价格大于5元
- 尾盘买入
- 卖出逻辑参考动量策略（最少持有5天 + 多重止损条件）
- 最多持有10只股票，每只10000元
- 非ST股（剔除ST/创业板/科创板/北交所）
"""

import numpy as np


def init(C):
    C.accountid = getattr(C, 'accountid', '')
    C.max_stocks = 10
    C.per_stock_amount = 10000
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.selected_stocks = []
    C.min_hold_days = 15
    C.scan_limit = 2000  # 中证2000约2000只股票
    C.max_candidates = 50
    print('横盘突破策略（中证2000版）初始化完成')
 

def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    
    C.selected_stocks = select_sideways_breakout_stocks(C, bar_date_str)
    
    # 卖出逻辑（参考动量策略）
    for stock in list(C.holding.keys()):
        if not C.holding.get(stock, False):
            continue
        
        try:
            buy_date = C.buy_date.get(stock, current_date_str)
            days_held = _trading_days_diff(buy_date, current_date_str)
            in_min_hold = days_held < getattr(C, 'min_hold_days', 15)
            
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
            
            ma_3_prev = None
            ma_3_today = None
            if len(closes) >= 5:
                ma_3_prev = np.mean(closes[-4:-1])
                ma_3_today = np.mean(closes[-3:])
            
            total_loss = (current_price - buy_price) / buy_price
            if total_loss < -0.20:
                sell_condition = True
                sell_reason = "总亏损20%止损"
            elif today_current_return < -0.09:
                sell_condition = True
                sell_reason = "跌停"
            elif today_low_return < -0.09 and today_current_return < -0.05:
                sell_condition = True
                sell_reason = "大跌"
            elif not in_min_hold and ma_3_prev is not None and len(closes) >= 4:
                if current_price < ma_3_prev:
                    sell_condition = True
                    sell_reason = f"破3日线({current_price:.3f}<{ma_3_prev:.3f})"
            elif not in_min_hold and ma_3_prev is not None and ma_3_today is not None and len(closes) >= 5:
                if ma_3_today < ma_3_prev * 0.998 and current_price < ma_3_today:
                    sell_condition = True
                    sell_reason = "MA3拐头向下"
            
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
    if not C.selected_stocks:
        return
    
    current_holdings = sum(1 for h in C.holding.values() if h)
    if current_holdings < C.max_stocks:
        for stock in C.selected_stocks:
            if C.holding.get(stock, False):
                continue
            
            try:
                data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period=C.period, count=25, subscribe=False)
                if stock not in data or len(data[stock]) < 25:
                    continue
                
                closes = list(data[stock]['close'])
                opens = list(data[stock]['open'])
                highs = list(data[stock]['high'])
                current_close = closes[-1]
                today_open = opens[-1]
                today_high = highs[-1]
                
                if current_close <= 0 or today_open <= 0:
                    continue
                
                # 检查价格大于5元
                if current_close <= 5.0:
                    continue
                
                # 计算今日涨幅
                today_return = (current_close - today_open) / today_open
                
                # 检查是否为一字板
                is_yiziban = (abs(today_open - today_high) < 1e-6)
                
                # 满足买入条件：涨幅大于9%且不是一字板
                if today_return > 0.09 and not is_yiziban:
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
                    if current_holdings >= C.max_stocks:
                        break
            
            except Exception as e:
                print(f"买入异常 {stock}: {e}")


def calculate_average_amplitude(closes, period=20):
    """计算过去period日的平均振幅（不包含最后一天）"""
    if len(closes) < period + 1:
        return float('inf')
    
    # 计算前period日的每日涨跌幅（不包含最后一天）
    returns = []
    for i in range(len(closes) - period - 1, len(closes) - 1):
        if closes[i] > 0 and i + 1 < len(closes):
            daily_return = abs(closes[i] + 1 - closes[i]) / closes[i]
            returns.append(daily_return)
    
    if len(returns) < period:
        return float('inf')
    
    avg_amplitude = np.mean(returns)
    return avg_amplitude


def select_sideways_breakout_stocks(C, bar_date_str):
    """选股：中证2000成分股 + 过去20日横盘 + 今日突破 + 趋势确认"""
    selected_stocks = []
    try:
        # 获取中证2000成分股
        zz2000_stocks = []
        try:
            zz2000_stocks = C.get_sector('000905.SH')  # 中证2000指数代码
        except Exception:
            pass
        
        if not zz2000_stocks:
            # 备用方案：尝试其他方式获取中证2000
            try:
                zz2000_stocks = C.get_index_constituent('000905.SH')
            except Exception:
                pass
        
        if not zz2000_stocks:
            # 如果还是获取不到，使用全A股作为备选
            try:
                zz2000_stocks = C.get_sector('A股')
            except Exception:
                pass
        
        if not zz2000_stocks:
            # 最终备用：固定股票池
            zz2000_stocks = [
                '600036.SH', '000333.SZ', '601318.SH', '000651.SZ', '600104.SH',
                '000858.SZ', '601288.SH', '000002.SZ', '600519.SH', '002475.SZ',
                '601668.SH', '000725.SZ', '601857.SH', '002415.SZ', '601988.SH',
                '600030.SH', '000001.SZ', '601628.SH', '601328.SH', '000625.SZ',
                '600100.SH', '000768.SZ', '600028.SH', '601899.SH', '000100.SZ'
            ]
        
        print(f"[{bar_date_str}] 中证2000股票池大小: {len(zz2000_stocks)}")
        
        valid_stocks = []
        passed_sector_filter = 0
        passed_data_filter = 0
        passed_price_filter = 0
        passed_sideways_filter = 0
        passed_breakout_filter = 0
        passed_trend_filter = 0
        
        # 扫描全部中证2000成分股（最多2000只）
        scan_limit = min(getattr(C, 'scan_limit', 2000), len(zz2000_stocks))
        
        for stock in zz2000_stocks[:scan_limit]:
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
                
                if current_close <= 0 or today_open <= 0:
                    continue
                
                # 1. 价格筛选：大于5元
                if current_close <= 5.0:
                    continue
                passed_price_filter += 1
                
                # 2. 检查横盘条件：过去20日（不含今日）平均振幅在2%-4%之间
                avg_amp = calculate_average_amplitude(closes, 20)
                if avg_amp < 0.02 or avg_amp > 0.04:
                    continue
                passed_sideways_filter += 1
                
                # 3. 检查今日突破：涨幅>9%且非一字板
                today_return = (current_close - today_open) / today_open
                today_high = highs[-1]
                is_yiziban = (abs(today_open - today_high) < 1e-6)
                
                if today_return <= 0.09 or is_yiziban:
                    continue
                passed_breakout_filter += 1
                
                # 4. 趋势确认：价格在MA60和MA20之上，且MA60向上
                if len(closes) >= 60:
                    ma20 = np.mean(closes[-20:])
                    ma60 = np.mean(closes[-60:])
                    ma60_prev = np.mean(closes[-61:-1])  # 前一日的MA60
                    
                    if current_close > ma20 and current_close > ma60 and ma60 > ma60_prev:
                        valid_stocks.append(stock)
                        passed_trend_filter += 1
                
            except Exception as e:
                continue
        
        print(f"[{bar_date_str}] 筛选统计: 总股票数: {scan_limit} 通过板块过滤: {passed_sector_filter} 通过数据获取: {passed_data_filter} 通过价格筛选: {passed_price_filter} 通过横盘筛选: {passed_sideways_filter} 通过突破筛选: {passed_breakout_filter} 通过趋势确认: {passed_trend_filter} 最终选出: {len(valid_stocks)}")
        selected_stocks = valid_stocks[:getattr(C, 'max_candidates', 50)]
        
    except Exception as e:
        print(f"选股异常: {e}")
        selected_stocks = []
    
    return selected_stocks


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
    import time
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)

