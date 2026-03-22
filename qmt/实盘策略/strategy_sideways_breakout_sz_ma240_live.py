#coding:gbk
"""
横盘异动突破策略（振幅+波动）+ 深证MA240 — 实盘版
- 尾盘 14:30-14:45 筛选股票，14:45 集中下单
- 横盘+突破+深证未破MA240 同回测版；卖出：7%%止损/单日大跌8%%/MA3拐头或破线，最少持有 min_hold_days
- 框架参考 strategy_sideways_breakout_official_style：G 类、get_trade_detail_data、passorder 备注、waiting_list、撤单重下
"""

import numpy as np
import time
import datetime

SZ_INDEX_CODE = '399001.SZ'


class G:
	"""策略全局状态"""
	pass


g = G()


def _order_remark(side, stock, shares, retry=0):
	s = 'HB%s%s_%s' % ('B' if side == 'buy' else 'S', stock, shares)
	return ('%s_R%d' % (s, retry)) if retry else s


def _has_pending_order(stock, side):
	return any(p.get('stock') == stock and p.get('side') == side for p in g.pending_orders.values())


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

	# 策略参数（与回测一致）
	g.max_stocks = 10
	g.per_stock_amount = 100000
	g.min_hold_days = 7
	g.sort_by_factor = getattr(C, 'sort_by_factor', 'market_cap')
	g.amp_min = getattr(C, 'amp_min', 0.03)
	g.amp_max = 0.05
	g.price_range_max = 1.15
	g.sideways_days = 20
	g.min_closes_for_buy = 22
	g.breakout_amp_mult = 1.3
	g.today_return_max = 0.08
	g.min_price = 3.0
	g.min_shares = 100
	g.max_shares_per_order = 10000
	g.stop_loss_total = 0.07
	g.stop_loss_single_day = 0.08
	g.ma3_turn_down_ratio = 0.998
	g.sz_ma240_count = 250
	g.sz_ma240_period = 240
	g.bar_count = 25

	# 尾盘时段与当日下单标记
	g.candidates_today = []
	g.ordered_at_date = ''
	g.screened_at_date = ''   # 当日已筛选日期，14:45 若未筛过则补跑一次
	if not g.accid:
		print('[实盘] 警告: accid 为空，请在策略设置中指定交易账户')
	print('横盘突破+深证MA240 实盘 14:30-14:45筛选 14:45下单 accid=%s' % g.accid)


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
	reason = ""
	if not stock_list:
		return out, "股票列表为空"
	if not hasattr(C, 'get_full_tick'):
		return out, "无 get_full_tick"
	try:
		ticks = C.get_full_tick(stock_list)
		if not ticks:
			return out, "get_full_tick 返回为空"
		for code, t in ticks.items():
			p = _parse_tick_price(t)
			if p is not None and p > 0:
				out[code] = p
		if not out:
			return out, "解析不到 last_price"
	except Exception as e:
		return out, "get_full_tick 异常: %s" % (str(e)[:80])
	return out, ""


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
		for index_code in ['399007.SZ']:
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


def _get_sort_value(C, stock_code, current_close):
	if g.sort_by_factor != 'market_cap':
		return 0
	try:
		if hasattr(C, 'get_instrument_detail'):
			info = C.get_instrument_detail([stock_code])
			if info and stock_code in info:
				inf = info[stock_code]
				if inf.get('circulation_market_value', 0) > 0:
					return float(inf['circulation_market_value'])
				if inf.get('market_value', 0) > 0:
					return float(inf['market_value'])
	except Exception:
		pass
	return float(current_close)


def _is_chinext_star_bse_or_st(stock_code):
	if not stock_code or len(stock_code) < 6:
		return False
	code = stock_code.split('.')[0]
	if code == '000408':
		return True
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


