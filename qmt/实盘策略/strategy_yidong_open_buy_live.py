#coding:gbk
import datetime
import sys
import time

STRATEGY_TAG = '[\u5361\u5f02\u52a8\u5f00\u76d8\u4e70]'
DEFAULT_SECTOR = '\u5361\u5f02\u52a8\u5f00\u76d8\u4e70\u5165\u6c60'
SESSION_AM_START, SESSION_AM_END = 92500, 113000
SESSION_PM_START, SESSION_PM_END = 130000, 150000
BUY_WINDOW_START, BUY_WINDOW_END = 92500, 93559
NO_RETRY_UNTIL_HMS = 93000  # 9:30前不因未成交撤单重挂(集合竞价委托状态不可见)
REMARK_PREFIX = 'YDO'
DEFAULT_ACCID = '30262698'
DEFAULT_MAX_AMOUNT_PER_STOCK = 100000.0
DEFAULT_MIN_SHARES = 100
DEFAULT_WITHDRAW_SECS = 15
DEFAULT_BUY_PREMIUM_PCT = 0.005
DEFAULT_PREMIUM_RETRY_STEP = 0.0
DEFAULT_AUCTION_TIMER_PERIOD = '5nSecond'
DEFAULT_AUCTION_TIMER_START = '09:25:00'


def _passorder_fn():
	fn = getattr(sys.modules.get('__main__'), 'passorder', None)
	return fn if fn else globals().get('passorder')


def _cancel_fn():
	fn = getattr(sys.modules.get('__main__'), 'cancel', None)
	return fn if fn else globals().get('cancel')


def _get_trade_detail_data_fn():
	fn = getattr(sys.modules.get('__main__'), 'get_trade_detail_data', None)
	return fn if fn else globals().get('get_trade_detail_data')


class G(object):
	pass


g = G()


def timetag_to_datetime(timetag, format_str='%Y%m%d%H%M%S'):
	for div in (1000.0, 1.0):
		try:
			return time.strftime(format_str, time.localtime(float(timetag) / div if div > 1 else float(timetag)))
		except Exception:
			pass
	return str(timetag)


def _canonical_stock_code(s):
	if s is None:
		return ''
	t = str(s).strip().upper().replace('\u3000', ' ')
	if not t:
		return ''
	if '.' in t:
		a, b = t.split('.', 1)
		if len(a) == 6 and a.isdigit() and b in ('SH', 'SZ', 'BJ'):
			return '%s.%s' % (a, b)
		if a in ('SH', 'SZ', 'BJ') and len(b) == 6 and b.isdigit():
			return '%s.%s' % (b, a)
	if len(t) >= 8 and t[:2] in ('SH', 'SZ', 'BJ') and t[2:8].isdigit():
		return '%s.%s' % (t[2:8], t[:2])
	if len(t) == 6 and t.isdigit():
		return (t + '.SH') if t.startswith(('60', '68', '51')) else (t + '.SZ')
	return t


def _normalize_position_code(pos):
	if pos is None:
		return ''
	ins = str(getattr(pos, 'm_strInstrumentID', None) or getattr(pos, 'stock_code', None) or '').strip()
	ex = str(getattr(pos, 'm_strExchangeID', None) or getattr(pos, 'exchange_id', None) or '').upper().strip()
	if '.' in ins:
		return _canonical_stock_code(ins)
	if not ins:
		return ''
	if ex in ('SH', 'SS', '\u4e0a\u6d77'):
		return ins + '.SH'
	if ex in ('SZ', '\u6df1\u5733'):
		return ins + '.SZ'
	if ex:
		return ins + '.' + ex
	return (ins + '.SH') if ins.startswith(('60', '68', '51')) else (ins + '.SZ')


def _code6(sym):
	c = _canonical_stock_code(sym)
	return c.split('.', 1)[0] if c else ''


def _is_qmt_backtest_context(C):
	for a in ('do_back_test', 'doBackTest', 'isDoBackTest'):
		if bool(getattr(C, a, False)):
			return True
	rm = getattr(C, 'run_mode', None) or getattr(C, 'runMode', None)
	try:
		if rm is not None and int(rm) == 1:
			return True
	except (TypeError, ValueError):
		pass
	return isinstance(rm, str) and rm.strip().upper() in ('BACKTEST', 'TRUE', '1', 'T')


def _in_handlebar_session(hms):
	if hms is None:
		return False
	try:
		h = int(hms)
	except (TypeError, ValueError):
		return False
	return (SESSION_AM_START <= h <= SESSION_AM_END) or (SESSION_PM_START <= h <= SESSION_PM_END)


