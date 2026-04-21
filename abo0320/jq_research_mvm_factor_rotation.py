# ==========================================
# 策略名称：三因子组合策略（动量 + 价值 + 市值）
# 策略逻辑：价值+动量+市值选股；空仓时建仓；持仓期间硬止损(-8%)+ATR 跟踪止损，无固定周期调仓
# ==========================================

import numpy as np
import pandas as pd


def initialize(context):
    """
    策略初始化
    """
    set_benchmark("000300.XSHG")

    # 股票池：沪深300成分股（可改为其他指数）
    context.stock_pool = get_index_stocks("000300.XSHG")

    # 选股数量
    context.stock_count = 10

    # 分钟线回测时 handle_data 一日多次，用该日期去重，保证「每交易日」只计 1 次
    context._last_counted_trade_date = None

    # ATR 跟踪止损：收盘价跌破「持仓以来最高收盘价 - atr_stop_mult * ATR」则清仓该标的
    context.atr_period = 14
    context.atr_stop_mult = 2.0
    # 每只股票持仓以来的最高收盘价（用于吊灯/跟踪止损）
    context.position_high = {}

    # 硬止损：相对持仓成本价（聚宽 avg_cost）浮亏达到该比例则清仓，例如 0.08 表示 -8%
    context.hard_stop_pct = 0.08

    # 动量周期（天）
    context.momentum_period = 20

    # 三因子权重（之和为 1）：动量 50%，价值 / 市值各 25%
    context.weight_momentum = 0.5
    context.weight_value = 0.25
    context.weight_mcap = 0.25

    # 市值：True 用 log(总市值)，False 用原值；mcap_prefer_small=True 时小市值 Z 分高（从小到大偏好）
    context.use_log_market_cap = True
    context.mcap_prefer_small = True

    # 去极值：截面 Winsorize，将因子值截断到 [clip_pct_low, clip_pct_high] 分位（默认 1%~99%）
    context.clip_pct_low = 0.01
    context.clip_pct_high = 0.99

    # 剔除 ST：选股时用 get_extras('is_st') 按当前交易日过滤
    context.exclude_st = True

    # 选股与下单时剔除停牌、涨跌停（依赖 data / get_current_data）
    context.exclude_suspend_and_limit = True

    log.info(
        "三因子+止损初始化: N=%s, 硬止损=%.0f%%, ATR=%s×%s, w=(动量%.2f,价值%.2f,市值%.2f)"
        % (
            context.stock_count,
            context.hard_stop_pct * 100,
            context.atr_period,
            context.atr_stop_mult,
            context.weight_momentum,
            context.weight_value,
            context.weight_mcap,
        )
    )


def _exclude_st_stocks(context, stock_list):
    """
    从股票列表中剔除 ST（聚宽 is_st：1=是 ST，0=否）。
    ST 状态随时间变化，须在每次选股日用 context.current_dt 计算。
    """
    if not stock_list:
        return []
    if not getattr(context, "exclude_st", True):
        return list(stock_list)
    d = context.current_dt.date()
    st_df = get_extras("is_st", stock_list, end_date=d, count=1)
    if st_df is None or st_df.empty:
        return list(stock_list)
    row = st_df.iloc[-1]
    out = []
    for s in stock_list:
        try:
            v = row[s]
        except (KeyError, TypeError):
            out.append(s)
            continue
        if pd.isna(v) or float(v) != 1.0:
            out.append(s)
    return out


def _is_empty_stock_positions(context):
    """无股票持仓（空仓）时 True，回测首日应立刻建仓。"""
    pos = context.portfolio.positions
    if not pos:
        return True
    for s in pos:
        if pos[s].total_amount > 0:
            return False
    return True


def _is_tradeable(context, data, stock):
    """
    当日可参与选股/调仓：非停牌，且非涨停、非跌停（聚宽 last_price 与 high_limit/low_limit）。
    若 data / get_current_data 无涨跌停价或 hi<=0，则不做涨跌停过滤（避免 hi=0 时误判全员涨停）。
    """
    if not getattr(context, "exclude_suspend_and_limit", True):
        return True
    if stock not in data:
        return True
    if data[stock].paused:
        return False
    cd = get_current_data()
    if stock not in cd:
        return True
    q = cd[stock]
    lp = getattr(q, "last_price", None)
    hi = getattr(q, "high_limit", None)
    lo = getattr(q, "low_limit", None)
    if not (np.isfinite(lp) and np.isfinite(hi) and np.isfinite(lo)):
        return True
    # 无效涨跌停价时勿用 lp>=hi-eps 判断（hi=0 会导致所有正价都被当成涨停）
    if hi <= 0 or lo <= 0 or hi <= lo:
        return True
    eps = 1e-4
    if lp >= hi - eps or lp <= lo + eps:
        return False
    return True


