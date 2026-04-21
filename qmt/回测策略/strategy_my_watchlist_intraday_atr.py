# coding: gbk
"""
QMT：自选池 get_stock_list_in_sector('我的自选')；满仓单票，总预算 per_stock_amount（默认 10 万）分批建仓。

开盘分档（gap = 今开/昨收 - 1）：
  A: -5% < gap < 3% — 记录开盘价，首笔买 50% 仅限 9:30–9:35；锚定价=成交价；相对锚定 -5% 补 30%、-8% 补 20% 仓位（按预算比例）。
  B: 3% < gap < 7% — 记录开盘价，股价跌至开盘价 -3% 时买 50% 并记锚定价；锚定 -5% 补 30%、-3% 补 20%（下跌过程中先触发较浅档位：
     先 -3% 档 20%，再 -5% 档 30%，与常见「先浅后深」一致）。
  C: gap > 7% — 记录开盘价，跌至开盘价 -4% 时买 50% 并记锚定价；之后同 B（锚定 -5% 30%、-3% 20%）。
  D: gap < -5% — 仅开盘买 50%，不再加仓。

指数：上证指数 000001.SH 收盘破 MA10 清仓全部；收盘在 MA5 下方不开新仓（仍可管理已有仓的加仓/卖出）。

卖出：ATR 仅作止盈（持仓盈利且触发吊灯回撤才平仓）；硬止损总浮亏 <= -8% 清仓；
      当日曾跌至昨收 -8% 且收盘仍低于昨收 -6% 时尾盘清仓。

自选与持仓：自选仅作候选；已持仓不加重复仓。止损/止盈跟踪 C.holding。

【重要】分档与分批依赖分钟 K，请用 1m 周期回测/实盘；日线周期仅作近似。
回测起止日期请在 QMT 回测面板设置，策略内不设回测区间。
"""

import sys
import time
from datetime import datetime

import numpy as np

try:
    import talib
except Exception:
    talib = None


STRATEGY_TAG = "我的自选分档建仓"

INDEX_SSE = "000001.SH"

STRATEGY_DEFAULTS = {
    # 默认资金账号；也可在策略参数里覆盖 account_id_override
    "account_id_override": "11219398",
    # 未注入 accountid 时的备用（一般留空，优先用上一项）
    "backtest_passorder_account_fallback": "",
    "block_handlebar_when_no_account": False,
    "watchlist_sector_name": "我的自选",
    "per_stock_amount": 100000,
    "min_order_shares": 100,
    "max_hold_count": 1,
    "ma_index_period_short": 5,
    "ma_index_period_long": 10,
    "atr_period": 14,
    "atr_stop_mult": 2.0,
    "bar_count": 80,
    "verbose_log": True,
    "allow_atr_same_day": True,
    "hard_stop_pct": -0.08,
    "intraday_touch_pct": -0.08,
    "intraday_fail_recover_pct": -0.06,
    "tail_clear_start_hhmmss": 145000,
    # A 档首买仅在开盘窗口内（与实盘一致）；加仓腿仍全天连续竞价按今开
    "a_first_buy_start_hhmmss": 92500,
    "a_first_buy_end_hhmmss": 93559,
}


def _cfg(C, key):
    return getattr(C, key, STRATEGY_DEFAULTS[key])


def timetag_to_datetime(timetag, format_str="%Y%m%d%H%M%S"):
    try:
        return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
    except Exception:
        try:
            return time.strftime(format_str, time.localtime(float(timetag)))
        except Exception:
            return str(timetag)


def _account_type_for_query(C):
    t = getattr(C, "accountType", None) or getattr(C, "account_type", None)
    return str(t) if t else "STOCK"


def _ohlc_to_list(raw):
    if raw is None:
        return []
    try:
        import pandas as pd

        if isinstance(raw, pd.Series):
            return [float(x) for x in raw.tolist()]
        if isinstance(raw, pd.DataFrame):
            return [float(x) for x in raw.iloc[:, 0].tolist()]
    except Exception:
        pass
    if hasattr(raw, "tolist") and not isinstance(raw, (list, tuple, bytes)):
        try:
            return [float(x) for x in raw.tolist()]
        except Exception:
            pass
    try:
        return [float(x) for x in list(raw)]
    except Exception:
        return []


def _vb(C):
    return bool(_cfg(C, "verbose_log"))


