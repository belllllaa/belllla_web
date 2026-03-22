#coding:gbk
"""
横盘异动突破策略（振幅+波动）
- 过去20交易日（不含今日）横盘区间震荡：
  - 平均振幅有上下限：下限可设（如≥1%）避免死股，上限 ≤5%
  - 价格波动区间 ≤ 15% （看最高和最低价）
  - 今日涨幅>平均振幅*1.3, 今日涨幅 <8%
- 价格大于3元 （放宽条件，原为5元）
- 尾盘买入
- 卖出逻辑：MA3拐头向下 + 最少持有 min_hold_days 个交易日（默认1天，偏高频）+ 止损
- 最多持有10只股票，每只10000元
- 非ST股（剔除ST/创业板/科创板/北交所）
- 持仓时间按【交易日】统计（用 barpos 差值）
- 截面选股：在通过横盘+突破的候选中，按规模因子（市值最小）排序，取前 N 只买入（可关闭改用先到先得）
- 冷却：单日最多买 max_buy_per_day 只，买入后冷却 cooldown_days 天
- 大盘过滤：中证1000 指数收盘价 < MA5 时当日不开仓
"""

import numpy as np
import time

def init(C):
    C.accountid = getattr(C, 'accountid', '')
    C.max_stocks = 10
    C.per_stock_amount = 100000
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.buy_barpos = {}   # 买入时的 K 线索引，用于按【交易日】计算持仓天数
    C.min_hold_days = getattr(C, 'min_hold_days', 1)   # 最少持有几天才允许MA3/破线出场，1=偏高频
    # 截面选股：'market_cap'=按市值最小取前N只，None 或 ''=按遍历顺序先到先得
    C.sort_by_factor = getattr(C, 'sort_by_factor', 'market_cap')
    # 平均振幅下限：避免几乎不波动的死股，保证「今日涨幅>平均振幅*1.3」有实际意义。设为 0 表示不设下限
    C.amp_min = getattr(C, 'amp_min', 0.01)
    # 单日最多买几只；买入后冷却几天（次日不买）。max_buy_per_day 设为 0 表示不限制
    C.max_buy_per_day = getattr(C, 'max_buy_per_day', 5)
    C.cooldown_days = getattr(C, 'cooldown_days', 1)
    C.last_buy_barpos = -999
    print('横盘突破策略（简化版-优化版）初始化完成')


