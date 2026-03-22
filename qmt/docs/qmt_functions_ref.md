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

### after_init - 初始化后函数
**原型**: `after_init(ContextInfo)`
- **说明**: 后初始化函数，在初始化函数执行完成后被调用一次

### handlebar - 行情事件函数
**原型**: `handlebar(ContextInfo)`
- **说明**: 行情事件函数，每根 K 线运行一次

### ContextInfo.is_last_bar - 是否为最后一根K线
- **返回**: bool - True是最新k线，False不是

### ContextInfo.is_new_bar - 判定是否为新的 K 线
- **返回**: bool

### ContextInfo.get_stock_name - 根据代码获取名称
**原型**: `ContextInfo.get_stock_name('stockcode')`

---

## 行情函数

### download_history_data - 下载历史行情数据
**原型**: `download_history_data(stockcode, period, startTime, endTime)`

### ContextInfo.get_market_data_ex - 获取行情数据
**参数**:
- fields: 数据字段
- stock_code: 合约代码列表
- period: 数据周期（如 '1d'）
- start_time / end_time: 时间范围
- count: 数据个数
- dividend_type: 除权方式
- fill_data: 是否填充数据

**返回**: dict { stock_code1 : value1, stock_code2 : value2, ... }

### ContextInfo.get_full_tick - 获取全推数据
**原型**: `ContextInfo.get_full_tick(stock_code=[])`

---

## 财务数据与价值因子

- **get_financial_data(field_list, stock_list, report_type, start_time, end_time)**：获取财务数据与价值因子；字段须为「表名.字段名」（如 `CAPITALSTRUCTURE.total_capital`、`ASHAREINCOME.net_profit_incl_min_int_inc`）；`report_type='announce_time'` 按公告日期取数防未来函数，`'report_time'` 按报告期。详见 [qmt_complete_functions.md](../qmt_complete_functions.md#财务数据与价值因子) 与 [QMT 价值因子获取函数介绍](https://blog.csdn.net/easyquant_qmt/article/details/155524376)。

---

## 交易函数

### passorder - 综合下单函数
**原型**:
```python
passorder(opType, orderType, accountid, orderCode, prType, price, volume,
          strategyName, quickTrade, userOrderId, ContextInfo)
```
- opType: 23 买入, 24 卖出
- orderType: 1101 按股数, 1102 按金额
- prType: 5 最新价, 11 指定价
- quickTrade: 1 非历史bar立即触发

### 回测专用（仅回测可用）
- `order_value(stockcode, value[, style, price], ContextInfo[, accId])` - 指定价值交易
- `order_target_percent(stockcode, tar_percent[, style, price], ContextInfo[, accId])` - 指定目标比例交易

---

## 引用函数

### talib - 技术分析库
- `talib.SMA(close, timeperiod)` - 简单移动平均
- `talib.EMA(close, timeperiod)` - 指数移动平均
- `talib.RSI(close, timeperiod)` - RSI
- `talib.MACD(close, fastperiod, slowperiod, signalperiod)` - MACD
- `talib.BBANDS(close, timeperiod, nbdevup, nbdevdn)` - 布林带

### numpy / pandas
QMT 内置 numpy、pandas 用于数值计算和数据处理。

---

## 枚举常量

| 参数 | 常用值 | 说明 |
|------|--------|------|
| opType | 23/24 | 买入/卖出 |
| orderType | 1101/1102 | 按股数/按金额 |
| prType | 5/11 | 最新价/指定价 |
| quickTrade | 1 | 非历史 bar 立即触发 |
