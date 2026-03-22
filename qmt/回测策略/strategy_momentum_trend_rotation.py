#coding:gbk
"""
QMT强势趋势轮动策略（只做多）
- 只做多中期、短期同时强势的趋势股
- 方案A：多周期动量 + 量能综合打分，择优买入
- 方案C：单日最多买入若干只 + 冷却期控制频率
- 大盘过滤：中证1000 破位60日线（收盘价 < MA60）时当日不开仓
- 卖出：ATR吊灯止损 / 短期动量转弱 / 持有到期轮动出场
- 止损：做多止损位 = 持仓期间最高价 - ATR(14)×倍数（进攻策略中证1000高波动 multiplier=3.0）
- 买入可选：三层过滤+波动率错峰（周线趋势、残差动量>0、小时线突破、ATR/close<0.05）
  使用三层过滤时，小时线由 5m 合成，回测前需对标的/区间下载 5m 数据：download_history_data(stock, '5m', startTime, endTime)
"""

import numpy as np
import time
from datetime import datetime

try:
	import talib
except Exception:
	talib = None


def trading_days_diff(date_start, date_end):
	"""计算两个日期之间的自然日天数差"""
	try:
		d1 = datetime.strptime(str(date_start), '%Y%m%d')
		d2 = datetime.strptime(str(date_end), '%Y%m%d')
		return max(0, (d2 - d1).days)
	except Exception:
		return 0


def timetag_to_datetime(timetag, format_str='%Y%m%d'):
	"""将 QMT 的 bar timetag 转为日期字符串。timetag 一般为毫秒。"""
	try:
		return time.strftime(format_str, time.localtime(timetag / 1000))
	except Exception:
		try:
			return time.strftime(format_str, time.localtime(timetag))
		except Exception:
			return str(timetag)


def init(C):
	"""初始化函数：所有可回测/调参因子集中在此，便于管理"""
	C.accountid = getattr(C, 'accountid', '')
	C.holding = {}
	C.buy_price = {}
	C.buy_shares = {}
	C.buy_date = {}
	C.sell_date = {}  # 记录卖出日期，用于冷却期

	# ---------- 仓位与资金 ----------
	C.max_hold_count = 10
	C.per_stock_amount = 100000
	C.min_order_shares = 100          # 最小下单股数（不足则跳过）

	# ---------- 多周期动量（选股门槛） ----------
	C.trend_short_period = 5
	C.trend_mid_period = 20
	C.long_period = 60
	C.short_mom_min = 0.02   # 近短期涨幅至少 2%
	C.mid_mom_min = 0.08    # 近中期涨幅至少 8%
	C.long_mom_min = 0.12   # 近长期涨幅至少 12%

	# ---------- 一字板过滤 ----------
	C.limit_up_min_ret = 0.095       # 当日涨幅>=此视为涨停
	C.limit_up_max_spread = 0.005    # 涨停且振幅<=此视为一字板，过滤

	# ---------- 量能过滤 ----------
	C.vol_lookback = 5                # 量能对比：前 N 日均量
	C.vol_min_ratio = 0.70            # 当日量 >= 前N日均量 * 此比例，否则过滤

	# ---------- 持股与退出 ----------
	C.min_hold_days = 1
	C.max_hold_days = 5
	C.atr_period = 14
	C.atr_multiplier = 3.0            # ATR吊灯止损倍数（进攻型可 3.0）

	# ---------- 综合得分权重（候选排序） ----------
	C.score_w_short = 0.4
	C.score_w_mid = 0.35
	C.score_w_long = 0.15
	C.score_w_volume = 0.10

	# ---------- 容量与冷却 ----------
	C.max_buy_per_day = 7
	C.cooldown_days = 1

	# ---------- 大盘与股票池 ----------
	C.index_ma_filter = '000852.SH'   # 破位此指数 MA 不开仓（中证1000）
	C.index_ma_count_buffer = 10     # 取数 count = long_period + 此值
	C.stock_pool_indices = ['000300.SH', '000905.SH', '000852.SH', '399006.SZ', '399001.SZ']
	C.stock_pool_scan_cap = 3500      # 扫描股票池前 N 只（控制耗时）

	# ---------- 数据长度缓冲 ----------
	C.required_data_buffer = 15       # 日线取数 count 在周期基础上的加数
	C.sell_data_count_min = 70        # 卖出逻辑取数至少 N 根

	# ---------- 三层过滤 + 波动率错峰（入场条件） ----------
	C.use_three_layer_filter = True
	C.market_index_residual = '000852.SH'
	C.weekly_sma_period = 10
	C.residual_lookback = 20
	C.hourly_breakout_bars = 20
	C.atr_vol_max = 0.05
	C.bars_per_week = 5
	C.bars_5m_per_hour = 12
	C.hourly_5m_buffer = 5            # 小时线用 5m 合成时多取的根数

	print("QMT强势趋势轮动策略初始化完成")


