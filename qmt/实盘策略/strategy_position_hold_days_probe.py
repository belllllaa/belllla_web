# -*- coding: utf-8 -*-
"""
持仓天数探测：从账户读取当前持仓，解析开仓日，打印到「当前 K 线日期」的
  自然日间隔、含首尾的自然日「第几天」、以及（若接口可用）交易日数量。

用法（QMT）：
  - 周期建议 1 分钟（与其它实盘探测一致）；也可日线，仅 is_last_bar 时打印一次/根。
  - 账户：优先 ContextInfo.accountid / account_id；否则默认 30262698；可用 init 参数 C.accountid 覆盖。
  - 仅 print，无下单。
  - 若每分钟都要打日志：在 QMT 里设 C.handlebar_each_bar = True（与 quote 探测相同）。
  - 首次想看 Position 上有哪些字段：设 C.hold_days_dump_attrs = True（只打印第一条持仓的字段采样）。
"""

import sys
import datetime

STRATEGY_TAG = '[HOLD-DAYS\u63a2\u6d4b]'


class G:
	pass


g = G()


def _get_trade_detail_data_fn():
	fn = getattr(sys.modules.get('__main__'), 'get_trade_detail_data', None)
	if fn is None:
		fn = globals().get('get_trade_detail_data')
	return fn


def _holdings_fn():
	fn = getattr(sys.modules.get('__main__'), 'holdings', None)
	if fn is None:
		fn = globals().get('holdings')
	return fn


def _get_trading_dates_fn():
	for mod in (sys.modules.get('__main__'),):
		if mod is None:
			continue
		fn = getattr(mod, 'get_trading_dates', None)
		if callable(fn):
			return fn
	return globals().get('get_trading_dates')


def timetag_to_datetime(timetag, format_str='%Y%m%d%H%M%S'):
	import time
	try:
		return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
	except Exception:
		try:
			return time.strftime(format_str, time.localtime(float(timetag)))
		except Exception:
			return str(timetag)


def _tag_to_yyyymmdd(raw):
	if raw is None:
		return None
	if isinstance(raw, str):
		s = raw.strip()
		if len(s) >= 8 and s[:8].isdigit():
			return s[:8]
		digits = ''.join(ch for ch in s if ch.isdigit())
		if len(digits) >= 8:
			return digits[:8]
		return None
	try:
		s = timetag_to_datetime(raw, '%Y%m%d%H%M%S')
		if len(s) >= 8 and s[:8].isdigit():
			return s[:8]
	except Exception:
		pass
	try:
		x = float(raw)
		if x > 1e12:
			s = timetag_to_datetime(x, '%Y%m%d%H%M%S')
			if len(s) >= 8 and s[:8].isdigit():
				return s[:8]
		s = str(int(x))
		if len(s) == 8 and s.isdigit():
			return s
	except Exception:
		pass
	return None


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
	return t


def _normalize_position_code(pos):
	if pos is None:
		return ''
	ins = (getattr(pos, 'm_strInstrumentID', None) or getattr(pos, 'stock_code', None) or '').strip()
	ex = (getattr(pos, 'm_strExchangeID', None) or getattr(pos, 'exchange_id', None) or '').upper().strip()
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
	if ins.startswith(('60', '68', '51')):
		return ins + '.SH'
	return ins + '.SZ'


def _holdings_code(pos):
	try:
		ins = getattr(pos, 'instrumentid', None) if not isinstance(pos, dict) else pos.get('instrumentid')
		ex = getattr(pos, 'exchangeid', None) if not isinstance(pos, dict) else pos.get('exchangeid')
		ins = (str(ins).strip() if ins is not None else '')
		ex = (str(ex).strip().upper() if ex is not None else '')
		if ins and ex:
			return _canonical_stock_code('%s.%s' % (ins, ex))
		if ins:
			return _canonical_stock_code(ins)
	except Exception:
		pass
	return ''


def _is_long_holding(pos):
	try:
		d = getattr(pos, 'direction', None) if not isinstance(pos, dict) else pos.get('direction')
		if d is None or str(d).strip() == '':
			return True
		return int(d) == 48
	except Exception:
		return True


def _position_volume(p):
	try:
		if isinstance(p, dict):
			for k in ('m_nVolume', 'volume', 'm_nCurrentVolume'):
				v = p.get(k)
				if v is not None:
					return int(v)
			return 0
		return int(getattr(p, 'm_nVolume', 0) or getattr(p, 'volume', 0) or 0)
	except Exception:
		return 0


