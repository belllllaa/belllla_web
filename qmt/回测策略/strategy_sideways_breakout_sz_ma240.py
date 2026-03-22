#coding:gbk
"""
横盘异动突破策略（振幅+波动）+ 深证指数MA240过滤
- 过去20交易日（不含今日）横盘区间震荡：
  - 平均振幅有上下限：下限可设（如≥3%）避免死股，上限 ≤5%
  - 价格波动区间 ≤ 15% （看最高和最低价）
  - 今日涨幅>平均振幅*1.3, 今日涨幅 <8%
- 价格大于3元 - 尾盘买入
- 卖出逻辑：最少持有7个交易日后可触发止损；止损条件：7%总亏损止损 + 做多移动止损（持仓期间最高价 - ATR(14)×倍数，默认2.0）
- 最多持有10只股票轮动，非ST股（剔除ST/创业板/科创板/北交所）
- 持仓时间按【交易日】统计（用 barpos 差值）
- 截面选股：在通过横盘+突破的候选中，按规模因子（市值最小）排序，取前 N 只买入（可关闭改用先到先得）
- 买入前三天（不含当日）不能连跌三天（三日收盘价依次走低则过滤）
- 【新增】深证指数（399001.SZ）跌破 MA240 时不开新仓
- 【可选】挤压突破入场：布林带完全位于肯特纳通道内（squeeze）+ 连续3日挤压 + 突破前20日最高 + 放量1.5倍（init 中 use_squeeze_entry=True 开启）
- 【可选】趋势因子过滤（init 中 trend_filter_mode）：周线类（交易周合成K线）与N日收益率动量。

  方案说明（与实务/研报中常见表述对齐，便于换模式对比回测）：
  1) weekly_ma_bull：周线（默认每5个交易日合成1根）收盘站上短均、短均站上长均——经典「均线多头」趋势定义。
  2) weekly_ma_new：在 1) 基础上要求「本周满足、上周不满足」——近似「趋势刚转强/弱转强」确认。
  3) weekly_3small_yang：近N周（默认3）均为小实体阳线——温和上攻而非暴动量拉升；实体/开盘比 ≤ trend_small_yang_max_body。
  4) ret_nd：N日（默认20）区间收益率落在 [trend_ret_min, trend_ret_max]——中期动量转强但未过度陡峭（过热过滤）。
  5) weekly_bull_and_ret：1) 与 4) 同时满足——趋势与动量双确认，信号更少。
  6) weekly_new_or_small3：满足 2)，或同时满足 3) 与 4)——偏「启动或爬坡」的宽松组合。

  说明：本策略未接 QMT 原生周线接口时，用「每 trend_week_len 根日线」合成周K，与日历周线略有差异，回测对比时勿与看盘软件周线逐点机械对齐。

QMT 知识库可用指标（见 qmt_complete_functions.md）：
- talib.SMA / EMA / RSI / MACD / BBANDS(close, 20, 2, 2)；talib.ATR(high, low, close, 14)；talib.TRANGE(high, low, close)
- 肯特纳通道、滚动最高/量均线可用 numpy + talib 自行计算
"""

import numpy as np
import time
try:
    import talib
except Exception:
    talib = None

# 深证成指代码，用于 MA240 过滤
SZ_INDEX_CODE = '399001.SZ'