def _account_id_for_order(C):
    accid = getattr(C, "accountid", None) or getattr(C, "account_id", None)
    if accid is None:
        return ""
    return str(accid).strip()


def _bootstrap_account(C):
    cur = getattr(C, "accountid", None)
    C.accountid = str(cur).strip() if cur is not None else ""
    if not C.accountid:
        aid = getattr(C, "account_id", None)
        if aid:
            C.accountid = str(aid).strip()
    if not C.accountid:
        for fn_name in ("get_accounts", "GetAccounts", "get_Accounts"):
            fn = getattr(C, fn_name, None)
            if not callable(fn):
                continue
            try:
                accs = fn()
                if not accs:
                    continue
                if isinstance(accs, (list, tuple)):
                    a0 = accs[0]
                else:
                    a0 = accs
                if isinstance(a0, str) and a0.strip():
                    C.accountid = a0.strip()
                    break
                if a0 is not None:
                    aid = (
                        getattr(a0, "accountID", None)
                        or getattr(a0, "accountid", None)
                        or getattr(a0, "AccountID", None)
                        or getattr(a0, "m_strAccountID", None)
                    )
                    if aid:
                        C.accountid = str(aid).strip()
                        break
            except Exception:
                continue
    ovr = (getattr(C, "account_id_override", None) or _cfg(C, "account_id_override") or "").strip()
    if ovr:
        C.accountid = ovr
    if not (getattr(C, "accountid", None) or "").strip():
        fb = (
            getattr(C, "backtest_passorder_account_fallback", None)
            or _cfg(C, "backtest_passorder_account_fallback")
            or ""
        )
        fb = str(fb).strip()
        if fb:
            C.accountid = fb
    if not (getattr(C, "accountid", None) or "").strip():
        try:
            main = sys.modules.get("__main__")
            if main is not None:
                m = getattr(main, "accountid", None) or getattr(main, "default_account", None)
                if m:
                    C.accountid = str(m).strip()
        except Exception:
            pass
    return (getattr(C, "accountid", None) or "").strip()


def _get_period(C):
    p = getattr(C, "period", None) or getattr(C, "Period", None) or "1d"
    return str(p).lower()


def _parse_hhmmss_from_bar(C):
    try:
        tt = C.get_bar_timetag(C.barpos)
        s = timetag_to_datetime(tt, "%Y%m%d%H%M%S")
        if len(s) >= 14:
            return int(s[8:14])
    except Exception:
        pass
    return None


def _in_session_trade(hhmmss):
    if hhmmss is None:
        return False
    if 93000 <= hhmmss <= 113000:
        return True
    if 130000 <= hhmmss <= 150000:
        return True
    return False


def _a_preopen_for_first_buy_bt(C, hhmmss):
    if hhmmss is None:
        return False
    try:
        h = int(hhmmss)
    except Exception:
        return False
    a0 = int(_cfg(C, "a_first_buy_start_hhmmss"))
    if a0 >= 93000:
        return False
    return a0 <= h < 93000


def _canonical_stock_code(s):
    if s is None:
        return ""
    t = str(s).strip().upper().replace("\u3000", " ")
    if not t:
        return ""
    if "." in t:
        a, b = t.split(".", 1)
        if len(a) == 6 and a.isdigit() and b in ("SH", "SZ", "BJ"):
            return "%s.%s" % (a, b)
        if a in ("SH", "SZ", "BJ") and len(b) == 6 and b.isdigit():
            return "%s.%s" % (b, a)
    if len(t) >= 8 and t[:2] in ("SH", "SZ", "BJ") and t[2:8].isdigit():
        return "%s.%s" % (t[2:8], t[:2])
    return t


def _pool_from_sector(C):
    name = (getattr(C, "watchlist_sector_name", None) or _cfg(C, "watchlist_sector_name") or "").strip()
    if not name or not hasattr(C, "get_stock_list_in_sector"):
        return []
    try:
        raw = C.get_stock_list_in_sector(name)
        if not raw:
            return []
        out = []
        seen = set()
        for x in raw:
            c = _canonical_stock_code(x)
            if not c:
                c = str(x).strip()
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return sorted(out)
    except Exception:
        return []