def handlebar(C):
	if not C.is_last_bar():
		return
	now = datetime.datetime.now()
	now_time = now.strftime('%H%M%S')
	# 仅尾盘 14:30-15:00 运行
	if now_time < '143000' or now_time > '150000':
		return

	bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	current_date_str = bar_date_str[:8]
	chart_period = getattr(C, 'period', '1d') or '1d'
	is_daily = (chart_period == '1d' or chart_period == '1D')

	try:
		account = get_trade_detail_data(g.accid, g.account_type, 'account')
	except Exception:
		account = []
	if not account:
		print('账号 %s 未登录' % g.accid)
		return
	account = account[0]
	available_cash = int(getattr(account, 'm_dAvailable', 0))

	# 成交回报：从 waiting_list 移除已成交
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

	# 同步 g.holding 与买入记录
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
			g.buy_barpos[code] = C.barpos if is_daily else 0

	all_stocks = get_stock_pool(C, bar_date_str)

	# 深证MA240：仅用于买入是否开新仓
	sz_below_ma240 = _is_sz_below_ma240(C, bar_date_str)
	print('[%s] 深证指数: %s' % (bar_date_str, '破MA240不开新仓' if sz_below_ma240 else '未破MA240'))

	# ---------- 卖出：先执行，释放仓位 ----------
	tick_holdings, _ = _build_full_tick_prices(C, list(holdings.keys()))
	for stock in list(holdings.keys()):
		can_use = holdings.get(stock, 0)
		if can_use < g.min_shares:
			continue
		try:
			data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period='1d', count=g.bar_count, subscribe=False)
			if stock not in data or len(data[stock]['close']) < 2:
				continue
			closes = list(data[stock]['close'])
			opens = list(data[stock]['open'])
			highs = list(data[stock]['high'])
			lows = list(data[stock]['low'])
			day_close = closes[-1]
			current_price = _get_current_price(C, stock, bar_date_str, day_close, tick_holdings)
			pos_obj = position_objs.get(stock)
			buy_price = g.buy_price.get(stock) or (getattr(pos_obj, 'm_dOpenPrice', None) if pos_obj else None) or current_price
			today_open = opens[-1]
			today_low = lows[-1]
			if today_open <= 0:
				continue
			total_loss = (current_price - buy_price) / buy_price if buy_price else 0
			today_ret = (current_price - today_open) / today_open
			today_low_ret = (today_low - today_open) / today_open
			buy_bar = g.buy_barpos.get(stock, C.barpos)
			days_held = max(0, C.barpos - buy_bar) if is_daily else 0
			in_min_hold = days_held < g.min_hold_days
			ma_3_prev = np.mean(closes[-4:-1]) if len(closes) >= 5 else None
			ma_3_today = np.mean(closes[-3:]) if len(closes) >= 5 else None
			sell_condition = False
			sell_reason = ''
			if total_loss < -g.stop_loss_total:
				sell_condition, sell_reason = True, '总亏损%.0f%%止损' % (g.stop_loss_total * 100)
			elif today_ret < -g.stop_loss_single_day or today_low_ret < -g.stop_loss_single_day:
				sell_condition, sell_reason = True, '单日大跌'
			elif not in_min_hold and ma_3_prev is not None and ma_3_today is not None:
				if ma_3_today < ma_3_prev * g.ma3_turn_down_ratio and current_price < ma_3_today:
					sell_condition, sell_reason = True, 'MA3拐头向下'
				elif current_price < ma_3_prev:
					sell_condition, sell_reason = True, '破3日线'
			if sell_condition and not _has_pending_order(stock, 'sell'):
				shares = g.buy_shares.get(stock) or (can_use // 100) * 100
				shares = min(shares, can_use // 100 * 100)
				if shares >= g.min_shares:
					msg = _order_remark('sell', stock, shares)
					passorder(g.sell_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg, C)
					g.holding[stock] = False
					g.waiting_list.append(msg)
					g.pending_orders[msg] = {'time': time.time(), 'stock': stock, 'side': 'sell', 'shares': shares, 'retry': 0}
					print(bar_date_str, '卖出', stock, shares, sell_reason)
		except Exception as e:
			print('卖出异常', stock, e)

	# ---------- 14:30-14:45 筛选：更新当日候选 ----------
	if '143000' <= now_time < '144500':
		g.candidates_today = []
		if sz_below_ma240:
			print('[%s] 14:30-14:45 筛选: 深证破MA240 不筛买入候选' % now_time)
		else:
			for stock in all_stocks:
				if stock in holdings or g.holding.get(stock, False) or _is_chinext_star_bse_or_st(stock):
					continue
				try:
					data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period='1d', count=g.bar_count, subscribe=False)
					if stock not in data or len(data[stock]['close']) < g.min_closes_for_buy:
						continue
					closes = list(data[stock]['close'])
					highs = list(data[stock]['high'])
					lows = list(data[stock]['low'])
					opens = list(data[stock]['open'])
					current_close = closes[-1]
					today_open = opens[-1]
					if current_close <= 0 or today_open <= 0 or current_close <= g.min_price:
						continue
					avg_amp, price_range = calculate_sideways_metrics(highs, lows, closes, g.sideways_days)
					if not (g.amp_min <= avg_amp <= g.amp_max) or price_range > g.price_range_max:
						continue
					today_return = (current_close - today_open) / today_open
					if today_return <= avg_amp * g.breakout_amp_mult or today_return >= g.today_return_max:
						continue
					if _is_three_consecutive_down(closes):
						continue
					sort_val = _get_sort_value(C, stock, current_close)
					g.candidates_today.append((stock, current_close, sort_val))
				except Exception:
					pass
			if g.sort_by_factor == 'market_cap' and g.candidates_today:
				g.candidates_today.sort(key=lambda x: x[2])
			g.screened_at_date = current_date_str
			print('[%s] 14:30-14:45 筛选完成 候选 %d 只' % (now_time, len(g.candidates_today)))

	# ---------- 14:45 下单 ----------
	if now_time >= '144500' and g.ordered_at_date != current_date_str:
		current_holdings = sum(1 for h in g.holding.values() if h)
		# 若 14:30-14:45 未跑过（如策略 14:45 才启动），则 14:45 做一次筛选
		if not getattr(g, 'screened_at_date', None) == current_date_str and not sz_below_ma240:
			g.candidates_today = []
			for stock in all_stocks:
				if stock in holdings or g.holding.get(stock, False) or _is_chinext_star_bse_or_st(stock):
					continue
				try:
					data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period='1d', count=g.bar_count, subscribe=False)
					if stock not in data or len(data[stock]['close']) < g.min_closes_for_buy:
						continue
					closes, highs, lows, opens = list(data[stock]['close']), list(data[stock]['high']), list(data[stock]['low']), list(data[stock]['open'])
					current_close, today_open = closes[-1], opens[-1]
					if current_close <= 0 or today_open <= 0 or current_close <= g.min_price:
						continue
					avg_amp, price_range = calculate_sideways_metrics(highs, lows, closes, g.sideways_days)
					if not (g.amp_min <= avg_amp <= g.amp_max) or price_range > g.price_range_max:
						continue
					today_return = (current_close - today_open) / today_open
					if today_return <= avg_amp * g.breakout_amp_mult or today_return >= g.today_return_max or _is_three_consecutive_down(closes):
						continue
					g.candidates_today.append((stock, current_close, _get_sort_value(C, stock, current_close)))
				except Exception:
					pass
			if g.sort_by_factor == 'market_cap' and g.candidates_today:
				g.candidates_today.sort(key=lambda x: x[2])
			g.screened_at_date = current_date_str
		need_buy = min(g.max_stocks - current_holdings, len(g.candidates_today))
		if need_buy <= 0:
			g.ordered_at_date = current_date_str
			return
		# 取候选当前价（14:45 用全推或日收）
		candidate_stocks = [g.candidates_today[i][0] for i in range(need_buy)]
		tick_snapshot, _ = _build_full_tick_prices(C, candidate_stocks)
		ordered = 0
		for i in range(need_buy):
			stock, fallback_close, _ = g.candidates_today[i]
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
			g.buy_barpos[stock] = C.barpos if is_daily else 0
			g.waiting_list.append(msg)
			g.pending_orders[msg] = {'time': time.time(), 'stock': stock, 'side': 'buy', 'shares': shares, 'retry': 0}
			ordered += 1
			available_cash -= g.per_stock_amount
			print(bar_date_str, '14:45 买入', stock, shares, '@', current_price)
			try:
				acc_list = get_trade_detail_data(g.accid, g.account_type, 'account')
				if acc_list:
					available_cash = int(getattr(acc_list[0], 'm_dAvailable', 0))
			except Exception:
				pass
		g.ordered_at_date = current_date_str
		if ordered > 0:
			print('[%s] 14:45 下单完成 共 %d 只' % (now_time, ordered))
