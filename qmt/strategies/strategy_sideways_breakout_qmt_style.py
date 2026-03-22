#coding:gbk
"""
横盘异动突破策略 - QMT 官方风格版（类 G + after_init 因子预计算）
- 参考 QMT 官方小市值策略：定义类 G 集中管理变量，after_init 做量价获取与因子计算，handlebar 只读预计算数据并下单
- 因子：横盘（20日振幅/区间）+ 突破（今日涨幅 ∈ (均幅*1.3, 8%)）+ 价格>3 + 前三天不连跌；截面按市值升序取前 N
- 防未来：pass_df / cap_df / close_df 等均 shift(1) 后存 g，handlebar 用当日即已为 T-1 信号
- 卖出：不在 buy_list 则卖 + 规则卖（7%止损、单日大跌、MA3 拐头/破线），最少持有 min_hold_days
- 实盘：以前一交易日为计算起点（涨幅、价格区间、持仓判断），当天早盘以开盘价挂单买入/卖出；总股本用 ContextInfo.get_total_share；时间范围未设置时用最近约半年
"""

import numpy as np
import pandas as pd
import time
from datetime import datetime, timedelta

class G:
    """策略全局状态，方便读取与 after_init 写入"""
    pass

g = G()


def init(C):
    # 账户与下单参数（兼容 accountid / account_id，未设置时使用默认账号）
    g.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or '11219398'
    g.buy_num = 10
    g.per_money = 10000
    g.min_hold_days = 3
    g.amp_min = 0.01
    g.sort_by_factor = getattr(C, 'sort_by_factor', 'market_cap')
    g.his_st = {}
    g.sector_name = getattr(C, 'sector_name', '深证300')  # 股票池板块，回测时可改
    g.s = []   # 股票池，after_init 中用 get_stock_list_in_sector(g.sector_name) 赋值
    # 持仓与买入记录（规则卖需要）
    g.holding = {}
    g.buy_price = {}
    g.buy_shares = {}
    g.buy_date = {}
    g.buy_barpos = {}
    # 预计算数据，after_init 中赋值
    g.pass_df = None   # 每日每只是否通过横盘+突破（shift(1)）
    g.cap_df = None    # 每日每只排序用市值（shift(1)）
    g.close_df = None
    g.open_df = None
    g.high_df = None
    g.low_df = None
    if not g.accid:
        print('[实盘] 警告: accid 为空，请在策略设置中指定交易账户')
    print('横盘突破策略（QMT 官方风格）初始化完成')