def calc_momentum_features(C, closes, volumes, highs, lows):
	"""
	动量与量能特征计算 + 基础过滤。
	返回 (metrics, passed_flags)：
	- metrics: dict 或 None（未通过过滤时为 None）
	- passed_flags: (passed_short, passed_mid, passed_long)，用于统计通过门槛的数量
	"""
	passed_short = False
	passed_mid = False
	passed_long = False

	if not closes or len(closes) < max(C.trend_short_period, C.trend_mid_period, C.long_period) + 1:
		return None, (passed_short, passed_mid, passed_long)

	current_close = closes[-1]
	if current_close <= 0:
		return None, (passed_short, passed_mid, passed_long)

	# 多周期动量（先算，再按门槛过滤）
	short_ret = closes[-1] / closes[-C.trend_short_period] - 1 if closes[-C.trend_short_period] > 0 else 0
	mid_ret = closes[-1] / closes[-C.trend_mid_period] - 1 if closes[-C.trend_mid_period] > 0 else 0
	long_ret = closes[-1] / closes[-C.long_period] - 1 if closes[-C.long_period] > 0 else 0

	# 一字板过滤
	if highs and lows and len(highs) >= 2 and len(lows) >= 2:
		prev_close = closes[-2]
		if prev_close > 0:
			day_ret = closes[-1] / prev_close - 1
			spread = (highs[-1] - lows[-1]) / prev_close
			if day_ret >= C.limit_up_min_ret and spread <= C.limit_up_max_spread:
				return None, (passed_short, passed_mid, passed_long)

	# 动量门槛（统计分层通过情况）
	if short_ret >= C.short_mom_min:
		passed_short = True
	else:
		return None, (passed_short, passed_mid, passed_long)

	if mid_ret >= C.mid_mom_min:
		passed_mid = True
	else:
		return None, (passed_short, passed_mid, passed_long)

	if long_ret >= C.long_mom_min:
		passed_long = True
	else:
		return None, (passed_short, passed_mid, passed_long)

	# 量能过滤
	vol_lookback_n = C.vol_lookback + 1
	if volumes and len(volumes) >= vol_lookback_n:
		vol_avg = np.mean(volumes[-vol_lookback_n:-1])
		current_vol = volumes[-1]
		if vol_avg > 0 and current_vol < vol_avg * C.vol_min_ratio:
			return None, (passed_short, passed_mid, passed_long)
		vol_ratio = current_vol / vol_avg if vol_avg > 0 else 1.0
	else:
		vol_ratio = 1.0

	metrics = {
		'short_ret': short_ret,
		'mid_ret': mid_ret,
		'long_ret': long_ret,
		'vol_ratio': vol_ratio,
		'current_close': current_close,
	}
	return metrics, (passed_short, passed_mid, passed_long)


def calc_atr(highs, lows, closes, period=14):
	"""计算 ATR(period)。需要至少 period+1 根 K 线。"""
	if not highs or not lows or not closes or len(closes) < period + 1:
		return None
	tr_list = []
	for i in range(1, min(len(highs), len(lows), len(closes))):
		prev_close = closes[i - 1]
		tr = max(
			highs[i] - lows[i],
			abs(highs[i] - prev_close),
			abs(lows[i] - prev_close)
		)
		tr_list.append(tr)
	if len(tr_list) < period:
		return None
	return np.mean(tr_list[-period:])


