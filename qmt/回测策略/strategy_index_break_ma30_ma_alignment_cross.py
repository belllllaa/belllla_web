# coding: gbk
"""
QMT 回测：大盘破位 MA30 + 相对强度 / 趋势 / 波动压缩 / 资金

- 门控：指数**收盘低于 MA30**（破位）当日才扫描买入。
- 选股（须同时满足）：
  1）近 N 日涨幅 **> 大盘涨幅 + 相对强度阈值**（默认 20 日、+10%）；
  2）收盘 **> MA50** 且 **MA50 > MA150**；
  3）近 N1 日 ATR 在**近 N2 根 K 的 ATR 分布中处于最低 P%**（默认 20 日 ATR、120 日窗、20% 分位）；
  4）近 V1 日**平均成交额** > 近 V2 日平均成交额（默认 5>60）；
  5）破位当日个股**涨幅 > 0**（昨收→今收）。
- 卖出：**ATR 吊灯**（atr_period×atr_multiplier）；剔除 ST/创业板/科创/北交所。

入口：init / handlebar。
"""

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

STRATEGY_DEFAULTS = {
    "per_stock_amount": 100_000,
    "initial_capital": 1_000_000,
    "min_order_shares": 100,
    "max_hold_count": 10,
    "max_buy_per_day": 4,
    "cooldown_days": 1,
    "min_price": 3.0,
    "daily_count": 200,
    "skip_zero_volume": True,
    # 大盘破位门控
    "index_gate_code": "000905.SH",
    "index_breakdown_ma_period": 30,
    # 1）相对强度：近 rs_lookback 日收益 > 指数收益 + rs_extra_vs_index
    "rs_lookback": 20,
    "rs_extra_vs_index": 0.10,
    # 2）趋势：收盘 > MA50 > MA150
    "trend_ma_fast": 50,
    "trend_ma_slow": 150,
    # 3）波动压缩：atr_compress_period 日 ATR，在近 atr_compress_hist_bars 根 K 的 ATR 序列中 ≤ 最低 atr_compress_bottom_pct%
    "atr_compress_period": 20,
    "atr_compress_hist_bars": 120,
    "atr_compress_bottom_pct": 20.0,
    # 4）成交额：近 vol_short 日均 > 近 vol_long 日均
    "vol_short": 5,
    "vol_long": 60,
    # 5）破位日涨幅 > 0（昨收→今收）
    "require_positive_close_on_breakdown": True,
    # 卖出：ATR 吊灯（可与压缩用不同周期）
    "atr_period": 14,
    "atr_multiplier": 2.0,
    "stock_pool_indices": (
        "000300.SH",
        "000905.SH",
        "000852.SH",
        "399001.SZ",
        "399006.SZ",
        "399007.SZ",
    ),
    "stock_pool_scan_cap": 4000,
}


def _cfg(C: Any, key: str) -> Any:
    return getattr(C, key, STRATEGY_DEFAULTS[key])


def trading_days_diff(date_start: str, date_end: str) -> int:
    try:
        d1 = datetime.strptime(str(date_start), "%Y%m%d")
        d2 = datetime.strptime(str(date_end), "%Y%m%d")
        return max(0, (d2 - d1).days)
    except Exception:
        return 0


def timetag_to_datetime(timetag: Any, format_str: str = "%Y%m%d") -> str:
    try:
        return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
    except Exception:
        try:
            return time.strftime(format_str, time.localtime(float(timetag)))
        except Exception:
            return str(timetag)


def _calc_atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> Optional[float]:
    if not highs or not lows or not closes or len(closes) < period + 1:
        return None
    n = min(len(highs), len(lows), len(closes))
    tr_list = []
    for i in range(1, n):
        prev_close = float(closes[i - 1])
        hi, lo = float(highs[i]), float(lows[i])
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        tr_list.append(tr)
    if len(tr_list) < period:
        return None
    return float(np.mean(tr_list[-period:]))


def _ret_n_days(closes: Sequence[float], n: int) -> Optional[float]:
    if not closes or len(closes) < n + 1:
        return None
    try:
        a = float(closes[-(n + 1)])
        b = float(closes[-1])
        if a <= 0 or b <= 0:
            return None
        return b / a - 1.0
    except Exception:
        return None