def after_init(C):
    """量价数据获取 + 横盘突破因子计算，结果 shift(1) 防未来"""
    # 取回测/实盘的时间范围：QMT 回测会注入 start_time/end_time（可能是数字时间戳或 'YYYYMMDD'），
    # 这里统一转成 8 位日期串；未设置时用默认。实盘时若仍是默认大区间则改为最近约半年，避免一次拉过多数据。
    start = getattr(C, 'start_time', '20200101')
    end = getattr(C, 'end_time', '20251231')
    if isinstance(start, (int, float)):
        start = str(int(start))[:8]
    else:
        start = (start or '20200101')[:8]
    if isinstance(end, (int, float)):
        end = str(int(end))[:8]
    else:
        end = (end or '20251231')[:8]
    if start == '20200101' and end == '20251231':
        end_d = datetime.now().date()
        start_d = end_d - timedelta(days=180)
        start = start_d.strftime('%Y%m%d')
        end = end_d.strftime('%Y%m%d')

    # 股票池（QMT 板块函数：g.sector_name，默认深证300，并剔除 ST/创业板/科创板/北交所）
    try:
        g.s = C.get_stock_list_in_sector(g.sector_name)
        if g.s:
            g.s = [s for s in g.s if not _is_chinext_star_bse_or_st(s)]
    except Exception as e:
        g.s = []
        print('[after_init] get_stock_list_in_sector 失败:', e)
    if not g.s:
        print('[after_init] 股票池为空，请检查 get_stock_list_in_sector')
        return

    # --- 量价数据获取 ---
    try:
        data = C.get_market_data_ex(
            ['close', 'open', 'high', 'low'],
            g.s,
            period='1d',
            start_time=start,
            end_time=end,
            dividend_type='front_ratio',
            fill_data=True,
            subscribe=False
        )
    except Exception as e:
        print('[after_init] get_market_data_ex 失败:', e)
        return

    if not data or len(g.s) == 0:
        return
    first_stock = g.s[0]
    if first_stock not in data or 'close' not in data[first_stock]:
        return

    L = len(data[first_stock]['close'])
    if L < 25:
        print('[after_init] 数据长度不足 25')
        return

    try:
        close_df = get_df_ex(data, 'close')
        open_df = get_df_ex(data, 'open')
        high_df = get_df_ex(data, 'high')
        low_df = get_df_ex(data, 'low')
    except Exception:
        date_index = _make_date_index(start, end, L)
        close_df = _get_df_ex(data, 'close', date_index, g.s)
        open_df = _get_df_ex(data, 'open', date_index, g.s)
        high_df = _get_df_ex(data, 'high', date_index, g.s)
        low_df = _get_df_ex(data, 'low', date_index, g.s)

    # --- 基础数据：总股本（用于市值排序）---
    df_total_volume = _get_total_volume_df(C, g.s)

    # --- 因子计算：横盘+突破 → pass；市值 → cap（无总股本时用收盘价近似排序）---
    pass_df = _build_pass_df(close_df, open_df, high_df, low_df, g.amp_min)
    if df_total_volume is not None and not df_total_volume.empty:
        cap_df = close_df * df_total_volume
    else:
        cap_df = close_df.copy()

    # 防未来：全部 shift(1)，当日 bar 只能用 T-1 信号
    g.pass_df = pass_df.shift(1)
    g.cap_df = cap_df.shift(1)
    g.close_df = close_df.shift(1)
    g.open_df = open_df.shift(1)
    g.high_df = high_df.shift(1)
    g.low_df = low_df.shift(1)
    print('[after_init] 因子预计算完成, 股票数=%d, 交易日数=%d' % (len(g.s), L))