def init(C):
    C.accountid = getattr(C, 'accountid', '')
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.buy_barpos = {}   # 买入时的 K 线索引，用于按【交易日】计算持仓天数

    # ---------- 回测可调参数（改这里即可）----------
    C.max_stocks = 7
    C.per_stock_amount = 140000
    C.min_hold_days = 7
    C.sort_by_factor = getattr(C, 'sort_by_factor', 'market_cap')  # 'market_cap'=按市值最小取前N只，''=先到先得

    # 横盘条件
    C.amp_min = getattr(C, 'amp_min', 0.03)   # 平均振幅下限（0=不设）
    C.amp_max = 0.05                           # 平均振幅上限
    C.price_range_max = 1.15                   # 价格波动区间上限（最高/最低比）
    C.sideways_days = 20                       # 横盘统计天数（不含当日）
    C.min_closes_for_buy = 22                  # 买入所需最少K线根数

    # 突破条件
    C.breakout_amp_mult = 1.3                  # 今日涨幅 > 平均振幅 * 该倍数
    C.today_return_max = 0.08                  # 今日涨幅上限（如8%）
    C.today_high_return_max = getattr(C, 'today_high_return_max', 0.095)  # 当日最高涨幅上限，≥则过滤（避免上午已拉涨停的票，默认9.5%）

    # 价格与数量
    C.min_price = 3.0                          # 最低价格过滤（元）
    C.min_shares = 100                         # 每笔最小股数（手）；股数由 per_stock_amount/现价 决定，不设单笔股数上限

    # 卖出
    C.use_stop_loss_total = getattr(C, 'use_stop_loss_total', False)  # 是否启用总亏损止损
    C.stop_loss_total = 0.07                   # 总亏损止损比例
    # 做多移动止损：止损位 = 持仓期间最高价 - ATR(14)×倍数（防守型建议 2.0）
    C.atr_period = 14
    C.atr_stop_mult = 2.0

    # 可选：挤压突破入场（布林在肯特纳内 + 连续3日挤压 + 突破20日高 + 放量1.5倍）
    C.use_squeeze_entry = getattr(C, 'use_squeeze_entry', False)

    # 深证MA240过滤
    C.sz_ma240_count = 250                     # 深证指数取数根数（需>=240）
    C.sz_ma240_period = 240                   # MA240 周期

    # ---------- 趋势因子过滤（买入前额外条件；'' 表示关闭）----------
    # 模式一览：
    #   ''                  不启用
    #   'weekly_ma_bull'    周线（每5个交易日一节）收盘 > MA短 > MA长
    #   'weekly_ma_new'     本周刚形成上述多头排列（上周非多头）
    #   'weekly_3small_yang' 近3个交易周均为小阳线（阳线且实体/开盘≤阈值）
    #   'ret_nd'            N日收益率在 [trend_ret_min, trend_ret_max]（过滤过冷/过热）
    #   'weekly_bull_and_ret'  weekly_ma_bull 且 ret_nd
    #   'weekly_new_or_small3' weekly_ma_new 或 (3小阳线 且 ret_nd)
    C.trend_filter_mode = getattr(C, 'trend_filter_mode', '')
    C.trend_week_len = getattr(C, 'trend_week_len', 5)           # 合成「交易周」天数（A股常用近似）
    C.trend_week_ma_short = getattr(C, 'trend_week_ma_short', 5) # 短均线周期（周）
    C.trend_week_ma_long = getattr(C, 'trend_week_ma_long', 10)  # 长均线周期（周）
    C.trend_small_yang_weeks = getattr(C, 'trend_small_yang_weeks', 3)
    C.trend_small_yang_max_body = getattr(C, 'trend_small_yang_max_body', 0.03)  # 小阳线：实体/开盘 ≤ 3%
    C.trend_ret_days = getattr(C, 'trend_ret_days', 20)          # 动量窗口（交易日）
    C.trend_ret_min = getattr(C, 'trend_ret_min', 0.0)           # N日收益下限，如 0 表示中期非负
    C.trend_ret_max = getattr(C, 'trend_ret_max', 0.18)          # N日收益上限，抑制过热

    # 其他：K 线根数（开启趋势过滤时需更长日线以供合成周线 + N 日收益）
    if C.trend_filter_mode:
        C.bar_count = max(getattr(C, 'bar_count', 80), C.sideways_days + 60)
        _need = max(55, C.trend_week_ma_long * C.trend_week_len + 2 * C.trend_week_len + C.trend_ret_days + 5)
        if C.min_closes_for_buy < _need:
            C.min_closes_for_buy = _need
    else:
        C.bar_count = getattr(C, 'bar_count', 25)
    # ---------- 以上参数可在回测前在 init 内修改 ----------

    print('横盘突破策略（简化版-优化版）+ 深证MA240过滤 初始化完成')