def _extract_open_date_yyyymmdd(p):
	if p is None:
		return None, []
	seen = []
	for nm in ('opendate', 'openDate', 'm_strOpenDate', 'm_strOpenDateEx', 'OpenDate'):
		try:
			if isinstance(p, dict):
				raw = p.get(nm)
			else:
				raw = getattr(p, nm, None)
			d = _tag_to_yyyymmdd(raw)
			seen.append('%s=%r->%s' % (nm, raw, d or '?'))
			if d:
				return d, seen
		except Exception:
			seen.append('%s=err' % nm)
	return None, seen


def _account_holdings_list():
	if not (g.accid or '').strip():
		return []
	hd = _holdings_fn()
	if not hd:
		return []
	try:
		return hd(g.accid) or []
	except Exception:
		return []


def _open_date_from_holdings_row(p):
	if not _is_long_holding(p):
		return None
	if _position_volume(p) <= 0:
		return None
	code = _holdings_code(p)
	if not code:
		return None
	try:
		raw = (getattr(p, 'opendate', None) if not isinstance(p, dict) else p.get('opendate'))
		d = _tag_to_yyyymmdd(raw)
		if d:
			return d
	except Exception:
		pass
	return None


def _positions_union_rows():
	"""同一标的可能同时出现在 holdings 与 position；不去重，便于合并解析开仓日。"""
	rows = []
	for p in _account_holdings_list():
		try:
			c = _holdings_code(p)
			if c:
				rows.append(('holdings()', p))
		except Exception:
			pass
	_gtd = _get_trade_detail_data_fn()
	if _gtd and (g.accid or '').strip():
		try:
			pos = _gtd(g.accid, g.account_type, 'position') or []
			for p in pos:
				c = _normalize_position_code(p)
				if c:
					rows.append(("get_trade_detail_data('position')", p))
		except Exception:
			pass
	return rows


def _open_date_for_stock(stock_canon, rows):
	d0 = None
	debug_lines = []
	for src, p in rows:
		c = _holdings_code(p) if src.startswith('holdings') else _normalize_position_code(p)
		c = _canonical_stock_code(c) or c
		if c != stock_canon:
			continue
		if not _is_long_holding(p):
			continue
		if _position_volume(p) <= 0:
			continue
		cand = None
		if src.startswith('holdings'):
			cand = _open_date_from_holdings_row(p)
			debug_lines.append('%s holdings_opendate->%s' % (src, cand or '?'))
		if not cand:
			cand, dbg = _extract_open_date_yyyymmdd(p)
			debug_lines.append('%s extract %s' % (src, ' '.join(dbg[:6])))
		if cand and not d0:
			d0 = cand
	return d0, debug_lines


def _parse_yyyymmdd(s):
	if not s or len(s) != 8 or not s.isdigit():
		return None
	try:
		return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
	except ValueError:
		return None


def _calendar_metrics(open_s, end_s):
	do = _parse_yyyymmdd(open_s)
	de = _parse_yyyymmdd(end_s)
	if not do or not de:
		return None, None, None
	gap = (de - do).days
	inclusive = gap + 1
	return gap, inclusive, (do, de)


def _count_trading_days_inclusive(open_s, end_s):
	fn = _get_trading_dates_fn()
	if not callable(fn):
		return None, 'get_trading_dates_unavailable'
	candidates = [
		(open_s, end_s),
		('SH', open_s, end_s),
		('SZ', open_s, end_s),
		(open_s, end_s, '1d'),
	]
	last_err = None
	for args in candidates:
		try:
			out = fn(*args)
			if out is None:
				continue
			if isinstance(out, (list, tuple)):
				n = len(out)
				if n > 0:
					return n, 'ok_args=%s' % (args,)
			if hasattr(out, '__len__'):
				n = len(out)
				if n > 0:
					return n, 'ok_args=%s' % (args,)
		except Exception as e:
			last_err = repr(e)
			continue
	return None, last_err or 'no_return'


def _is_qmt_backtest_context(C):
	if bool(getattr(C, 'do_back_test', False)):
		return True
	if bool(getattr(C, 'isDoBackTest', False)):
		return True
	rm = getattr(C, 'run_mode', None)
	if rm is None:
		rm = getattr(C, 'runMode', None)
	try:
		if rm is not None and int(rm) == 1:
			return True
	except (TypeError, ValueError):
		pass
	if isinstance(rm, str) and rm.strip().upper() in ('BACKTEST', 'TRUE', '1', 'T'):
		return True
	return False


def _handlebar_should_run(C):
	try:
		if C.is_last_bar():
			return True
	except Exception:
		return True
	if bool(getattr(g, 'handlebar_each_bar', False)):
		return True
	if _is_qmt_backtest_context(C):
		return True
	return False


