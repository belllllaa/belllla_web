#coding:gbk
"""
QMT强势趋势轮动策略（只做多）
- 只做多中期、短期同时强势的趋势股
- 方案A：用多周期动量 + 量能综合打分，择优买入
- 方案C：单日最多买入若干只 + 冷却期控制频率
- 卖出：短期动量转弱 / 止损 / 持有1~5天轮动出场
- 回撤/胜率过滤：60日涨幅上限、日波动率上限、近20日正收益天数占比（文献常用）
"""

# QMT 内置下单函数，回测/实盘时由运行环境注入；仅用于静态检查，避免 reportUndefinedVariable
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    def passorder(*args, **kwargs): ...

import numpy as np
import time
from datetime import datetime

def trading_days_diff(date_start, date_end):
    """计算两个日期之间的自然日天数差"""
    try:
        d1 = datetime.strptime(str(date_start), '%Y%m%d')
        d2 = datetime.strptime(str(date_end), '%Y%m%d')
        return max(0, (d2 - d1).days)
    except Exception:
        return 0

def init(C):
    """初始化函数"""
    C.accountid = getattr(C, 'accountid', '')
    C.max_hold_count = 10           # 最多同时持有10只
    C.per_stock_amount = 100000
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.buy_barpos = {}               # 记录买入时的bar索引，用于按交易日计数
    C.sell_date = {}  # 方案C：记录卖出日期，用于冷却期
    # 多周期动量参数（趋势强势过滤）
    C.trend_short_period = 5        # 短期动量周期（近5日）
    C.trend_mid_period = 20         # 中期动量周期（近20日）
    C.long_period = 60              # 长期趋势观察周期（近60日）
    C.short_mom_min = 0.02          # 近5日涨幅至少2%
    C.mid_mom_min = 0.08            # 近20日涨幅至少8%
    C.long_mom_min = 0.12           # 近60日涨幅至少12%
    C.long_mom_max = 0.45          # 近60日涨幅上限45%，避免追已过度延伸的票（压低回撤）
    C.daily_vol_max = 0.050        # 近20日日收益波动率上限5%，过滤情绪化高波动标的
    C.positive_days_ratio_min = 0.50  # 近20日中至少50%为正收益日，过滤震荡/阴跌（提高胜率）
    # 持股时间与退出条件：博1~2天轮动
    C.min_hold_days = 1             # 最少持有1天
    C.max_hold_days = 5             # 最多持有5天，主打短线轮动
    C.stop_loss_pct = -0.04         # 单笔止损 -4%，快速止损
    # 方案A：综合得分权重（只用多周期动量 + 量能）
    C.score_w_short = 0.4           # 短期动量权重
    C.score_w_mid = 0.35            # 中期动量权重
    C.score_w_long = 0.15           # 长期动量权重
    C.score_w_volume = 0.10         # 量能权重
    # 方案C：容量控制（提高出手频率）
    C.max_buy_per_day = 5           # 单日最多买5只，提高建仓速度
    C.cooldown_days = 1             # 冷却1日，允许更快重新入场
    print("QMT强势趋势轮动策略初始化完成")

