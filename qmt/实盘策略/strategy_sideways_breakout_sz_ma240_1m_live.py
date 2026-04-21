#coding:gbk
"""
横盘异动突破 + 深证MA240 — 实盘（1 分钟周期）
- 参考 strategy_sideways_breakout_official_style：G、get_trade_detail_data、passorder 备注、waiting_list、撤单重下
- 与回测版 strategy_sideways_breakout_sz_ma240 对齐：日线横盘+突破、深证未破 MA240、前三天不连跌；买入筛选中「涨幅」为相对昨收：(当前价-昨收)/昨收、(当日最高-昨收)/昨收（昨收=closes[-2]；当前价优先 tick 见 _scan_candidates）
- 不含：挤压入场（use_squeeze_entry）、总亏损止损（use_stop_loss_total）
- 卖出：仅最少持有日后 ATR(14) 移动止损（与回测一致）
- 定时：每个交易日 14:45–14:55 每分钟筛选；出现信号则打印代码与涨跌幅(相对昨收)并下单；满 7 只或到 14:55 停止买入
- 日志：买入相关 print 仅在 14:45–14:55；同一根 1m K 可能多次进 handlebar，已按 barpos 去重，避免约每几秒重复打日志
- 最少持有：1 分钟下按「自然日」与买入日比较（非 barpos），见文档说明

请在 QMT 中将策略周期设为 1 分钟，并指定交易账户。
"""

import numpy as np
import time
import datetime

try:
	import talib
except Exception:
	talib = None

SZ_INDEX_CODE = '399001.SZ'
# 买入筛选与「定时」日志窗口（与 handlebar 内判断一致）
BUY_WINDOW_START = '144500'
BUY_WINDOW_END = '145559'


def _in_buy_window(now_time_str):
	return BUY_WINDOW_START <= now_time_str <= BUY_WINDOW_END


class G:
	pass


g = G()


def _order_remark(side, stock, shares, retry=0):
	s = 'HB%s%s_%s' % ('B' if side == 'buy' else 'S', stock, shares)
	return ('%s_R%d' % (s, retry)) if retry else s


def _has_pending_order(stock, side):
	return any(p.get('stock') == stock and p.get('side') == side for p in g.pending_orders.values())


def _calendar_days_held(buy_date_str, current_date_str):
	"""买入日(YYYYMMDD) 至 当前日 的自然日差；1 分钟周期下用于最少持有判断。"""
	try:
		d1 = datetime.datetime.strptime(buy_date_str, '%Y%m%d')
		d2 = datetime.datetime.strptime(current_date_str, '%Y%m%d')
		return max(0, (d2 - d1).days)
	except Exception:
		return 0


def init(C):
	g.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or '11219398'
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	g.holding = {}
	g.buy_price = {}
	g.buy_shares = {}
	g.buy_date = {}
	g.buy_barpos = {}
	g.waiting_list = []
	g.pending_orders = {}
	g.QUICK_TRADE = 2
	g.WITHDRAW_SECS = 30
	g.MAX_RETRY = 2
	g.buy_code = 23 if g.account_type == 'STOCK' else 33
	g.sell_code = 24 if g.account_type == 'STOCK' else 34

	g.max_stocks = 7
	g.per_stock_amount = 6000
	g.min_hold_days = 7
	g.sort_by_factor = getattr(C, 'sort_by_factor', 'market_cap')
	g.amp_min = getattr(C, 'amp_min', 0.03)
	g.amp_max = 0.06
	g.price_range_max = 1.15
	g.sideways_days = 20
	g.min_closes_for_buy = 22
	# 以下阈值均基于「相对昨收」涨幅：ret=(当前价-昨收)/昨收；当日最高涨幅=(当日最高-昨收)/昨收
	g.breakout_amp_mult = 1.3
	g.today_return_max = 0.08
	g.today_high_return_max = getattr(C, 'today_high_return_max', 0.095)
	g.min_price = 3.0
	g.min_shares = 100
	g.max_shares_per_order = 10000

	g.atr_period = 14
	g.atr_stop_mult = 2.0

	g.sz_ma240_count = 250
	g.sz_ma240_period = 240
	g.bar_count = 25

	g.candidates_today = []
	g.ordered_at_date = ''
	g.screened_at_date = ''
	# 深证破 MA240 时每日只打一次「不开新仓」提示（handlebar 内使用）
	g._ma240_buy_warn_date = ''
	# 同一 barpos 只执行一次主逻辑（避免 is_last_bar 在同一根 K 上多次为 True 时重复日志/重复计算）
	g._last_handlebar_barpos = None

	if not g.accid:
		print('[实盘] 警告: accid 为空，请在策略设置中指定交易账户')
	print('横盘突破+深证MA240 实盘(1m) 14:45-14:55筛选下单 无挤压/无总亏止损 仅ATR止盈 accid=%s' % g.accid)