def handlebar(C):
    backtest_time = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d')
    backtest_time_8 = backtest_time[:8] if len(backtest_time) >= 8 else backtest_time
    today_8 = backtest_time_8  # 当前K线日期，用于当天早盘开盘价挂单

    if g.pass_df is None or g.pass_df.empty:
        return
    # 以前一交易日为计算起点：信号、涨幅与价格区间、持仓判断均用前一日数据；当日仅用开盘价挂单
    if backtest_time_8 not in g.pass_df.index:
        backtest_time_8 = str(g.pass_df.index[-1])[:8]

    # 前一日信号：通过横盘+突破的标的，按市值升序取前 buy_num
    pass_series = g.pass_df.loc[backtest_time_8]
    cap_series = g.cap_df.loc[backtest_time_8] if g.cap_df is not None else None
    buy_list = daily_filter(pass_series, cap_series, backtest_time_8)

    # --- 获取持仓（优先 QMT 持仓接口，否则用 g.holding）---
    hold = get_holdings(C, g.accid, 'stock')
    hold_list = list(hold.keys()) if isinstance(hold, dict) else []

    # --- 卖出：不在 buy_list 的持仓 + 规则卖（止损/大跌/MA3）---
    need_sell = [s for s in hold_list if s not in buy_list]
    for stock in list(g.holding.keys()):
        if not g.holding.get(stock, True):
            continue
        if stock in need_sell:
            continue
        # 规则卖
        try:
            if backtest_time_8 not in g.close_df.index:
                continue
            idx = g.close_df.index.get_loc(backtest_time_8)
            if idx < 4:
                continue
            closes = g.close_df.iloc[idx - 4 : idx + 1][stock]
            if pd.isna(closes).any() or len(closes) < 5:
                continue
            closes = closes.dropna().tolist()
            if len(closes) < 5:
                continue
            current_price = closes[-1]
            buy_price = g.buy_price.get(stock, current_price)
            today_open = g.open_df.loc[backtest_time_8, stock] if stock in g.open_df.columns else current_price
            today_high = g.high_df.loc[backtest_time_8, stock] if stock in g.high_df.columns else current_price
            today_low = g.low_df.loc[backtest_time_8, stock] if stock in g.low_df.columns else current_price
            if today_open <= 0:
                continue
            today_return = (current_price - today_open) / today_open
            today_low_return = (today_low - today_open) / today_open
            total_loss = (current_price - buy_price) / buy_price if buy_price and buy_price > 0 else 0
            ma3_prev = np.mean(closes[-4:-1])
            ma3_today = np.mean(closes[-3:])
            buy_bar = g.buy_barpos.get(stock, C.barpos)
            days_held = max(0, C.barpos - buy_bar)
            in_min_hold = days_held < g.min_hold_days

            sell_rule = False
            if total_loss < -0.07:
                sell_rule = True
            elif today_return < -0.08 or today_low_return < -0.08:
                sell_rule = True
            elif not in_min_hold and current_price < ma3_prev:
                sell_rule = True
            elif not in_min_hold and ma3_today < ma3_prev * 0.998 and current_price < ma3_today:
                sell_rule = True

            if sell_rule:
                need_sell.append(stock)
        except Exception as e:
            pass

    for stock in need_sell:
        if stock not in hold:
            continue
        try:
            vol = hold[stock].get('持仓数量', hold[stock].get('volume', 0)) if isinstance(hold[stock], dict) else g.buy_shares.get(stock, 0)
            if vol is None or (isinstance(vol, (int, float)) and vol < 100):
                vol = g.buy_shares.get(stock, 0)
            if not vol or (isinstance(vol, (int, float)) and vol < 100):
                continue
            if g.accid:
                open_p = _get_open_price(C, stock, today_8)
                if open_p and open_p > 0:
                    passorder(24, 1101, g.accid, stock, 11, float(open_p), int(vol), "横盘突破", 1, "", C)
                else:
                    passorder(24, 1101, g.accid, stock, 5, -1, int(vol), "横盘突破", 1, "", C)
            g.holding[stock] = False
            for d in [g.buy_price, g.buy_shares, g.buy_date, g.buy_barpos]:
                if stock in d:
                    del d[stock]
            print(backtest_time_8, '卖出', stock, vol, '规则/不在名单')
        except Exception as e:
            print('卖出异常', stock, e)

    # --- 买入：有信号且 accid 有效即下单（实盘有信号就买，不等到尾盘）---
    if not g.accid:
        return

    hold = get_holdings(C, g.accid, 'stock')
    hold_list = list(hold.keys()) if isinstance(hold, dict) else []
    buy_list = [s for s in buy_list if s not in hold_list]
    buy_num = g.buy_num - len(hold_list)
    if buy_num <= 0 or not buy_list:
        return

    buy_list = buy_list[:buy_num]
    for s in buy_list:
        try:
            # 当天早盘开盘价挂单
            price = _get_open_price(C, s, today_8)
            if price is None or pd.isna(price) or price <= 0:
                price = g.open_df.loc[backtest_time_8, s] if g.open_df is not None and backtest_time_8 in g.open_df.index and s in g.open_df.columns else None
            if price is None or pd.isna(price) or price <= 0:
                if g.close_df is not None and backtest_time_8 in g.close_df.index and s in g.close_df.columns:
                    price = g.close_df.loc[backtest_time_8, s]
            if not price or price <= 0:
                continue
            passorder(23, 1102, g.accid, s, 11, float(price), g.per_money, "横盘突破", 1, "", C)
            g.holding[s] = True
            g.buy_price[s] = float(price)
            g.buy_shares[s] = int(g.per_money / price / 100) * 100
            if g.buy_shares[s] < 100:
                g.buy_shares[s] = 100
            g.buy_date[s] = backtest_time_8
            g.buy_barpos[s] = C.barpos
            print(backtest_time_8, '买入', s, g.buy_shares[s], '@', price)
        except Exception as e:
            print('买入异常', s, e)


def daily_filter(pass_series, cap_series, backtest_time):
    """将 pass_series 中为 True 的标的筛出，去 ST/创业板/科创板/北交所，再按 cap 升序取前 g.buy_num"""
    if pass_series is None or pass_series.empty:
        return []
    sl = pass_series[pass_series == True].index.tolist()
    if not sl:
        return []
    sl = [s for s in sl if not is_st(s, backtest_time) and not _is_chinext_star_bse_or_st(s)]
    if g.sort_by_factor == 'market_cap' and cap_series is not None and not cap_series.empty:
        cap_series = cap_series.reindex(sl).fillna(np.inf)
        sl = sorted(sl, key=lambda k: cap_series.get(k, np.inf))
    return sl[: g.buy_num]