def _in_buy_window(hms):
	if hms is None:
		return False
	try:
		h = int(hms)
	except (TypeError, ValueError):
		return False
	return BUY_WINDOW_START <= h <= BUY_WINDOW_END


def _in_auction_no_retry_window(hms):
	"""9:25-9:30 集合竞价期间系统不显示委托结果，跳过撤单重挂。"""
	if hms is None:
		return False
	try:
		h = int(hms)
	except (TypeError, ValueError):
		return False
	return BUY_WINDOW_START <= h < NO_RETRY_UNTIL_HMS


def _wall_hhmmss():
	try:
		return int(datetime.datetime.now().strftime('%H%M%S'))
	except Exception:
		return None


def _passorder_time_ok(C):
	hms = getattr(g, '_handlebar_hhmmss', None) if _is_qmt_backtest_context(C) else _wall_hhmmss()
	if hms is None:
		return False
	hms = int(hms)
	return _in_buy_window(hms)


def _should_passorder(C):
	return bool(getattr(g, 'live_orders', True)) and bool((g.accid or '').strip()) and not _is_qmt_backtest_context(C)


def _passorder_go(C, op_code, stock, volume, remark, pr_type=11, pr_value=0.0):
	try:
		vol = (int(volume) // g.min_shares) * g.min_shares
	except Exception:
		return False
	if vol < g.min_shares or not _passorder_time_ok(C):
		return False
	note = str(remark or '')[:23].replace('|', '_')
	po = _passorder_fn()
	if po is None:
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, '\u65e0passorder', shares=vol, limit_px=pr_value, remark=note)
		return False
	try:
		pt = int(pr_type) if pr_type is not None else 11
		pv = max(0.01, round(float(pr_value), 3)) if pt == 11 else float(pr_value or 0)
		ret = po(int(op_code), 1101, g.accid, str(stock), pt, pv, vol,
		         str(g.strategy_order_name), int(g.quick_trade), note, C)
	except Exception as e:
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, 'passorder\u5f02\u5e38:%s' % e, shares=vol, remark=note)
		return False
	if ret is False:
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, '\u5238\u5546\u62d2\u5355', shares=vol, limit_px=pv, remark=note)
		return False
	return True


def _tick_px(t):
	if t is None:
		return None
	for k in ('lastPrice', 'last_price', 'm_nLastPrice', 'nLast'):
		v = getattr(t, k, None) if not isinstance(t, dict) else t.get(k)
		if v is not None:
			try:
				x = float(v)
				return x if x > 0 else None
			except Exception:
				pass
	return None


def _tick_pre_close(t):
	if t is None:
		return None
	for k in ('preClose', 'preclose', 'm_dPreClose', 'm_dPreClosePrice', 'lastClose', 'yesterdayClose'):
		v = getattr(t, k, None) if not isinstance(t, dict) else t.get(k)
		if v is not None:
			try:
				x = float(v)
				if x > 0:
					return x
			except Exception:
				pass
	return None


def _full_ticks(C, codes):
	out = {}
	if codes and hasattr(C, 'get_full_tick'):
		try:
			raw = C.get_full_tick(codes) or {}
			out.update(raw)
		except Exception:
			pass
	return out


def _tick_prices(C, codes):
	return dict((c, p) for c, t in _full_ticks(C, codes).items() for p in [_tick_px(t)] if p)


def _prev_close(C, stock, tick_obj, end_time_str):
	pc = _tick_pre_close(tick_obj)
	if pc and pc > 0:
		return pc
	if not hasattr(C, 'get_market_data_ex'):
		return None
	try:
		kw = dict(period='1d', count=3, subscribe=False)
		if end_time_str:
			kw['end_time'] = end_time_str
		data = C.get_market_data_ex(['close'], [stock], **kw) or {}
		stk = data.get(stock)
		if stk is None:
			for k in (stock, _canonical_stock_code(stock)):
				if k in data:
					stk = data[k]
					break
		cl = list((stk or {}).get('close') or getattr(stk, 'close', []) or [])
		if len(cl) >= 2:
			v = float(cl[-2])
			return v if v > 0 else None
		if cl:
			v = float(cl[-1])
			return v if v > 0 else None
	except Exception:
		pass
	return None


def _pct_chg(last_px, prev_close):
	try:
		pc = float(prev_close)
		return (float(last_px) / pc - 1.0) * 100.0 if pc > 0 else None
	except Exception:
		return None