def _normalize_position_code(pos):
	if pos is None:
		return ''
	ins = (getattr(pos, 'm_strInstrumentID', None) or getattr(pos, 'stock_code', None) or '').strip()
	ex = (getattr(pos, 'm_strExchangeID', None) or getattr(pos, 'exchange_id', None) or '').upper().strip()
	if '.' in ins:
		return ins
	if not ins:
		return ''
	if ex in ('SH', 'SS', '上海'):
		return ins + '.SH'
	if ex in ('SZ', '深圳'):
		return ins + '.SZ'
	if ex:
		return ins + '.' + ex
	if ins.startswith(('60', '68', '51')):
		return ins + '.SH'
	return ins + '.SZ'


def _parse_tick_price(t):
	if t is None:
		return None
	p = (getattr(t, 'lastPrice', None) or getattr(t, 'last_price', None) or
	     getattr(t, 'm_nLastPrice', None) or getattr(t, 'nLast', None))
	if p is None and isinstance(t, dict):
		p = t.get('lastPrice') or t.get('last_price') or t.get('m_nLastPrice') or t.get('nLast')
	if p is not None:
		try:
			return float(p)
		except Exception:
			pass
	return None


def _build_full_tick_prices(C, stock_list):
	out = {}
	if not stock_list:
		return out, '股票列表为空'
	if not hasattr(C, 'get_full_tick'):
		return out, '无 get_full_tick'
	try:
		ticks = C.get_full_tick(stock_list)
		if not ticks:
			return out, 'get_full_tick 返回为空'
		for code, t in ticks.items():
			p = _parse_tick_price(t)
			if p is not None and p > 0:
				out[code] = p
		if not out:
			return out, '解析不到 last_price'
	except Exception as e:
		return out, str(e)[:80]
	return out, ''


def _get_current_price(C, stock, bar_date_str, fallback_close, tick_snapshot=None):
	if tick_snapshot is not None and stock in tick_snapshot and tick_snapshot[stock] > 0:
		return tick_snapshot[stock]
	try:
		if hasattr(C, 'get_full_tick'):
			ticks = C.get_full_tick([stock])
			if ticks and stock in ticks:
				p = _parse_tick_price(ticks[stock])
				if p is not None and p > 0:
					return p
	except Exception:
		pass
	try:
		m1 = C.get_market_data_ex(['close'], [stock], period='1m', count=1, end_time=bar_date_str, subscribe=False)
		if m1 and stock in m1 and m1[stock].get('close') and len(m1[stock]['close']) > 0:
			c = m1[stock]['close']
			p = c[-1] if hasattr(c, '__getitem__') else list(c)[-1]
			if p is not None and float(p) > 0:
				return float(p)
	except Exception:
		pass
	return fallback_close