def handlebar(C):
    """日线回调函数 - 所有买卖逻辑都在这里"""
    try:
        # 获取当前回测日期
        current_timetag = C.get_bar_timetag(C.barpos)
        current_date_str = timetag_to_datetime(current_timetag, '%Y%m%d')
        current_datetime_str = timetag_to_datetime(current_timetag, '%Y%m%d%H%M%S')
        
        print(f"[{current_datetime_str}] 开始执行动量与反转组合策略分析")
        
        # 获取股票池
        all_stocks = get_stock_pool_method2_only(C, current_datetime_str)
        print(f"[{current_datetime_str}] 股票池大小: {len(all_stocks)} 只股票")
        
        # 先处理卖出逻辑（短线趋势轮动：止损 + 动量转弱 + 到期）
        stocks_to_remove = []
        for stock in list(C.holding.keys()):
            if not C.holding.get(stock, False):
                continue
            
            try:
                # 获取股票数据（需足够长度覆盖长期周期）
                data = C.get_market_data_ex(['close'], [stock], end_time=current_datetime_str, period='1d', count=max(70, C.long_period + 10), subscribe=False)
                if stock not in data or len(data[stock]) < C.trend_short_period + 2:
                    continue
                
                closes = list(data[stock]['close'])
                current_close = closes[-1]
                yesterday_close = closes[-2] if len(closes) >= 2 else current_close
                buy_price = C.buy_price.get(stock, current_close)
                buy_date = C.buy_date.get(stock, current_date_str)
                buy_bar = C.buy_barpos.get(stock, C.barpos)
                # 用bar索引差值表示持有的“交易日”数量（包含买入当日）
                days_held = max(0, C.barpos - buy_bar)
                profit_pct = (current_close - buy_price) / buy_price if buy_price > 0 else 0
                shares = C.buy_shares.get(stock, 0)
                
                # 计算短期均线，用于判断动量是否转弱
                short_ma = np.mean(closes[-C.trend_short_period:]) if len(closes) >= C.trend_short_period else np.mean(closes)
                
                sell_reason = ""
                should_sell = False
                # ① 止损：单笔亏损达到阈值（不受最小持有限制）
                if profit_pct <= C.stop_loss_pct:
                    sell_reason = f"止损({profit_pct:.1%})"
                    should_sell = True
                # ② 短期动量转弱：已过最小持有期，且收盘价跌破昨日收盘或短期均线
                elif days_held >= C.min_hold_days and (current_close < yesterday_close or current_close < short_ma):
                    sell_reason = f"短期动量转弱 持有{days_held}天"
                    should_sell = True
                # ③ 到期：持有超过最大天数，做轮动出场
                elif days_held >= C.max_hold_days:
                    sell_reason = f"持有{days_held}天到期"
                    should_sell = True
                
                if should_sell and shares >= 100:
                    passorder(24, 1101, C.accountid, stock, 5, 0, shares, "动量反转", 1, "", C)
                    C.holding[stock] = False
                    C.sell_date[stock] = current_date_str
                    stocks_to_remove.append(stock)
                    profit = (current_close - buy_price) * shares
                    print(f"{current_datetime_str} 卖出 {stock} {shares}股 @ {current_close:.3f} {sell_reason} 盈亏: {profit:.2f} ({profit_pct:.1%})")
                        
            except Exception as e:
                print(f"{current_datetime_str} 卖出异常 {stock}: {e}")
        
        # 清理已卖出股票
        for stock in stocks_to_remove:
            for key in [C.buy_price, C.buy_shares, C.buy_date, C.buy_barpos]:
                if stock in key:
                    del key[stock]
        
        # 处理买入逻辑：方案A多周期动量打分 + 方案C容量控制
        current_holdings = sum(1 for h in C.holding.values() if h)
        total_stocks = min(3500, len(all_stocks))
        required_data_length = max(C.trend_short_period, C.long_period) + 15
        
        # 第一轮：收集所有通过条件的候选股及原始因子值
        candidates = []
        passed_sector_filter = 0
        passed_data_filter = 0
        passed_short_mom = 0
        passed_mid_mom = 0
        passed_long_mom = 0
        
        for stock in all_stocks[:total_stocks]:
            if C.holding.get(stock, False):
                continue
            if is_chinext_star_bse_or_st(C, stock):
                continue
            passed_sector_filter += 1
            
            try:
                # 增加 high/low 用于识别一字板
                data = C.get_market_data_ex(['close', 'volume', 'high', 'low'], [stock], end_time=current_datetime_str, period='1d', count=required_data_length, subscribe=False)
                if stock not in data or len(data[stock]['close']) < required_data_length:
                    continue
                passed_data_filter += 1

                closes = list(data[stock]['close'])
                volumes = list(data[stock].get('volume', []))
                highs = list(data[stock].get('high', []))
                lows = list(data[stock].get('low', []))
                current_close = closes[-1]
                if current_close <= 0:
                    continue
                
                # 1. 多周期趋势动量（只做强势趋势股）
                if len(closes) <= max(C.trend_short_period, C.trend_mid_period, C.long_period):
                    continue
                short_ret = closes[-1] / closes[-C.trend_short_period] - 1 if closes[-C.trend_short_period] > 0 else 0
                mid_ret = closes[-1] / closes[-C.trend_mid_period] - 1 if closes[-C.trend_mid_period] > 0 else 0
                long_ret = closes[-1] / closes[-C.long_period] - 1 if closes[-C.long_period] > 0 else 0

                # 一字板过滤：当日接近涨停且高低价几乎不动，实盘很难买入
                if len(highs) == len(closes) and len(lows) == len(closes) and len(closes) >= 2:
                    prev_close = closes[-2]
                    if prev_close > 0:
                        day_ret = closes[-1] / prev_close - 1
                        spread = (highs[-1] - lows[-1]) / prev_close if prev_close > 0 else 0
                        # 涨幅>=9.5%，且日内振幅<0.5%，视为一字涨停，直接剔除
                        if day_ret >= 0.095 and spread <= 0.005:
                            continue

                if short_ret < C.short_mom_min:
                    continue
                passed_short_mom += 1
                if mid_ret < C.mid_mom_min:
                    continue
                passed_mid_mom += 1
                if long_ret < C.long_mom_min:
                    continue
                passed_long_mom += 1
                # 涨幅上限：60日已涨太多易回撤，剔除（降低回撤、提高胜率；文献常用排除过度延伸）
                if long_ret > getattr(C, 'long_mom_max', 0.45):
                    continue
                # 波动率 + 正收益天数占比：近20日日收益序列
                if len(closes) >= 21:
                    rets_20 = []
                    for i in range(-19, 0):
                        if closes[i - 1] and closes[i - 1] > 0:
                            rets_20.append(closes[i] / closes[i - 1] - 1)
                    if len(rets_20) >= 15:
                        vol_20 = float(np.std(rets_20))
                        if vol_20 > getattr(C, 'daily_vol_max', 0.05):
                            continue
                        # 正收益天数占比：近20日中至少一半为正收益日，过滤震荡/阴跌（提高胜率）
                        positive_ratio = sum(1 for r in rets_20 if r > 0) / len(rets_20)
                        if positive_ratio < getattr(C, 'positive_days_ratio_min', 0.50):
                            continue

                # 2. 成交量确认
                if len(volumes) >= 6:
                    vol_5_avg = np.mean(volumes[-6:-1])
                    current_vol = volumes[-1]
                    if vol_5_avg > 0 and current_vol < vol_5_avg * 0.7:
                        continue
                    vol_ratio = current_vol / vol_5_avg
                else:
                    vol_ratio = 1.0
                
                # 每只最多 per_stock_amount 元，按100股整数倍计算可买股数
                target_shares = int(C.per_stock_amount / current_close)
                shares = (target_shares // 100) * 100
                if shares < 100:
                    continue
                
                # 方案A：收集候选及原始因子（多周期动量 + 量能）
                candidates.append({
                    'stock': stock,
                    'short_ret': short_ret,
                    'mid_ret': mid_ret,
                    'long_ret': long_ret,
                    'vol_ratio': vol_ratio,
                    'shares': shares,
                    'current_close': current_close,
                })
                
            except Exception as e:
                pass
        
        # 方案A：综合得分排序
        final_bought = 0
        if candidates and current_holdings < C.max_hold_count:
            short_vals = [c['short_ret'] for c in candidates]
            mid_vals = [c['mid_ret'] for c in candidates]
            long_vals = [c['long_ret'] for c in candidates]
            vol_vals = [c['vol_ratio'] for c in candidates]
            
            short_min, short_max = min(short_vals), max(short_vals)
            mid_min, mid_max = min(mid_vals), max(mid_vals)
            long_min, long_max = min(long_vals), max(long_vals)
            vol_min, vol_max = min(vol_vals), max(vol_vals)
            
            def _norm(v, vmin, vmax):
                if vmax <= vmin:
                    return 0.5
                return (v - vmin) / (vmax - vmin)
            
            for c in candidates:
                s_short = _norm(c['short_ret'], short_min, short_max)
                s_mid = _norm(c['mid_ret'], mid_min, mid_max)
                s_long = _norm(c['long_ret'], long_min, long_max)
                s_vol = _norm(c['vol_ratio'], vol_min, vol_max)
                c['score'] = (
                    C.score_w_short * s_short +
                    C.score_w_mid * s_mid +
                    C.score_w_long * s_long +
                    C.score_w_volume * s_vol
                )
            
            candidates.sort(key=lambda x: x['score'], reverse=True)
            
            # 方案C：单日最多买N只 + 冷却期
            bought_today = 0
            for c in candidates:
                if current_holdings >= C.max_hold_count or bought_today >= C.max_buy_per_day:
                    break
                stock = c['stock']
                # 冷却期：卖出后N日内不重复买入
                if stock in C.sell_date:
                    days_since_sell = trading_days_diff(C.sell_date[stock], current_date_str)
                    if days_since_sell < C.cooldown_days:
                        continue
                
                passorder(23, 1101, C.accountid, stock, 5, 0, c['shares'], "动量反转", 1, "", C)
                C.holding[stock] = True
                C.buy_price[stock] = c['current_close']
                C.buy_shares[stock] = c['shares']
                C.buy_date[stock] = current_date_str
                C.buy_barpos[stock] = C.barpos
                current_holdings += 1
                final_bought += 1
                bought_today += 1
                print(f"{current_datetime_str} 买入 {stock} {c['shares']}股 @ {c['current_close']:.3f} 得分:{c['score']:.3f} 短动量:{c['short_ret']*100:.1f}% 中动量:{c['mid_ret']*100:.1f}% 长动量:{c['long_ret']*100:.1f}%")
        
        # 打印筛选统计
        print(f"{current_datetime_str} 筛选统计:")
        print(f"  总分析股票: {total_stocks} 候选池: {len(candidates)} 通过短期动量:{passed_short_mom} 通过中期动量:{passed_mid_mom} 通过长期动量:{passed_long_mom}")
        print(f"  方案C: 单日最多买{C.max_buy_per_day}只 冷却{C.cooldown_days}天 实际买入:{final_bought}")
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