def _pct_blocked(sym, last_px, prev_close):
	pct = _pct_chg(last_px, prev_close)
	if pct is None:
		return False, '\u65e0\u6da8\u8dcc\u5e45'
	c6 = _code6(sym)
	lo, hi = ((-30.0, -15.0) if c6.startswith(('68', '30')) else (-10.0, -8.0))
	if lo - 1e-6 <= pct <= hi + 1e-6:
		return True, '\u8dcc\u5e45\u5e26[%.0f%%,%.0f%%]' % (lo, hi)
	thr = 15.0 if c6.startswith(('68', '30')) else 8.0
	if pct > thr + 1e-6:
		return True, '\u6da8\u5e45>%.0f%%' % thr
	return False, 'OK'


def _buy_shares(cap, px):
	try:
		amt, p = float(cap), float(px)
	except Exception:
		return 0
	if amt <= 0 or p <= 0:
		return 0
	sh = int(amt / p / g.min_shares) * g.min_shares
	return sh if sh >= g.min_shares else 0


def _buy_premium_pct(retry=0):
	base = float(g.buy_premium_pct)
	step = float(getattr(g, 'buy_premium_retry_step', DEFAULT_PREMIUM_RETRY_STEP) or 0)
	return base + step * int(retry or 0)


def _limit_buy(last_px, retry=0):
	try:
		return max(0.01, round(float(last_px) * (1.0 + _buy_premium_pct(retry)), 3))
	except Exception:
		return None


def _remark(stock, shares, retry=0):
	base = '%s_%s_%d' % (REMARK_PREFIX, stock.replace('.', '_'), int(shares))
	return ((base + '_R%d' % retry) if retry else base)[:23]


def _stock_name(C, code):
	try:
		if hasattr(C, 'get_stock_name'):
			n = C.get_stock_name(code)
			if n:
				return str(n).strip()
	except Exception:
		pass
	try:
		fn = getattr(C, 'get_instrumentdetail', None) or getattr(C, 'get_instrumentDetail', None)
		if fn:
			d = fn(code)
			if isinstance(d, dict):
				for k in ('InstrumentName', 'm_strInstrumentName', 'name'):
					if d.get(k):
						return str(d[k]).strip()
	except Exception:
		pass
	return ''


def _log_today_buy_pool(C, bar_dt, pool):
	d_str = bar_dt[:8]
	items = []
	for code in sorted(pool or []):
		nm = _stock_name(C, code)
		items.append('%s(%s)' % (nm, code) if nm else str(code))
	sector = (getattr(g, 'sector_name', None) or DEFAULT_SECTOR).strip()
	print('%s [\u4eca\u65e5\u5f85\u4e70\u6c60] \u65e5\u671f=%s \u677f\u5757=%r \u6570\u91cf=%d' % (
		STRATEGY_TAG, d_str, sector, len(pool or [])))
	print('%s [\u4eca\u65e5\u5f85\u4e70\u6c60] %s' % (
		STRATEGY_TAG, ' | '.join(items) if items else '\u65e0'))


def _pool_from_sector(C):
	name = (getattr(g, 'sector_name', None) or DEFAULT_SECTOR).strip()
	if not name or not hasattr(C, 'get_stock_list_in_sector'):
		return []
	try:
		raw = C.get_stock_list_in_sector(name) or []
		out, seen = [], set()
		for x in raw:
			c = _canonical_stock_code(x) or str(x).strip()
			if c and c not in seen:
				seen.add(c)
				out.append(c)
		return sorted(out)
	except Exception:
		return []


def _refresh_buy_pool(C):
	"""\u6bcf\u6b21\u4ece QMT \u677f\u5757\u91cd\u62c9\u80a1\u7968\u6c60\uff1b\u53d8\u5316\u65f6\u6e05\u7a7a\u5df2\u5c1d\u8bd5\u4e70\u5165\u3002"""
	pool = _pool_from_sector(C)
	cur = tuple(sorted(pool or []))
	prev = tuple(getattr(g, '_buy_pool_snapshot', ()) or ())
	changed = (cur != prev)
	g._buy_pool_snapshot = list(cur)
	if changed:
		g._tried_stocks = set()
	return pool, changed