def _is_sz_below_ma240(C, bar_date_str):
	try:
		data = C.get_market_data_ex(
			['close'], [SZ_INDEX_CODE],
			end_time=bar_date_str, period='1d', count=g.sz_ma240_count, subscribe=False
		)
		if SZ_INDEX_CODE not in data or len(data[SZ_INDEX_CODE]['close']) < g.sz_ma240_period:
			return False
		closes = list(data[SZ_INDEX_CODE]['close'])
		ma240 = np.mean(closes[-g.sz_ma240_period:])
		return float(closes[-1]) < float(ma240)
	except Exception as e:
		print('深证MA240检查异常:', e)
		return False


def get_stock_pool(C, bar_date_str):
	all_stocks = []
	try:
		index_stocks = []
		for index_code in ['399007.SZ', '000903.SH', '000905.SH']:
			try:
				if hasattr(C, 'get_index_constituent'):
					stocks = C.get_index_constituent(index_code)
				elif hasattr(C, 'get_sector'):
					stocks = C.get_sector(index_code)
				else:
					continue
				if stocks:
					index_stocks.extend(stocks)
			except Exception:
				continue
		if index_stocks:
			all_stocks = list(set(index_stocks))
	except Exception as e:
		print('组合指数成分股失败:', e)
	return all_stocks


def calculate_sideways_metrics(highs, lows, closes, period=20):
	if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
		return float('inf'), float('inf')
	amplitude_sum = 0
	valid_days = 0
	for i in range(len(closes) - period - 1, len(closes) - 1):
		if closes[i] > 0:
			high_low_diff = highs[i + 1] - lows[i + 1]
			amplitude_sum += high_low_diff / closes[i]
			valid_days += 1
	avg_amplitude = amplitude_sum / valid_days if valid_days else float('inf')
	recent_highs = highs[-period - 1:-1]
	recent_lows = lows[-period - 1:-1]
	if not recent_highs or not recent_lows:
		price_range = float('inf')
	else:
		period_low = min(recent_lows)
		price_range = max(recent_highs) / period_low if period_low > 0 else float('inf')
	return avg_amplitude, price_range


def _is_three_consecutive_down(closes):
	if len(closes) < 6:
		return False
	return (closes[-2] < closes[-3]) and (closes[-3] < closes[-4]) and (closes[-4] < closes[-5])


def _qmt_sort_market_cap(C, stock_code, price):
	"""仅用 QMT 内置接口：get_instrumentdetail(股本×价)；或 get_instrument_detail 市值字段。失败返回 None。"""
	try:
		p = float(price)
	except Exception:
		p = 0.0
	if p <= 0:
		return None
	for name in ('get_instrumentdetail', 'get_instrumentDetail'):
		if not hasattr(C, name):
			continue
		try:
			inf = getattr(C, name)(stock_code)
			if isinstance(inf, dict):
				fv = inf.get('FloatVolume', inf.get('float_volume'))
				tv = inf.get('TotalVolume', inf.get('total_volume'))
				try:
					if fv is not None and float(fv) > 0:
						return float(fv) * p
					if tv is not None and float(tv) > 0:
						return float(tv) * p
				except (TypeError, ValueError):
					pass
		except Exception:
			pass
	if hasattr(C, 'get_instrument_detail'):
		for complete in (True, False):
			try:
				info = C.get_instrument_detail([stock_code], iscomplete=complete)
			except TypeError:
				break
			except Exception:
				continue
			if info and stock_code in info:
				inf = info[stock_code]
				for k in ('circulation_market_value', 'market_value'):
					try:
						v = inf.get(k, 0) if isinstance(inf, dict) else getattr(inf, k, 0)
						if v and float(v) > 0:
							return float(v)
					except Exception:
						pass
		try:
			info = C.get_instrument_detail([stock_code])
			if info and stock_code in info:
				inf = info[stock_code]
				if isinstance(inf, dict):
					if inf.get('circulation_market_value', 0) > 0:
						return float(inf['circulation_market_value'])
					if inf.get('market_value', 0) > 0:
						return float(inf['market_value'])
		except Exception:
			pass
	return None


