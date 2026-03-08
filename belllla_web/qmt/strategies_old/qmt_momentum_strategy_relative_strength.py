#coding:gbk
"""
动量突破策略  
突破10日新高+趋势向上+量能放大+相对强度筛选+市值40-500亿+剔除ST/创业板/科创板/北交所
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
    C.min_hold_days = 5
    C.scan_limit = 1800  # 扩大扫描范围
    C.max_candidates = 50
    # 市值范围：40亿到500亿
    C.min_market_cap = 50e8  # 40亿
    C.max_market_cap = 1000e8  # 500亿
    print('动量突破策略初始化完成')
 

def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    
    C.selected_stocks = select_momentum_stocks_with_relative_strength(C, bar_date_str)
    
    # 卖出逻辑（保持不变）
    for stock in list(C.holding.keys()):
        if not C.holding.get(stock, False):
            continue
        
        try:
            buy_date = C.buy_date.get(stock, current_date_str)
            days_held = _trading_days_diff(buy_date, current_date_str)
            in_min_hold = days_held < getattr(C, 'min_hold_days',5)
            
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
            if total_loss < -0.10:
                sell_condition = True
                sell_reason = "总亏损10%止损"
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
                    passorder(24, 1101, C.accountid, stock, 5, 0, shares, "动量突破", 1, "", C)
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
                data = C.get_market_data_ex(['close', 'high', 'low', 'open', 'volume'], [stock], end_time=bar_date_str, period=C.period, count=30, subscribe=False)
                if stock not in data or len(data[stock]) < 25:
                    continue
                
                closes = list(data[stock]['close'])
                opens = list(data[stock]['open'])
                highs = list(data[stock]['high'])
                volumes = list(data[stock].get('volume', []))
                current_close = closes[-1]
                
                if current_close <= 0:
                    continue
                
                # 1. 突破10日新高
                high_10= max(highs[-11:-1])
                if current_close <= high_10:
                    continue
                
                # 2. 趋势向上
                if len(closes) >= 20:
                    ma_20 = np.mean(closes[-20:])
                    if current_close <= ma_20:
                        continue
                
                # 3. MA多头排列
                if len(closes) >= 20:
                    ma_5 = np.mean(closes[-5:])
                    ma_10 = np.mean(closes[-10:])
                    ma_20 = np.mean(closes[-20:])
                    if not (ma_5 > ma_10 > ma_20):
                        continue
                
                # 4. 量能放大
                if len(volumes) >= 6:
                    today_vol = volumes[-1]
                    avg_vol_5 = np.mean(volumes[-6:-1])
                    if avg_vol_5 > 0:
                        volume_ratio = today_vol / avg_vol_5
                        if volume_ratio < 1.8:
                            continue
                
                # 5. 市值筛选和板块过滤
                market_cap_ok = check_market_cap_range(C, stock, bar_date_str)
                if not market_cap_ok or _is_chinext_star_bse_or_st(stock):
                    continue
                
                target_shares = int(C.per_stock_amount / current_close)
                shares = (target_shares // 100) * 100
                if shares < 100 or shares > 10000:
                    continue
                
                passorder(23, 1101, C.accountid, stock, 5, 0, shares, "动量突破", 1, "", C)
                C.holding[stock] = True
                C.buy_price[stock] = current_close
                C.buy_shares[stock] = shares
                C.buy_date[stock] = current_date_str
                print(f"{bar_date_str} 买入 {stock} {shares}股 @ {current_close:.3f} 突破10日新高")
                C.draw_text(1, 1, '买')
                
                current_holdings += 1
                if current_holdings >= C.max_stocks:
                    break
            
            except Exception as e:
                print(f"买入异常 {stock}: {e}")

def check_market_cap_range(C, stock_code, bar_date_str):
    """检查市值是否在50-1000亿范围内"""
    try:
        min_cap = getattr(C, 'min_market_cap', 50e8)
        max_cap = getattr(C, 'max_market_cap', 1000e8)
        instrument_info = C.get_instrument_detail([stock_code])
        if instrument_info and stock_code in instrument_info:
            info = instrument_info[stock_code]
            if 'circulation_market_value' in info and info['circulation_market_value'] > 0:
                market_cap = info['circulation_market_value']
                return min_cap <= market_cap <= max_cap
            elif 'market_value' in info and info['market_value'] > 0:
                market_cap = info['market_value']
                return min_cap <= market_cap <= max_cap
        return True
    except Exception:
        return True

def calculate_relative_strength(C, stock, bar_date_str, period=20):
    """计算相对强度：个股涨幅 vs 大盘涨幅"""
    try:
        # 获取个股数据
        stock_data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=period+5, subscribe=False)
        if stock not in stock_data or len(stock_data[stock]) < period + 1:
            return 0
        
        stock_closes = list(stock_data[stock]['close'])
        stock_return = (stock_closes[-1] - stock_closes[-period-1]) / stock_closes[-period-1]
        
        # 获取大盘数据（沪深300）
        market_data = C.get_market_data_ex(['close'], ['000300.SH'], end_time=bar_date_str, period='1d', count=period+5, subscribe=False)
        if '000300.SH' not in market_data or len(market_data['000300.SH']) < period + 1:
            return 0
        
        market_closes = list(market_data['000300.SH']['close'])
        market_return = (market_closes[-1] - market_closes[-period-1]) / market_closes[-period-1]
        
        # 计算相对强度
        if market_return != 0:
            relative_strength = stock_return / market_return
        else:
            relative_strength = stock_return / 0.001  # 避免除零
        
        return relative_strength
        
    except Exception:
        return 0

def select_momentum_stocks_with_relative_strength(C, bar_date_str):
    """选股：全市场 + 动量突破 + 相对强度筛选"""
    selected_stocks = []
    try:
        # 使用更大的股票池（全市场）
        all_a_stocks = []
        try:
            # 尝试获取全A股
            all_a_stocks = C.get_sector('A股')
        except Exception:
            pass
        
        if not all_a_stocks:
            # 备用方案：组合多个指数成分股
            try:
                hs300 = C.get_sector('000300.SH') or []
                zz500 = C.get_sector('000905.SH') or []
                zz1000 = C.get_sector('000852.SH') or []
                all_a_stocks = list(set(hs300 + zz500 + zz1000))
            except Exception:
                pass
        
        if not all_a_stocks:
            # 最终备用：固定股票池
            all_a_stocks = [
                '600036.SH', '000333.SZ', '601318.SH', '000651.SZ', '600104.SH',
                '000858.SZ', '601288.SH', '000002.SZ', '600519.SH', '002475.SZ',
                '601668.SH', '000725.SZ', '601857.SH', '002415.SZ', '601988.SH',
                '600030.SH', '000001.SZ', '601628.SH', '601328.SH', '000625.SZ',
                '600100.SH', '000768.SZ', '600028.SH', '601899.SH', '000100.SZ'
            ]
        
        scan_limit = getattr(C, 'scan_limit', 500)
        max_candidates = getattr(C, 'max_candidates', 50)
        valid_stocks = []
        
        for stock in all_a_stocks[:scan_limit]:
            if _is_chinext_star_bse_or_st(stock):
                continue
            
            try:
                data = C.get_market_data_ex(['close', 'high', 'open', 'low', 'volume'], [stock], end_time=bar_date_str, period='1d', count=25, subscribe=False)
                if stock not in data or len(data[stock]['close']) < 22:
                    continue
                
                closes = list(data[stock]['close'])
                highs = list(data[stock]['high'])
                volumes = list(data[stock].get('volume', []))
                current_close = closes[-1]
                
                # 1. 突破10日新高
                high_10 = max(highs[-11:-1])
                if current_close <= high_10:
                    continue
                
                # 2. 趋势向上
                if len(closes) >= 20:
                    ma_20 = np.mean(closes[-20:])
                    if current_close <= ma_20:
                        continue
                
                # 3. MA多头排列
                if len(closes) >= 20:
                    ma_5 = np.mean(closes[-5:])
                    ma_10 = np.mean(closes[-10:])
                    ma_20 = np.mean(closes[-20:])
                    if not (ma_5 > ma_10 > ma_20):
                        continue
                
                # 4. 量能放大
                if len(volumes) >= 6:
                    today_vol = volumes[-1]
                    avg_vol_5 = np.mean(volumes[-6:-1])
                    if avg_vol_5 > 0:
                        volume_ratio = today_vol / avg_vol_5
                        if volume_ratio < 1.5:
                            continue
                
                # 5. 相对强度筛选（关键新增）
                relative_strength = calculate_relative_strength(C, stock, bar_date_str, 20)
                if relative_strength < 1.2:  # 必须跑赢大盘20%
                    continue
                
                # 6. 市值筛选
                market_cap_ok = check_market_cap_range(C, stock, bar_date_str)
                if not market_cap_ok:
                    continue
                
                valid_stocks.append(stock)
                if len(valid_stocks) >= max_candidates:
                    break
            except Exception:
                continue
        
        selected_stocks = valid_stocks
    except Exception as e:
        print(f"选股异常: {e}")
        selected_stocks = ['600036.SH', '000333.SZ', '601318.SH', '000651.SZ', '600104.SH']
    
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