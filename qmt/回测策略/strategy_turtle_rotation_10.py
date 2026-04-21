# -*- coding: utf-8 -*-
"""
QMT backtest: Turtle breakout (20d high / 10d low exit) + index universe scan.
Flow: scan pool -> entry_cross -> rank by momentum -> buy up to max_holdings, 100k per stock max.
No pyramid adds. Position: min(100000, available cash) per order, 100-share lot.
"""

import numpy as np
import time


def _ohlc_to_list(raw):
	if raw is None:
		return []
	try:
		import pandas as pd
		if isinstance(raw, pd.Series):
			return raw.tolist()
		if isinstance(raw, pd.DataFrame):
			return raw.iloc[:, 0].tolist()
	except Exception:
		pass
	if hasattr(raw, 'tolist') and not isinstance(raw, (list, tuple, bytes)):
		try:
			return list(raw.tolist())
		except Exception:
			pass
	try:
		return list(raw)
	except Exception:
		return []


def _timetag_to_str(timetag, fmt='%Y%m%d%H%M%S'):
	try:
		return time.strftime(fmt, time.localtime(timetag / 1000))
	except Exception:
		try:
			return time.strftime(fmt, time.localtime(timetag))
		except Exception:
			return str(timetag)


def _calc_tr_series(highs, lows, closes):
	highs = _ohlc_to_list(highs)
	lows = _ohlc_to_list(lows)
	closes = _ohlc_to_list(closes)
	n = min(len(highs), len(lows), len(closes))
	if n < 2:
		return []
	tr_list = []
	for i in range(1, n):
		h, l, pc = highs[i], lows[i], closes[i - 1]
		tr = max(h - l, abs(h - pc), abs(l - pc))
		tr_list.append(tr)
	return tr_list


def _calc_atr_sma(highs, lows, closes, period=14):
	tr_list = _calc_tr_series(highs, lows, closes)
	if len(tr_list) < period:
		return None
	return float(np.mean(tr_list[-period:]))


