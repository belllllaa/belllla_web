# QMT 官方知识库 - 全站索引

> 来源：迅投知识库 https://dict.thinktrader.net/innerApi/  
> 本文档对内置 Python 相关主要页面做索引与要点归纳，便于本地查阅与跳转。

---

## 一、入口与基础

### 1. 快速开始 · 场景需求

**链接**：[start_now.html#二、场景需求](https://dict.thinktrader.net/innerApi/start_now.html#%E4%BA%8C%E3%80%81%E5%9C%BA%E6%99%AF%E9%9C%80%E6%B1%82)

| 类型 | 要点 |
|------|------|
| **回测模型** | 遍历历史 K 线；用 `get_market_data_ex(..., subscribe=False)` 读本地数据；撮合规则：指定价在当根 K 高低点间按指定价，否则按收盘价。 |
| **实盘模型** | 接收未来 K 线生成信号并下单。**逐 K 线生效**：quickTrade=0，信号在下一根 K 线首 tick 发出；**立即下单**：quickTrade=2，用全局变量（如自定义 Class）存状态，勿用 ContextInfo。 |
| **运行机制** | handlebar：主图历史 K 线 + 盘中订阅推送，可模拟逐 K 线；subscribe：分笔触发回调；run_time：定时触发。 |

### 2. 使用须知

**链接**：[user_attention.html](https://dict.thinktrader.net/innerApi/user_attention.html)

| 主题 | 要点 |
|------|------|
| 安装路径 | 勿装 C 盘；若只能 C 盘则“以管理员权限启动”。 |
| Python 库 | 盘前/盘后更新，盘中下载慢；装完需重启客户端。 |
| **ContextInfo** | 修改会在下一根 bar 才保留；**勿在 C 上存需持久化的变量**，用自建全局对象（如 `class G(): pass; g = G()`）。 |
| 线程/进程 | 不支持多线程、多进程；所有策略同一线程，避免阻塞。 |
| 主图 | 策略依赖 K 线图驱动；可设“快速计算”或 `is_last_bar()` 过滤。 |
| 无反应/报错 | 先“恢复默认布局”；检查是否有其他策略在跑；必要时重启客户端。 |
| 数据下载 | 操作 → 数据管理；可设定时下载。 |

### 3. 界面操作

**链接**：[interface_operation.html](https://dict.thinktrader.net/innerApi/interface_operation.html)

| 主题 | 要点 |
|------|------|
| 新建策略 | 模型研究 → 编辑示例 / 新建模型；模型管理右键新建。 |
| 策略编写 | 首行 `#coding:gbk`；必须 `init`、`handlebar`；右侧可设默认周期、品种、复权、快速计算、刷新间隔等。 |
| 回测参数 | 开始/结束时间、基准、初始资金、滑点、手续费、印花税、最大成交比例等。 |
| 策略运行 | 编译=保存；运行受主图品种与周期影响；关策略可关附图或取消叠加。 |
| 策略回测 | 需先补充数据；绩效分析、当日买卖、持仓、操作明细、日志等。 |
| 回测 vs 运行 | 回测=历史运算；运行=实时运算但不发真实委托；真实委托需在“模型交易”里添加策略。 |

---

## 二、变量与数据结构

### 4. 变量约定

**链接**：[variable_convention.html](https://dict.thinktrader.net/innerApi/variable_convention.html)

| 主题 | 要点 |
|------|------|
| 函数命名 | `get_`：数据来自客户端内存；`query_`：向服务器查询。 |
| 账号类型 | 'STOCK' / 'CREDIT' / 'FUTURE' / 'FUTURE_OPTION' / 'STOCK_OPTION' / 'HUGANGTONG' / 'SHENGANGTONG'。 |
| symbol | 格式 `代码.市场`，如 000001.SZ、600000.SH；期货代码区分大小写。 |
| 模式 | 调试运行、回测、模拟信号、实盘交易。 |
| **ContextInfo** | start/end 回测时间；capital 回测初始资金；period/barpos/stockcode/market/benchmark/do_back_test 等只读。 |

### 5. 数据结构

**链接**：[data_structure.html](https://dict.thinktrader.net/innerApi/data_structure.html)

| 类别 | 主要对象/表 |
|------|-------------|
| 数据类 | Tick、Bar、l2quote、l2order、l2transaction、l2transactioncount、l2orderqueue 等。 |
| 交易类 | **Account**（m_dAvailable 等）、**Order**（m_strRemark、m_nOrderStatus 等）、**Deal**、**Position**（m_nCanUseVolume、m_dOpenPrice 等）、PositionStatistics、两融相关、PassorderArguments、CTaskDetail 等。 |
| 证券状态 | openInt：股票 0/1/11~23，期货 0~5。 |

---

## 三、系统与行情函数

### 6. 系统函数

**链接**：[system_function.html](https://dict.thinktrader.net/innerApi/system_function.html)

| 名称 | 说明 |
|------|------|
| init / after_init | 策略开始时各执行一次；after_init 后可调用 get_trading_dates 等。 |
| handlebar | 每根 K 线/每个 tick 调用；历史从左到右，盘中随 tick 驱动。 |
| **C.is_last_bar()** | 是否最后一根 K 线。 |
| **C.is_new_bar()** | 是否该 K 线首个 tick。 |
| C.run_time(func, period, startTime) | 定时器；period 如 '5nSecond'、'1nDay'。 |
| C.schedule_run / cancel_schedule_run | 新版定时器，支持任务组、重复次数、interval。 |
| stop | 策略关闭前调用；此时交易已断开，不可报撤单。 |
| C.get_stock_name / get_open_date | 名称、上市日。 |
| C.set_output_index_property | 指标绘制属性。 |
| 板块 | create_sector_folder、get_sector_list、reset_sector_stock_list、add/remove_stock_from_sector。 |

### 7. 行情函数

**链接**：[data_function.html](https://dict.thinktrader.net/innerApi/data_function.html)

| 类别 | 要点 |
|------|------|
| 下载 | `download_history_data(stockcode, period, startTime, endTime)`；合成周期依赖基础周期（如 15m 用 5m）。 |
| **get_market_data_ex** | 推荐；fields、stock_code、period、start_time、end_time、count、subscribe（回测 False）。返回 dict of DataFrame。 |
| get_full_tick | 仅最新分笔，无历史；全推，无订阅数限制。 |
| subscribe_quote / unsubscribe_quote | 订阅/反订阅；有数量限制；result_type 可选 'dict'/'list'。 |
| subscribe_whole_quote | 全推，增量推送。 |
| call_formula / subscribe_formula | 调用/订阅 VBA 模型结果。 |
| 财务 | get_financial_data、get_raw_financial_data；需先下载财务数据。 |
| 合约/期权/交易日 | get_instrument_detail、get_st_status、get_main_contract、get_option_list、get_trading_dates（仅 after_init/handlebar）等。 |

---

## 四、交易与回报

### 8. 交易函数

**链接**：[trading_function.html](https://dict.thinktrader.net/innerApi/trading_function.html)

| 名称 | 说明 |
|------|------|
| **passorder** | 综合下单；opType(23买/24卖/33担保品买等)、orderType(1101股/1102金额)、accountID、orderCode、prType(5最新/11指定/14对手/42市价)、volume、strategyName、**quickTrade**、**userOrderId**、ContextInfo。 |
| algo_passorder | 算法拆单；末尾可跟 userOrderParam 字典。 |
| smart_algo_passorder | 智能算法（VWAP 等），需权限。 |
| cancel / cancel_task / pause_task / resume_task | 撤单、撤/暂停/继续任务。 |
| **get_trade_detail_data** | (accountID, accountType, strDatatype, [strategyName])；strDatatype：'account'/'position'/'order'/'deal'/'task'。 |
| get_history_trade_detail_data | 历史委托/成交/持仓。 |
| get_ipo_data / get_new_purchase_limit | 新股新债、申购额度。 |
| get_value_by_order_id / get_last_order_id | 按委托号查委托/成交。 |
| get_assure_contract / get_enable_short_contract | 两融担保标的、可融券。 |
| query_credit_account / query_credit_opvolume | 信用账户、两融可下单量（配合回调）。 |
| set_basket / get_basket | 组合篮子。 |
| 仅回测 | order_lots、order_value、order_percent、order_target_*、order_shares、buy_open、sell_close_* 等。 |

### 9. 成交回报实时主推函数

**链接**：[callback_function.html](https://dict.thinktrader.net/innerApi/callback_function.html)

| 回调 | 说明 |
|------|------|
| account_callback | 资金账号状态变化；需 init 里 C.set_account(account)。 |
| task_callback | 任务状态变化。 |
| order_callback | 委托状态变化。 |
| deal_callback | 成交状态变化。 |
| position_callback | 持仓状态变化。 |
| orderError_callback | 异常下单。 |
| credit_account_callback | query_credit_account 结果。 |
| credit_opvolume_callback | query_credit_opvolume 结果。 |

*以上主推仅在实盘运行且 set_account 后生效。*

---

## 五、引用与枚举

### 10. 引用函数

**链接**：[quote_function.html](https://dict.thinktrader.net/innerApi/quote_function.html)

| 名称 | 说明 |
|------|------|
| ext_data / ext_data_rank / ext_data_range / ext_data_rank_range | 扩展数据及排名。 |
| get_factor_value / get_factor_rank | 因子数据及排名。 |
| call_vba | 不推荐；建议 call_formula / subscribe_formula。 |

### 11. 枚举常量

**链接**：[enum_constants.html](https://dict.thinktrader.net/innerApi/enum_constants.html)

*页面含 opType、orderType、prType、quickTrade、委托状态、价格类型等枚举；查阅时直接打开链接。*

---

## 六、示例与常见问题

### 12. 完整示例

**链接**：[code_examples.html](https://dict.thinktrader.net/innerApi/code_examples.html)

详见同目录 **《QMT知识库_完整示例目录》**，包含：

- 获取行情：订阅全推、N 分钟 K 线、Lv1/Lv2、全市场涨幅、扩展数据等。
- 交易下单：股票/基金/两融/期货/期权/新股/债券/ETF、组合与套利、passorder 用法、投资备注、委托持仓资金、快速交易、调仓、止盈止损、算法单等。
- 交易数据查询：get_trade_detail_data 查 order/deal/position/account。

### 13. 常见问题

**链接**：[question_answer.html](https://dict.thinktrader.net/innerApi/question_answer.html)

| 分类 | 要点 |
|------|------|
| Python 环境 | 白名单报错找券商；pandas 报错检查路径与库、重启客户端。 |
| ContextInfo 逐 K 线保存 | 只有 K 线结束时的修改会保留；立刻下单用 quickTrade=2 + 全局变量。 |
| **quickTrade** | 0=仅 K 线结束生效；1=当前为最新 K 线时生效；2=任意时刻生效（定时器/after_init/回调里用 2）。 |
| 下单与回报 | 接口异步，不等待回报；get_trade_detail_data 读本地缓存；需自建委托状态与防超单。 |
| 下单失败 | 确认在模型交易实盘模式；检查 quickTrade；看左下角报错。 |
| 行情 | 本地 / 全推 / 订阅区别；get_market_data_ex 在 init 中仅本地；超订阅数会前值填充。 |
| 对手价/五档 | 需把全推行情级别改为五档。 |
| 非交易时段 handlebar | 服务会推送，可按时间 return。 |
| openInt | 沪深不同时段 12/13/14/15/18/22/23 等。 |
| 日志 | 安装目录 userdata\\log（Formula 为策略日志）。 |

---

## 七、链接速查表

| 页面 | URL |
|------|-----|
| 快速开始·场景需求 | https://dict.thinktrader.net/innerApi/start_now.html#二、场景需求 |
| 使用须知 | https://dict.thinktrader.net/innerApi/user_attention.html |
| 界面操作 | https://dict.thinktrader.net/innerApi/interface_operation.html |
| 变量约定 | https://dict.thinktrader.net/innerApi/variable_convention.html |
| 数据结构 | https://dict.thinktrader.net/innerApi/data_structure.html |
| 系统函数 | https://dict.thinktrader.net/innerApi/system_function.html |
| 行情函数 | https://dict.thinktrader.net/innerApi/data_function.html |
| 交易函数 | https://dict.thinktrader.net/innerApi/trading_function.html |
| 成交回报主推 | https://dict.thinktrader.net/innerApi/callback_function.html |
| 引用函数 | https://dict.thinktrader.net/innerApi/quote_function.html |
| 枚举常量 | https://dict.thinktrader.net/innerApi/enum_constants.html |
| 完整示例 | https://dict.thinktrader.net/innerApi/code_examples.html |
| 常见问题 | https://dict.thinktrader.net/innerApi/question_answer.html |

---

*文档根据迅投 QMT 知识库整理，便于本地检索与跳转官方原文。*
