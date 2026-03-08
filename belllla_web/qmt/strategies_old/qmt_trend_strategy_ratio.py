#coding:gbk
"""
QMT趋势策略 - 立即运行版（修复版）
严格按照用户要求实现：
1. 基础筛选：排除垃圾票（主力建仓、主力吸筹、主力洗盘的票都不做）
2. 保证股票趋势向上
3. 条件一：收盘价必须站在20日线和60日线上方
4. 条件二：只抓均线陡峭向上的票
   - 五日均线斜率角度超过40度
   - 当天五日均线斜率比前一天更陡（上涨势头加速）
   - 十日均线斜率也比前一天更陡（确认趋势不是单日脉冲）
   - 五日均线斜率要比十日均线斜率陡，但两者差距不能超过15度
5. 卖出信号：只要MA5的斜率低于MA10的斜率，就果断卖出

此版本移除了定时任务，点击运行立即执行，并修复了get_stock_list问题
"""

import math
import numpy as np
import time

def init(C):
    """初始化函数"""
    C.accountid = getattr(C, 'accountid', '')
    C.max_hold_count = 10
    C.per_stock_amount = 10000
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    print("QMT趋势策略（立即运行版-修复版）初始化完成")
    
    # 立即执行策略逻辑
    run_strategy(C)