def _get_sort_value(C, stock_code, current_close):
	if g.sort_by_factor != 'market_cap':
		return 0
	mv = _qmt_sort_market_cap(C, stock_code, current_close)
	if mv is not None and mv > 0:
		return float(mv)
	return float(current_close)


def _is_chinext_star_bse_or_st(stock_code):
	if not stock_code or len(stock_code) < 6:
		return False
	code = stock_code.split('.')[0]
	if (stock_code.split('.')[-1] or '').upper() == 'BJ':
		return True
	if code.startswith('300') or code.startswith('688') or code.startswith('689') or code.startswith('920'):
		return True
	if 'ST' in stock_code.upper():
		return True
	return False


def timetag_to_datetime(timetag, format_str='%Y%m%d'):
	try:
		return time.strftime(format_str, time.localtime(timetag / 1000))
	except Exception:
		return str(timetag)


def _do_withdraw_and_retry(C):
	if not g.waiting_list:
		return
	now_ts = time.time()
	try:
		orders = get_trade_detail_data(g.accid, g.account_type, 'order')
	except Exception:
		orders = []
	ORDER_DONE = 56
	ORDER_CANCEL_STATES = (53, 54, 57)
	to_remove = []
	to_retry = []
	for remark in list(g.waiting_list):
		pinfo = g.pending_orders.get(remark)
		if not pinfo:
			to_remove.append(remark)
			continue
		if now_ts - pinfo['time'] < g.WITHDRAW_SECS:
			continue
		order_match = None
		for o in orders:
			if (getattr(o, 'm_strRemark', '') or '') == remark:
				order_match = o
				break
		if not order_match:
			continue
		status = getattr(order_match, 'm_nOrderStatus', 0)
		order_sys_id = getattr(order_match, 'm_strOrderSysID', '') or ''
		if status == ORDER_DONE:
			to_remove.append(remark)
			continue
		if status in ORDER_CANCEL_STATES:
			to_remove.append(remark)
			if pinfo.get('side') == 'sell':
				g.holding[pinfo['stock']] = True
			else:
				s = pinfo.get('stock')
				g.holding[s] = False
				for d in [g.buy_price, g.buy_shares, g.buy_date, g.buy_barpos]:
					d.pop(s, None)
			continue
		if pinfo.get('retry', 0) >= g.MAX_RETRY:
			to_remove.append(remark)
			continue
		to_retry.append((remark, pinfo, order_sys_id))
	for r in to_remove:
		if r in g.waiting_list:
			g.waiting_list.remove(r)
		g.pending_orders.pop(r, None)
	for remark, pinfo, order_sys_id in to_retry:
		if remark in g.waiting_list:
			g.waiting_list.remove(remark)
		g.pending_orders.pop(remark, None)
		try:
			cancel(order_sys_id, g.accid, g.account_type, C)
		except Exception as e:
			print('撤单失败', order_sys_id, e)
			continue
		stock = pinfo['stock']
		side = pinfo.get('side', 'buy')
		shares = pinfo['shares']
		retry = pinfo.get('retry', 0) + 1
		if side == 'sell':
			g.holding[stock] = True
		msg2 = _order_remark(side, stock, shares, retry)
		if side == 'sell':
			passorder(g.sell_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg2, C)
			g.holding[stock] = False
		else:
			passorder(g.buy_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg2, C)
		g.waiting_list.append(msg2)
		g.pending_orders[msg2] = {'time': time.time(), 'stock': stock, 'side': side, 'shares': shares, 'retry': retry}
		print('超时撤单重下', side, stock, shares, 'retry=%d' % retry)


