# 量化开源项目本地引用

本目录用于存放从 GitHub 克隆的量化策略/选股开源项目，便于在 Cursor 中 @ 引用具体代码。

## 推荐克隆（在项目根目录执行）

```powershell
cd c:\Users\bellaBB\Desktop\qmt001bb

# 策略库（轻量，vnpy 用）
git clone --depth 1 https://github.com/qtbrain/strategy-vnpy.git references/strategy-vnpy

# A 股选股（海龟、缠论等）
git clone --depth 1 https://github.com/sngyai/Sequoia.git references/Sequoia

# 多因子选股器
git clone --depth 1 https://github.com/jinyang756/xuanguqi.git references/xuanguqi
```

克隆完成后，在 Cursor 聊天中可 @ `references/strategy-vnpy` 等目录，让 AI 直接参考其中策略逻辑并改写成 QMT 代码。

完整项目列表与说明见：**`docs/quant_open_source_projects.md`**。