def _index_breakdown_below_ma_ok(C, bar_date_str: str) -> bool:
    """指数收盘 < MA(index_breakdown_ma_period) 返回 True（破位门控通过）。"""
    code = str(_cfg(C, "index_gate_code"))
    p = max(2, int(_cfg(C, "index_breakdown_ma_period")))
    need = p + 5
    try:
        data = C.get_market_data_ex(
            ["close"], [code], end_time=bar_date_str, period="1d", count=need, subscribe=False
        )
        if not data or code not in data or "close" not in data[code]:
            return False
        closes = list(data[code]["close"])
        if len(closes) < p:
            return False
        last = float(closes[-1])
        ma = float(np.mean(closes[-p:]))
        if ma <= 0:
            return False
        return last < ma
    except Exception:
        return False


def _get_index_closes(C, bar_date_str: str, count: int) -> Optional[List[float]]:
    code = str(_cfg(C, "index_gate_code"))
    try:
        data = C.get_market_data_ex(
            ["close"], [code], end_time=bar_date_str, period="1d", count=count, subscribe=False
        )
        if not data or code not in data or "close" not in data[code]:
            return None
        return list(data[code]["close"])
    except Exception:
        return None


def _passes_relative_strength(C, stock_closes: List[float], index_closes: List[float]) -> bool:
    """近 rs_lookback 日：个股涨幅 > 指数涨幅 + rs_extra_vs_index。"""
    n = max(2, int(_cfg(C, "rs_lookback")))
    extra = float(_cfg(C, "rs_extra_vs_index"))
    rs = _ret_n_days(stock_closes, n)
    ri = _ret_n_days(index_closes, n)
    if rs is None or ri is None:
        return False
    return float(rs) > float(ri) + extra


def _passes_ma50_ma150(C, closes: List[float]) -> bool:
    """收盘 > MA50 且 MA50 > MA150。"""
    pf = max(2, int(_cfg(C, "trend_ma_fast")))
    ps = max(pf + 1, int(_cfg(C, "trend_ma_slow")))
    if len(closes) < ps:
        return False
    last = float(closes[-1])
    ma_f = float(np.mean(closes[-pf:]))
    ma_s = float(np.mean(closes[-ps:]))
    if ma_s <= 0:
        return False
    return last > ma_f > ma_s


def _atr_n_at_end(highs: List[float], lows: List[float], closes: List[float], period: int, end_idx: int) -> Optional[float]:
    """截至 end_idx（含）的 K 线，计算 ATR(period)。"""
    p = max(1, int(period))
    start = end_idx - p
    if start < 0 or end_idx >= len(closes):
        return None
    h = highs[start : end_idx + 1]
    l = lows[start : end_idx + 1]
    c = closes[start : end_idx + 1]
    return _calc_atr(h, l, c, p)


def _passes_atr_compress_bottom_pct(
    C, highs: List[float], lows: List[float], closes: List[float]
) -> bool:
    """近 atr_compress_period 日 ATR 在近 atr_compress_hist_bars 根 K 的 ATR 序列中处于最低 bottom_pct%。"""
    ap = max(2, int(_cfg(C, "atr_compress_period")))
    hist = max(20, int(_cfg(C, "atr_compress_hist_bars")))
    try:
        pct = float(_cfg(C, "atr_compress_bottom_pct"))
    except (TypeError, ValueError):
        pct = 20.0
    pct = max(0.0, min(100.0, pct))
    L = len(closes)
    if L < hist + ap + 2:
        return False
    atr_series: List[float] = []
    for k in range(hist):
        end_idx = L - 1 - k
        av = _atr_n_at_end(highs, lows, closes, ap, end_idx)
        if av is None:
            return False
        atr_series.append(av)
    cur = atr_series[0]
    thr = float(np.percentile(np.asarray(atr_series, dtype=float), pct))
    return cur <= thr


def _amount_series(vols: List[float], closes: List[float], amounts: Optional[List[float]]) -> List[float]:
    if amounts and len(amounts) == len(closes) and len(amounts) == len(vols):
        try:
            if sum(1 for x in amounts[-5:] if x is not None and float(x) > 0) >= 1:
                return [float(x) if x is not None else 0.0 for x in amounts]
        except Exception:
            pass
    return [float(v) * float(c) for v, c in zip(vols, closes)]