def _monitor_buy_pool(C, bar_dt):
	"""24h \u677f\u5757\u76d1\u63a7\uff1a\u6bcf\u6839 K \u7ebf\u62c9\u6c60\uff1b\u4ec5\u80a1\u7968\u6c60\u53d8\u5316\u65f6\u6253\u65e5\u5fd7\u3002"""
	pool, changed = _refresh_buy_pool(C)
	if changed:
		print('%s [\u677f\u5757\u91cd\u8f7d] \u65f6\u95f4=%s \u6570\u91cf=%d \u677f\u5757=%r' % (
			STRATEGY_TAG, bar_dt, len(pool or []), (getattr(g, 'sector_name', None) or DEFAULT_SECTOR)))
		_log_today_buy_pool(C, bar_dt, pool)
	return pool, changed


def _account_cash():
	gtd = _get_trade_detail_data_fn()
	if not gtd or not (g.accid or '').strip():
		return 0.0
	try:
		accs = gtd(g.accid, g.account_type, 'account') or []
		return float(getattr(accs[0], 'm_dAvailable', 0) or 0) if accs else 0.0
	except Exception:
		return 0.0


def _positions():
	gtd = _get_trade_detail_data_fn()
	out = {}
	if not gtd or not (g.accid or '').strip():
		return out
	try:
		for p in gtd(g.accid, g.account_type, 'position') or []:
			code = _canonical_stock_code(_normalize_position_code(p)) or ''
			if code:
				out[code] = int(getattr(p, 'm_nVolume', 0) or 0)
	except Exception:
		pass
	return out


def _log(tag, stock, reason, **kw):
	parts = ['%s [%s] \u4ee3\u7801=%s \u539f\u56e0=%s' % (STRATEGY_TAG, tag, stock or '--', reason or '--')]
	for k, v in kw.items():
		if v is not None:
			parts.append('%s=%s' % (k, v))
	print(' '.join(parts))


def _pending_buy(stock):
	return any(p.get('stock') == stock and p.get('side') == 'buy' for p in g.pending_orders.values())


def _reg_pending(remark, stock, shares, retry, meta):
	g.waiting_list.append(remark)
	g.pending_orders[remark] = {'time': time.time(), 'stock': stock, 'side': 'buy',
	                            'shares': int(shares), 'retry': int(retry), 'meta': dict(meta or {})}


def _deal_attr(deal, *names):
	for n in names:
		v = getattr(deal, n, None) if not isinstance(deal, dict) else deal.get(n)
		if v is not None:
			return v
	return None


def _log_fill(remark, deal, pinfo):
	if remark in g._logged_fill_remarks:
		return
	g._logged_fill_remarks.add(remark)
	meta = pinfo.get('meta') or {}
	fp = _deal_attr(deal, 'm_dPrice', 'm_dTradedPrice', 'price')
	fv = _deal_attr(deal, 'm_nVolume', 'volume')
	sh = int(fv) if fv is not None else int(pinfo.get('shares', 0) or 0)
	st = pinfo.get('stock') or meta.get('stock') or '--'
	pct = meta.get('pct')
	print('%s [\u4e70\u5165\u6210\u4ea4] \u4ee3\u7801=%s \u80a1\u6570=%d \u6210\u4ea4\u4ef7=%s \u9650\u4ef7=%s \u6da8\u8dcc\u5e45=%s \u5907\u6ce8=%s' % (
		STRATEGY_TAG, st, sh, ('%.3f' % fp) if fp else '--',
		('%.3f' % meta['limit_px']) if meta.get('limit_px') else '--',
		('%.2f%%' % pct) if pct is not None else '--', remark))


def _sync_deals():
	gtd = _get_trade_detail_data_fn()
	if not gtd or not g.waiting_list:
		return
	try:
		deals = gtd(g.accid, g.account_type, 'deal') or []
	except Exception:
		return
	by_rmk = dict((str(_deal_attr(d, 'm_strRemark', 'remark') or ''), d) for d in deals)
	by_rmk.pop('', None)
	done = []
	for r in list(g.waiting_list):
		if r in by_rmk:
			p = g.pending_orders.get(r)
			if p:
				_log_fill(r, by_rmk[r], p)
			done.append(r)
	for r in done:
		g.waiting_list.remove(r)
		g.pending_orders.pop(r, None)


