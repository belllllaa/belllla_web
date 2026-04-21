# ==========================================
# 策略名称：价值因子策略（PE倒数）
# 策略逻辑：选出PE最低的20只股票，等权重买入
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

    # 调仓计数器
    context.days_since_rebalance = 0

    log.info('价值因子策略初始化完成')


def handle_data(context, data):
    """
    每日执行
    """
    context.days_since_rebalance += 1

    # 判断是否需要调仓
    if context.days_since_rebalance >= context.rebalance_interval:
        # 选股
        selected_stocks = select_by_value_factor(context, data)

        # 调仓
        rebalance(context, data, selected_stocks)

        # 重置计数器
        context.days_since_rebalance = 0


def select_by_value_factor(context, data):
    """
    价值因子选股
    """
    # 获取所有股票的估值数据
    q = query(
        valuation.code,
        valuation.pe_ratio
    ).filter(
        valuation.code.in_(context.stock_pool)
    )

    df = get_fundamentals(q)

    # 数据清洗
    df = df.dropna()  # 删除缺失值
    df = df[df['pe_ratio'] > 0]  # 只保留PE > 0的股票（排除亏损股）
    df = df[df['pe_ratio'] < 100]  # 排除极端值

    # 计算价值因子（PE倒数）
    df['value_pe'] = 1 / df['pe_ratio']

    # 按价值因子降序排序，选出前N只
    df = df.sort_values('value_pe', ascending=False)
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
            order_target(stock, 0)  # 卖出全部

    # 2. 买入目标股票（等权重）
    if len(target_stocks) > 0:
        target_value = context.portfolio.total_value / len(target_stocks)

        for stock in target_stocks:
            # 检查是否可交易
            if not data[stock].paused:
                order_target_value(stock, target_value)


# ==========================================
# 代码说明：
#
# 1. select_by_value_factor() - 价值因子选股
#    - 获取PE数据
#    - 计算PE倒数（价值因子）
#    - 排序选出前20只
#
# 2. rebalance() - 调仓
#    - 卖出不在目标列表的股票
#    - 等权重买入目标股票
#
# 3. order_target_value() - 下单API
#    - 自动计算需要买入/卖出的股数
#    - 使目标股票市值达到指定金额
# ==========================================