def _check_stop_loss_total(C, current_price, buy_price):
    """
    总亏损止损：当前价相对成本价亏损超过 C.stop_loss_total（如7%）时触发。
    仅当 C.use_stop_loss_total 为 True 时生效。
    返回 (是否触发, 原因文案)。
    """
    if not getattr(C, 'use_stop_loss_total', True):
        return False, ""
    if buy_price is None or buy_price <= 0:
        return False, ""
    pct = getattr(C, 'stop_loss_total', 0.07)
    total_loss = (current_price - buy_price) / buy_price
    if total_loss < -pct:
        return True, f"总亏损{pct:.0%}止损"
    return False, ""


def _is_sz_below_ma240(C, bar_date_str):
    """
    判断深证指数（399001.SZ）是否跌破 MA240。
    若跌破则不开新仓。获取失败或数据不足时保守处理：允许开仓（避免因行情缺失误拦）。
    """
    try:
        count = getattr(C, 'sz_ma240_count', 250)
        period_len = getattr(C, 'sz_ma240_period', 240)
        data = C.get_market_data_ex(
            ['close'], [SZ_INDEX_CODE],
            end_time=bar_date_str, period='1d', count=count, subscribe=False
        )
        if SZ_INDEX_CODE not in data or len(data[SZ_INDEX_CODE]['close']) < period_len:
            return False  # 数据不足时不拦截
        closes = list(data[SZ_INDEX_CODE]['close'])
        ma240 = np.mean(closes[-period_len:])
        current_close = closes[-1]
        return float(current_close) < float(ma240)
    except Exception as e:
        print(f"深证MA240检查异常: {e}")
        return False


def _trading_weekly_ohlc(closes, opens, highs, lows, n_weeks, week_len):
    """
    从日线末尾向前合成 n_weeks 根「交易周」K（每 week_len 根日线为一周），
    返回 (open, high, low, close)，每根数组按时间从旧到新（最后一根为最近一周）。
    不足数据时返回 None。
    """
    if n_weeks <= 0 or week_len <= 0:
        return None
    if min(len(closes), len(opens), len(highs), len(lows)) < n_weeks * week_len:
        return None
    wo, wh, w_low, wc = [], [], [], []
    end = len(closes)
    for _ in range(n_weeks):
        start = end - week_len
        if start < 0:
            return None
        seg = slice(start, end)
        wo.append(float(opens[start]))
        wc.append(float(closes[end - 1]))
        wh.append(max(highs[seg]))
        w_low.append(min(lows[seg]))
        end = start
    wo.reverse()
    wh.reverse()
    w_low.reverse()
    wc.reverse()
    return wo, wh, w_low, wc


def _weekly_ma_bull_series(week_closes, short_p, long_p):
    """
    对周线收盘序列逐根判断：收盘 > SMA(短) > SMA(长)。
    返回与 week_closes 等长的 bool 列表；数据不足或 talib 不可用时返回 None。
    """
    if talib is None or len(week_closes) < long_p + 1:
        return None
    arr = np.array(week_closes, dtype=np.float64)
    sma_s = talib.SMA(arr, short_p)
    sma_l = talib.SMA(arr, long_p)
    out = []
    for i in range(len(week_closes)):
        if np.isnan(sma_s[i]) or np.isnan(sma_l[i]):
            out.append(False)
            continue
        out.append(week_closes[i] > sma_s[i] > sma_l[i])
    return out


def _last_n_weeks_small_yang(weekly_opens, weekly_closes, n_weeks, max_body_pct):
    """最近 n_weeks 根周K（含最近一周）：均为阳线且实体/开盘 <= max_body_pct。"""
    if n_weeks <= 0 or len(weekly_closes) < n_weeks or len(weekly_opens) < n_weeks:
        return False
    for i in range(-n_weeks, 0):
        o, c = weekly_opens[i], weekly_closes[i]
        if o <= 0 or c <= o:
            return False
        if (c - o) / o > max_body_pct:
            return False
    return True