def _position_codes(C):
    accid = _account_id_for_order(C)
    if not accid:
        return set()
    try:
        pos = get_trade_detail_data(accid, _account_type_for_query(C), "position")
    except Exception:
        return set()
    if not pos:
        return set()
    out = set()
    for p in pos:
        try:
            c = _canonical_stock_code("%s.%s" % (p.m_strInstrumentID, p.m_strExchangeID))
            if not c:
                c = "%s.%s" % (p.m_strInstrumentID, p.m_strExchangeID)
            if int(getattr(p, "m_nVolume", 0) or 0) > 0:
                out.add(c)
        except Exception:
            continue
    return out


def _sse_ma_state(C, dt_full):
    """
    返回 (close_idx, ma5, ma10, allow_new_long, liquidate_all)
    allow_new_long: 收盘 >= MA5 才允许开新仓
    liquidate_all: 收盘 < MA10 清仓
    """
    n = max(int(_cfg(C, "ma_index_period_long")), 15)
    try:
        data_d = C.get_market_data_ex(
            ["close"],
            [INDEX_SSE],
            end_time=dt_full,
            period="1d",
            count=n,
            subscribe=False,
        )
        if INDEX_SSE not in data_d:
            return None, None, None, True, False
        closes = _ohlc_to_list(data_d[INDEX_SSE].get("close"))
        if not closes or len(closes) < int(_cfg(C, "ma_index_period_long")):
            return None, None, None, True, False
        last = float(closes[-1])
        p5 = int(_cfg(C, "ma_index_period_short"))
        p10 = int(_cfg(C, "ma_index_period_long"))
        ma5 = sum(float(x) for x in closes[-p5:]) / float(p5)
        ma10 = sum(float(x) for x in closes[-p10:]) / float(p10)
        allow_new = last >= ma5
        liq_all = last < ma10
        return last, ma5, ma10, allow_new, liq_all
    except Exception:
        return None, None, None, True, False


def _daily_open_prevclose(C, stock, dt_full):
    try:
        data_d = C.get_market_data_ex(
            ["open", "close"],
            [stock],
            end_time=dt_full,
            period="1d",
            count=max(int(_cfg(C, "bar_count")), 5),
            subscribe=False,
        )
        if stock not in data_d:
            return None, None
        opens = _ohlc_to_list(data_d[stock].get("open"))
        closes = _ohlc_to_list(data_d[stock].get("close"))
        if len(closes) < 2 or not opens:
            return None, None
        prev_close = float(closes[-2])
        open_today = float(opens[-1])
        if prev_close <= 0 or open_today <= 0:
            return None, None
        return open_today, prev_close
    except Exception:
        return None, None


def _gap_bracket(gap):
    """返回 'A'|'B'|'C'|'D'|None（边界：gap<=-5% 为 D；-5%~3% 为 A；3%~7% 为 B；>7% 为 C）"""
    if gap is None:
        return None
    if gap <= -0.05:
        return "D"
    if gap < 0.03:
        return "A"
    if gap < 0.07:
        return "B"
    return "C"


