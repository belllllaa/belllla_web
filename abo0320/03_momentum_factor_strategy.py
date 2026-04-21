# ==========================================
# 策略名称：动量因子策略（20日收益率）
# 策略逻辑：选出20日涨幅最大的20只股票
# ==========================================

def initialize(context):
    """
    策略初始化
    """
    set_benchmark('000300.XSHG')
    context.stock_pool = get_index_stocks('000300.XSHG')
    context.stock_count = 20
    context.rebalance_interval = 20
    context.days_since_rebalance = 0

    # 动量计算周期
    context.momentum_period = 20

    log.info('动量因子策略初始化完成')


def handle_data(context, data):
    """
    每日执行
    """
    context.days_since_rebalance += 1

    if context.days_since_rebalance >= context.rebalance_interval:
        selected_stocks = select_by_momentum_factor(context, data)
        rebalance(context, data, selected_stocks)
        context.days_since_rebalance = 0


def select_by_momentum_factor(context, data):
    """
    动量因子选股
    """
    momentum_list = []

    for stock in context.stock_pool:
        # 获取历史价格
        hist = attribute_history(
            stock,
            count=context.momentum_period + 1,  # 需要21天数据来计算20日收益率
            unit='1d',
            fields=['close'],
            skip_paused=True  # 跳过停牌日
        )

        # 检查数据是否充足
        if len(hist) < context.momentum_period + 1:
            continue

        # 计算动量（20日收益率）
        momentum = (hist['close'][-1] - hist['close'][0]) / hist['close'][0]

        momentum_list.append({
            'code': stock,
            'momentum': momentum
        })

    # 转为DataFrame并排序
    import pandas as pd
    df = pd.DataFrame(momentum_list)

    if len(df) == 0:
        return []

    # 按动量降序排序，选出前N只
    df = df.sort_values('momentum', ascending=False)
    selected = df.head(context.stock_count)

    log.info(f'本次选股数量：{len(selected)}')

    return selected['code'].tolist()


def rebalance(context, data, target_stocks):
    """
    调仓操作（与价值因子策略相同）
    """
    # 卖出
    for stock in list(context.portfolio.positions.keys()):
        if stock not in target_stocks:
            order_target(stock, 0)

    # 买入
    if len(target_stocks) > 0:
        target_value = context.portfolio.total_value / len(target_stocks)
        for stock in target_stocks:
            if not data[stock].paused:
                order_target_value(stock, target_value)


# ==========================================
# 代码说明：
#
# 1. select_by_momentum_factor() - 动量因子选股
#    - 遍历所有股票
#    - 获取每只股票的20日历史价格
#    - 计算动量 = (当前价 - 20日前价格) / 20日前价格
#    - 排序选出动量最大的前20只
#
# 2. attribute_history() - 获取历史数据API
#    - count: 获取多少天的数据
#    - unit: 时间单位（'1d' = 日线）
#    - fields: 需要的字段（close = 收盘价）
#    - skip_paused: 跳过停牌日
# ==========================================
