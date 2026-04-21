# ==========================================
# 策略名称：双因子组合策略（价值 + 动量）
# 策略逻辑：价值因子 + 动量因子综合打分，选出前20只等权重买入
# ==========================================

def initialize(context):
    """
    策略初始化
    """
    set_benchmark('000300.XSHG')

    # 股票池：沪深300成分股
    context.stock_pool = get_index_stocks('000300.XSHG')

    # 选股数量
    context.stock_count = 20

    # 调仓间隔（天）
    context.rebalance_interval = 20
    context.days_since_rebalance = 0

    # 动量周期（天）
    context.momentum_period = 20

    # 因子权重
    context.value_weight = 0.5
    context.momentum_weight = 0.5

    log.info('双因子组合策略初始化完成')


def handle_data(context, data):
    """
    每日执行
    """
    context.days_since_rebalance += 1

    if context.days_since_rebalance >= context.rebalance_interval:
        selected_stocks = select_by_combined_factors(context, data)
        rebalance(context, data, selected_stocks)
        context.days_since_rebalance = 0


def select_by_combined_factors(context, data):
    """
    双因子选股：价值（PE倒数）+ 动量（20日收益率）
    """
    # 1. 获取估值数据（价值因子）
    q = query(
        valuation.code,
        valuation.pe_ratio
    ).filter(
        valuation.code.in_(context.stock_pool)
    )
    df = get_fundamentals(q)

    # 价值因子数据清洗
    df = df.dropna()
    df = df[(df['pe_ratio'] > 0) & (df['pe_ratio'] < 100)]
    df['value_pe'] = 1 / df['pe_ratio']

    # 2. 计算动量因子
    momentum_list = []
    for stock in df['code'].tolist():
        hist = attribute_history(
            stock,
            count=context.momentum_period + 1,
            unit='1d',
            fields=['close'],
            skip_paused=True
        )
        if len(hist) < context.momentum_period + 1:
            continue
        momentum = (hist['close'][-1] - hist['close'][0]) / hist['close'][0]
        momentum_list.append({'code': stock, 'momentum': momentum})

    if len(momentum_list) == 0:
        return []

    import pandas as pd
    momentum_df = pd.DataFrame(momentum_list)

    # 3. 合并数据
    df = df.merge(momentum_df, on='code')
    df = df.dropna()

    if len(df) == 0:
        return []

    # 4. 标准化因子值（Z-Score）
    value_std = df['value_pe'].std()
    if value_std and value_std > 0:
        df['value_pe_std'] = (df['value_pe'] - df['value_pe'].mean()) / value_std
    else:
        df['value_pe_std'] = 0

    momentum_std = df['momentum'].std()
    if momentum_std and momentum_std > 0:
        df['momentum_std'] = (df['momentum'] - df['momentum'].mean()) / momentum_std
    else:
        df['momentum_std'] = 0

    # 5. 合成综合得分
    df['score'] = (
        df['value_pe_std'] * context.value_weight
        + df['momentum_std'] * context.momentum_weight
    )

    # 6. 按综合得分排序选股
    df = df.sort_values('score', ascending=False)
    selected = df.head(context.stock_count)

    log.info(f'本次选股数量：{len(selected)}')

    return selected['code'].tolist()


def rebalance(context, data, target_stocks):
    """
    调仓操作
    """
    # 1. 卖出不在目标列表中的股票
    for stock in list(context.portfolio.positions.keys()):
        if stock not in target_stocks:
            order_target(stock, 0)

    # 2. 买入目标股票（等权重）
    if len(target_stocks) > 0:
        target_value = context.portfolio.total_value / len(target_stocks)
        for stock in target_stocks:
            if not data[stock].paused:
                order_target_value(stock, target_value)