def _passes_volume_flow(C, vols: List[float], closes: List[float], amounts: Optional[List[float]]) -> bool:
    """近 vol_short 日平均成交额 > 近 vol_long 日平均成交额。"""
    vs = max(2, int(_cfg(C, "vol_short")))
    vl = max(vs + 1, int(_cfg(C, "vol_long")))
    if len(closes) < vl or len(vols) < vl:
        return False
    amt = _amount_series(vols, closes, amounts)
    if len(amt) < vl:
        return False
    a_s = float(np.mean(amt[-vs:]))
    a_l = float(np.mean(amt[-vl:]))
    return a_s > a_l


def _day_ret_last(closes: Sequence[float]) -> Optional[float]:
    if len(closes) < 2:
        return None
    try:
        prev_c = float(closes[-2])
        last = float(closes[-1])
        if prev_c <= 0:
            return None
        return last / prev_c - 1.0
    except Exception:
        return None


def _passes_positive_on_breakdown_day(C, closes: List[float]) -> bool:
    """大盘破位当日个股涨幅 > 0。"""
    if not bool(_cfg(C, "require_positive_close_on_breakdown")):
        return True
    dr = _day_ret_last(closes)
    if dr is None:
        return False
    return float(dr) > 0.0


def _passes_all_buy_filters(
    C,
    closes: List[float],
    highs: List[float],
    lows: List[float],
    vols: List[float],
    amounts: Optional[List[float]],
    index_closes: List[float],
) -> bool:
    if not _passes_relative_strength(C, closes, index_closes):
        return False
    if not _passes_ma50_ma150(C, closes):
        return False
    if not _passes_atr_compress_bottom_pct(C, highs, lows, closes):
        return False
    if not _passes_volume_flow(C, vols, closes, amounts):
        return False
    if not _passes_positive_on_breakdown_day(C, closes):
        return False
    return True


def _is_chinext_star_bse_or_st(C, stock_code: str) -> bool:
    """True=剔除标的：ST、创业板、科创板、北交所。"""
    if not stock_code or len(stock_code) < 6:
        return False
    code = stock_code.split(".")[0]
    suf = (stock_code.split(".")[-1] or "").upper()
    if suf == "BJ":
        return True
    if code.startswith(("300", "301", "302", "688", "689", "920")):
        return True
    try:
        name = C.get_stock_name(stock_code)
        if name:
            u = name.upper()
            if "ST" in u:
                return True
    except Exception:
        pass
    return False


def get_stock_pool(C, current_date_str: str) -> List[str]:
    all_stocks: List[str] = []
    try:
        index_stocks = []
        for index_code in _cfg(C, "stock_pool_indices"):
            try:
                if hasattr(C, "get_index_constituent"):
                    stocks = C.get_index_constituent(index_code)
                    if stocks:
                        index_stocks.extend(list(stocks))
                elif hasattr(C, "get_stock_list_in_sector"):
                    stocks = C.get_stock_list_in_sector(index_code)
                    if stocks:
                        index_stocks.extend(list(stocks))
                elif hasattr(C, "get_sector"):
                    stocks = C.get_sector(index_code)
                    if stocks:
                        index_stocks.extend(list(stocks))
            except Exception:
                continue
        if index_stocks:
            all_stocks = list(set(index_stocks))
    except Exception as e:
        print("股票池获取失败: %s" % e)
    return all_stocks


