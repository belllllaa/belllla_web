# QMT 知识库 - 完整示例目录

> 来源：[迅投知识库 - 完整示例](https://dict.thinktrader.net/innerApi/code_examples.html)  
> 本文档为该页面的完整遍历与目录索引，便于本地查阅。  
> **更多知识库页面**（快速开始、使用须知、变量约定、系统/行情/交易函数、主推、常见问题等）见同目录 **《QMT知识库_全站索引》**。

---

## 一、获取行情示例

### 1. 按品种划分

| 小节 | 说明 |
|------|------|
| **两融 → 获取融资融券账户可融资买入标的** | `get_assure_contract(账号)` 取担保明细，筛选 `m_eFinStatus==48` 为可融资买入标的 |

### 2. 按功能划分

| 小节 | 说明 |
|------|------|
| **订阅K线全推** | VIP 权限；`C.subscribe_quote(stock_code, period='1m', result_type='dict', callback=call_back)` 订阅全市场 1m K 线 |
| **获取N分钟周期K线数据** | 先 `download_history_data` 再 `get_market_data_ex`；1d 以上用 1d 合成，5m~1d 用 5m 合成，1m~5m 用 1m 合成 |
| **获取 Lv1 行情数据** | `get_market_data_ex`：subscribe=False 从本地取、无订阅数限制；subscribe=True 可拿动态行情、≤500 只 |
| **获取 Lv2 数据** | 需数据源支持。**方法1**：订阅后 `get_market_data_ex(period='l2transaction'/'l2quote'/'l2order'/'l2transactioncount')` 查询；**方法2**：`subscribe_quote(..., callback=...)` 回调接收 l2quote / l2transaction / l2order / l2transactioncount / l2quoteaux / l2orderqueue |
| **使用 Lv1 全推数据计算全市场涨幅** | `C.get_full_tick(股票列表)` + 市值加权涨幅、中位数、涨跌家数；`C.run_time` 定时执行 |
| **在行情回调函数里处理动态行情** | `subscribe_quote(..., callback=on_quote)`，回调仅一个位置参数 `data`；`stop` 里 `unsubscribe_quote` |
| **python 写入扩展数据** | `create_extend_data`、`reset_extend_data_stock_list`、`set_extend_data_value`（投研接口） |
| **扩展数据展示 → 每1分钟统计一次市场涨跌情况** | `ContextInfo.schedule_run(on_timer, 开始时间, 3, timedelta(seconds=60), 'my_timer')` |

---

## 二、交易下单示例

### 1. 按品种划分

| 品种 | 示例要点 |
|------|----------|
| **股票** | 最新价买卖 `passorder(23/24, 1101, account, code, 5, 0, 数量, '', 1, '', C)`；沪市市价 42、保护限价；京市 101 股/手 |
| **基金** | 申购 60、赎回 61 |
| **两融** | 担保品买入 33、融资买入 27；指定价 11 |
| **期货** | 开多 0、开空 3、平多 6 等；`passorder(..., 5, -1, 手数, 1, C)` |
| **期权** | 买入开仓 50、卖出平仓 51 |
| **新股申购** | `get_ipo_data("STOCK")` 取发行价、可申购额度；`passorder(23, 1101, account, stock, 11, ipo_price, maxPurchaseNum, ...)` |
| **债券** | 可转债最新价买入，张数 |
| **ETF** | 最新价买入，份数 |
| **组合交易** | `set_basket(basket)`；`passorder(35, 2101, account, 'basket1', 5, 1, 份数, '', 2, 'strReMark', C)` 按数量；2102 按权重、金额 |
| **组合套利交易** | accountID 格式 `'stockAccountID, futureAccountID'`；orderType 2331/2332/2333 |

### 2. 按功能划分

| 功能 | 说明 |
|------|------|
| **passorder 下单函数** | quickTrade=2 立即下单；=0 K 线走完下单；=1 历史 K 线不触发。1101 按股、1102 按金额；prType 5 最新价、11 指定价 |
| **集合竞价下单** | `C.run_time("myHandlebar", "5nSecond", "2019-10-14 13:20:00")`，在 091500~092500 内用指定价下单 |
| **止盈止损示例** | `get_trade_detail_data(account, accountType, 'position')` 取持仓；盈亏比例止损；涨停炸板用买三价卖出（prType 14） |
| **passorder 下算法单** | `algo_passorder(23, 1101, account, code, -1, -1, target_vol, '', 2, '备注', userparam, C)`，userparam 为算法参数字典 |
| **如何使用投资备注** | 投资备注 = passorder 的 userOrderId 参数（长度<24），仅 passorder / algo_passorder / smart_algo_passorder 支持；委托/成交对象用 `m_strRemark` 匹配 |
| **如何获取委托持仓及资金数据** | `get_trade_detail_data(account, accountType, 'order'/'deal'/'position'/'account')`，订单 m_strOrderSysID、持仓 m_nCanUseVolume、账户 m_dAvailable 等 |
| **使用快速交易参数委托** | quickTrade=2 可在 `after_init`、`run_time` 回调里立即下单 |
| **调整至目标持仓** | 类 A 存状态；`run_time` 定时调 f；`get_trade_detail_data` 取 account、position；用 m_strRemark 维护 waiting_dict，防超单；超时撤单 `cancel(order.m_strOrderSysID, ...)` |
| **获取融资融券账户可融资买入标的** | 同“获取行情”两融小节 |
| **获取两融账号信息示例** | `query_credit_account(account_str, 1234, C)` + 回调 |
| **直接还款示例** | `passorder(32, 1101, account, s, 5, 0, money, 2, ContextInfo)` |

---

## 三、交易数据查询示例

- 与“如何获取委托持仓及资金数据”相同：`get_trade_detail_data` 查 order / deal / position / account，打印各对象 `m_` 前缀字段。

---

## 四、常用锚点（你提供的链接）

- **如何使用投资备注**：`#如何使用投资备注`  
  投资备注即 passorder 的 userOrderId（第 10 个参数），用于在委托/成交里通过 `m_strRemark` 区分本策略报单，便于防超单、对单。

---

## 五、与实盘策略相关的要点汇总

1. **账号与持仓**：`account`、`accountType` 为界面选择；取资金/持仓用 `get_trade_detail_data(account, accountType, 'account'/'position')`。
2. **仅最后一根 K 线下单**：`if not C.is_last_bar(): return`。
3. **交易时段**：可用 `datetime.now().strftime('%H%M%S')` 判断 093000~150000。
4. **防超单**：用“投资备注”记录每笔委托，用 `get_trade_detail_data(..., 'deal')` 的 `m_strRemark` 对单；未查到成交前可暂停新单（waiting_list / waiting_dict）。
5. **passorder 常用**：股票买 23 卖 24、按股 1101、最新价 5、立即下单 quickTrade=2、备注传字符串。
6. **周期与数据**：日线策略用 `period='1d'`；N 分钟需先下载对应周期数据。

---

*文档由知识库页面内容整理，便于本地遍历与检索。*