def _repost_buy(C, pinfo, nr):
	"""超时未成交或废单后的限价重挂；nr \u4e3a\u672c\u8f6e\u91cd\u8bd5\u8f6e\u6b21\uff081\u8d77\uff09\u3002"""
	stk, sh = pinfo['stock'], int(pinfo['shares'])
	lpx = _tick_prices(C, [stk]).get(stk)
	if not lpx:
		_log('\u91cd\u6302\u672a\u6210\u529f', stk, '\u65e0\u73b0\u4ef7', retry=nr)
		return False
	limit = _limit_buy(lpx, nr)
	note = _remark(stk, sh, nr)
	if not (limit and _should_passorder(C) and _passorder_go(C, g.buy_code, stk, sh, note, 11, limit)):
		_log('\u91cd\u6302\u672a\u6210\u529f', stk, 'passorder\u5931\u8d25', retry=nr, remark=note)
		return False
	meta = dict(pinfo.get('meta') or {})
	meta.update(last_px=lpx, limit_px=limit, retry=nr, premium_pct=_buy_premium_pct(nr))
	_reg_pending(note, stk, sh, nr, meta)
	print('%s [\u64a4\u5355\u91cd\u6302] \u4ee3\u7801=%s retry=%d \u9650\u4ef7=%.3f \u6ea2\u4ef7=%.2f%% \u5907\u6ce8=%s' % (
		STRATEGY_TAG, stk, nr, limit, _buy_premium_pct(nr) * 100, note))
	return True


def _cancel_retry(C):
	if not g.waiting_list:
		return
	cur_hms = getattr(g, '_handlebar_hhmmss', None) if _is_qmt_backtest_context(C) else _wall_hhmmss()
	if _in_auction_no_retry_window(cur_hms):
		return
	gtd, cancel = _get_trade_detail_data_fn(), _cancel_fn()
	if not gtd:
		return
	now = time.time()
	try:
		orders = gtd(g.accid, g.account_type, 'order') or []
	except Exception:
		orders = []
	ORDER_DONE, ORDER_CANCEL = 56, (53, 54, 57)
	rm, retry_q, repost_q = [], [], []
	for r in list(g.waiting_list):
		p = g.pending_orders.get(r)
		if not p or now - p['time'] < g.withdraw_secs:
			continue
		om = None
		for o in orders:
			if (getattr(o, 'm_strRemark', '') or '') == r:
				om = o
				break
		if not om:
			continue
		st = getattr(om, 'm_nOrderStatus', 0)
		oid = getattr(om, 'm_strOrderSysID', '') or ''
		if st == ORDER_DONE:
			_log_fill(r, om, p)
			rm.append(r)
		elif st in ORDER_CANCEL:
			nr = int(p.get('retry', 0)) + 1
			if nr > g.max_retry:
				_log('\u4e70\u5165\u672a\u6210\u529f', p.get('stock'),
				     '\u5e9f\u5355\u4e14\u5df2\u8fbe\u6700\u5927\u91cd\u8bd5%d\u6b21' % g.max_retry,
				     remark=r, retry=p.get('retry', 0))
				rm.append(r)
			else:
				_log('\u4e70\u5165\u672a\u6210\u4ea4', p.get('stock'),
				     '\u59d4\u6258\u5df2\u64a4/\u5e9f\u5355\uff0c\u51c6\u5907\u91cd\u6302', remark=r, retry=nr)
				repost_q.append((p, nr))
				rm.append(r)
		elif p.get('retry', 0) >= g.max_retry:
			_log('\u4e70\u5165\u672a\u6210\u4ea4', p.get('stock'), '\u8fbe\u6700\u5927\u91cd\u8bd5%d' % g.max_retry, remark=r)
			rm.append(r)
		else:
			retry_q.append((r, p, oid))
	for r in rm:
		if r in g.waiting_list:
			g.waiting_list.remove(r)
		g.pending_orders.pop(r, None)
	for p, nr in repost_q:
		_repost_buy(C, p, nr)
	for old_r, p, oid in retry_q:
		stk = p['stock']
		nr = int(p.get('retry', 0)) + 1
		if not oid or not cancel:
			_log('\u64a4\u5355\u672a\u6210\u529f', stk, '\u65e0orderId/cancel', remark=old_r)
			continue
		try:
			cancel(oid, g.accid, g.account_type, C)
			print('%s [\u64a4\u5355\u6210\u529f] \u4ee3\u7801=%s \u5907\u6ce8=%s' % (STRATEGY_TAG, stk, old_r))
		except Exception as e:
			_log('\u64a4\u5355\u672a\u6210\u529f', stk, str(e), orderId=oid)
			continue
		_repost_buy(C, p, nr)


def _rollover(d_str):
	if g._session_date != d_str:
		g._session_date = d_str
		g._tried_stocks = set()
		g.waiting_list = []
		g.pending_orders = {}
		g._logged_fill_remarks = set()
		g._buy_pool_snapshot = []