def _shares_for_cash(cash_yuan, price, mos):
    if price <= 0 or cash_yuan <= 0:
        return 0
    sh = int(float(cash_yuan) / float(price))
    return (sh // mos) * mos


def _avg_cost(C, stock):
    sh = int(C.buy_shares.get(stock, 0) or 0)
    tc = float(C.total_cost.get(stock, 0) or 0)
    if sh <= 0:
        return None
    return tc / float(sh)


def _check_atr_take_profit_only(
    C,
    days_held_effective,
    highs,
    lows,
    closes,
    current_close,
    avg_cost,
):
    """ATR 吊灯，仅在浮盈时作为止盈触发。"""
    if talib is None:
        return False, "talib 未安装"
    if avg_cost is None or current_close <= avg_cost:
        return False, "ATR止盈仅浮盈触发"
    if not highs or not lows or not closes or len(closes) < 2:
        return False, "K线不足"
    if days_held_effective < 1 and not bool(_cfg(C, "allow_atr_same_day")):
        return False, "持仓不足1日"

    n_since = min(max(days_held_effective, 1), len(highs))
    try:
        highest_high = max(float(x) for x in highs[-n_since:])
    except Exception:
        return False, "最高价失败"

    try:
        atr_arr = talib.ATR(
            np.array(highs, dtype=np.float64),
            np.array(lows, dtype=np.float64),
            np.array(closes, dtype=np.float64),
            int(_cfg(C, "atr_period")),
        )
        atr_v = float(atr_arr[-1]) if len(atr_arr) and not np.isnan(atr_arr[-1]) else None
    except Exception:
        atr_v = None

    mult = float(_cfg(C, "atr_stop_mult"))
    if atr_v is None or atr_v <= 0:
        return False, "ATR无效"

    stop = highest_high - atr_v * mult
    if current_close <= stop:
        return True, "ATR止盈 线=%.3f" % stop
    return False, "ATR未触发"


def _clear_stock_state(C, stock):
    for d in (
        C.holding,
        C.buy_price,
        C.buy_shares,
        C.buy_date,
        C.total_cost,
        C.anchor_buy,
        C.gap_bracket,
        C.open_px,
        C.prev_close_ref,
        C.leg_done,
        C.wait_first,
        C.touch_neg8,
    ):
        if isinstance(d, dict):
            d.pop(stock, None)
    if hasattr(C, "_day_low_marker"):
        C._day_low_marker.pop(stock, None)
    if hasattr(C, "_day_low_val"):
        C._day_low_val.pop(stock, None)


def init(C):
    print("%s init" % STRATEGY_TAG)
    try:
        C.accountid = getattr(C, "accountid", "")
        C.holding = {}
        C.buy_price = {}
        C.buy_shares = {}
        C.buy_date = {}
        C.total_cost = {}
        C.anchor_buy = {}
        C.gap_bracket = {}
        C.open_px = {}
        C.prev_close_ref = {}
        C.leg_done = {}
        C.wait_first = {}
        C.touch_neg8 = {}
        C._day_low_marker = {}
        C._day_low_val = {}
        C._morning_trade_date = ""
        C._afternoon_trade_date = ""

        for k, v in STRATEGY_DEFAULTS.items():
            setattr(C, k, getattr(C, k, v))

        aid = _bootstrap_account(C)
        print("  accountid=%r" % aid)
        print(
            "  sector=%r 单票预算=%.0f MA指数=%d/%d"
            % (
                C.watchlist_sector_name,
                float(C.per_stock_amount),
                int(C.ma_index_period_short),
                int(C.ma_index_period_long),
            )
        )
        pool = _pool_from_sector(C)
        print("  自选池探测 count=%d %s" % (len(pool), pool[:12] if pool else []))
        print("%s init done" % STRATEGY_TAG)
    except Exception as e:
        print("%s INIT FAIL %r" % (STRATEGY_TAG, e))
        raise


def _primary_holding_stock(C):
    """返回 C.holding 中实际键名（用于字典读写一致）。"""
    for k, v in C.holding.items():
        if v and int(C.buy_shares.get(k, 0) or 0) > 0:
            return k
    return None


def _apply_buy_leg(C, stock, cash_yuan, price_now, dt_full, d_str, mos, tag):
    sh = _shares_for_cash(cash_yuan, price_now, mos)
    if sh < mos:
        return False
    passorder(23, 1101, C.accountid, stock, 5, 0, sh, STRATEGY_TAG, 1, "", C)
    prev_sh = int(C.buy_shares.get(stock, 0) or 0)
    prev_tc = float(C.total_cost.get(stock, 0) or 0)
    C.buy_shares[stock] = prev_sh + sh
    C.total_cost[stock] = prev_tc + sh * float(price_now)
    C.holding[stock] = True
    C.buy_date[stock] = d_str
    avg = C.total_cost[stock] / float(C.buy_shares[stock])
    C.buy_price[stock] = avg
    print("%s 【%s】%s %d股 @%.3f 约%.0f元 均本%.3f" % (dt_full, tag, stock, sh, price_now, sh * price_now, avg))
    return True


def handlebar(C):
    dt_full = ""
    try:
        _bootstrap_account(C)
        aid = _account_id_for_order(C)
        if not aid:
            if not getattr(C, "_warned_no_account", False):
                C._warned_no_account = True
                print("%s 未解析到资金账号" % STRATEGY_TAG)
            if bool(getattr(C, "block_handlebar_when_no_account", False)):
                return

        tt = C.get_bar_timetag(C.barpos)
        dt_full = timetag_to_datetime(tt, "%Y%m%d%H%M%S")
        d_str = dt_full[:8]
        period = _get_period(C)
        hhmmss = _parse_hhmmss_from_bar(C)

        pool = _pool_from_sector(C)
        pos_codes = _position_codes(C)
        if not hasattr(C, "_day_low_marker"):
            C._day_low_marker = {}
        if not hasattr(C, "_day_low_val"):
            C._day_low_val = {}

        hold_keys = set()
        for k, v in C.holding.items():
            if v:
                ck = _canonical_stock_code(k) or k
                hold_keys.add(ck)
        already = pos_codes | hold_keys

        mos = int(C.min_order_shares)
        notional = float(C.per_stock_amount)
        mhc = int(C.max_hold_count)

        idx_close, idx_ma5, idx_ma10, index_allow_new, index_liquidate_all = _sse_ma_state(C, dt_full)
        if _vb(C) and idx_close is not None:
            print(
                "%s 上证 收=%.2f MA5=%.2f MA10=%.2f 开新=%s 清全=%s"
                % (
                    d_str,
                    idx_close,
                    idx_ma5 or 0,
                    idx_ma10 or 0,
                    index_allow_new,
                    index_liquidate_all,
                )
            )

        def liquidate_stock(stock, reason):
            sh = int(C.buy_shares.get(stock, 0) or 0)
            if sh < mos:
                _clear_stock_state(C, stock)
                return
            try:
                data_m = C.get_market_data_ex(
                    ["close"],
                    [stock],
                    end_time=dt_full,
                    period="1m",
                    count=1,
                    subscribe=False,
                )
                px = float(_ohlc_to_list(data_m[stock].get("close"))[-1]) if stock in data_m else 0.0
            except Exception:
                px = 0.0
            passorder(24, 1101, C.accountid, stock, 5, 0, sh, STRATEGY_TAG, 1, "", C)
            print("%s 【清仓】%s %d股 原因:%s px=%.3f" % (dt_full, stock, sh, reason, px))
            _clear_stock_state(C, stock)

        def run_index_liquidate():
            if not index_liquidate_all:
                return
            if not _in_session_trade(hhmmss):
                return
            for stock in list(C.holding.keys()):
                if C.holding.get(stock):
                    liquidate_stock(stock, "上证破MA10清仓")

        def run_risk_sell():
            if not _in_session_trade(hhmmss):
                return
            for stock in list(C.holding.keys()):
                if not C.holding.get(stock):
                    continue
                try:
                    data_d = C.get_market_data_ex(
                        ["close", "high", "low", "open"],
                        [stock],
                        end_time=dt_full,
                        period="1d",
                        count=int(_cfg(C, "bar_count")),
                        subscribe=False,
                    )
                    if stock not in data_d:
                        continue
                    highs = _ohlc_to_list(data_d[stock].get("high"))
                    lows = _ohlc_to_list(data_d[stock].get("low"))
                    closes = _ohlc_to_list(data_d[stock].get("close"))
                    if len(closes) < 2:
                        continue

                    if period == "1m":
                        data_m = C.get_market_data_ex(
                            ["close", "low", "high"],
                            [stock],
                            end_time=dt_full,
                            period="1m",
                            count=1,
                            subscribe=False,
                        )
                        if stock not in data_m:
                            continue
                        cm = _ohlc_to_list(data_m[stock].get("close"))
                        lm = _ohlc_to_list(data_m[stock].get("low"))
                        if not cm:
                            continue
                        px = float(cm[-1])
                        bar_low = float(lm[-1]) if lm else px
                    else:
                        px = float(closes[-1])
                        bar_low = px

                    prev_ref = float(C.prev_close_ref.get(stock, closes[-2]))
                    if prev_ref <= 0:
                        prev_ref = float(closes[-2])

                    if C._day_low_marker.get(stock) != d_str:
                        C._day_low_marker[stock] = d_str
                        C._day_low_val[stock] = bar_low
                    else:
                        C._day_low_val[stock] = min(float(C._day_low_val.get(stock, bar_low)), bar_low)
                    dv = float(C._day_low_val[stock])

                    if dv / prev_ref - 1.0 <= float(_cfg(C, "intraday_touch_pct")):
                        C.touch_neg8[stock] = d_str

                    avg_c = _avg_cost(C, stock)
                    if avg_c and px / avg_c - 1.0 <= float(_cfg(C, "hard_stop_pct")):
                        liquidate_stock(stock, "硬止损-8%")
                        continue

                    tail_start = int(_cfg(C, "tail_clear_start_hhmmss"))
                    if hhmmss is not None and hhmmss >= tail_start and period == "1m":
                        if C.touch_neg8.get(stock) == d_str and (px / prev_ref - 1.0) < float(
                            _cfg(C, "intraday_fail_recover_pct")
                        ):
                            liquidate_stock(stock, "尾盘曾触-8%且收盘未回到-6%")
                            continue

                    bdate = C.buy_date.get(stock, d_str)
                    try:
                        dh = max(
                            0,
                            (datetime.strptime(d_str, "%Y%m%d") - datetime.strptime(bdate, "%Y%m%d")).days,
                        )
                    except Exception:
                        dh = 1
                    if bdate == d_str:
                        dh_eff = 1 if bool(_cfg(C, "allow_atr_same_day")) else 0
                    else:
                        dh_eff = max(1, dh)

                    should_tp, note = _check_atr_take_profit_only(
                        C, dh_eff, highs, lows, closes, px, avg_c
                    )
                    if _vb(C):
                        print("%s 【止盈检查】%s %s" % (dt_full, stock, note))
                    if should_tp:
                        liquidate_stock(stock, note)
                except Exception as e:
                    print("%s 【风控卖异常】%s %s" % (dt_full, stock, e))

        def run_pyramid_and_entry():
            if period != "1m":
                return

            ph = _primary_holding_stock(C)
            if ph:
                if not _in_session_trade(hhmmss):
                    br_ph = C.gap_bracket.get(ph)
                    if not (br_ph == "A" and _a_preopen_for_first_buy_bt(C, hhmmss)):
                        return
                stock = ph
                bracket = C.gap_bracket.get(stock)
                anchor = C.anchor_buy.get(stock)
                if bracket == "D" or anchor is None:
                    return
                legs = list(C.leg_done.get(stock, [True, False, False]))
                if len(legs) != 3:
                    legs = [True, False, False]
                price_now = None
                try:
                    data_m = C.get_market_data_ex(
                        ["close"],
                        [stock],
                        end_time=dt_full,
                        period="1m",
                        count=1,
                        subscribe=False,
                    )
                    if stock in data_m:
                        cm = _ohlc_to_list(data_m[stock].get("close"))
                        if cm:
                            price_now = float(cm[-1])
                except Exception:
                    pass
                if price_now is None or price_now <= 0:
                    return

                if bracket == "A":
                    o_a = C.open_px.get(stock)
                    if o_a is not None and o_a > 0:
                        if not legs[1] and price_now <= o_a * 0.95:
                            if _apply_buy_leg(
                                C,
                                stock,
                                notional * 0.30,
                                price_now,
                                dt_full,
                                d_str,
                                mos,
                                "\u3010A\u6863\u3011\u52a0\u4ed330%|\u4eca\u5f00x0.95(-5%)",
                            ):
                                legs[1] = True
                        if not legs[2] and price_now <= o_a * 0.92:
                            if _apply_buy_leg(
                                C,
                                stock,
                                notional * 0.20,
                                price_now,
                                dt_full,
                                d_str,
                                mos,
                                "\u3010A\u6863\u3011\u52a0\u4ed320%|\u4eca\u5f00x0.92(-8%)",
                            ):
                                legs[2] = True
                elif bracket == "B":
                    o_b = C.open_px.get(stock)
                    if o_b is not None and o_b > 0:
                        if not legs[1] and price_now <= o_b * 0.95:
                            if _apply_buy_leg(
                                C,
                                stock,
                                notional * 0.30,
                                price_now,
                                dt_full,
                                d_str,
                                mos,
                                "\u3010B\u6863\u3011\u52a0\u4ed330%|\u4eca\u5f00x0.95(-5%)",
                            ):
                                legs[1] = True
                        if not legs[2] and price_now <= o_b * 0.92:
                            if _apply_buy_leg(
                                C,
                                stock,
                                notional * 0.20,
                                price_now,
                                dt_full,
                                d_str,
                                mos,
                                "\u3010B\u6863\u3011\u52a0\u4ed320%|\u4eca\u5f00x0.92(-8%)",
                            ):
                                legs[2] = True
                elif bracket == "C":
                    o_c = C.open_px.get(stock)
                    if o_c is not None and o_c > 0:
                        if not legs[1] and price_now <= o_c * 0.91:
                            if _apply_buy_leg(
                                C,
                                stock,
                                notional * 0.30,
                                price_now,
                                dt_full,
                                d_str,
                                mos,
                                "\u3010C\u6863\u3011\u52a0\u4ed330%|\u4eca\u5f00x0.91(-9%)",
                            ):
                                legs[1] = True
                        if not legs[2] and price_now <= o_c * 0.88:
                            if _apply_buy_leg(
                                C,
                                stock,
                                notional * 0.20,
                                price_now,
                                dt_full,
                                d_str,
                                mos,
                                "\u3010C\u6863\u3011\u52a0\u4ed320%|\u4eca\u5f00x0.88(-12%)",
                            ):
                                legs[2] = True
                C.leg_done[stock] = legs
                return

            if not (_in_session_trade(hhmmss) or _a_preopen_for_first_buy_bt(C, hhmmss)):
                return

            if not pool:
                return
            if not index_allow_new:
                if _vb(C):
                    print("%s 【不开新仓】上证在MA5下" % dt_full)
                return
            if len(already) >= mhc:
                return

            stock = _canonical_stock_code(pool[0]) or pool[0]
            if stock in already:
                if _vb(C):
                    print("%s 【跳过】%s 已持仓" % (dt_full, stock))
                return

            o_today, prev_c = _daily_open_prevclose(C, stock, dt_full)
            if o_today is None:
                return
            gap = o_today / prev_c - 1.0
            br = _gap_bracket(gap)

            C.open_px[stock] = o_today
            C.prev_close_ref[stock] = prev_c
            C.gap_bracket[stock] = br

            if _a_preopen_for_first_buy_bt(C, hhmmss) and (not _in_session_trade(hhmmss)) and br != "A":
                return

            price_now = None
            try:
                data_m = C.get_market_data_ex(
                    ["close"],
                    [stock],
                    end_time=dt_full,
                    period="1m",
                    count=1,
                    subscribe=False,
                )
                if stock in data_m:
                    cm = _ohlc_to_list(data_m[stock].get("close"))
                    if cm:
                        price_now = float(cm[-1])
            except Exception:
                pass
            if price_now is None or price_now <= 0:
                return

            legs = [False, False, False]

            if br == "D":
                if _apply_buy_leg(
                    C,
                    stock,
                    notional * 0.50,
                    price_now,
                    dt_full,
                    d_str,
                    mos,
                    "\u3010D\u6863\u3011\u9996\u4e7050%\u5355\u7b14\u65e0\u52a0\u4ed3",
                ):
                    legs[0] = True
                    C.anchor_buy[stock] = price_now
                    C.leg_done[stock] = legs
                return

            if br == "A":
                a0 = int(_cfg(C, "a_first_buy_start_hhmmss"))
                a1 = int(_cfg(C, "a_first_buy_end_hhmmss"))
                if hhmmss is None or not (a0 <= hhmmss <= a1):
                    return
                if _apply_buy_leg(
                    C,
                    stock,
                    notional * 0.50,
                    price_now,
                    dt_full,
                    d_str,
                    mos,
                    "\u3010A\u6863\u3011\u9996\u4e7050%|%06d-%06d" % (a0, a1),
                ):
                    legs[0] = True
                    C.anchor_buy[stock] = price_now
                    C.leg_done[stock] = legs
                return

            if br == "B":
                thr = C.open_px[stock] * 0.97
                if price_now > thr:
                    return
                if _apply_buy_leg(
                    C,
                    stock,
                    notional * 0.50,
                    price_now,
                    dt_full,
                    d_str,
                    mos,
                    "\u3010B\u6863\u3011\u9996\u4e7050%|\u4eca\u5f00x0.97",
                ):
                    legs[0] = True
                    C.anchor_buy[stock] = price_now
                    C.leg_done[stock] = legs
                return

            if br == "C":
                thr = C.open_px[stock] * 0.96
                if price_now > thr:
                    return
                if _apply_buy_leg(
                    C,
                    stock,
                    notional * 0.50,
                    price_now,
                    dt_full,
                    d_str,
                    mos,
                    "\u3010C\u6863\u3011\u9996\u4e7050%|\u4eca\u5f00x0.96",
                ):
                    legs[0] = True
                    C.anchor_buy[stock] = price_now
                    C.leg_done[stock] = legs
                return

        run_index_liquidate()
        run_risk_sell()
        if period == "1m":
            run_pyramid_and_entry()
        else:
            if _vb(C):
                print("%s 当前为日线周期：分档/分批未启用，请改 1m" % dt_full)

    except Exception as e:
        print("%s handlebar ERR %r dt=%s" % (STRATEGY_TAG, e, dt_full))


def handleBar(C):
    handlebar(C)


def handle_bar(C):
    handlebar(C)