def _nday_return_in_range(closes, n_days, r_min, r_max):
    """N 日收益率 (今收/前第N日收 - 1) 落在 [r_min, r_max]。"""
    if n_days <= 0 or len(closes) < n_days + 1:
        return False
    base = closes[-1 - n_days]
    if base is None or base <= 0:
        return False
    r = closes[-1] / base - 1.0
    return r_min <= r <= r_max


def _pass_trend_filter(C, closes, highs, lows, opens):
    """
    买入侧趋势因子过滤。定义参考常见量价与动量因子：
    - 周线多头排列：价格位于短均线上方、短均线位于长均线上方（经典趋势跟踪表述）；
    - 「刚多头」：本周满足多头、上周不满足，类似短周期均线上穿后的确认；
    - 小连阳：连续数周阳线且实体不大，偏「温和爬坡」而非急拉；
    - N 日收益：中期动量在合理区间（避免跌势接力也避免过度偏离）。
    """
    mode = (getattr(C, 'trend_filter_mode', '') or '').strip().lower()
    if not mode:
        return True

    wl = int(getattr(C, 'trend_week_len', 5))
    ms = int(getattr(C, 'trend_week_ma_short', 5))
    ml = int(getattr(C, 'trend_week_ma_long', 10))
    n_small = int(getattr(C, 'trend_small_yang_weeks', 3))
    small_body = float(getattr(C, 'trend_small_yang_max_body', 0.03))
    nd = int(getattr(C, 'trend_ret_days', 20))
    rmin = float(getattr(C, 'trend_ret_min', 0.0))
    rmax = float(getattr(C, 'trend_ret_max', 0.18))

    n_weeks_need = max(ml + 3, ms + 3, 12)
    pack = _trading_weekly_ohlc(closes, opens, highs, lows, n_weeks_need, wl)
    if pack is None:
        return False
    wo, wh, w_low, wc = pack

    bulls = _weekly_ma_bull_series(wc, ms, ml)
    bull_now = bulls[-1] if bulls else False
    bull_prev = bulls[-2] if bulls and len(bulls) >= 2 else False

    small_ok = _last_n_weeks_small_yang(wo, wc, n_small, small_body)
    ret_ok = _nday_return_in_range(closes, nd, rmin, rmax)

    if mode in ('weekly_ma_bull', 'ma_bull', 'w_ma_bull'):
        return bool(bull_now)

    if mode in ('weekly_ma_new', 'weekly_ma_bull_new', 'ma_new', 'w_ma_new'):
        if bulls is None:
            return False
        return bool(bull_now and not bull_prev)

    if mode in ('weekly_3small_yang', 'weekly_3_small_yang', 'small_yang'):
        return bool(small_ok)

    if mode in ('ret_nd', 'nd_ret', 'mom_nd'):
        return bool(ret_ok)

    if mode in ('weekly_bull_and_ret', 'bull_ret', 'w_bull_ret'):
        if bulls is None:
            return False
        return bool(bull_now and ret_ok)

    if mode in ('weekly_new_or_small3', 'new_or_small', 'w_new_or_sy'):
        if bulls is None:
            new_ok = False
        else:
            new_ok = bool(bull_now and not bull_prev)
        return bool(new_ok or (small_ok and ret_ok))

    # 未知模式不拦（便于扩展）；若希望严格可改为 return False
    print(f"[趋势过滤] 未知 trend_filter_mode={mode!r}，已跳过")
    return True