def _scan_summary(bar_dt, stats, extra):
	labels = {'order_ok': '\u59d4\u6258\u6210\u529f', 'fail_order': '\u4e0b\u5355\u5931\u8d25', 'fail_no_price': '\u65e0\u73b0\u4ef7',
	          'fail_cap': '\u989d\u5ea6\u4e0d\u8db3', 'fail_shares': '\u80a1\u6570\u4e0d\u8db3', 'fail_limit': '\u9650\u4ef7\u5931\u8d25',
	          'skip_filter': '\u6da8\u8dcc\u5e45\u8fc7\u6ee4', 'skip_pending': '\u5728\u9014\u5355', 'skip_tried': '\u5df2\u5904\u7406', 'skip_backtest': '\u56de\u6d4b\u4e0d\u5355'}
	parts = ['%s [\u626b\u63cf\u6c47\u603b] %s' % (STRATEGY_TAG, bar_dt)]
	for k, lb in labels.items():
		if stats.get(k):
			parts.append('%s=%d' % (lb, stats[k]))
	if extra:
		parts.append(str(extra))
	print(' | '.join(parts))


def _try_buy(C, stock, tick_map, tick_full, end_time, cash_cap):
	if stock in g._tried_stocks:
		_log('\u4e70\u5165\u8df3\u8fc7', stock, '\u672c\u65e5\u5df2\u5904\u7406')
		return False, 'skip_tried'
	if _pending_buy(stock):
		_log('\u4e70\u5165\u8df3\u8fc7', stock, '\u5df2\u6709\u4e70\u5355\u5728\u9014')
		g._tried_stocks.add(stock)
		return False, 'skip_pending'
	last = tick_map.get(stock)
	if not last or last <= 0:
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, '\u65e0\u73b0\u4ef7')
		g._tried_stocks.add(stock)
		return False, 'fail_no_price'
	prev = _prev_close(C, stock, tick_full.get(stock), end_time)
	pct = _pct_chg(last, prev)
	blocked, why = _pct_blocked(stock, last, prev)
	if blocked:
		_log('\u4e70\u5165\u8df3\u8fc7', stock, why, last_px='%.3f' % last,
		     prev_close=('%.3f' % prev) if prev else '--', pct=('%.2f%%' % pct) if pct is not None else '--')
		g._tried_stocks.add(stock)
		return False, 'skip_filter'
	held = _positions().get(stock, 0)
	# \u5355\u7b14\u4e0a\u9650\u6309\u672c\u6b21\u4e70\u5165\u91d1\u989d\uff0c\u4e0d\u56e0\u5df2\u6709\u6301\u4ed3\u6263\u51cf\uff08\u5141\u8bb8\u52a0\u4ed3\uff09
	if g.max_amount_per_stock > 0:
		cap = min(float(cash_cap), float(g.max_amount_per_stock))
	else:
		cap = float(cash_cap)
	if cap < last * g.min_shares:
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, '\u989d\u5ea6\u4e0d\u8db3', remain='%.0f' % cap, held=held, cap_limit='%.0f' % g.max_amount_per_stock)
		g._tried_stocks.add(stock)
		return False, 'fail_cap'
	sh = _buy_shares(cap, last)
	if sh < g.min_shares:
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, '\u80a1\u6570\u4e0d\u8db3', cap='%.0f' % cap)
		g._tried_stocks.add(stock)
		return False, 'fail_shares'
	limit = _limit_buy(last, 0)
	if not limit:
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, '\u9650\u4ef7\u5931\u8d25')
		g._tried_stocks.add(stock)
		return False, 'fail_limit'
	rmk = _remark(stock, sh, 0)
	meta = dict(stock=stock, last_px=last, limit_px=limit, prev_close=prev, pct=pct, amount_est=sh * limit)
	if not _should_passorder(C):
		_log('\u4e70\u5165\u672a\u6210\u529f', stock, '\u56de\u6d4b\u4e0d\u53d1\u5355', shares=sh, limit_px='%.3f' % limit)
		g._tried_stocks.add(stock)
		return False, 'skip_backtest'
	ok = _passorder_go(C, g.buy_code, stock, sh, rmk, 11, limit)
	g._tried_stocks.add(stock)
	if ok:
		_reg_pending(rmk, stock, sh, 0, meta)
		print('%s [\u4e70\u5165\u59d4\u6258] \u4ee3\u7801=%s \u80a1\u6570=%d \u73b0\u4ef7=%.3f \u9650\u4ef7=%.3f \u6da8\u8dcc\u5e45=%s \u91d1\u989d=%.2f \u5907\u6ce8=%s' % (
			STRATEGY_TAG, stock, sh, last, limit,
			('%.2f%%' % pct) if pct is not None else '--', sh * limit, rmk))
		return True, 'order_ok'
	return False, 'fail_order'


