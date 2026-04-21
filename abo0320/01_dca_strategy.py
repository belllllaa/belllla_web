# ==========================================
# 策略名称：沪深300指数定投策略
# 策略逻辑：每月1号买入10000元沪深300ETF
# ==========================================

def initialize(context):
    """
    策略初始化（只运行一次）
    """
    # 设置基准
    set_benchmark('000300.XSHG')  # 沪深300指数

    # 设置要定投的标的（沪深300ETF）
    context.target_stock = '510300.XSHG'  # 华泰柏瑞沪深300ETF

    # 每次定投金额
    context.investment_amount = 10000  # 每次投入10000元

    # 设置定投日（每月1号）
    context.target_day = 1

    # 打印初始化信息
    log.info('策略初始化完成')
    log.info(f'定投标的：{context.target_stock}')
    log.info(f'每次投入：{context.investment_amount}元')


def handle_data(context, data):
    """
    每日执行（每个交易日9:30运行一次）
    """
    # 获取当前日期
    current_date = context.current_dt

    # 判断是否为每月1号（或1号是非交易日则顺延到下一个交易日）
    if current_date.day == context.target_day:
        # 执行定投
        do_investment(context, data)


def do_investment(context, data):
    """
    执行定投操作
    """
    stock = context.target_stock
    amount = context.investment_amount

    # 检查标的是否可交易
    if data[stock].paused:
        log.info(f'{stock} 停牌，本次定投跳过')
        return

    # 获取当前价格
    current_price = data[stock].close

    # 计算可买入股数（向下取整到100的倍数）
    shares_to_buy = (amount // current_price) // 100 * 100

    if shares_to_buy > 0:
        # 下单买入
        order(stock, shares_to_buy)
        log.info(f'定投买入 {stock}，数量：{shares_to_buy}股，价格：{current_price:.2f}')
    else:
        log.info(f'资金不足，无法买入（需要{current_price * 100:.2f}元）')


# ==========================================
# 代码解释：
#
# 1. initialize() - 策略初始化
#    - 只运行一次（回测开始时）
#    - 设置策略参数（标的、金额、定投日期）
#
# 2. handle_data() - 每日执行
#    - 每个交易日9:30运行一次
#    - 检查是否为定投日
#
# 3. do_investment() - 定投操作
#    - 检查标的是否可交易
#    - 计算可买入股数
#    - 下单买入
# ==========================================