def init(C) -> None:
    C.accountid = getattr(C, "accountid", "")
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.sell_date = {}

    for key, val in STRATEGY_DEFAULTS.items():
        setattr(C, key, getattr(C, key, val))

    try:
        cap = float(getattr(C, "capital", None) or 0.0)
    except (TypeError, ValueError):
        cap = 0.0
    if cap > 0:
        C._sim_cash = cap
    else:
        C._sim_cash = float(_cfg(C, "initial_capital"))

    print(
        "破位MA30+RS/趋势/压缩/成交额 指数%s<MA%d | %d日强+指数+%.0f%% MA%d>MA%d | ATR%d在%d根K分布下%.0f%%分位 | 成交%d>%d日 | 破位日涨>0 | 卖ATR(%d)x%.1f | 每票%.0f元 最多%d只 日买%d 冷却%d"
        % (
            _cfg(C, "index_gate_code"),
            int(_cfg(C, "index_breakdown_ma_period")),
            int(_cfg(C, "rs_lookback")),
            float(_cfg(C, "rs_extra_vs_index")) * 100,
            int(_cfg(C, "trend_ma_fast")),
            int(_cfg(C, "trend_ma_slow")),
            int(_cfg(C, "atr_compress_period")),
            int(_cfg(C, "atr_compress_hist_bars")),
            float(_cfg(C, "atr_compress_bottom_pct")),
            int(_cfg(C, "vol_short")),
            int(_cfg(C, "vol_long")),
            int(_cfg(C, "atr_period")),
            float(_cfg(C, "atr_multiplier")),
            float(_cfg(C, "per_stock_amount")),
            int(_cfg(C, "max_hold_count")),
            int(_cfg(C, "max_buy_per_day")),
            int(_cfg(C, "cooldown_days")),
        )
    )