def _auction_timer_start_time():
	try:
		return '%s %s' % (datetime.datetime.now().strftime('%Y-%m-%d'), DEFAULT_AUCTION_TIMER_START)
	except Exception:
		return DEFAULT_AUCTION_TIMER_START


def _register_auction_timer(C):
	"""\u5b9e\u76d8\u7528 run_time \u8865\u53d1\uff1a1 \u5206\u949f K \u7ebf\u9996\u6839\u5e38\u5728 9:30 \u624d\u8d70\u5b8c\uff0c\u96c6\u5408\u7ade\u4ef7 9:25 \u9700\u5b9a\u65f6\u626b\u6c60\u3002"""
	if _is_qmt_backtest_context(C) or not bool(getattr(g, 'auction_timer', True)):
		return
	rt = getattr(C, 'run_time', None)
	if not rt:
		print('%s [WARN] \u65e0 run_time \u63a5\u53e3\uff0c9:25 \u53ea\u80fd\u7b49 1 \u5206\u949f K \u7ebf(\u7ea69:30)' % (STRATEGY_TAG,))
		return
	try:
		st = _auction_timer_start_time()
		period = str(getattr(g, 'auction_timer_period', DEFAULT_AUCTION_TIMER_PERIOD) or DEFAULT_AUCTION_TIMER_PERIOD)
		rt('on_open_buy_timer', period, st)
		print('%s run_time \u5df2\u6ce8\u518c start=%s period=%s (\u96c6\u5408\u7ade\u4ef7/9:25\u8865\u53d1)' % (
			STRATEGY_TAG, st, period))
	except Exception as e:
		print('%s [WARN] run_time\u6ce8\u518c\u5931\u8d25: %s' % (STRATEGY_TAG, e))


