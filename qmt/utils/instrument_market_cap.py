#coding:utf-8
"""
QMT 合约详情与市值兼容。

官方文档常见两种接口（不同版本可能只实现其一）：
- **get_instrumentdetail(stockcode)**：单字符串参数，返回 dict，含 **FloatVolume**（流通股本）、
  **TotalVolume**（总股本）等；无直接市值字段时可用 **流通市值≈FloatVolume×现价**、
  **总市值≈TotalVolume×现价**（现价建议传截面排序用的 current_close）。
- **get_instrument_detail([code], iscomplete=...)**：部分终端返回 circulation_market_value / market_value 等。

常见问题：
- 键名可能是英文驼峰、蛇形或 m_d 前缀等；
- 仅 get_instrument_detail 时部分环境需 iscomplete=True 才有市值类字段。

策略中用法：
    from qmt.utils.instrument_market_cap import get_market_cap_for_sort
    v = get_market_cap_for_sort(C, '600519.SH', current_close)  # 第三参用于股本×价；失败返回 None
"""

from __future__ import annotations


def _get_field(obj, key):
	"""dict 或对象属性。"""
	if obj is None:
		return None
	if isinstance(obj, dict):
		return obj.get(key)
	try:
		return getattr(obj, key, None)
	except Exception:
		return None


def _try_float_positive(val):
	if val is None:
		return None
	try:
		f = float(val)
		if f > 0:
			return f
	except (TypeError, ValueError):
		pass
	return None


# 流通市值优先，其次总市值（与策略「小市值优先」一致）
_FLOAT_KEYS = (
	'circulation_market_value',
	'float_market_cap',
	'float_market_value',
	'FloatMarketValue',
	'FloatMarketCap',
	'floatMarketCap',
	'circulationMarketValue',
	'm_dFloatMarketValue',
	'm_floatMarketValue',
	'm_nFloatMarketValue',
	'流通市值',
)
_TOTAL_KEYS = (
	'market_value',
	'total_market_cap',
	'total_market_value',
	'TotalMarketValue',
	'TotalMarketCap',
	'totalMarketCap',
	'marketValue',
	'm_dTotalMarketValue',
	'm_totalMarketValue',
	'm_nTotalMarketValue',
	'总市值',
)

# 官方 get_instrumentdetail 文档：FloatVolume=流通股本，TotalVolume=总股本（单位一般为股）
_SHARE_FLOAT_KEYS = ('FloatVolume', 'float_volume', 'floatVolume', 'm_nFloatVolume')
_SHARE_TOTAL_KEYS = ('TotalVolume', 'total_volume', 'totalVolume', 'm_nTotalVolume')


def _market_cap_from_shares_and_price(inf, current_price):
	"""流通市值优先，其次总市值。current_price 为截面价（元/股）。"""
	if inf is None or current_price is None:
		return None
	p = _try_float_positive(current_price)
	if p is None:
		return None
	for keys in (_SHARE_FLOAT_KEYS, _SHARE_TOTAL_KEYS):
		for key in keys:
			sh = _try_float_positive(_get_field(inf, key))
			if sh is not None:
				return sh * p
	return None


def extract_market_cap_from_detail(inf, current_price=None):
	"""
	从单票详情中取市值：先直接市值字段，再 流通股本/总股本×现价。
	inf 为 get_instrumentdetail / get_instrument_detail 返回的 dict 或对象。
	current_price：有则可用于 FloatVolume/TotalVolume 推算市值。
	成功返回 float，否则 None。
	"""
	if inf is None:
		return None
	for key in _FLOAT_KEYS + _TOTAL_KEYS:
		v = _try_float_positive(_get_field(inf, key))
		if v is not None:
			return v
	# 兜底：扫描 dict 键名含 market / Market / 市值
	if isinstance(inf, dict):
		for k, v in inf.items():
			if v is None:
				continue
			ks = str(k).lower()
			if 'market' in ks or '市值' in str(k):
				fv = _try_float_positive(v)
				if fv is not None:
					return fv
	mv = _market_cap_from_shares_and_price(inf, current_price)
	if mv is not None:
		return mv
	return None


def fetch_instrument_detail_node(C, stock_code):
	"""
	取单票详情 dict。优先官方 get_instrumentdetail(字符串)（含 FloatVolume/TotalVolume）；
	再尝试 get_instrument_detail 列表形式及 iscomplete。
	"""
	# 1) 迅投文档：ContextInfo.get_instrumentdetail('600000.SH') -> dict
	for attr in ('get_instrumentdetail', 'get_instrumentDetail'):
		fn = getattr(C, attr, None)
		if callable(fn):
			try:
				info = fn(stock_code)
				if isinstance(info, dict) and info:
					return info
			except Exception:
				pass

	if not hasattr(C, 'get_instrument_detail'):
		return None

	def _pick(info):
		if not info:
			return None
		if isinstance(info, dict):
			if stock_code in info:
				return info[stock_code]
			if len(info) == 1:
				return list(info.values())[0]
		return None

	for iscomplete in (True, False):
		try:
			info = C.get_instrument_detail([stock_code], iscomplete=iscomplete)
			node = _pick(info)
			if node is not None:
				return node
		except TypeError:
			continue
		except Exception:
			continue
	try:
		info = C.get_instrument_detail([stock_code])
		node = _pick(info)
		if node is not None:
			return node
	except Exception:
		pass
	try:
		info = C.get_instrument_detail(stock_code)
		node = _pick(info)
		if node is not None:
			return node
	except Exception:
		pass
	return None


def get_market_cap_for_sort(C, stock_code, current_price=None):
	"""
	用于截面排序：返回正值市值（元），失败返回 None。
	current_price：排序时刻的现价/昨收等（元）；传入后可从 FloatVolume/TotalVolume 推算市值。
	"""
	inf = fetch_instrument_detail_node(C, stock_code)
	return extract_market_cap_from_detail(inf, current_price=current_price)