def _scan_candidates(C, bar_date_str, all_stocks, holdings, tick_map=None):
	"""日线数据筛选，返回 (candidates, stats)。

	candidates: [(stock, close, sort_val, today_return), ...]
	stats: 各阶段数量；sideways_codes 为仅通过横盘（未要求突破等）的股票代码列表。
	"""
	candidates = []
	stats = {
		'pool': len(all_stocks),
		'eligible': 0,
		'data_ok': 0,
		'price_ok': 0,
		'sideways_ok': 0,
		'sideways_codes': [],
		'blocked_high': 0,
		'blocked_breakout': 0,
		'blocked_3down': 0,
		'except_fail': 0,
	}
	for stock in all_stocks:
		if stock in holdings or g.holding.get(stock, False) or _is_chinext_star_bse_or_st(stock):
			continue
		stats['eligible'] += 1
		try:
			data = C.get_market_data_ex(
				['close', 'high', 'low'], [stock],
				end_time=bar_date_str, period='1d', count=g.bar_count, subscribe=False
			)
			if stock not in data or len(data[stock]['close']) < g.min_closes_for_buy:
				continue
			stats['data_ok'] += 1
			closes = list(data[stock]['close'])
			highs = list(data[stock]['high'])
			lows = list(data[stock]['low'])
			if len(closes) < 2:
				continue
			prev_close = float(closes[-2])
			daily_last_close = float(closes[-1])
			if prev_close <= 0:
				continue
			current_price = _get_current_price(C, stock, bar_date_str, daily_last_close, tick_map)
			if current_price <= 0 or current_price < g.min_price:
				continue
			stats['price_ok'] += 1
			avg_amp, price_range = calculate_sideways_metrics(highs, lows, closes, g.sideways_days)
			if not (g.amp_min <= avg_amp <= g.amp_max) or price_range > g.price_range_max:
				continue
			stats['sideways_ok'] += 1
			stats['sideways_codes'].append(stock)
			today_return = (current_price - prev_close) / prev_close
			today_high_return = (float(highs[-1]) - prev_close) / prev_close if prev_close > 0 else 0
			if today_high_return >= g.today_high_return_max:
				stats['blocked_high'] += 1
				continue
			if today_return <= avg_amp * g.breakout_amp_mult or today_return >= g.today_return_max:
				stats['blocked_breakout'] += 1
				continue
			if _is_three_consecutive_down(closes):
				stats['blocked_3down'] += 1
				continue
			sort_val = _get_sort_value(C, stock, current_price)
			candidates.append((stock, current_price, sort_val, today_return))
		except Exception:
			stats['except_fail'] += 1
	if g.sort_by_factor == 'market_cap' and candidates:
		candidates.sort(key=lambda x: x[2])
	return candidates, stats