def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]

    # 获取股票池 - （组合指数成分股），这是最可靠的方法
    all_stocks = get_stock_pool(C, bar_date_str)

    print(f"[{bar_date_str}] 股票池大小: {len(all_stocks)} 只股票")

    # 卖出逻辑
    for stock in list(C.holding.keys()):
        if not C.holding.get(stock, False):
            continue

        try:
            buy_bar = C.buy_barpos.get(stock, C.barpos)
            # 持仓天数 = 当前 bar 索引 - 买入时 bar 索引（按【交易日】计算）
            days_held = max(0, C.barpos - buy_bar)
            in_min_hold = days_held < C.min_hold_days

            # 需足够 K 线计算 ATR(14) 与持仓期间最高价
            bar_count = max(getattr(C, 'bar_count', 25), days_held + 10, getattr(C, 'atr_period', 14) + 5)
            data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period=getattr(C, 'period', '1d'), count=bar_count, subscribe=False)
            if stock not in data or len(data[stock].get('close', [])) < 2:
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

            sell_condition = False
            sell_reason = ""

            stop_triggered, stop_reason = _check_stop_loss_total(C, current_price, buy_price)
            if stop_triggered:
                sell_condition = True
                sell_reason = stop_reason
            elif not in_min_hold and talib is not None and days_held >= 1:
                # 做多移动止损：止损位 = 持仓期间最高价 - ATR(14)×倍数
                n_since_entry = min(days_held + 1, len(highs))
                highest_high_since_entry = max(highs[-n_since_entry:])
                try:
                    high_arr = np.array(highs, dtype=np.float64)
                    low_arr = np.array(lows, dtype=np.float64)
                    close_arr = np.array(closes, dtype=np.float64)
                    atr_arr = talib.ATR(high_arr, low_arr, close_arr, getattr(C, 'atr_period', 14))
                    atr_14 = float(atr_arr[-1]) if len(atr_arr) and not np.isnan(atr_arr[-1]) else None
                except Exception:
                    atr_14 = None
                if atr_14 is not None and atr_14 > 0:
                    mult = getattr(C, 'atr_stop_mult', 2.0)
                    stop_loss = highest_high_since_entry - atr_14 * mult
                    if current_price <= stop_loss:
                        sell_condition = True
                        sell_reason = f"ATR移动止损(最高{highest_high_since_entry:.3f}-ATR*{mult:.1f}={stop_loss:.3f})"

            if sell_condition and stock in C.buy_shares:
                shares = C.buy_shares[stock]
                if shares >= C.min_shares:
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

    # 买入逻辑：先检查深证指数是否跌破 MA240，跌破则不开新仓
    sz_below_ma240 = _is_sz_below_ma240(C, bar_date_str)
    print(f"[{bar_date_str}] 深证指数: {'破MA240，不开新仓' if sz_below_ma240 else '未破MA240'}")
    current_holdings = sum(1 for h in C.holding.values() if h)

    if current_holdings < C.max_stocks and not sz_below_ma240:
        total_stocks = len(all_stocks)  # 全扫描，无上限
        passed_sector_filter = 0
        passed_data_filter = 0
        passed_price_filter = 0
        passed_sideways_filter = 0
        passed_trend_filter = 0
        passed_breakout_filter = 0
        candidates = []   # (stock, current_close, sort_value) 用于截面排序

        for stock in all_stocks:
            if C.holding.get(stock, False):
                continue
            if _is_chinext_star_bse_or_st(stock):
                continue
            passed_sector_filter += 1

            try:
                fields = ['close', 'high', 'low', 'open']
                if getattr(C, 'use_squeeze_entry', False):
                    fields.append('volume')
                data = C.get_market_data_ex(fields, [stock], end_time=bar_date_str, period='1d', count=C.bar_count, subscribe=False)
                if stock not in data or len(data[stock]['close']) < C.min_closes_for_buy:
                    continue
                passed_data_filter += 1

                closes = list(data[stock]['close'])
                highs = list(data[stock]['high'])
                lows = list(data[stock]['low'])
                opens = list(data[stock]['open'])
                volumes = list(data[stock].get('volume', [])) if 'volume' in data[stock] else None
                current_close = closes[-1]
                today_open = opens[-1]

                if current_close <= 0 or today_open <= 0:
                    continue
                if current_close <= C.min_price:
                    continue
                passed_price_filter += 1

                # 可选：挤压突破入场需同时满足（布林在肯特纳内连续3日 + 突破20日高 + 放量1.5倍）
                if getattr(C, 'use_squeeze_entry', False):
                    if not _check_squeeze_entry(closes, highs, lows, volumes):
                        continue

                avg_amplitude, price_range = calculate_sideways_metrics(highs, lows, closes, C.sideways_days)
                if (C.amp_min <= avg_amplitude <= C.amp_max) and price_range <= C.price_range_max:
                    passed_sideways_filter += 1
                    today_return = (current_close - today_open) / today_open
                    # 当日最高涨幅：盘中已摸涨停/近涨停（默认≥9.5%）则不符合「尾盘温和突破」，不买
                    today_high_return = (highs[-1] - today_open) / today_open if today_open and today_open > 0 else 0
                    if today_high_return >= C.today_high_return_max:
                        continue
                    if today_return > avg_amplitude * C.breakout_amp_mult and today_return < C.today_return_max:
                        # 买入前三天（不含当日）不能连跌三天
                        if _is_three_consecutive_down(closes):
                            continue
                        if not _pass_trend_filter(C, closes, highs, lows, opens):
                            continue
                        passed_trend_filter += 1
                        passed_breakout_filter += 1
                        # 截面因子：用于排序的值（市值最小优先时 sort_value 越小越靠前）
                        sort_value = _get_sort_value(C, stock, current_close)
                        candidates.append((stock, current_close, sort_value))

            except Exception as e:
                print(f"买入异常 {stock}: {e}")

        # 截面选股：按因子排序后取前 N 只再下单（sort_by 已在 init 设定，此处只读一次）
        sort_by = C.sort_by_factor
        if sort_by == 'market_cap' and candidates:
            candidates.sort(key=lambda x: x[2])   # 按市值升序，最小的在前
        need_buy = min(C.max_stocks - current_holdings, len(candidates))
        final_selected = 0

        for i in range(need_buy):
            stock, current_close, _ = candidates[i]
            target_shares = int(C.per_stock_amount / current_close)
            shares = (target_shares // C.min_shares) * C.min_shares
            if shares < C.min_shares:
                continue
            passorder(23, 1101, C.accountid, stock, 5, 0, shares, "横盘突破", 1, "", C)
            C.holding[stock] = True
            C.buy_price[stock] = current_close
            C.buy_shares[stock] = shares
            C.buy_date[stock] = current_date_str
            C.buy_barpos[stock] = C.barpos
            print(f"{bar_date_str} 买入 {stock} {shares}股 @ {current_close:.3f} 横盘突破")
            C.draw_text(1, 1, '买')
            final_selected += 1

        tr_tag = f" 趋势{passed_trend_filter}" if getattr(C, 'trend_filter_mode', '') else ""
        print(f"[{bar_date_str}] 筛选统计: 总分析{total_stocks} 板块{passed_sector_filter} 数据{passed_data_filter} 价格>{C.min_price}共{passed_price_filter} 横盘{passed_sideways_filter}{tr_tag} 突破{passed_breakout_filter} 候选{len(candidates)} 买入{final_selected}")
    elif current_holdings < C.max_stocks and sz_below_ma240:
        print(f"[{bar_date_str}] 深证破MA240不开新仓，当前持仓: {current_holdings}")


def _check_squeeze_entry(closes, highs, lows, volumes, bb_period=20, kc_mult=1.5, vol_mult=1.5):
    """
    挤压突破入场条件（需同时满足）：
    - 布林带完全位于肯特纳通道内部（连续3日挤压）
    - 收盘突破前20日最高价
    - 成交量 > 20日均量 × vol_mult（如1.5倍）
    使用 QMT 内置 talib：BBANDS、SMA、TRANGE。
    返回 True 表示满足入场条件；数据不足或 talib 不可用时返回 False。
    """
    if talib is None or len(closes) < 22 or len(highs) < 22 or len(lows) < 22:
        return False
    if volumes is None or len(volumes) < 21:
        return False
    try:
        close_arr = np.array(closes, dtype=np.float64)
        high_arr = np.array(highs, dtype=np.float64)
        low_arr = np.array(lows, dtype=np.float64)
        # 布林带 BB(20, 2, 2)
        bb_upper, bb_middle, bb_lower = talib.BBANDS(close_arr, bb_period, 2, 2)
        # 肯特纳通道：中轨 SMA(close,20)，带宽 SMA(TRANGE,20)，上下轨 ±1.5*带宽
        kc_middle = talib.SMA(close_arr, bb_period)
        tr = talib.TRANGE(high_arr, low_arr, close_arr)
        kc_range = talib.SMA(tr, bb_period)
        kc_upper = kc_middle + kc_mult * kc_range
        kc_lower = kc_middle - kc_mult * kc_range
        # 挤压：布林带完全在肯特纳内
        squeeze_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
        # 连续3天挤压（当日、前1日、前2日）
        if not (squeeze_on[-1] and squeeze_on[-2] and squeeze_on[-3]):
            return False
        # 突破前20日最高价（不含当日，即 high[-21:-1]）
        prev_20_high = max(highs[-21:-1]) if len(highs) >= 21 else 0
        if closes[-1] <= prev_20_high or prev_20_high <= 0:
            return False
        # 放量：当日量 > 20日均量 × vol_mult
        vol_ma20 = np.mean(volumes[-20:])
        if vol_ma20 <= 0 or volumes[-1] <= vol_ma20 * vol_mult:
            return False
        return True
    except Exception:
        return False


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


def get_stock_pool(C, current_date_str):
    """获取股票池 - （组合指数成分股），这是最可靠的方法"""
    all_stocks = []

    try:
        # 组合多个指数成分股（最可靠的方法）
        index_stocks = []
        indices = ['399007.SZ']

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
            print(f"组合指数成分股 {len(all_stocks)} 只")
            return all_stocks
    except Exception as e:
        print(f"组合指数成分股失败: {e}")

    return all_stocks


def _is_three_consecutive_down(closes):
    """买入前三天（不含当日）是否连跌三天：前1日、前2日、前3日每日收盘均低于前一交易日收盘。"""
    if len(closes) < 6:
        return False
    down1 = closes[-2] < closes[-3]  # 前1日跌
    down2 = closes[-3] < closes[-4]  # 前2日跌
    down3 = closes[-4] < closes[-5]  # 前3日跌
    return down1 and down2 and down3


def _get_sort_value(C, stock_code, current_close):
    """截面选股用的排序值：规模因子=市值，越小越优先买入。获取失败时用收盘价近似（同池内低价常对应小市值）。"""
    sort_by = C.sort_by_factor
    if sort_by != 'market_cap':
        return 0
    try:
        if hasattr(C, 'get_instrument_detail'):
            instrument_info = C.get_instrument_detail([stock_code])
            if instrument_info and stock_code in instrument_info:
                info = instrument_info[stock_code]
                if info.get('circulation_market_value', 0) > 0:
                    return float(info['circulation_market_value'])
                if info.get('market_value', 0) > 0:
                    return float(info['market_value'])
    except Exception:
        pass
    return float(current_close)


def _is_chinext_star_bse_or_st(stock_code):
    """剔除ST股、创业板、科创板、北交所"""
    if not stock_code or len(stock_code) < 6:
        return False
    code = stock_code.split('.')[0]
    if code == '000408':
        return True  # 单独剔除
    suffix = (stock_code.split('.')[-1] or '').upper()
    if suffix == 'BJ':
        return True
    if code.startswith('300'):
        return True
    if code.startswith('688') or code.startswith('689'):
        return True
    if code.startswith('920'):
        return True
    if 'ST' in stock_code.upper():
        return True
    return False


def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)