def _round_shares_a_share(shares, lot=100):
	if shares is None or shares <= 0:
		return 0
	n = int(shares // lot) * lot
	return n if n >= lot else 0


def _empty_state():
	return {
		'total_shares': 0,
		'first_buy_price': 0.0,
	}


def init(C):
	C.accountid = getattr(C, 'accountid', '') or 'turtle_rotation'

	# Universe: multi-index constituents union (same idea as strategy_momentum_trend_rotation)
	C.stock_pool_indices = ['000300.SH', '000905.SH', '000852.SH', '399006.SZ', '399001.SZ']
	C.stock_pool_scan_cap = 800
	# Optional: if non-empty, only trade these codes (fixed list) instead of scanning indices
	C.stock_pool_override = []

	C.max_holdings = 10
	C.per_stock_cap = 100000.0
	C.entry_period = 20
	C.exit_period = 10
	C.atr_period = 14
	C.stop_loss_atr = 2.0
	C.min_shares = 100
	C.cash_use_ratio = 0.97
	C.buy_cost_buffer = 1.002

	# Momentum ranking (only among names with entry_cross today)
	C.mom_short = 5
	C.mom_mid = 20
	C.mom_w_short = 0.45
	C.mom_w_mid = 0.55

	C.data_count = max(C.entry_period + 5, C.exit_period + 5, C.atr_period + 25, C.mom_mid + 5, 80)

	# Dynamic: stock_code -> state; only stocks with position need full state
	C.turtle = {}
	C.initial_capital = 1000000.0


def _get_equity(C):
	try:
		acc = get_trade_detail_data(C.accountid, 'stock', 'account')
		if acc:
			return float(acc[0].m_dBalance)
	except Exception:
		pass
	return float(getattr(C, 'initial_capital', 0.0) or 1e6)


def _get_available_cash(C):
	try:
		acc = get_trade_detail_data(C.accountid, 'stock', 'account')
		if acc:
			return float(acc[0].m_dAvailable)
	except Exception:
		pass
	return float(getattr(C, 'initial_capital', 0.0) or 1e6)


def _shares_fixed_cap(cash, price, per_cap, min_shares, cash_ratio):
	if price <= 0:
		return 0
	budget = min(cash * cash_ratio, per_cap)
	return _round_shares_a_share(budget / price, min_shares)


def get_stock_pool(C, _current_date_str):
	all_stocks = []
	override = getattr(C, 'stock_pool_override', None) or []
	if override:
		return list(override)
	try:
		index_stocks = []
		for index_code in getattr(C, 'stock_pool_indices', []):
			try:
				if hasattr(C, 'get_index_constituent'):
					stocks = C.get_index_constituent(index_code)
					if stocks:
						index_stocks.extend(stocks)
				elif hasattr(C, 'get_stock_list_in_sector'):
					stocks = C.get_stock_list_in_sector(index_code)
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
	except Exception:
		pass
	return all_stocks


def is_chinext_star_bse_or_st(C, stock_code):
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
	try:
		name = C.get_stock_name(stock_code)
		if name and ('ST' in name.upper() or '*ST' in name or 'S*ST' in name):
			return True
	except Exception:
		pass
	return False


def _mom_score(closes, short_n, mid_n, w_short, w_mid):
	if not closes or len(closes) < mid_n + 2:
		return None
	c = np.array(closes, dtype=float)
	if c[-1] <= 0 or c[-short_n - 1] <= 0 or c[-mid_n - 1] <= 0:
		return None
	r_s = c[-1] / c[-short_n - 1] - 1.0
	r_m = c[-1] / c[-mid_n - 1] - 1.0
	return float(w_short * r_s + w_mid * r_m)


def _parse_ohlc(C, stock, bar_date_str):
	try:
		data = C.get_market_data_ex(
			['close', 'high', 'low'],
			[stock],
			end_time=bar_date_str,
			period='1d',
			count=C.data_count,
			subscribe=False,
		)
	except Exception:
		return None
	if data is None or not isinstance(data, dict) or stock not in data:
		return None
	d = data[stock]
	if isinstance(d, dict):
		closes = _ohlc_to_list(d.get('close'))
		highs = _ohlc_to_list(d.get('high'))
		lows = _ohlc_to_list(d.get('low'))
	else:
		try:
			import pandas as pd
			if isinstance(d, pd.DataFrame) and all(c in d.columns for c in ('close', 'high', 'low')):
				closes = _ohlc_to_list(d['close'])
				highs = _ohlc_to_list(d['high'])
				lows = _ohlc_to_list(d['low'])
			else:
				return None
		except Exception:
			return None
	if len(closes) < C.entry_period + 3 or len(highs) < C.entry_period + 3 or len(lows) < C.exit_period + 3:
		return None
	return closes, highs, lows


def handlebar(C):
	try:
		bar_timetag = C.get_bar_timetag(C.barpos)
	except Exception:
		return

	bar_date_str = _timetag_to_str(bar_timetag, '%Y%m%d%H%M%S')

	cash_left = _get_available_cash(C)
	fee_buf = float(getattr(C, 'buy_cost_buffer', 1.002))
	cash_ratio = float(getattr(C, 'cash_use_ratio', 0.97))
	per_cap = float(getattr(C, 'per_stock_cap', 100000.0))

	universe = get_stock_pool(C, bar_date_str[:8])
	cap_n = int(getattr(C, 'stock_pool_scan_cap', 800))
	if not universe:
		return
	universe = universe[:cap_n]

	# ---------- Pass 1: exits / stops for held names only ----------
	for stock in list(C.turtle.keys()):
		st = C.turtle[stock]
		if st.get('total_shares', 0) < C.min_shares:
			continue

		parsed = _parse_ohlc(C, stock, bar_date_str)
		if not parsed:
			continue
		closes, highs, lows = parsed

		cur = float(closes[-1])
		prev = float(closes[-2])
		atr = _calc_atr_sma(highs, lows, closes, C.atr_period)
		if atr is None or atr <= 0:
			continue

		low_today = min(float(x) for x in lows[-(C.exit_period + 1):-1])
		low_yesterday = min(float(x) for x in lows[-(C.exit_period + 2):-2])
		exit_cross = cur < low_today and prev >= low_yesterday

		sh = st['total_shares']
		# Stop
		if st.get('first_buy_price', 0) > 0:
			stop_line = st['first_buy_price'] - C.stop_loss_atr * atr
			if cur < stop_line:
				passorder(24, 1101, C.accountid, stock, 5, 0, sh, 'turtle_sl', 1, '', C)
				C.turtle[stock] = _empty_state()
				continue
		# Exit channel
		if exit_cross:
			passorder(24, 1101, C.accountid, stock, 5, 0, sh, 'turtle_exit', 1, '', C)
			C.turtle[stock] = _empty_state()

	# Refresh cash after sells (same bar; local tracker)
	cash_left = _get_available_cash(C)

	# ---------- Pass 2: scan breakouts, rank momentum, buy ----------
	entry_short = getattr(C, 'mom_short', 5)
	entry_mid = getattr(C, 'mom_mid', 20)
	candidates = []

	for stock in universe:
		if is_chinext_star_bse_or_st(C, stock):
			continue
		st = C.turtle.get(stock)
		if st and st.get('total_shares', 0) >= C.min_shares:
			continue

		parsed = _parse_ohlc(C, stock, bar_date_str)
		if not parsed:
			continue
		closes, highs, lows = parsed
		if len(closes) < entry_mid + 3:
			continue

		cur = float(closes[-1])
		prev = float(closes[-2])

		upper_today = max(float(x) for x in highs[-(C.entry_period + 1):-1])
		upper_yesterday = max(float(x) for x in highs[-(C.entry_period + 2):-2])
		entry_cross = cur > upper_today and prev <= upper_yesterday
		if not entry_cross:
			continue

		score = _mom_score(
			closes, entry_short, entry_mid,
			float(getattr(C, 'mom_w_short', 0.45)),
			float(getattr(C, 'mom_w_mid', 0.55)),
		)
		if score is None:
			continue
		candidates.append({'stock': stock, 'score': score, 'price': cur})

	candidates.sort(key=lambda x: x['score'], reverse=True)

	n_hold = sum(1 for s in C.turtle.values() if s.get('total_shares', 0) >= C.min_shares)
	max_h = int(getattr(C, 'max_holdings', 10))

	for c in candidates:
		if n_hold >= max_h:
			break
		stock = c['stock']
		st = C.turtle.get(stock)
		if st and st.get('total_shares', 0) >= C.min_shares:
			continue

		cur = c['price']
		vol = _shares_fixed_cap(cash_left, cur, per_cap, C.min_shares, cash_ratio)
		if vol < C.min_shares:
			continue

		passorder(23, 1101, C.accountid, stock, 5, 0, vol, 'turtle_entry', 1, '', C)
		cash_left = max(0.0, cash_left - vol * cur * fee_buf)
		C.turtle[stock] = {'total_shares': vol, 'first_buy_price': cur}
		n_hold += 1