def _run_open_buy_cycle(C, bar_dt, wall, trigger='handlebar'):
	g._handlebar_hhmmss = wall
	if not g.accid:
		print('%s %s accid \u4e3a\u7a7a' % (STRATEGY_TAG, bar_dt))
		return
	_sync_deals()
	_cancel_retry(C)
	do_scan = True
	if trigger == 'timer':
		slot = (bar_dt[:8], int(wall) // 100)
		if getattr(g, '_last_timer_scan_slot', None) == slot:
			do_scan = False
		else:
			g._last_timer_scan_slot = slot
	if not do_scan:
		return
	pool, _ = _refresh_buy_pool(C)
	if not pool:
		return
	if trigger == 'timer':
		print('%s ========== %s \u5f00\u76d8\u4e70\u5165(timer) \u6c60=%d ==========' % (
			STRATEGY_TAG, bar_dt, len(pool)))
	else:
		print('%s ========== %s \u5f00\u76d8\u4e70\u5165 \u6c60=%d ==========' % (STRATEGY_TAG, bar_dt, len(pool)))
	tick_full = _full_ticks(C, pool)
	tick_map = dict((c, p) for c, t in tick_full.items() for p in [_tick_px(t)] if p)
	for c in pool:
		if c not in tick_map:
			_log('\u4e70\u5165\u672a\u6210\u529f', c, '\u80a1\u7968\u6c60\u5185\u65e0\u73b0\u4ef7')
	cash = _account_cash()
	print('%s \u53ef\u7528=%.2f \u5355\u7968\u4e0a\u9650=%.0f' % (STRATEGY_TAG, cash, g.max_amount_per_stock))
	if cash <= 0 and _should_passorder(C):
		print('%s %s [\u626b\u63cf\u7ec8\u6b62] \u53ef\u7528\u8d44\u91d1\u4e3a0' % (STRATEGY_TAG, bar_dt))
		return
	stats = {}
	cap0 = min(float(g.max_amount_per_stock), cash) if cash > 0 else float(g.max_amount_per_stock)
	for stk in pool:
		if stk not in tick_map:
			stats['fail_no_price'] = stats.get('fail_no_price', 0) + 1
			continue
		_ok, tag = _try_buy(C, stk, tick_map, tick_full, bar_dt, cap0)
		stats[tag] = stats.get(tag, 0) + 1
	_cancel_retry(C)
	_scan_summary(bar_dt, stats, 'pool=%d trigger=%s' % (len(pool), trigger))


def on_open_buy_timer(C):
	"""\u5b9e\u76d8 run_time \u56de\u8c03\uff1bquick_trade=2 \u53ef\u5728\u6b64\u76f4\u63a5 passorder\u3002"""
	if _is_qmt_backtest_context(C):
		return
	wall = _wall_hhmmss()
	if wall is None:
		return
	bar_dt = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
	d_str = bar_dt[:8]
	_rollover(d_str)
	_monitor_buy_pool(C, bar_dt)
	if not _in_handlebar_session(wall) or not _in_buy_window(wall):
		return
	_run_open_buy_cycle(C, bar_dt, wall, trigger='timer')


def init(C):
	g.accid = str(getattr(C, 'accountid', None) or getattr(C, 'account_id', None) or DEFAULT_ACCID).strip()
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	g.sector_name = getattr(C, 'sector_name', None) or DEFAULT_SECTOR
	g.max_amount_per_stock = float(getattr(C, 'max_amount_per_stock', DEFAULT_MAX_AMOUNT_PER_STOCK) or DEFAULT_MAX_AMOUNT_PER_STOCK)
	g.buy_premium_pct = float(getattr(C, 'buy_premium_pct', DEFAULT_BUY_PREMIUM_PCT) or DEFAULT_BUY_PREMIUM_PCT)
	g.buy_premium_retry_step = float(getattr(C, 'buy_premium_retry_step', DEFAULT_PREMIUM_RETRY_STEP) or DEFAULT_PREMIUM_RETRY_STEP)
	g.withdraw_secs = int(getattr(C, 'withdraw_secs', DEFAULT_WITHDRAW_SECS) or DEFAULT_WITHDRAW_SECS)
	g.max_retry = int(getattr(C, 'max_retry', 3) or 3)
	g.quick_trade = int(getattr(C, 'quick_trade', 2) or 2)
	g.strategy_order_name = str(getattr(C, 'strategy_order_name', None) or '\u5361\u5f02\u52a8\u5f00\u76d8\u4e70')[:12]
	g.live_orders = bool(getattr(C, 'live_orders', True))
	g.min_shares = int(getattr(C, 'min_shares', DEFAULT_MIN_SHARES) or DEFAULT_MIN_SHARES)
	g.buy_code = 23 if g.account_type == 'STOCK' else 33
	g.waiting_list, g.pending_orders = [], {}
	g._session_date, g._tried_stocks = '', set()
	g._last_handle_key, g._logged_fill_remarks = None, set()
	g._handlebar_hhmmss = None
	g._buy_pool_snapshot = []
	g.auction_timer = bool(getattr(C, 'auction_timer', True))
	g.auction_timer_period = getattr(C, 'auction_timer_period', DEFAULT_AUCTION_TIMER_PERIOD) or DEFAULT_AUCTION_TIMER_PERIOD
	g._last_timer_scan_slot = None
	_register_auction_timer(C)
	print('=' * 64)
	print('%s init acc=%s sector=%r cap=%.0f prem=%.2f%%+step%.2f%% wd=%ds retry=%d live=%s' % (
		STRATEGY_TAG, g.accid, g.sector_name, g.max_amount_per_stock,
		g.buy_premium_pct * 100, g.buy_premium_retry_step * 100, g.withdraw_secs, g.max_retry, g.live_orders))
	print('%s \u677f\u575724h\u76d1\u63a7 \u672a\u6210\u4ea4%d\u79d2\u64a4\u5355\u91cd\u6302(09:25-09:30\u4e0d\u64a4\u5355\u91cd\u6302) \u4e70\u516509:25-09:35 run_time=%s \u5907\u6ce8=%s_*' % (
		STRATEGY_TAG, g.withdraw_secs, ('on' if g.auction_timer else 'off'), REMARK_PREFIX))
	print('=' * 64)


def handlebar(C):
	try:
		if not C.is_last_bar():
			return
	except Exception:
		pass
	wall = _wall_hhmmss()
	now = datetime.datetime.now()
	try:
		bar_dt = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	except Exception:
		bar_dt = now.strftime('%Y%m%d%H%M%S')
	d_str = bar_dt[:8]
	hkey = (d_str, getattr(C, 'barpos', None), 'open_buy')
	if hkey == g._last_handle_key:
		return
	g._last_handle_key = hkey
	_rollover(d_str)
	_monitor_buy_pool(C, bar_dt)
	if wall is None or not _in_handlebar_session(wall):
		return
	if not _in_buy_window(wall):
		return
	_run_open_buy_cycle(C, bar_dt, wall, trigger='handlebar')


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