def _compute_atr(stock, period):
    """用日线 high/low/close 计算 ATR（最近 period 根 TR 的算术均值）。"""
    hist = attribute_history(
        stock,
        count=period + 5,
        unit="1d",
        fields=["high", "low", "close"],
        skip_paused=True,
    )
    if hist is None or len(hist["close"]) < period + 1:
        return None
    high = np.asarray(hist["high"], dtype=float)
    low = np.asarray(hist["low"], dtype=float)
    close = np.asarray(hist["close"], dtype=float)
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
    )
    if len(tr) < period:
        return None
    return float(np.mean(tr[-period:]))


def _apply_stop_losses(context, data):
    """持仓标的：先硬止损（相对成本价浮亏）；再 ATR 跟踪止损；并维护 position_high。"""
    mult = getattr(context, "atr_stop_mult", 2.0)
    period = getattr(context, "atr_period", 14)
    hard_pct = getattr(context, "hard_stop_pct", 0.08)
    pos = context.portfolio.positions
    for stock in list(pos.keys()):
        if pos[stock].total_amount <= 0:
            continue
        if stock not in data:
            continue
        close = data[stock].close
        if close is None or (isinstance(close, float) and not np.isfinite(close)):
            continue
        close = float(close)
        p = pos[stock]
        avg_cost = getattr(p, "avg_cost", None)
        if avg_cost is not None and float(avg_cost) > 0 and np.isfinite(avg_cost):
            avg_cost = float(avg_cost)
            if close <= avg_cost * (1.0 - hard_pct):
                order_target(stock, 0)
                context.position_high.pop(stock, None)
                log.info(
                    "硬止损-%.0f%%: %s close=%.3f avg=%.3f"
                    % (hard_pct * 100, stock, close, avg_cost)
                )
                continue
        old_high = context.position_high.get(stock, close)
        atr = _compute_atr(stock, period)
        if atr is not None and atr > 0 and old_high > 0:
            stop_line = old_high - mult * atr
            if close < stop_line:
                order_target(stock, 0)
                context.position_high.pop(stock, None)
                log.info("ATR止损卖出: %s close=%.3f line=%.3f ATR=%.4f" % (stock, close, stop_line, atr))
                continue
        context.position_high[stock] = max(old_high, close)


def _winsorize_series(s: pd.Series, low: float, high: float) -> pd.Series:
    """截面分位截断：将序列限制在 [low, high] 分位数之间，抑制极端值。"""
    s = pd.to_numeric(s, errors="coerce")
    valid = s.dropna()
    if len(valid) == 0:
        return s
    q_lo = valid.quantile(low)
    q_hi = valid.quantile(high)
    if not np.isfinite(q_lo) or not np.isfinite(q_hi):
        return s
    if q_lo > q_hi:
        q_lo, q_hi = q_hi, q_lo
    return s.clip(lower=q_lo, upper=q_hi)


def handle_data(context, data):
    """
    每个交易日执行（聚宽不会在休市日调用；分钟频率下每个自然日只按第一根有效 bar 计一个交易日）。
    有仓：先硬止损(-8% 可调)再 ATR 止损；空仓：因子选股建仓。无固定 N 日调仓。
    """
    today = context.current_dt.date()
    if getattr(context, "_last_counted_trade_date", None) == today:
        return
    context._last_counted_trade_date = today

    if not _is_empty_stock_positions(context):
        _apply_stop_losses(context, data)

    if _is_empty_stock_positions(context):
        selected_stocks = select_by_mvm_factors(context, data)
        rebalance(context, data, selected_stocks)