def check_weekly_trend(C, closes):
	"""第一层：周线趋势。周收盘 > SMA(周收盘, weekly_sma_period)。日线每 bars_per_week 根合成一周。"""
	if not closes or len(closes) < (C.weekly_sma_period + 1) * C.bars_per_week:
		return False
	weekly_closes = []
	for i in range((len(closes) - 1) // C.bars_per_week):
		idx = (i + 1) * C.bars_per_week - 1
		if idx < len(closes):
			weekly_closes.append(closes[idx])
	if len(weekly_closes) < C.weekly_sma_period:
		return False
	last_weekly = weekly_closes[-1]
	sma_weekly = np.mean(weekly_closes[-C.weekly_sma_period:])
	return last_weekly > sma_weekly and sma_weekly > 0


def calculate_residual_momentum(closes, market_closes, lookback):
	"""
	第二层：残差动量 > 0。用最近 lookback 日收益回归：r_stock = alpha + beta * r_market，残差均值>0。
	closes、market_closes 为等长日线收盘序列，最后一条为当前。
	"""
	if not closes or not market_closes or len(closes) < lookback + 1 or len(market_closes) < lookback + 1:
		return None
	n = min(len(closes), len(market_closes), lookback + 1)
	c = np.array(closes[-n:], dtype=float)
	m = np.array(market_closes[-n:], dtype=float)
	r_s = (c[1:] / c[:-1] - 1.0)
	r_m = (m[1:] / m[:-1] - 1.0)
	if np.std(r_m) < 1e-12:
		return np.mean(r_s)
	beta = np.cov(r_s, r_m)[0, 1] / (np.var(r_m) + 1e-12)
	residual = r_s - beta * r_m
	return np.mean(residual)


def check_hourly_breakout(C, stock, current_datetime_str):
	"""
	第三层：小时线突破。当前小时收盘 > 过去 hourly_breakout_bars 根小时收盘的最大值。
	用 5m 数据每 12 根合成 1 小时（取该小时最后一根 close）。
	"""
	bars_needed = (C.hourly_breakout_bars + 1) * C.bars_5m_per_hour + C.hourly_5m_buffer
	try:
		data_5m = C.get_market_data_ex(
			['close'], [stock], end_time=current_datetime_str,
			period='5m', count=bars_needed, subscribe=False
		)
	except Exception:
		return False
	if not data_5m or stock not in data_5m or 'close' not in data_5m:
		return False
	closes_5m = list(data_5m[stock]['close'])
	if len(closes_5m) < (C.hourly_breakout_bars + 1) * C.bars_5m_per_hour:
		return False
	hourly_closes = []
	for i in range((len(closes_5m) - 1) // C.bars_5m_per_hour):
		idx = (i + 1) * C.bars_5m_per_hour - 1
		if idx < len(closes_5m):
			hourly_closes.append(closes_5m[idx])
	if len(hourly_closes) < C.hourly_breakout_bars + 1:
		return False
	current_hourly = hourly_closes[-1]
	prev_high = max(hourly_closes[-(C.hourly_breakout_bars + 1):-1])
	return current_hourly > prev_high and prev_high > 0


def check_atr_vol_ok(highs, lows, closes, atr_period, current_close, atr_vol_max):
	"""波动率错峰：ATR(14)/close < atr_vol_max，避免追高在波动率峰值。"""
	if not current_close or current_close <= 0:
		return False
	atr = calc_atr(highs, lows, closes, atr_period)
	if atr is None:
		return False
	return (atr / current_close) < atr_vol_max


def handlebar(C):
	"""日线回调 - 先卖后买"""
	current_datetime_str = ""
	try:
		current_timetag = C.get_bar_timetag(C.barpos)
		current_date_str = timetag_to_datetime(current_timetag, '%Y%m%d')
		current_datetime_str = timetag_to_datetime(current_timetag, '%Y%m%d%H%M%S')

		# 股票池
		all_stocks = get_stock_pool(C, current_datetime_str)
		if not all_stocks:
			return

		# ---------- 卖出：ATR吊灯止损 / 短期动量转弱 / 到期 ----------
		stocks_to_remove = []
		for stock in list(C.holding.keys()):
			if not C.holding.get(stock, False):
				continue
			try:
				# 需要 high/low/close 计算持仓期间最高价与 ATR(14)
				data = C.get_market_data_ex(
					['close', 'high', 'low'], [stock], end_time=current_datetime_str,
					period='1d', count=max(C.sell_data_count_min, C.long_period + C.index_ma_count_buffer, C.atr_period + 20), subscribe=False
				)
				if stock not in data or 'close' not in data[stock]:
					continue
				closes = list(data[stock]['close'])
				highs = list(data[stock].get('high', []))
				lows = list(data[stock].get('low', []))
				if len(closes) < C.trend_short_period + 2:
					continue

				current_close = closes[-1]
				yesterday_close = closes[-2]
				buy_date = C.buy_date.get(stock, current_date_str)
				days_held = trading_days_diff(buy_date, current_date_str)
				buy_price = C.buy_price.get(stock, current_close)
				profit_pct = (current_close - buy_price) / buy_price if buy_price > 0 else 0
				shares = C.buy_shares.get(stock, 0)

				# 持仓期间最高价（自买入日至今的 high 的最大值）
				bars_since_entry = min(days_held + 1, len(closes), len(highs) if highs else 0)
				if bars_since_entry <= 0 or not highs:
					highest_high_since_entry = current_close
				else:
					highest_high_since_entry = max(highs[-bars_since_entry:])

				atr_14 = calc_atr(highs, lows, closes, C.atr_period)
				stop_loss = highest_high_since_entry - (atr_14 * C.atr_multiplier) if atr_14 is not None else None

				short_ma = np.mean(closes[-C.trend_short_period:])
				sell_reason = ""
				should_sell = False

				# ATR吊灯止损：当前收盘价 <= 止损位 则卖出
				if stop_loss is not None and current_close <= stop_loss:
					sell_reason = "ATR吊灯止损(最高%.3f ATR×%.1f 止损位%.3f)" % (highest_high_since_entry, C.atr_multiplier, stop_loss)
					should_sell = True
				elif days_held >= C.min_hold_days and (current_close < yesterday_close or current_close < short_ma):
					sell_reason = "短期动量转弱 持有%d天" % days_held
					should_sell = True
				elif days_held >= C.max_hold_days:
					sell_reason = "持有%d天到期" % days_held
					should_sell = True

				if should_sell and shares >= C.min_order_shares:
					passorder(24, 1101, C.accountid, stock, 5, 0, shares, "强势趋势轮动", 1, "", C)
					C.holding[stock] = False
					C.sell_date[stock] = current_date_str
					stocks_to_remove.append(stock)
					profit = (current_close - buy_price) * shares
					print("%s 卖出 %s %d股 @ %.3f %s 盈亏: %.2f (%.1f%%)" % (current_datetime_str, stock, shares, current_close, sell_reason, profit, profit_pct * 100))
			except Exception as e:
				print("%s 卖出异常 %s: %s" % (current_datetime_str, stock, e))

		# 清理已卖出标的的持仓记录（保留 sell_date 供冷却期使用）
		for stock in stocks_to_remove:
			for d in [C.holding, C.buy_price, C.buy_shares, C.buy_date]:
				d.pop(stock, None)

		# ---------- 买入：多周期动量打分 + 容量与冷却；可选三层过滤+波动率错峰 ----------
		current_holdings = sum(1 for h in C.holding.values() if h)
		total_stocks = min(C.stock_pool_scan_cap, len(all_stocks))
		required_data_length = max(C.trend_short_period, C.trend_mid_period, C.long_period) + C.required_data_buffer
		# 周线需至少 (weekly_sma_period+1)*bars_per_week 根日线
		if getattr(C, 'use_three_layer_filter', False):
			required_data_length = max(required_data_length, (C.weekly_sma_period + 1) * C.bars_per_week)

		# 残差动量：提前取指数日线（与个股对齐）
		market_closes = []
		if getattr(C, 'use_three_layer_filter', False):
			try:
				md = C.get_market_data_ex(
					['close'], [C.market_index_residual], end_time=current_datetime_str,
					period='1d', count=required_data_length, subscribe=False
				)
				if md and C.market_index_residual in md and md[C.market_index_residual].get('close'):
					market_closes = list(md[C.market_index_residual]['close'])
			except Exception:
				pass

		candidates = []
		passed_short_mom = 0
		passed_mid_mom = 0
		passed_long_mom = 0

		for stock in all_stocks[:total_stocks]:
			if C.holding.get(stock, False):
				continue
			if is_chinext_star_bse_or_st(C, stock):
				continue
			try:
				data = C.get_market_data_ex(
					['close', 'volume', 'high', 'low'], [stock],
					end_time=current_datetime_str, period='1d', count=required_data_length, subscribe=False
				)
				if stock not in data or len(data[stock].get('close', [])) < required_data_length:
					continue

				closes = list(data[stock]['close'])
				volumes = list(data[stock].get('volume', []))
				highs = list(data[stock].get('high', []))
				lows = list(data[stock].get('low', []))

				metrics, passed_flags = calc_momentum_features(C, closes, volumes, highs, lows)
				p_short, p_mid, p_long = passed_flags
				if p_short:
					passed_short_mom += 1
				if p_mid:
					passed_mid_mom += 1
				if p_long:
					passed_long_mom += 1
				if metrics is None:
					continue

				# 三层过滤 + 波动率错峰
				if getattr(C, 'use_three_layer_filter', False):
					if not check_weekly_trend(C, closes):
						continue
					residual_mom = calculate_residual_momentum(closes, market_closes, C.residual_lookback)
					if residual_mom is None or residual_mom <= 0:
						continue
					if not check_hourly_breakout(C, stock, current_datetime_str):
						continue
					if not check_atr_vol_ok(highs, lows, closes, C.atr_period, metrics['current_close'], C.atr_vol_max):
						continue

				current_close = metrics['current_close']
				target_shares = int(C.per_stock_amount / current_close)
				shares = (target_shares // C.min_order_shares) * C.min_order_shares
				if shares < C.min_order_shares:
					continue

				candidates.append({
					'stock': stock,
					'short_ret': metrics['short_ret'],
					'mid_ret': metrics['mid_ret'],
					'long_ret': metrics['long_ret'],
					'vol_ratio': metrics['vol_ratio'],
					'shares': shares,
					'current_close': current_close,
				})
			except Exception:
				pass

		# 中证1000 破位60日线不开仓
		if not is_csi1000_above_ma60(C, current_datetime_str):
			print("%s 中证1000破位60日线，不开仓" % current_datetime_str)
			candidates = []

		# 综合得分排序后下单
		final_bought = 0
		if candidates and current_holdings < C.max_hold_count:
			short_vals = [c['short_ret'] for c in candidates]
			mid_vals = [c['mid_ret'] for c in candidates]
			long_vals = [c['long_ret'] for c in candidates]
			vol_vals = [c['vol_ratio'] for c in candidates]
			s_min, s_max = min(short_vals), max(short_vals)
			m_min, m_max = min(mid_vals), max(mid_vals)
			l_min, l_max = min(long_vals), max(long_vals)
			v_min, v_max = min(vol_vals), max(vol_vals)

			def _norm(v, lo, hi):
				if hi <= lo:
					return 0.5
				return (v - lo) / (hi - lo)

			for c in candidates:
				c['score'] = (
					C.score_w_short * _norm(c['short_ret'], s_min, s_max) +
					C.score_w_mid * _norm(c['mid_ret'], m_min, m_max) +
					C.score_w_long * _norm(c['long_ret'], l_min, l_max) +
					C.score_w_volume * _norm(c['vol_ratio'], v_min, v_max)
				)
			candidates.sort(key=lambda x: x['score'], reverse=True)

			bought_today = 0
			for c in candidates:
				if current_holdings >= C.max_hold_count or bought_today >= C.max_buy_per_day:
					break
				stock = c['stock']
				if stock in C.sell_date:
					if trading_days_diff(C.sell_date[stock], current_date_str) < C.cooldown_days:
						continue

				passorder(23, 1101, C.accountid, stock, 5, 0, c['shares'], "强势趋势轮动", 1, "", C)
				C.holding[stock] = True
				C.buy_price[stock] = c['current_close']
				C.buy_shares[stock] = c['shares']
				C.buy_date[stock] = current_date_str
				current_holdings += 1
				final_bought += 1
				bought_today += 1
				print("%s 买入 %s %d股 @ %.3f 得分:%.3f 短:%.1f%% 中:%.1f%% 长:%.1f%%" % (
					current_datetime_str, stock, c['shares'], c['current_close'],
					c['score'], c['short_ret'] * 100, c['mid_ret'] * 100, c['long_ret'] * 100))

		print("%s 候选%d 通过短/中/长动量: %d/%d/%d 单日最多买%d 实际买%d 持仓%d" % (
			current_datetime_str, len(candidates), passed_short_mom, passed_mid_mom, passed_long_mom,
			C.max_buy_per_day, final_bought, sum(1 for h in C.holding.values() if h)))

	except Exception as e:
		print("%s handlebar异常: %s" % (current_datetime_str or "?", e))


def get_stock_pool(C, current_date_str):
	"""获取股票池（多指数成分取并集）。QMT 可用 get_index_constituent 或 get_stock_list_in_sector 等。"""
	all_stocks = []
	try:
		index_stocks = []
		indices = getattr(C, 'stock_pool_indices', ['000300.SH', '000905.SH', '000852.SH', '399006.SZ', '399001.SZ'])
		for index_code in indices:
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
	except Exception as e:
		print("股票池获取失败: %s" % e)
	return all_stocks


def is_csi1000_above_ma60(C, bar_date_str):
	"""大盘指数收盘 >= MA(long_period) 时返回 True 可开仓；破位返回 False。数据不足时返回 True 避免误拦。"""
	index_code = getattr(C, 'index_ma_filter', '000852.SH')
	try:
		data = C.get_market_data_ex(
			['close'], [index_code], end_time=bar_date_str, period='1d',
			count=C.long_period + C.index_ma_count_buffer, subscribe=False
		)
		if not data or index_code not in data or 'close' not in data[index_code]:
			return True
		closes = list(data[index_code]['close'])
		if len(closes) < C.long_period:
			return True
		ma60 = np.mean(closes[-C.long_period:])
		last_close = closes[-1]
		return last_close >= ma60
	except Exception:
		return True


def is_chinext_star_bse_or_st(C, stock_code):
	"""剔除 ST、创业板、科创板、北交所。ST 通过股票名称判断。"""
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