def is_st(s, date):
    """判断某日在历史上是否为 ST"""
    st_dict = g.his_st.get(s, {})
    if not st_dict:
        return False
    # 简化：若 his_st 未维护则仅代码规则
    if 'ST' in str(s).upper():
        return True
    return False


def _get_stock_pool(C, date_str):
    """组合指数成分股"""
    indices = ['000001.SH', '399001.SZ', '000300.SH', '000905.SH', '000852.SH', '000903.SH']
    out = []
    for code in indices:
        try:
            if hasattr(C, 'get_index_constituent'):
                st = C.get_index_constituent(code)
            elif hasattr(C, 'get_sector'):
                st = C.get_sector(code)
            else:
                continue
            if st:
                out.extend(st)
        except Exception:
            continue
    if out:
        out = list(set(out))
        out = [s for s in out if not _is_chinext_star_bse_or_st(s)]
    return out


def _is_chinext_star_bse_or_st(stock_code):
    if not stock_code or len(stock_code) < 6:
        return True
    code = stock_code.split('.')[0]
    suffix = (stock_code.split('.')[-1] or '').upper()
    if suffix == 'BJ' or code.startswith('300') or code.startswith('688') or code.startswith('689'):
        return True
    if 'ST' in stock_code.upper():
        return True
    return False


def get_df_ex(data: dict, field: str) -> pd.DataFrame:
    """用于在使用 get_market_data_ex 的情况下，取到标准 df。
    data: get_market_data_ex 返回的 dict
    field: 'time','open','high','low','close','volume','amount','preClose' 等
    返回：以时间为 index、标的为 columns 的 df
    """
    _index = data[list(data.keys())[0]].index.tolist()
    _columns = list(data.keys())
    df = pd.DataFrame(index=_index, columns=_columns)
    for i in _columns:
        df[i] = data[i][field]
    return df


def _make_date_index(start, end, length):
    try:
        dr = pd.bdate_range(start=start, end=end)
        if len(dr) >= length:
            return dr[-length:].tolist()
        return dr.tolist()[:length]
    except Exception:
        return list(range(length))


def _get_df_ex(data, field, date_index, stock_list):
    """从 get_market_data_ex 返回的 data 中抽出 field，组成 DataFrame；index=date_index, columns=stock_list"""
    rows = {}
    for s in stock_list:
        if s not in data or field not in data[s]:
            continue
        rows[s] = list(data[s][field]) if hasattr(data[s][field], '__iter__') and not isinstance(data[s][field], (str, dict)) else data[s][field]
    if not rows:
        return pd.DataFrame()
    L = min(len(rows[k]) for k in rows)
    for k in rows:
        rows[k] = rows[k][-L:]
    df = pd.DataFrame(rows, index=date_index[-L:] if len(date_index) >= L else range(L))
    return df


def _get_open_price(C, stock, date_8):
    """取某日开盘价，用于当天早盘开盘挂单。先查 g.open_df，没有再拉 get_market_data_ex。"""
    if g.open_df is not None and not g.open_df.empty and date_8 in g.open_df.index and stock in g.open_df.columns:
        v = g.open_df.loc[date_8, stock]
        if v is not None and not pd.isna(v) and v > 0:
            return float(v)
    try:
        data = C.get_market_data_ex(['open'], [stock], period='1d', end_time=date_8, count=2, subscribe=False)
        if data and stock in data and 'open' in data[stock] and len(data[stock]['open']) > 0:
            o = data[stock]['open'][-1]
            if o is not None and o > 0:
                return float(o)
    except Exception:
        pass
    return None


def _get_total_volume_df(C, stock_list):
    """总股本 Series，index=股票代码（用于市值=close*总股本）。使用 QMT 内置 get_total_share(stockcode)。"""
    try:
        if not hasattr(C, 'get_total_share'):
            return None
        total_volumes = {}
        for stock in stock_list:
            try:
                v = C.get_total_share(stock)
                if v is not None and (isinstance(v, (int, float)) and v > 0):
                    total_volumes[stock] = float(v)
            except Exception:
                continue
        if not total_volumes:
            return None
        return pd.Series(total_volumes)
    except Exception:
        return None


