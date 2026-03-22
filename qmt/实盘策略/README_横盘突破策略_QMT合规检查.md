# 横盘突破策略（官方风格）— QMT 知识库合规检查

> 策略文件：本目录 `strategy_sideways_breakout_official_style.py`  
> 对照文档：`qmt/docs/QMT知识库_全站索引.md`、`QMT知识库_完整示例目录.md`

## 合规项对照

| 知识库要点 | 本策略实现 | 状态 |
|------------|------------|------|
| 首行 `#coding:gbk` | 第 1 行 | ✅ |
| 必须提供 `init`、`handlebar` | 有且仅在此两处写策略逻辑 | ✅ |
| 勿在 ContextInfo 上存持久化变量，用自建全局对象 | `class G` + `g = G()` 存状态 | ✅ |
| 实盘立即下单用 quickTrade=2 + 全局变量 | `g.QUICK_TRADE = 2`，passorder 第 9 参传入 | ✅ |
| 仅最后一根 K 线下单 | `if not C.is_last_bar(): return` | ✅ |
| 交易时段过滤 | `093000`～`150000` 用 `datetime` 判断 | ✅ |
| 账号/资金/持仓/委托/成交用 `get_trade_detail_data` | account / position / order / deal 均用该接口 | ✅ |
| Account 可用字段 | `m_dAvailable` 取可用资金 | ✅ |
| Position 可用字段 | `m_strInstrumentID`、`m_strExchangeID`、`m_nCanUseVolume` | ✅ |
| Order 可用字段 | `m_strRemark` 对单、`m_nOrderStatus` 判状态、`m_strOrderSysID` 撤单 | ✅ |
| 投资备注（userOrderId）长度 < 24 | `_order_remark()` 生成 HBx 代码_股数[_R重试]，保证 <24 字符 | ✅ |
| 防超单：备注 + 成交对单 | `waiting_list` + deal 的 `m_strRemark` 匹配，未成交前不新开同逻辑单 | ✅ |
| 撤单 API | `cancel(order_sys_id, account_id, account_type, C)` | ✅ |
| passorder 参数顺序 | opType, orderType, accountID, orderCode, prType, price, volume, strategyName, quickTrade, userOrderId, C | ✅ |
| 股票买卖 opType | 23 买 / 24 卖（普通）；33/34 两融 | ✅ |
| orderType 按股 | 1101 | ✅ |
| prType 最新价 | 5 | ✅ |
| 回测行情 subscribe=False | `get_market_data_ex(..., subscribe=False)` | ✅ |
| symbol 格式 代码.市场 | 如 000001.SZ、600000.SH，与 get_market_data_ex / passorder 一致 | ✅ |

## 可选增强（未强制）

- **set_account**：若使用 account_callback / deal_callback 等主推，需在 init 中 `C.set_account(account)`；当前策略仅轮询 `get_trade_detail_data`，未用主推，可不设。
- **strategyName**：`get_trade_detail_data` 第四参可选 strategyName 过滤；当前未传，取全账号数据后在代码内用 `m_strRemark` 区分本策略。

## 运行与周期

- 实盘/回测均建议使用 **日线** 周期；用分钟线时 `barpos` 为分钟根数，持有天数会错误。
- 实盘需在 **模型交易** 中添加该策略并选择账号，否则不会发真实委托。
