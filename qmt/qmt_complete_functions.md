# QMT 内置Python函数完整文档

## 目录
- [系统函数](#系统函数)
- [行情函数](#行情函数)
- [交易函数](#交易函数)
- [引用函数](#引用函数)
- [绘图函数](#绘图函数)
- [枚举常量](#枚举常量)

---

## 系统函数

### ContextInfo 对象
ContextInfo 是策略运行环境对象，是 init, after_init, handlebar 等基本方法的入参，里面包括了终端自带的属性和方法。

### init - 初始化函数
**原型**: `init(ContextInfo)`
- **说明**: 初始化函数，只在整个策略开始时调用运行到一次
- **参数**: ContextInfo - 策略运行环境对象
- **返回**: 无
- **示例**:
```python
def init(ContextInfo):
    ContextInfo.initProfit = 0
```

### after_init - 初始化后函数
**原型**: `after_init(ContextInfo)`
- **说明**: 后初始化函数，在初始化函数执行完成后被调用一次
- **参数**: ContextInfo - 策略运行环境对象
- **返回**: 无
- **示例**:
```python
def after_init(ContextInfo):
    print('系统会在init函数执行完后和执行handlebar之前调用after_init')
```

### handlebar - 行情事件函数
**原型**: `handlebar(ContextInfo)`
- **说明**: 行情事件函数，每根 K 线运行一次；实时行情获取状态下，先每根历史 K 线运行一次，再在每个 tick 数据来后驱动运行一次
- **参数**: ContextInfo - 策略运行环境对象
- **返回**: 无
- **示例**:
```python
def handlebar(ContextInfo):
    print(ContextInfo.barpos)
```

### ContextInfo.schedule_run - 设置定时器
**原型**: `ContextInfo.schedule_run(func, time_point, repeat_times=0, interval=None, name='')`
- **说明**: 新版设置定时器函数，支持任务分组、任务取消等功能
- **参数**:
  - func: 回调函数
  - time_point: 预定的第一次触发时间
  - repeat_times: 重复触发次数
  - interval: 时间间隔
  - name: 定时器任务组名
- **返回**: int - 定时任务号
- **示例**:
```python
import datetime as dt
def on_timer(C):
    print('hello world')
def init(ContextInfo):
    tid = ContextInfo.schedule_run(on_timer, '20231231235959', -1, dt.timedelta(minutes=1), 'my_timer')
```

### ContextInfo.run_time - 设置定时器（旧版）
**原型**: `ContextInfo.run_time(funcName, period, startTime)`
- **说明**: 设置定时器函数，可以指定时间间隔，定时触发用户定义的回调函数
- **参数**:
  - funcName: 回调函数名
  - period: 重复调用的时间间隔
  - startTime: 定时器第一次启动的时间
- **示例**:
```python
import time
def init(ContextInfo):
    ContextInfo.run_time("f", "5nSecond", "2019-10-14 13:20:00")
def f(ContextInfo):
    print('hello world')
```

### ContextInfo.is_last_bar - 是否为最后一根K线
**原型**: `ContextInfo.is_last_bar()`
- **说明**: 判定是否为最后一根 K 线
- **返回**: bool - True是最新k线，False不是
- **示例**:
```python
def handlebar(ContextInfo):
    print(ContextInfo.is_last_bar())
```

### ContextInfo.is_new_bar - 判定是否为新的 K 线
**原型**: `ContextInfo.is_new_bar()`
- **说明**: 某根 K 线的第一个 tick 数据到来时，判定该 K 线为新的 K 线
- **返回**: bool
- **示例**:
```python
def handlebar(ContextInfo):
    print(ContextInfo.is_new_bar())
```

### ContextInfo.get_stock_name - 根据代码获取名称
**原型**: `ContextInfo.get_stock_name('stockcode')`
- **说明**: 根据代码获取名称
- **参数**: stockcode - 股票代码
- **返回**: string（GBK编码）
- **示例**:
```python
def handlebar(ContextInfo):
    print(ContextInfo.get_stock_name('000001.SZ'))
```

### ContextInfo.get_open_date - 根据代码返回对应股票的上市时间
**原型**: `ContextInfo.get_open_date('stockcode')`
- **说明**: 根据代码返回对应股票的上市时间
- **参数**: stockcode - 股票代码
- **返回**: number
- **示例**:
```python
def init(ContextInfo):
    print(ContextInfo.get_open_date('000001.SZ'))
```

### 板块管理函数
- `create_sector(parent_node, sector_name, overwrite)` - 创建板块
- `create_sector_folder(parent_node, folder_name, overwrite)` - 创建板块目录节点
- `get_sector_list(node)` - 获取板块目录信息
- `reset_sector_stock_list(sector, stock_list)` - 设置板块成分股
- `remove_stock_from_sector(sector, stock_code)` - 移除板块成分股
- `add_stock_to_sector(sector, stock_code)` - 添加板块成分股

---

## 行情函数

### download_history_data - 下载指定合约代码指定周期对应时间范围的行情数据
**原型**: `download_history_data(stockcode, period, startTime, endTime)`
- **说明**: 下载指定合约代码指定周期对应时间范围的行情数据
- **参数**:
  - stockcode: 股票代码，格式为'stkcode.market'
  - period: K线周期类型
  - startTime: 起始时间
  - endTime: 结束时间
- **示例**:
```python
def init(C):
    download_history_data("000001.SZ", "1d", "20230101", "")
```

### ContextInfo.get_market_data_ex - 获取行情数据
**原型**: 
```python
ContextInfo.get_market_data_ex(
    fields=[],
    stock_code=[],
    period='follow',
    start_time='',
    end_time='',
    count=-1,
    dividend_type='follow',
    fill_data=True,
    subscribe=True
)
```
- **说明**: 获取实时行情与历史行情数据
- **参数**:
  - fields: 数据字段
  - stock_code: 合约代码列表
  - period: 数据周期
  - start_time: 数据起始时间
  - end_time: 数据结束时间
  - count: 数据个数
  - dividend_type: 除权方式
  - fill_data: 是否填充数据
  - subscribe: 订阅数据开关
- **返回**: dict { stock_code1 : value1, stock_code2 : value2, ... }
- **示例**:
```python
def handlebar(C):
    data1 = C.get_market_data_ex([], C.stock_list, period="1d", count=1)
    data2 = C.get_market_data_ex([], C.stock_list, period="1d", start_time=C.start_time, end_time=C.end_time)
```

### ContextInfo.get_full_tick - 获取全推数据
**原型**: `ContextInfo.get_full_tick(stock_code=[])`
- **说明**: 获取最新分笔数据
- **参数**: stock_code - 合约代码列表
- **返回**: dict - 最新分笔数据
- **示例**:
```python
def handlebar(C):
    tick = C.get_full_tick(C.stock_list)
    print(tick["510050.SH"])
```

### ContextInfo.subscribe_quote - 订阅行情数据
**原型**: 
```python
ContextInfo.subscribe_quote(
    stock_code,
    period='follow',
    dividend_type='follow',
    result_type='',
    callback=None
)
```
- **说明**: 订阅行情数据
- **参数**:
  - stock_code: 股票代码
  - period: K线周期类型
  - dividend_type: 除权方式
  - result_type: 返回数据格式
  - callback: 指定推送行情的回调函数
- **返回**: int - 订阅号
- **示例**:
```python
def call_back(data):
    print(data)
def init(C):
    C.subID = C.subscribe_quote("000001.SZ", "1d", callback=call_back)
```

### ContextInfo.subscribe_whole_quote - 订阅全推数据
**原型**: `ContextInfo.subscribe_whole_quote(code_list, callback=None)`
- **说明**: 订阅全推数据，全推数据只有分笔周期
- **参数**:
  - code_list: 市场代码列表/品种代码列表
  - callback: 数据推送回调
- **返回**: int - 订阅号
- **示例**:
```python
def call_back(data):
    print(data)
def init(C):
    C.stock_list = ["000001.SZ", "600519.SH", "510050.SH"]
    C.subID = C.subscribe_whole_quote(C.stock_list, callback=call_back)
```

### ContextInfo.unsubscribe_quote - 反订阅行情数据
**原型**: `ContextInfo.unsubscribe_quote(subId)`
- **说明**: 反订阅行情数据
- **参数**: subId - 行情订阅返回的订阅号
- **示例**:
```python
def handlebar(C):
    if C.subID > 0:
        C.unsubscribe_quote(C.subID)
```

### 模型相关函数
- `subscribe_formula(formula_name, stock_code, period, start_time="", end_time="", count=-1, dividend_type="none", extend_param={}, callback=None)` - 订阅模型
- `unsubscribe_formula(subID)` - 反订阅模型
- `call_formula(formula_name, stock_code, period, start_time="", end_time="", count=-1, dividend_type="none", extend_param={})` - 调用模型
- `call_formula_batch(formula_names, stock_codes, period, start_time="", end_time="", count=-1, dividend_type="none", extend_params=[])` - 批量调用模型

### 其他行情函数
- `ContextInfo.get_svol(stockcode)` - 获取内盘成交量
- `ContextInfo.get_bvol(stockcode)` - 获取外盘成交量
- `ContextInfo.get_turnover_rate(stock_list, startTime, endTime)` - 获取换手率
- `ContextInfo.get_longhubang(stock_list, startTime, endTime)` - 获取龙虎榜数据
- `ContextInfo.get_north_finance_change(period)` - 获取北向数据
- `ContextInfo.get_hkt_details(stockcode)` - 获取持股明细
- `ContextInfo.get_hkt_statistics(stockcode)` - 获取持股统计
- `get_etf_info(stockcode)` - 获取ETF申赎清单
- `get_etf_iopv(stockcode)` - 获取ETF基金份额参考净值

### 历史数据函数（不推荐使用）
- `ContextInfo.get_local_data(stock_code, start_time='', end_time='', period='1d', divid_type='none', count=-1)` - 获取本地行情数据
- `ContextInfo.get_history_data(len, period, field, dividend_type=0, skip_paused=True)` - 获取历史行情数据
- `ContextInfo.get_market_data(fields, stock_code=[], start_time='', end_time='', skip_paused=True, period='follow', dividend_type='follow', count=-1)` - 获取行情数据

---

## 交易函数

### passorder - 综合下单函数
**原型**:
```python
passorder(
    opType, orderType, accountid,
    orderCode, prType, price, volume,
    strategyName, quickTrade, userOrderId,
    ContextInfo
)
```
- **说明**: 综合下单函数，用于股票、期货、期权等下单和新股、新债申购、融资融券等交易操作
- **参数**:
  - opType: 交易类型
  - orderType: 下单方式
  - accountid: 资金账号
  - orderCode: 下单代码
  - prType: 下单选价类型
  - price: 下单价格
  - volume: 下单数量
  - strategyName: 自定义策略名
  - quickTrade: 设定是否立即触发下单
  - userOrderId: 用户自设委托ID
  - ContextInfo: 系统参数
- **示例**:
```python
# 股票最新价买入100股
passorder(23, 1101, account, "000001.SZ", 5, 0, 100, "示例", 1, "投资备注", ContextInfo)
```

### algo_passorder - 算法下单（拆单）函数
**原型**: `algo_passorder(opType, orderType, accountid, orderCode, prType, price, volume, [strategyName, quickTrade, userOrderId, userOrderParam], ContextInfo)`
- **说明**: 用于按固定时间间隔和固定规则把目标交易数量拆分成多次下单的交易函数
- **参数**: 同passorder，额外支持userOrderParam参数用于算法交易参数

### smart_algo_passorder - 智能算法（VWAP等）函数
**原型**: `smart_algo_passorder(opType, orderType, accountid, orderCode, prType, price, volume, strageName, quickTrade, userOrderId, smartAlgoType, limitOverRate, minAmountPerOrder, [targetPriceLevel, startTime, endTime, limitControl], ContextInfo)`
- **说明**: 用于使用主动算法或被动算法交易的函数如VWAP TWAP等
- **参数**: 支持智能算法相关参数

### 撤单相关函数
- `cancel(orderId, accountId, accountType, ContextInfo)` - 撤销委托
- `cancel_task(taskId, accountId, accountType, ContextInfo)` - 撤销任务
- `pause_task(taskId, accountId, accountType, ContextInfo)` - 暂停任务
- `resume_task(taskId, accountId, accountType, ContextInfo)` - 继续任务

### 股票篮子函数
- `get_basket(basketName)` - 获取股票篮子
- `set_basket(basketDict)` - 设置股票篮子

### 交易查询函数
- `get_trade_detail_data(accountID, strAccountType, strDatatype, strategyName)` - 查询账号资金信息、委托记录等
- `get_history_trade_detail_data(accountID, strAccountType, strDatatype, strStratDate, strEndDate)` - 查询历史交易明细
- `get_ipo_data([type])` - 获取当日新股新债信息
- `get_new_purchase_limit(accid)` - 获取账户新股申购额度
- `get_value_by_order_id(orderId, accountID, strAccountType, strDatatype)` - 根据委托号获取委托或成交信息
- `get_last_order_id(accountID, strAccountType, strDatatype, strategyName)` - 获取最新的委托或成交的委托号

### 两融相关函数
- `get_assure_contract(accId)` - 获取两融担保标的明细
- `get_enable_short_contract(accId)` - 获取可融券明细
- `query_credit_account(accountId, seq, ContextInfo)` - 查询信用账户明细
- `query_credit_opvolume(accountId, stockCode, opType, prType, price, seq, ContextInfo)` - 查询两融最大可下单量
- `get_unclosed_compacts(accountID, accountType)` - 获取未了结负债合约明细
- `get_closed_compacts(accountID, accountType)` - 获取已了结负债合约明细

### 期权相关函数
- `get_option_subject_position(accountID)` - 取期权标的持仓
- `get_comb_option(accountID)` - 取期权组合持仓

### 其他交易函数（仅回测可用）
- `order_lots(stockcode, lots[, style, price], ContextInfo[, accId])` - 指定手数交易
- `order_value(stockcode, value[, style, price], ContextInfo[, accId])` - 指定价值交易
- `order_percent(stockcode, percent[, style, price], ContextInfo[, accId])` - 指定比例交易
- `order_target_value(stockcode, tar_value[, style, price], ContextInfo[, accId])` - 指定目标价值交易
- `order_target_percent(stockcode, tar_percent[, style, price], ContextInfo[, accId])` - 指定目标比例交易
- `order_shares(stockcode, shares[, style, price], ContextInfo[, accId])` - 指定股数交易

### 期货交易函数（仅回测可用）
- `buy_open(stockcode, amount[, style, price], ContextInfo[, accId])` - 期货买入开仓
- `buy_close_tdayfirst(stockcode, amount[, style, price], ContextInfo[, accId])` - 期货买入平仓（平今优先）
- `buy_close_ydayfirst(stockcode, amount[, style, price], ContextInfo[, accId])` - 期货买入平仓（平昨优先）
- `sell_open(stockcode, amount[, style, price], ContextInfo[, accId])` - 期货卖出开仓
- `sell_close_tdayfirst(stockcode, amount[, style, price], ContextInfo[, accId])` - 期货卖出平仓（平今优先）
- `sell_close_ydayfirst(stockcode, amount[, style, price], ContextInfo[, accId])` - 期货卖出平仓（平昨优先）

### 港股通函数
- `get_hkt_exchange_rate(accountID, accountType)` - 获取沪深港通汇率数据

---

## 引用函数

### talib - 技术分析库
QMT内置了talib技术分析库，支持各种技术指标计算。

**常用函数**:
- `talib.SMA(close, timeperiod)` - 简单移动平均线
- `talib.EMA(close, timeperiod)` - 指数移动平均线
- `talib.RSI(close, timeperiod)` - 相对强弱指数
- `talib.MACD(close, fastperiod, slowperiod, signalperiod)` - MACD指标
- `talib.BBANDS(close, timeperiod, nbdevup, nbdevdn)` - 布林带

**示例**:
```python
import talib
def handlebar(C):
    data = C.get_market_data_ex(['close'], ['000001.SZ'], period='1d', count=30)
    close_prices = data['000001.SZ']['close'].values
    ma10 = talib.SMA(close_prices, 10)
    rsi = talib.RSI(close_prices, 14)
```

### numpy - 数值计算库
QMT内置了numpy库，用于数值计算和数组操作。

**常用函数**:
- `numpy.mean(array)` - 计算平均值
- `numpy.std(array)` - 计算标准差
- `numpy.max(array)` - 计算最大值
- `numpy.min(array)` - 计算最小值

**示例**:
```python
import numpy as np
def handlebar(C):
    data = C.get_market_data_ex(['close'], ['000001.SZ'], period='1d', count=20)
    close_prices = data['000001.SZ']['close'].values
    ma20 = np.mean(close_prices)
```

### pandas - 数据分析库
QMT内置了pandas库，用于数据处理和分析。

**常用功能**:
- DataFrame操作
- 数据筛选和过滤
- 时间序列处理

**示例**:
```python
import pandas as pd
def handlebar(C):
    data = C.get_market_data_ex(['close', 'volume'], ['000001.SZ'], period='1d', count=10)
    df = data['000001.SZ']
    # 计算成交量移动平均
    df['vol_ma5'] = df['volume'].rolling(5).mean()
```

---

## 绘图函数

### ContextInfo.draw_text - 绘制文本
**原型**: `ContextInfo.draw_text(x, y, text)`
- **说明**: 在图表上绘制文本
- **参数**:
  - x: X坐标
  - y: Y坐标  
  - text: 要显示的文本
- **示例**:
```python
def handlebar(C):
    C.draw_text(1, 1, '买')
    C.draw_text(1, 1, '卖')
```

### ContextInfo.set_output_index_property - 设定指标绘制的属性
**原型**: `ContextInfo.set_output_index_property(index_name, draw_style=0, color='white', noaxis=False, nodraw=False, noshow=False)`
- **说明**: 设定指标绘制的属性
- **参数**:
  - index_name: 指标名称
  - draw_style: 绘制样式
  - color: 颜色
  - noaxis: 是否无坐标
  - nodraw: 是否不画线
  - noshow: 是否不展示
- **示例**:
```python
def init(ContextInfo):
    ContextInfo.set_output_index_property('单位净值', nodraw=True)
```

### paint - 绘制指标
**说明**: 在策略中定义的变量会自动作为指标绘制到图表上

**示例**:
```python
def handlebar(C):
    # 这些变量会自动绘制为指标
    C.ma10 = np.mean(closes[-10:])
    C.ma20 = np.mean(closes[-20:])
```

---

## 枚举常量

### opType - 操作类型
- **股票**:
  - 23: 买入
  - 24: 卖出
- **融资融券**:
  - 33: 融资买入
  - 34: 融券卖出
  - 35: 卖券还款
  - 36: 买券还券
- **期货**:
  - 0: 开多
  - 1: 平多
  - 2: 开空
  - 3: 平空

### orderType - 下单方式
- 1101: 按股数买卖
- 1102: 按金额买卖
- 1201: 按手数买卖
- 1202: 按金额买卖（期货）

### prType - 下单选价类型
- 5: 最新价
- 11: 指定价
- 14: 对手价
- 49: 科创板盘后定价

### quickTrade - 快速下单
- 0: 默认模式（逐K线生效）
- 1: 快速下单（非历史bar立即触发）
- 2: 立即下单（任何情况下立即触发）

### volume - 下单数量单位
- 根据orderType最后一位确定：
  - 1: 股/手
  - 2: 元
  - 3: %

---