def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]

    # 获取股票池 - （组合指数成分股），这是最可靠的方法
    all_stocks = get_stock_pool_method2_only(C, bar_date_str)

    print(f"[{bar_date_str}] 股票池大小: {len(all_stocks)} 只股票")

    # 卖出逻辑
    for stock in list(C.holding.keys()):
        if not C.holding.get(stock, False):
            continue

        try:
            buy_bar = C.buy_barpos.get(stock, C.barpos)
            # 持仓天数 = 当前 bar 索引 - 买入时 bar 索引（按【交易日】计算）
            days_held = max(0, C.barpos - buy_bar)
            in_min_hold = days_held < getattr(C, 'min_hold_days', 1)

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
            if total_loss < -0.07:
                sell_condition = True
                sell_reason = "总亏损7%止损"
            elif today_current_return < -0.08:
                sell_condition = True
                sell_reason = "大跌"
            elif today_low_return < -0.08 :
                sell_condition = True
                sell_reason = "大跌振幅"
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

                    for key in [C.buy_price, C.buy_shares, C.buy_date, C.buy_barpos]:
                        if stock in key:
                            del key[stock]
                    C.draw_text(1, 1, '卖')

        except Exception as e:
            print(f"卖出异常 {stock}: {e}")

    # 买入逻辑：先收集所有通过横盘+突破的候选，再按截面因子（市值最小）排序取前 N 只
    # 中证1000 收盘价 < MA5 时不开仓
    if not _csi1000_above_ma5(C, bar_date_str):
        pass  # 本日不开仓，跳过下方买入
    else:
        current_holdings = sum(1 for h in C.holding.values() if h)
        last_buy_bar = getattr(C, 'last_buy_barpos', -999)
        in_cooldown = last_buy_bar >= 0 and (C.barpos - last_buy_bar) <= getattr(C, 'cooldown_days', 1)
        if current_holdings < C.max_stocks and not in_cooldown:
            total_stocks = min(3500, len(all_stocks))
            passed_sector_filter = 0
            passed_data_filter = 0
            passed_price_filter = 0
            passed_sideways_filter = 0
            passed_breakout_filter = 0
            candidates = []   # (stock, current_close, sort_value) 用于截面排序

            for stock in all_stocks[:total_stocks]:
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

                    if current_close <= 0 or today_open <= 0:
                        continue
                    if current_close <= 3.0:
                        continue
                    passed_price_filter += 1

                    avg_amplitude, price_range = calculate_sideways_metrics(highs, lows, closes, 20)
                    amp_min = getattr(C, 'amp_min', 0)
                    if (amp_min <= avg_amplitude <= 0.05) and price_range <= 1.15:
                        passed_sideways_filter += 1
                        today_return = (current_close - today_open) / today_open
                        if today_return > avg_amplitude * 1.3 and today_return < 0.08:
                            passed_breakout_filter += 1
                            sort_value = _get_sort_value(C, stock, current_close)
                            candidates.append((stock, current_close, sort_value))

                except Exception as e:
                    print(f"买入异常 {stock}: {e}")

            sort_by = getattr(C, 'sort_by_factor', 'market_cap')
            if sort_by == 'market_cap' and candidates:
                candidates.sort(key=lambda x: x[2])
            max_per_day = getattr(C, 'max_buy_per_day', 0)
            cap = C.max_stocks - current_holdings
            if max_per_day > 0:
                cap = min(cap, max_per_day)
            need_buy = min(cap, len(candidates))
            final_selected = 0

            for i in range(need_buy):
                stock, current_close, _ = candidates[i]
                target_shares = int(C.per_stock_amount / current_close)
                shares = (target_shares // 100) * 100
                if shares < 100 or shares > 10000:
                    continue
                passorder(23, 1101, C.accountid, stock, 5, 0, shares, "横盘突破", 1, "", C)
                C.holding[stock] = True
                C.buy_price[stock] = current_close
                C.buy_shares[stock] = shares
                C.buy_date[stock] = current_date_str
                C.buy_barpos[stock] = C.barpos
                C.last_buy_barpos = C.barpos
                print(f"{bar_date_str} 买入 {stock} {shares}股 @ {current_close:.3f} 横盘突破")
                C.draw_text(1, 1, '买')
                final_selected += 1

            print(f"[{bar_date_str}] 筛选统计:")
            print(f"  总分析股票: {total_stocks}  通过板块: {passed_sector_filter}  数据: {passed_data_filter}  价格>3: {passed_price_filter}  横盘: {passed_sideways_filter}  突破: {passed_breakout_filter}  候选数: {len(candidates)}  实际买入: {final_selected}")

def calculate_sideways_metrics(highs, lows, closes, period=20):
    """计算横盘指标：平均振幅和价格波动区间"""
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return float('inf'), float('inf')

    # 计算前period日的平均振幅（不包含最后一天）
    amplitude_sum = 0
    valid_days = 0
    for i in range(len(closes) - period - 1, len(closes) - 1):
        if closes[i] > 0:
            high_low_diff = highs[i+1] - lows[i+1]
            amplitude = high_low_diff / closes[i]
            amplitude_sum += amplitude
            valid_days += 1

    if valid_days == 0:
        avg_amplitude = float('inf')
    else:
        avg_amplitude = amplitude_sum / valid_days

    # 计算前period日的价格波动区间（不包含最后一天）
    recent_highs = highs[-period-1:-1]
    recent_lows = lows[-period-1:-1]

    if recent_highs and recent_lows:
        period_high = max(recent_highs)
        period_low = min(recent_lows)
        if period_low > 0:
            price_range = period_high / period_low
        else:
            price_range = float('inf')
    else:
        price_range = float('inf')

    return avg_amplitude, price_range

def get_stock_pool_method2_only(C, current_date_str):
    """获取股票池 - （组合指数成分股），这是最可靠的方法"""
    all_stocks = []

    try:
        # 组合多个指数成分股（最可靠的方法）
        index_stocks = []
        indices = ['000905.SH', '000852.SH']

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
            print(f"成功: 组合指数成分股 {len(all_stocks)} 只")
            return all_stocks
    except Exception as e:
        print(f"组合指数成分股失败: {e}")

    return all_stocks

def _is_three_consecutive_down(closes):
    """买入前三天（不含当日）是否连跌三天：前1日、前2日、前3日每日收盘均低于前一交易日收盘。"""
    if len(closes) < 6:
        return False
    down1 = closes[-2] < closes[-3]
    down2 = closes[-3] < closes[-4]
    down3 = closes[-4] < closes[-5]
    return down1 and down2 and down3

def _csi1000_above_ma5(C, bar_date_str):
    """中证1000(000852.SH) 收盘价 >= MA5 时返回 True，可开仓；否则 False，不开仓。数据不足时返回 True 避免误拦。"""
    try:
        data = C.get_market_data_ex(['close'], ['000852.SH'], end_time=bar_date_str, period='1d', count=10, subscribe=False)
        if not data or '000852.SH' not in data or len(data['000852.SH']['close']) < 5:
            return True
        closes = list(data['000852.SH']['close'])
        ma5 = np.mean(closes[-5:])
        return float(closes[-1]) >= ma5
    except Exception:
        return True


def _get_sort_value(C, stock_code, current_close):
    """截面选股用的排序值：规模因子=市值，越小越优先买入。用 get_total_share 取总股数，市值=收盘价*总股数；失败时用收盘价近似。"""
    sort_by = getattr(C, 'sort_by_factor', 'market_cap')
    if sort_by != 'market_cap':
        return 0
    try:
        if hasattr(C, 'get_total_share'):
            total_share = C.get_total_share(stock_code)
            if total_share is not None and total_share > 0 and current_close and current_close > 0:
                return float(current_close) * float(total_share)
    except Exception:
        pass
    return float(current_close)

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