def handlebar(C) -> None:
    current_datetime_str = ""
    try:
        current_timetag = C.get_bar_timetag(C.barpos)
        current_date_str = timetag_to_datetime(current_timetag, "%Y%m%d")
        current_datetime_str = timetag_to_datetime(current_timetag, "%Y%m%d%H%M%S")

        all_stocks = get_stock_pool(C, current_datetime_str)
        if not all_stocks:
            return

        rs_n = int(_cfg(C, "rs_lookback"))
        ps = max(int(_cfg(C, "trend_ma_slow")), int(_cfg(C, "trend_ma_fast")))
        vl = int(_cfg(C, "vol_long"))
        hist = int(_cfg(C, "atr_compress_hist_bars"))
        ap_c = int(_cfg(C, "atr_compress_period"))
        need_len = max(rs_n + 2, ps + 2, vl + 2, hist + ap_c + 5, int(_cfg(C, "atr_period")) + 2)
        count = max(int(_cfg(C, "daily_count")), need_len + 20, int(_cfg(C, "index_breakdown_ma_period")) + 10)

        stocks_to_remove: List[str] = []
        for stock in list(C.holding.keys()):
            if not C.holding.get(stock, False):
                continue
            try:
                data = C.get_market_data_ex(
                    ["close", "high", "low"],
                    [stock],
                    end_time=current_datetime_str,
                    period="1d",
                    count=max(80, int(_cfg(C, "atr_period")) + 25),
                    subscribe=False,
                )
                if stock not in data or "close" not in data[stock]:
                    continue
                closes = list(data[stock]["close"])
                highs = list(data[stock].get("high", []))
                lows = list(data[stock].get("low", []))
                if len(closes) < 5:
                    continue
                current_close = float(closes[-1])
                buy_price = float(C.buy_price.get(stock, current_close))
                profit_pct = (current_close - buy_price) / buy_price if buy_price > 0 else 0.0
                shares = int(C.buy_shares.get(stock, 0))

                buy_date = C.buy_date.get(stock, current_date_str)
                days_held = trading_days_diff(buy_date, current_date_str)
                bars_since_entry = min(days_held + 1, len(closes), len(highs) if highs else 0)
                if bars_since_entry <= 0 or not highs:
                    highest_high = current_close
                else:
                    highest_high = max(float(x) for x in highs[-bars_since_entry:])

                atr_v = _calc_atr(highs, lows, closes, int(_cfg(C, "atr_period"))) if highs and lows else None
                mult = float(_cfg(C, "atr_multiplier"))
                chandelier = highest_high - (atr_v * mult) if atr_v is not None else None
                should_sell = chandelier is not None and current_close <= chandelier

                if should_sell and shares >= int(_cfg(C, "min_order_shares")):
                    passorder(24, 1101, C.accountid, stock, 5, 0, shares, "破位MA30选股", 1, "", C)
                    try:
                        C._sim_cash = float(getattr(C, "_sim_cash", 0.0)) + float(shares) * float(current_close)
                    except Exception:
                        pass
                    C.holding[stock] = False
                    C.sell_date[stock] = current_date_str
                    stocks_to_remove.append(stock)
                    profit = (current_close - buy_price) * shares
                    print(
                        "%s 卖出 %s %d股 @ %.3f ATR吊灯 盈亏:%.2f (%.1f%%)"
                        % (current_datetime_str, stock, shares, current_close, profit, profit_pct * 100)
                    )
            except Exception as e:
                print("%s 卖出异常 %s: %s" % (current_datetime_str, stock, e))

        for stock in stocks_to_remove:
            for d in (C.holding, C.buy_price, C.buy_shares, C.buy_date):
                d.pop(stock, None)

        if not _index_breakdown_below_ma_ok(C, current_datetime_str):
            return

        index_closes = _get_index_closes(C, current_datetime_str, max(rs_n + 5, int(_cfg(C, "index_breakdown_ma_period")) + 10))
        if not index_closes or len(index_closes) < rs_n + 1:
            return

        total_scan = min(int(_cfg(C, "stock_pool_scan_cap")), len(all_stocks))
        candidates: List[Dict[str, Any]] = []

        for stock in all_stocks[:total_scan]:
            if C.holding.get(stock, False):
                continue
            if _is_chinext_star_bse_or_st(C, stock):
                continue
            if stock in getattr(C, "sell_date", {}) and trading_days_diff(C.sell_date[stock], current_date_str) < int(
                _cfg(C, "cooldown_days")
            ):
                continue
            try:
                data = C.get_market_data_ex(
                    ["close", "high", "low", "volume"],
                    [stock],
                    end_time=current_datetime_str,
                    period="1d",
                    count=count,
                    subscribe=False,
                )
                if stock not in data or len(data[stock].get("close", [])) < need_len:
                    continue
                closes = list(data[stock]["close"])
                highs = list(data[stock].get("high", []))
                lows = list(data[stock].get("low", []))
                vols = list(data[stock].get("volume", []))
                amts = None
                try:
                    if "amount" in data[stock] and data[stock]["amount"] is not None:
                        amts = list(data[stock]["amount"])
                except Exception:
                    amts = None
                if bool(_cfg(C, "skip_zero_volume")) and vols and float(vols[-1]) <= 0:
                    continue
                if float(closes[-1]) < float(_cfg(C, "min_price")):
                    continue
                if not _passes_all_buy_filters(C, closes, highs, lows, vols, amts, index_closes):
                    continue
                price = float(closes[-1])
                per_amt = float(_cfg(C, "per_stock_amount"))
                target_shares = int(per_amt / price)
                shares = (target_shares // int(_cfg(C, "min_order_shares"))) * int(_cfg(C, "min_order_shares"))
                if shares < int(_cfg(C, "min_order_shares")):
                    continue
                candidates.append({"stock": stock, "price": price, "shares": shares})
            except Exception:
                pass

        candidates.sort(key=lambda x: str(x["stock"]))

        final_bought = 0
        bought_today = 0
        current_holdings = sum(1 for h in C.holding.values() if h)
        if candidates:
            for c in candidates:
                if current_holdings >= int(_cfg(C, "max_hold_count")):
                    break
                if bought_today >= int(_cfg(C, "max_buy_per_day")):
                    break
                stock = c["stock"]
                cost = float(c["shares"]) * float(c["price"])
                if float(getattr(C, "_sim_cash", 0.0)) < cost:
                    continue
                passorder(23, 1101, C.accountid, stock, 5, 0, c["shares"], "破位MA30选股", 1, "", C)
                try:
                    C._sim_cash = float(getattr(C, "_sim_cash", 0.0)) - cost
                except Exception:
                    pass
                C.holding[stock] = True
                C.buy_price[stock] = c["price"]
                C.buy_shares[stock] = c["shares"]
                C.buy_date[stock] = current_date_str
                current_holdings += 1
                final_bought += 1
                bought_today += 1
                print("%s 买入 %s %d股 @ %.3f RS+趋势+压缩+额" % (current_datetime_str, stock, c["shares"], c["price"]))

        if final_bought:
            print(
                "%s 本日买入%d 持仓%d 剩余现金%.0f"
                % (
                    current_datetime_str,
                    final_bought,
                    sum(1 for h in C.holding.values() if h),
                    float(getattr(C, "_sim_cash", 0.0)),
                )
            )

    except Exception as e:
        print("%s handlebar异常: %s" % (current_datetime_str or "?", e))