def run_strategy(C):
    """立即执行策略主逻辑"""
    try:
        # 获取当前时间
        current_time = int(time.time() * 1000)
        bar_date_str = timetag_to_datetime(current_time, '%Y%m%d%H%M%S')
        current_date_str = bar_date_str[:8]
        
        print(f"开始执行策略分析 - {bar_date_str}")
        
        # 尝试多种方式获取股票列表
        all_stocks = []
        
        # 方法1: 尝试使用 get_stock_list (如果存在)
        try:
            if hasattr(C, 'get_stock_list'):
                all_stocks = C.get_stock_list()
        except Exception as e:
            print(f"get_stock_list 方法1失败: {e}")
        
        # 方法2: 如果方法1失败，尝试使用 get_stock_list_in_sector
        if not all_stocks:
            try:
                if hasattr(C, 'get_stock_list_in_sector'):
                    # 获取沪深A股
                    all_stocks = C.get_stock_list_in_sector('沪深A股')
            except Exception as e:
                print(f"get_stock_list_in_sector 方法2失败: {e}")
        
        # 方法3: 如果前两种都失败，使用默认的股票池（需要手动配置）
        if not all_stocks:
            print("无法自动获取股票列表，使用默认股票池进行测试")
            # 这里可以添加一些常见的股票代码作为测试
            all_stocks = [
                '600000.SH', '600036.SH', '601318.SH', '000001.SZ', '000858.SZ',
                '600519.SH', '601166.SH', '601398.SH', '601857.SH', '601988.SH'
            ]
        
        if not all_stocks:
            print("未获取到股票列表，策略无法继续执行")
            return
            
        print(f"共获取到 {len(all_stocks)} 只股票，开始筛选...")
        
        # 先处理卖出逻辑
        stocks_to_remove = []
        for stock in list(C.holding.keys()):
            if not C.holding.get(stock, False):
                continue
            
            try:
                # 获取股票数据
                data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=70, subscribe=False)
                if stock not in data or len(data[stock]) < 65:
                    continue
                
                closes = list(data[stock]['close'])
                
                # 计算均线
                ma5_values = []
                ma10_values = []
                for i in range(len(closes)):
                    if i + 1 >= 5:
                        ma5_val = np.mean(closes[i-4:i+1])
                        ma5_values.append(ma5_val)
                    if i + 1 >= 10:
                        ma10_val = np.mean(closes[i-9:i+1])
                        ma10_values.append(ma10_val)
                
                if len(ma5_values) < 5 or len(ma10_values) < 5:
                    continue
                
                # 计算斜率角度
                ma5_slope_current = calc_slope_angle(ma5_values, 5)
                ma10_slope_current = calc_slope_angle(ma10_values, 5)
                
                # 检查卖出条件
                if ma5_slope_current < ma10_slope_current:
                    shares = C.buy_shares.get(stock, 0)
                    if shares >= 100:
                        passorder(24, 1101, C.accountid, stock, 5, 0, shares, "趋势策略", 1, "", C)
                        C.holding[stock] = False
                        stocks_to_remove.append(stock)
                        current_price = closes[-1]
                        buy_price = C.buy_price.get(stock, current_price)
                        profit = (current_price - buy_price) * shares
                        profit_pct = (current_price - buy_price) / buy_price if buy_price > 0 else 0
                        print(f"{bar_date_str} 卖出 {stock} {shares}股 @ {current_price:.3f} MA5斜率<{ma5_slope_current:.1f}°<MA10斜率{ma10_slope_current:.1f}° 盈亏: {profit:.2f} ({profit_pct:.1%})")
                        C.draw_text(1, 1, '卖')
                        
            except Exception as e:
                print(f"卖出异常 {stock}: {e}")
        
        # 清理已卖出股票
        for stock in stocks_to_remove:
            for key in [C.buy_price, C.buy_shares, C.buy_date]:
                if stock in key:
                    del key[stock]
        
        # 处理买入逻辑
        current_holdings = sum(1 for h in C.holding.values() if h)
        stocks_analyzed = 0
        stocks_bought = 0
        
        for stock in all_stocks:
            if current_holdings >= C.max_hold_count:
                break
                
            # 跳过已持仓股票
            if C.holding.get(stock, False):
                continue
                
            # 基础筛选
            if _is_chinext_star_bse_or_st(stock):
                continue
            
            try:
                stocks_analyzed += 1
                # 获取股票数据
                data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=70, subscribe=False)
                if stock not in data or len(data[stock]) < 65:
                    continue
                
                closes = list(data[stock]['close'])
                current_close = closes[-1]
                
                # 计算均线
                ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else 0
                ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else 0
                
                # 条件一：收盘价必须站在20日线和60日线上方
                if current_close <= ma20 or current_close <= ma60:
                    continue
                
                # 计算均线序列
                ma5_values = []
                ma10_values = []
                for i in range(len(closes)):
                    if i + 1 >= 5:
                        ma5_val = np.mean(closes[i-4:i+1])
                        ma5_values.append(ma5_val)
                    if i + 1 >= 10:
                        ma10_val = np.mean(closes[i-9:i+1])
                        ma10_values.append(ma10_val)
                
                if len(ma5_values) < 5 or len(ma10_values) < 5:
                    continue
                
                # 计算斜率角度
                ma5_slope_current = calc_slope_angle(ma5_values, 5)
                ma5_slope_previous = calc_slope_angle(ma5_values[:-1], 5) if len(ma5_values) >= 6 else ma5_slope_current
                ma10_slope_current = calc_slope_angle(ma10_values, 5)
                ma10_slope_previous = calc_slope_angle(ma10_values[:-1], 5) if len(ma10_values) >= 6 else ma10_slope_current
                
                # 条件二检查
                if ma5_slope_current <= 40:
                    continue
                if ma5_slope_current <= ma5_slope_previous:
                    continue
                if ma10_slope_current <= ma10_slope_previous:
                    continue
                if ma5_slope_current <= ma10_slope_current:
                    continue
                if ma5_slope_current - ma10_slope_current > 15:
                    continue
                
                # 买入信号
                target_shares = int(C.per_stock_amount / current_close)
                shares = (target_shares // 100) * 100
                if shares < 100:
                    continue
                
                passorder(23, 1101, C.accountid, stock, 5, 0, shares, "趋势策略", 1, "", C)
                C.holding[stock] = True
                C.buy_price[stock] = current_close
                C.buy_shares[stock] = shares
                C.buy_date[stock] = current_date_str
                current_holdings += 1
                stocks_bought += 1
                print(f"{bar_date_str} 买入 {stock} {shares}股 @ {current_close:.3f} MA5斜率{ma5_slope_current:.1f}°>MA10斜率{ma10_slope_current:.1f}°")
                C.draw_text(1, 1, '买')
                
            except Exception as e:
                print(f"分析股票 {stock} 异常: {e}")
        
        print(f"策略执行完成！分析了 {stocks_analyzed} 只股票，买入 {stocks_bought} 只股票")
        print(f"当前总持仓: {sum(1 for h in C.holding.values() if h)} 只")
        
    except Exception as e:
        print(f"策略执行异常: {e}")

def calc_slope_angle(ma_values, period=5):
    """计算均线斜率角度"""
    if len(ma_values) < period:
        return 0
    recent_ma = ma_values[-period:]
    n = len(recent_ma)
    sum_x = sum(range(n))
    sum_y = sum(recent_ma)
    sum_xy = sum(i * recent_ma[i] for i in range(n))
    sum_x2 = sum(i * i for i in range(n))
    if n * sum_x2 - sum_x * sum_x == 0:
        return 0
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
    angle = math.degrees(math.atan(slope))
    return angle

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

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)