def _build_pass_df(close_df, open_df, high_df, low_df, amp_min):
    """按日、按标的计算是否通过横盘+突破，返回 bool DataFrame，index=日期，columns=股票"""
    if close_df is None or close_df.empty or len(close_df) < 22:
        return pd.DataFrame()
    pass_df = pd.DataFrame(False, index=close_df.index, columns=close_df.columns)
    period = 20
    for i in range(21, len(close_df)):
        for s in close_df.columns:
            try:
                closes = close_df.iloc[i - 21 : i - 1][s]
                highs = high_df.iloc[i - 21 : i - 1][s]
                lows = low_df.iloc[i - 21 : i - 1][s]
                if closes.isna().any() or highs.isna().any() or lows.isna().any():
                    continue
                closes = closes.tolist()
                highs = highs.tolist()
                lows = lows.tolist()
                if len(closes) < period:
                    continue
                avg_amp, price_range = _calc_sideways(highs, lows, closes, period)
                if not (amp_min <= avg_amp <= 0.05 and price_range <= 1.15):
                    continue
                today_c = close_df.iloc[i][s]
                today_o = open_df.iloc[i][s]
                if pd.isna(today_c) or pd.isna(today_o) or today_o <= 0 or today_c <= 3.0:
                    continue
                today_ret = (today_c - today_o) / today_o
                if not (today_ret > avg_amp * 1.3 and today_ret < 0.08):
                    continue
                # 前三天（不含当日）连跌过滤
                if i >= 5:
                    c_prev = [close_df.iloc[i - k][s] for k in range(2, 6)]
                    if not any(pd.isna(c_prev)) and _three_consecutive_down(c_prev):
                        continue
                pass_df.at[pass_df.index[i], s] = True
            except Exception:
                continue
    return pass_df


def _calc_sideways(highs, lows, closes, period=20):
    if len(highs) < period or len(lows) < period or len(closes) < period:
        return float('inf'), float('inf')
    amp_sum = 0
    n = 0
    for j in range(period):
        if closes[j] and closes[j] > 0:
            amp_sum += (highs[j] - lows[j]) / closes[j]
            n += 1
    avg_amp = amp_sum / n if n else float('inf')
    period_high = max(highs[:period])
    period_low = min(lows[:period])
    price_range = period_high / period_low if period_low and period_low > 0 else float('inf')
    return avg_amp, price_range


def _three_consecutive_down(closes_last4):
    """closes_last4 = [前1日, 前2日, 前3日, 前4日]，判断前1>前2>前3 是否连跌"""
    if len(closes_last4) < 4:
        return False
    return closes_last4[0] < closes_last4[1] and closes_last4[1] < closes_last4[2] and closes_last4[2] < closes_last4[3]


def get_holdings(C, accid, asset_type):
    """获取持仓：优先 QMT 接口 get_holdings，否则 get_trade_detail_data，再否则用 g.holding"""
    if not accid:
        return {s: {'持仓数量': g.buy_shares.get(s, 0)} for s in g.holding if g.holding.get(s)}
    try:
        if hasattr(C, 'get_holdings'):
            h = C.get_holdings(accid, asset_type)
            if h is not None and isinstance(h, dict):
                return h
        if hasattr(C, 'get_trade_detail_data'):
            pos = C.get_trade_detail_data(accid, asset_type, 'position')
            if pos is not None:
                if isinstance(pos, dict):
                    return pos
                if isinstance(pos, (list, tuple)) and len(pos) > 0:
                    out = {}
                    for p in pos:
                        code = getattr(p, 'm_strInstrumentID', None) or getattr(p, 'stock_code', None) or (p.get('stock_code') if isinstance(p, dict) else None)
                        if code:
                            out[code] = p if isinstance(p, dict) else {'持仓数量': getattr(p, 'm_nVolume', getattr(p, 'volume', 0))}
                    return out
    except Exception:
        pass
    return {s: {'持仓数量': g.buy_shares.get(s, 0)} for s in g.holding if g.holding.get(s)}


def timetag_to_datetime(timetag, format_str='%Y%m%d'):
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)