def _dump_position_attrs_sample(rows):
	if not rows:
		print('%s dump_attrs: \u65e0\u6301\u4ed3\u884c' % STRATEGY_TAG)
		return
	_src, p = rows[0]
	print('%s dump_attrs: \u6765\u6e90=%s type=%s' % (STRATEGY_TAG, _src, type(p)))
	try:
		if isinstance(p, dict):
			keys = sorted(p.keys())
			for k in keys[:60]:
				print('  %s=%r' % (k, p.get(k)))
			if len(keys) > 60:
				print('  ... %d keys total' % len(keys))
			return
		names = [x for x in dir(p) if x.startswith('m_') or 'open' in x.lower() or 'date' in x.lower() or 'volume' in x.lower() or 'instrument' in x.lower()]
		for k in sorted(set(names))[:80]:
			try:
				print('  %s=%r' % (k, getattr(p, k)))
			except Exception as e:
				print('  %s=<err %s>' % (k, e))
	except Exception as e:
		print('%s dump_attrs err: %s' % (STRATEGY_TAG, e))


def init(C):
	g.accid = (getattr(C, 'accountid', None) or getattr(C, 'account_id', None) or getattr(C, 'accountId', None) or '')
	g.accid = str(g.accid).strip() or '30262698'
	g.account_type = str(getattr(C, 'account_type', None) or getattr(C, 'accountType', None) or 'STOCK').strip() or 'STOCK'
	g.handlebar_each_bar = bool(getattr(C, 'handlebar_each_bar', False))
	g.hold_days_dump_attrs = bool(getattr(C, 'hold_days_dump_attrs', False))
	g._last_handlebar_barpos = None
	g._did_dump_attrs = False
	print('=' * 60)
	print('%s init accid=%s account_type=%s handlebar_each_bar=%s hold_days_dump_attrs=%s' % (
		STRATEGY_TAG, g.accid or '(\u7a7a\u8bf7\u5728\u754c\u9762\u9009\u8d26\u6237\u6216\u8bbe C.accountid)', g.account_type,
		g.handlebar_each_bar, g.hold_days_dump_attrs))
	print('\u4ec5\u6253\u5370\u6301\u4ed3\u4e0e\u5929\u6570\uff0c\u4e0d\u4e0b\u5355\u3002')
	print('=' * 60)


def handlebar(C):
	if not _handlebar_should_run(C):
		return
	bp = getattr(C, 'barpos', None)
	if bp is not None and bp == getattr(g, '_last_handlebar_barpos', None):
		return
	g._last_handlebar_barpos = bp

	dt_full = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	d_str = dt_full[:8]

	if not g.accid:
		print('%s %s \u65e0\u8d26\u6237ID\uff0c\u65e0\u6cd5\u67e5\u8be2\u6301\u4ed3' % (dt_full, STRATEGY_TAG))
		return

	rows = _positions_union_rows()
	if g.hold_days_dump_attrs and not g._did_dump_attrs:
		_dump_position_attrs_sample(rows)
		g._did_dump_attrs = True

	if not rows:
		print('%s %s \u5f53\u524d\u65e0\u6301\u4ed3\uff08holdings \u4e0e position \u5747\u7a7a\uff09' % (dt_full, STRATEGY_TAG))
		return

	by_code = {}
	for src, p in rows:
		c = _holdings_code(p) if src.startswith('holdings') else _normalize_position_code(p)
		c = _canonical_stock_code(c) or c
		if not c:
			continue
		if c not in by_code:
			by_code[c] = (src, p)

	print('%s %s as_of_date=%s rows=%d unique_codes=%d' % (dt_full, STRATEGY_TAG, d_str, len(rows), len(by_code)))

	for code in sorted(by_code.keys()):
		_src, p = by_code[code]
		open_d, dbg = _open_date_for_stock(code, rows)
		vol = _position_volume(p)
		gap, inclusive, _pair = _calendar_metrics(open_d, d_str) if open_d else (None, None, None)
		n_td, td_note = _count_trading_days_inclusive(open_d, d_str) if open_d else (None, None)

		if not open_d:
			print('%s code=%s vol=%d open_date=(\u672a\u89e3\u51fa) debug: %s' % (
				STRATEGY_TAG, code, vol, '; '.join(dbg[:3]) if dbg else ''))
			continue

		print('%s code=%s vol=%d open_date=%s -> cal_gap_days=%s cal_inclusive_days=%s trading_days_inclusive=%s (%s)' % (
			STRATEGY_TAG, code, vol, open_d,
			gap if gap is not None else '--',
			inclusive if inclusive is not None else '--',
			n_td if n_td is not None else '--',
			td_note or ''))


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
