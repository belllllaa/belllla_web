#coding:gbk
"""
QMT均值回归策略（只做多）- 方案B：Z-score回升确认 + 止损止盈 + 趋势过滤
基于数学统计学的均值回归策略，核心逻辑：
- 计算N日移动平均线和标准差
- 买入条件：
  ① 昨日 Z-score < -1.5（超卖）
  ② 今日 Z-score > 昨日 Z-score 且 回升幅度 >= 0.2（避免假反弹）
  ③ 今日 Z-score 仍 < -0.5（未完全回归，仍有空间）
  ④ 股价 > MA60 且 MA20 > MA60（只做上升趋势中的回调，绝不接飞刀）
  ⑤ 成交量确认
- 卖出：止损 -6% / 止盈 Z>=0 / 持有满 max_hold_days 天
"""

import numpy as np
import time
from datetime import datetime

def trading_days_diff(date_start, date_end):
    """计算两个日期之间的自然日天数差（用于持有天数判断）"""
    try:
        d1 = datetime.strptime(str(date_start), '%Y%m%d')
        d2 = datetime.strptime(str(date_end), '%Y%m%d')
        return max(0, (d2 - d1).days)
    except Exception:
        return 0

def init(C):
    """初始化函数"""
    C.accountid = getattr(C, 'accountid', '')
    C.max_hold_count = 10
    C.per_stock_amount = 10000
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    # 均值回归参数
    C.ma_period = 20          # 移动平均周期
    C.ma_trend_period = 60    # 趋势判断用 MA60
    # Z-score 回升确认参数
    C.z_score_yesterday_max = -1.5   # 昨日需超卖（Z < -1.5）
    C.z_score_today_min = -0.5       # 今日仍有空间（Z < -0.5，未完全回归）
    C.z_score_rebound_min = 0.2     # 今日Z必须比昨日至少回升0.2（过滤假反弹）
    C.max_hold_days = 8             # 最大持有天数（延长给回归更多时间）
    C.stop_loss_pct = -0.06         # 单笔止损 -6%
    C.profit_target_z = 0.0         # Z-score 回归到 0 时止盈
    print("QMT均值回归策略（方案B 止损止盈+趋势过滤）初始化完成")