def select_by_mvm_factors(context, data):
    """
    三因子选股：价值（1/PE 与 1/PB 等权合成 Z 分）+ 动量 + 市值。
    结构与 abo0320/04_combined_factor_strategy.py 的 select_by_combined_factors 对齐（分步注释 + 逐列 Z-Score）。
    """
    # 1. 获取估值数据（价值因子 + 市值）；股票池先剔除 ST
    pool = _exclude_st_stocks(context, context.stock_pool)
    if not pool:
        return []

    q = query(
        valuation.code,
        valuation.pe_ratio,
        valuation.pb_ratio,
        valuation.market_cap,
    ).filter(
        valuation.code.in_(pool)
    )
    df = get_fundamentals(q)

    # 价值 / 市值数据清洗：正 PE、正 PB（便于 1/PE、1/PB）与正市值
    df = df.dropna()
    df = df[(df["pe_ratio"] > 0) & (df["pb_ratio"] > 0)]
    df = df[df["market_cap"] > 0]
    df["value_pe"] = 1 / df["pe_ratio"]
    df["value_pb"] = 1 / df["pb_ratio"]
    m = df["market_cap"].astype(float)
    if context.use_log_market_cap:
        size_base = np.log(m)
    else:
        size_base = m
    # 小市值偏好：对规模取负再标准化，使同截面内市值越小 → cap_raw 越大 → mcap_std 越高
    if getattr(context, "mcap_prefer_small", True):
        df["cap_raw"] = -size_base
    else:
        df["cap_raw"] = size_base

    # 2. 计算动量因子（与 04 相同写法）；跳过停牌、涨跌停
    momentum_list = []
    for stock in df["code"].tolist():
        if not _is_tradeable(context, data, stock):
            continue
        hist = attribute_history(
            stock,
            count=context.momentum_period + 1,
            unit="1d",
            fields=["close"],
            skip_paused=True,
        )
        if len(hist) < context.momentum_period + 1:
            continue
        momentum = (hist["close"][-1] - hist["close"][0]) / hist["close"][0]
        momentum_list.append({"code": stock, "momentum": momentum})

    if len(momentum_list) == 0:
        return []

    momentum_df = pd.DataFrame(momentum_list)

    # 3. 合并数据
    df = df.merge(momentum_df, on="code")
    df = df.dropna()

    if len(df) == 0:
        return []

    # 3b. 合并后再筛一遍停牌、涨跌停（与动量环节一致）
    df = df[df["code"].apply(lambda c: _is_tradeable(context, data, c))]
    if len(df) == 0:
        return []

    # 4. 去极值：价值（PE/PB）、动量、市值原始值截面分位截断，再标准化
    lo, hi = context.clip_pct_low, context.clip_pct_high
    df["value_pe"] = _winsorize_series(df["value_pe"], lo, hi)
    df["value_pb"] = _winsorize_series(df["value_pb"], lo, hi)
    df["momentum"] = _winsorize_series(df["momentum"], lo, hi)
    df["cap_raw"] = _winsorize_series(df["cap_raw"], lo, hi)

    # 5. 标准化因子值（Z-Score）；PE、PB 各自标准化后等权合成价值 Z 分
    value_pe_s = df["value_pe"].std()
    if value_pe_s and value_pe_s > 0:
        df["value_pe_std"] = (df["value_pe"] - df["value_pe"].mean()) / value_pe_s
    else:
        df["value_pe_std"] = 0

    value_pb_s = df["value_pb"].std()
    if value_pb_s and value_pb_s > 0:
        df["value_pb_std"] = (df["value_pb"] - df["value_pb"].mean()) / value_pb_s
    else:
        df["value_pb_std"] = 0

    df["value_std"] = (df["value_pe_std"] + df["value_pb_std"]) / 2.0

    momentum_std = df["momentum"].std()
    if momentum_std and momentum_std > 0:
        df["momentum_std"] = (df["momentum"] - df["momentum"].mean()) / momentum_std
    else:
        df["momentum_std"] = 0

    mcap_std = df["cap_raw"].std()
    if mcap_std and mcap_std > 0:
        df["mcap_std"] = (df["cap_raw"] - df["cap_raw"].mean()) / mcap_std
    else:
        df["mcap_std"] = 0

    # 6. 合成综合得分（三因子权重；价值 = PE/PB 合成 Z 分）
    df["score"] = (
        df["value_std"] * context.weight_value
        + df["momentum_std"] * context.weight_momentum
        + df["mcap_std"] * context.weight_mcap
    )

    # 7. 按综合得分排序选股；最终名单再排除停牌、涨跌停
    df = df.sort_values("score", ascending=False)
    codes_ok = []
    for _, row in df.iterrows():
        c = row["code"]
        if not _is_tradeable(context, data, c):
            continue
        codes_ok.append(c)
        if len(codes_ok) >= context.stock_count:
            break

    log.info("本次选股数量：%s" % len(codes_ok))

    return codes_ok


def rebalance(context, data, target_stocks):
    """
    调仓操作
    """
    for stock in list(context.portfolio.positions.keys()):
        if stock not in target_stocks:
            order_target(stock, 0)

    if len(target_stocks) > 0:
        tradeable = [s for s in target_stocks if _is_tradeable(context, data, s)]
        if not tradeable:
            return
        target_value = context.portfolio.total_value / len(tradeable)
        for stock in tradeable:
            order_target_value(stock, target_value)
        for stock in tradeable:
            if stock in data and data[stock].close is not None:
                c = float(data[stock].close)
                if np.isfinite(c):
                    context.position_high[stock] = c