def handlebar(C):
	if not C.is_last_bar():
		return
	bp = getattr(C, 'barpos', None)
	if bp is not None and bp == getattr(g, '_last_handlebar_barpos', None):
		return
	g._last_handlebar_barpos = bp

	now = datetime.datetime.now()
	now_time = now.strftime('%H%M%S')
	if now_time < '093000' or now_time > '150000':
		return

	bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	current_date_str = bar_date_str[:8]

	try:
		account = get_trade_detail_data(g.accid, g.account_type, 'account')
	except Exception:
		account = []
	if not account:
		print('账号 %s 未登录' % g.accid)
		return
	account = account[0]
	available_cash = int(getattr(account, 'm_dAvailable', 0))

	if g.waiting_list:
		found_list = []
		try:
			deals = get_trade_detail_data(g.accid, g.account_type, 'deal')
			for deal in deals:
				remark = getattr(deal, 'm_strRemark', '') or ''
				if remark in g.waiting_list:
					found_list.append(remark)
		except Exception:
			pass
		for r in found_list:
			pinfo = g.pending_orders.get(r)
			if pinfo and pinfo.get('side') == 'sell':
				s = pinfo['stock']
				for d in [g.buy_price, g.buy_shares, g.buy_date, g.buy_barpos]:
					d.pop(s, None)
			if r in g.waiting_list:
				g.waiting_list.remove(r)
			g.pending_orders.pop(r, None)
	_do_withdraw_and_retry(C)
	if g.waiting_list:
		if _in_buy_window(now_time):
			print('[%s] 有未成交委托 暂停报单' % now_time)
		return

	try:
		positions = get_trade_detail_data(g.accid, g.account_type, 'position')
		holdings = {}
		position_objs = {}
		for i in positions:
			code = _normalize_position_code(i)
			if not code:
				continue
			vol = getattr(i, 'm_nCanUseVolume', 0) or 0
			holdings[code] = vol
			position_objs[code] = i
	except Exception:
		holdings = {}
		position_objs = {}

	for code in list(g.holding.keys()):
		g.holding[code] = (code in holdings)
	for code in holdings:
		g.holding[code] = True
		if code not in g.buy_price and code in position_objs:
			g.buy_price[code] = getattr(position_objs[code], 'm_dOpenPrice', None) or getattr(position_objs[code], 'm_dCost', None)
		if code not in g.buy_shares and code in holdings:
			g.buy_shares[code] = (holdings[code] // 100) * 100
		if code not in g.buy_date:
			g.buy_date[code] = current_date_str
		if code not in g.buy_barpos:
			g.buy_barpos[code] = C.barpos

	# ---------- 卖出：仅 ATR 移动止损（无总亏损止损）；卖出日志不受买入窗口限制 ----------
	tick_holdings, _ = _build_full_tick_prices(C, list(holdings.keys()))
	for stock in list(holdings.keys()):
		can_use = holdings.get(stock, 0)
		if can_use < g.min_shares:
			continue
		try:
			bd = g.buy_date.get(stock, current_date_str)
			days_cal = _calendar_days_held(bd, current_date_str)
			in_min_hold = days_cal < g.min_hold_days

			bar_count = max(g.bar_count, days_cal + 20, g.atr_period + 5)
			data = C.get_market_data_ex(
				['close', 'high', 'low', 'open'], [stock],
				end_time=bar_date_str, period='1d', count=bar_count, subscribe=False
			)
			if stock not in data or len(data[stock]['close']) < 2:
				continue
			closes = list(data[stock]['close'])
			highs = list(data[stock]['high'])
			lows = list(data[stock]['low'])
			day_close = closes[-1]
			current_price = _get_current_price(C, stock, bar_date_str, day_close, tick_holdings)
			if talib is None or in_min_hold:
				continue
			n_since = min(max(1, days_cal + 1), len(highs))
			highest_high_since_entry = max(highs[-n_since:])
			high_arr = np.array(highs, dtype=np.float64)
			low_arr = np.array(lows, dtype=np.float64)
			close_arr = np.array(closes, dtype=np.float64)
			atr_arr = talib.ATR(high_arr, low_arr, close_arr, g.atr_period)
			atr_14 = float(atr_arr[-1]) if len(atr_arr) and not np.isnan(atr_arr[-1]) else None
			if atr_14 is None or atr_14 <= 0:
				continue
			stop_loss = highest_high_since_entry - atr_14 * g.atr_stop_mult
			if current_price <= stop_loss and not _has_pending_order(stock, 'sell'):
				shares = g.buy_shares.get(stock) or (can_use // 100) * 100
				shares = min(shares, can_use // 100 * 100)
				if shares >= g.min_shares:
					msg = _order_remark('sell', stock, shares)
					passorder(g.sell_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg, C)
					g.holding[stock] = False
					g.waiting_list.append(msg)
					g.pending_orders[msg] = {'time': time.time(), 'stock': stock, 'side': 'sell', 'shares': shares, 'retry': 0}
					print(bar_date_str, '卖出', stock, shares, 'ATR移动止损')
		except Exception as e:
			print('卖出异常', stock, e)

	# ---------- 买入窗口：仅此时拉股票池、检查深证 MA240、打买入相关日志并下单 ----------
	if not _in_buy_window(now_time):
		return

	all_stocks = get_stock_pool(C, bar_date_str)
	sz_below_ma240 = _is_sz_below_ma240(C, bar_date_str)
	print('[%s] 深证指数: %s' % (bar_date_str, '破MA240不开新仓' if sz_below_ma240 else '未破MA240'))

	current_holdings = sum(1 for h in g.holding.values() if h)
	if current_holdings >= g.max_stocks:
		print('[%s] [筛选] 共0只: (跳过，持仓已满 %d/%d)' % (now_time, current_holdings, g.max_stocks))
		return

	if sz_below_ma240:
		if g._ma240_buy_warn_date != current_date_str:
			g._ma240_buy_warn_date = current_date_str
			print('[%s] 深证破MA240 本日买入窗口内不开新仓' % now_time)
		print('[%s] [筛选] 共0只: (跳过，深证破MA240不开新仓)' % now_time)
		return

	tick_for_screen, _ = _build_full_tick_prices(C, all_stocks)
	g.candidates_today, _scan_st = _scan_candidates(C, bar_date_str, all_stocks, holdings, tick_for_screen)

	n_cand = len(g.candidates_today)
	_sw = _scan_st.get('sideways_codes') or []
	_sw_str = ','.join(_sw) if _sw else '(无)'
	print('[%s] [横盘通过] 共%d只: %s' % (now_time, len(_sw), _sw_str))
	codes_list = [r[0] for r in g.candidates_today]
	# 代码过多时截断显示，避免日志过长
	_max_show = 80
	if len(codes_list) <= _max_show:
		codes_str = ','.join(codes_list) if codes_list else '(无)'
	else:
		codes_str = ','.join(codes_list[:_max_show]) + ' ...（另%d只）' % (len(codes_list) - _max_show)
	print('[%s] [筛选] 共%d只: %s' % (now_time, n_cand, codes_str))

	if not g.candidates_today:
		return

	slots_to_fill = min(g.max_stocks - current_holdings, len(g.candidates_today))
	if slots_to_fill <= 0:
		return

	all_codes = [r[0] for r in g.candidates_today]
	tick_snapshot, _ = _build_full_tick_prices(C, all_codes)
	ordered = 0
	for row in g.candidates_today:
		if ordered >= slots_to_fill:
			break
		stock = row[0]
		fallback_close = row[1]
		ret_vs_prev = float(row[3]) if len(row) >= 4 else 0.0
		if stock in holdings or g.holding.get(stock, False) or _has_pending_order(stock, 'buy'):
			continue
		current_price = _get_current_price(C, stock, bar_date_str, fallback_close, tick_snapshot)
		if current_price <= 0 or current_price < g.min_price:
			continue
		target_shares = int(g.per_stock_amount / current_price)
		shares = (target_shares // g.min_shares) * g.min_shares
		if shares < g.min_shares or shares > g.max_shares_per_order:
			continue
		if g.per_stock_amount > available_cash:
			print('[%s] 可用资金不足 跳过后续买入' % now_time)
			break
		msg = _order_remark('buy', stock, shares)
		passorder(g.buy_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg, C)
		g.holding[stock] = True
		g.buy_price[stock] = current_price
		g.buy_shares[stock] = shares
		g.buy_date[stock] = current_date_str
		g.buy_barpos[stock] = C.barpos
		g.waiting_list.append(msg)
		g.pending_orders[msg] = {'time': time.time(), 'stock': stock, 'side': 'buy', 'shares': shares, 'retry': 0}
		ordered += 1
		available_cash -= g.per_stock_amount
		print('[%s] 下单 %s %d股 @%.3f 涨跌幅(相对昨收)=%.2f%%' % (now_time, stock, shares, current_price, ret_vs_prev * 100.0))
		try:
			acc_list = get_trade_detail_data(g.accid, g.account_type, 'account')
			if acc_list:
				available_cash = int(getattr(acc_list[0], 'm_dAvailable', 0))
		except Exception:
			pass

	if ordered > 0:
		print('[%s] 本轮下单 %d 只（买入窗口 14:45-14:55；持仓满 %d 只或 14:55 后不再买）' % (now_time, ordered, g.max_stocks))