def handlebar(C):
    """日线回调函数 - 所有买卖逻辑都在这里"""
    try:
        # 获取当前回测日期
        current_timetag = C.get_bar_timetag(C.barpos)
        current_date_str = timetag_to_datetime(current_timetag, '%Y%m%d')
        current_datetime_str = timetag_to_datetime(current_timetag, '%Y%m%d%H%M%S')
        
        print(f"[{current_datetime_str}] 开始执行均值回归策略分析")
        
        # 获取股票池
        all_stocks = get_stock_pool_method2_only(C, current_datetime_str)
        print(f"[{current_datetime_str}] 股票池大小: {len(all_stocks)} 只股票")
        
        # 先处理卖出逻辑（止损 / 止盈 / 到期）
        stocks_to_remove = []
        for stock in list(C.holding.keys()):
            if not C.holding.get(stock, False):
                continue
            
            try:
                # 获取股票数据（需要足够长度计算 Z-score 和 MA60）
                data = C.get_market_data_ex(['close'], [stock], end_time=current_datetime_str, period='1d', count=max(65, C.ma_trend_period + 10), subscribe=False)
                if stock not in data or len(data[stock]) < 10:
                    continue
                
                closes = list(data[stock]['close'])
                current_close = closes[-1]
                buy_price = C.buy_price.get(stock, current_close)
                buy_date = C.buy_date.get(stock, current_date_str)
                
                # 计算持有天数
                days_held = trading_days_diff(buy_date, current_date_str)
                
                # 计算当前 Z-score（用于止盈判断）
                ma_period = C.ma_period
                ma_today = np.mean(closes[-ma_period:])
                std_today = np.std(closes[-ma_period:])
                z_score_today = (current_close - ma_today) / std_today if std_today > 0 else 0
                
                profit_pct = (current_close - buy_price) / buy_price if buy_price > 0 else 0
                shares = C.buy_shares.get(stock, 0)
                sell_reason = ""
                should_sell = False
                
                # ① 止损：单笔亏损达到阈值
                if profit_pct <= C.stop_loss_pct:
                    sell_reason = f"止损({profit_pct:.1%})"
                    should_sell = True
                # ② 止盈：Z-score 已回归到 0 或以上
                elif z_score_today >= C.profit_target_z:
                    sell_reason = f"止盈(Z={z_score_today:.2f})"
                    should_sell = True
                # ③ 到期：持有超过最大天数
                elif days_held >= C.max_hold_days:
                    sell_reason = f"持有{days_held}天到期"
                    should_sell = True
                
                if should_sell and shares >= 100:
                    passorder(24, 1101, C.accountid, stock, 5, 0, shares, "均值回归", 1, "", C)
                    C.holding[stock] = False
                    stocks_to_remove.append(stock)
                    profit = (current_close - buy_price) * shares
                    print(f"{current_datetime_str} 卖出 {stock} {shares}股 @ {current_close:.3f} {sell_reason} 盈亏: {profit:.2f} ({profit_pct:.1%})")
                        
            except Exception as e:
                print(f"{current_datetime_str} 卖出异常 {stock}: {e}")
        
        # 清理已卖出股票
        for stock in stocks_to_remove:
            for key in [C.buy_price, C.buy_shares, C.buy_date]:
                if stock in key:
                    del key[stock]
        
        # 处理买入逻辑
        current_holdings = sum(1 for h in C.holding.values() if h)
        total_stocks = min(3500, len(all_stocks))
        passed_sector_filter = 0
        passed_data_filter = 0
        passed_mean_reversion = 0
        passed_trend_filter = 0
        passed_volume_confirm = 0
        final_bought = 0
        
        for stock in all_stocks[:total_stocks]:
            if current_holdings >= C.max_hold_count:
                break
                
            # 跳过已持仓股票
            if C.holding.get(stock, False):
                continue
                
            # 基础筛选：剔除ST/创业板/科创板/北交所
            if is_chinext_star_bse_or_st(C, stock):
                continue
            passed_sector_filter += 1
            
            try:
                # 获取股票数据（需要 ma_trend_period+5 用于 MA60 趋势过滤）
                required_len = max(C.ma_period + 15, C.ma_trend_period + 5)
                data = C.get_market_data_ex(['close', 'volume'], [stock], end_time=current_datetime_str, period='1d', count=required_len, subscribe=False)
                if stock not in data or len(data[stock]['close']) < required_len:
                    continue
                passed_data_filter += 1
                
                closes = list(data[stock]['close'])
                volumes = list(data[stock].get('volume', []))
                current_close = closes[-1]
                
                if current_close <= 0:
                    continue
                
                ma_period = C.ma_period
                
                # 今日Z-score：基于 closes[-ma_period:]
                ma_today = np.mean(closes[-ma_period:])
                std_today = np.std(closes[-ma_period:])
                z_score_today = (current_close - ma_today) / std_today if std_today > 0 else 0
                
                # 昨日Z-score：基于 closes[-ma_period-1:-1]（不含今日）
                closes_yesterday = closes[-ma_period-1:-1]
                yesterday_close = closes[-2]
                ma_yesterday = np.mean(closes_yesterday)
                std_yesterday = np.std(closes_yesterday)
                z_score_yesterday = (yesterday_close - ma_yesterday) / std_yesterday if std_yesterday > 0 else 0
                
                # Z-score 回升确认（加强版）
                # ① 昨日 Z-score < -1.5（超卖）
                # ② 今日 Z-score > 昨日 Z-score 且 回升幅度 >= 0.2（过滤假反弹）
                # ③ 今日 Z-score 仍 < -0.5（未完全回归，仍有空间）
                cond1 = z_score_yesterday < C.z_score_yesterday_max
                z_rebound = z_score_today - z_score_yesterday
                cond2 = z_rebound >= C.z_score_rebound_min
                cond3 = z_score_today < C.z_score_today_min
                mean_reversion_condition = cond1 and cond2 and cond3
                
                if not mean_reversion_condition:
                    continue
                passed_mean_reversion += 1
                
                # 趋势过滤：只做上升趋势中的回调，绝不接飞刀
                # 必须满足：股价 > MA60 且 MA20 > MA60（确保是回调而非下跌半山腰）
                if len(closes) >= C.ma_trend_period:
                    ma60_now = np.mean(closes[-C.ma_trend_period:])
                    ma20_now = ma_today  # 已计算
                    price_above_ma60 = current_close > ma60_now
                    ma20_above_ma60 = ma20_now > ma60_now
                    trend_ok = price_above_ma60 and ma20_above_ma60
                else:
                    trend_ok = False
                if not trend_ok:
                    continue
                passed_trend_filter += 1
                
                # 成交量确认：今日成交量要大于前5日平均成交量的80%
                if len(volumes) >= 6:
                    vol_5_avg = np.mean(volumes[-6:-1])
                    current_vol = volumes[-1]
                    if vol_5_avg > 0 and current_vol < vol_5_avg * 0.8:
                        continue
                passed_volume_confirm += 1
                
                # 买入信号确认
                target_shares = int(C.per_stock_amount / current_close)
                shares = (target_shares // 100) * 100
                if shares < 100:
                    continue
                
                # 执行买入
                passorder(23, 1101, C.accountid, stock, 5, 0, shares, "均值回归", 1, "", C)
                C.holding[stock] = True
                C.buy_price[stock] = current_close
                C.buy_shares[stock] = shares
                C.buy_date[stock] = current_date_str
                current_holdings += 1
                final_bought += 1
                z_change = z_score_today - z_score_yesterday
                print(f"{current_datetime_str} 买入 {stock} {shares}股 @ {current_close:.3f} Z昨日:{z_score_yesterday:.2f} Z今日:{z_score_today:.2f} 回升:{z_change:.2f}")
                
            except Exception as e:
                print(f"{current_datetime_str} 分析股票 {stock} 异常: {e}")
        
        # 打印详细的筛选统计
        print(f"{current_datetime_str} 筛选统计:")
        print(f"  总分析股票: {total_stocks}")
        print(f"  通过板块过滤: {passed_sector_filter}")
        print(f"  通过数据获取: {passed_data_filter}")
        print(f"  通过Z-score回升条件: {passed_mean_reversion}")
        print(f"  通过趋势过滤: {passed_trend_filter}")
        print(f"  通过成交量确认: {passed_volume_confirm}")
        print(f"  实际买入数量: {final_bought}")
        print(f"{current_datetime_str} 当前总持仓: {sum(1 for h in C.holding.values() if h)} 只")
        
    except Exception as e:
        print(f"{current_datetime_str} handlebar异常: {e}")

def get_stock_pool_method2_only(C, current_date_str):
    """获取股票池 - （组合指数成分股）"""
    all_stocks = []
    try:
        index_stocks = []
        indices = ['000001.SH', '399001.SZ', '000300.SH', '000905.SH', '000852.SH']
        
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
            print(f"成功获取股票池: {len(all_stocks)} 只股票")
            return all_stocks
            
    except Exception as e:
        print(f"股票池获取失败: {e}")
    
    return []

def is_chinext_star_bse_or_st(C, stock_code):
    """剔除ST股、创业板、科创板、北交所。ST需通过股票名称判断（代码中无ST）"""
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
    # ST在股票名称中，不在代码中，需用get_stock_name判断
    try:
        name = C.get_stock_name(stock_code)
        if name and ('ST' in name.upper() or '*ST' in name or 'S*ST' in name):
            return True
    except Exception:
        pass
    return False

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)
