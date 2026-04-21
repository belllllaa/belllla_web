# Cursor 中安装「读 PDF」类 MCP（自行操作）

助手**不能**替你在本机写入 `%APPDATA%\Cursor\mcp.json`，请按下述任选一种方式配置后**重启 Cursor**，再在 MCP 面板确认服务已连接。

---

## 方案 A：Smithery 上的 PDF Text Reader（适合快速试）

1. 安装 Smithery CLI（需 Node.js 20+）：
   ```bash
   npm install -g @smithery/cli@latest
   ```
2. 将 PDF Reader 加入 Cursor（示例，以 Smithery 页面为准）：
   ```bash
   smithery mcp add @wfyi-joy/pdf-reader-mcp --client cursor
   ```
3. 或打开 [Smithery - PDF Text Reader](https://smithery.ai/server/@wfyi-joy/pdf-reader-mcp) 按页面「Install for Cursor」复制配置到 `mcp.json`。

---

## 方案 B：GP PDF Reader（gpetraroli/mcp_pdf_reader）

开源仓库：<https://github.com/gpetraroli/mcp_pdf_reader>

1. 克隆后 `npm install` 构建，在 `mcp.json` 中增加（路径改成你的本机绝对路径）：
   ```json
   {
     "mcpServers": {
       "mcp-gp-pdf-reader": {
         "command": "node",
         "args": ["D:/path/to/mcp_gp_pdf_reader/index.js"]
       }
     }
   }
   ```
2. 常见能力：`read-pdf`、`search-pdf`、`pdf-metadata`（以仓库 README 为准）。  
3. 要求：Node.js 18+。

---

## 方案 D：pdf-mcp-server（Python / PyMuPDF，读取专用）

官方说明：<https://github.com/c70311tw/pdf-mcp-server/blob/main/readme.md>（README 亦说明由模型生成，以仓库实际代码为准。）

**特点**：用 Python 跑 `server.py`，依赖 **PyMuPDF** 等，提供工具大致包括：

| 工具 | 用途 |
|------|------|
| `read_pdf_text` | 提取正文（可分页） |
| `get_pdf_metadata` | 元数据 |
| `extract_pdf_images` | 提取嵌入图片 |
| `get_pdf_page_info` | 页面信息 |
| `search_pdf_text` | 关键字搜索 |

**本仓库已克隆至**：`belllla_web/third_party/pdf-mcp-server`（可直接 `pip install -r requirements.txt`）。

**安装（若在其他机器上自克隆）**：

```bash
git clone https://github.com/c70311tw/pdf-mcp-server.git
cd pdf-mcp-server
pip install -r requirements.txt
```

**本机测试**：

```bash
python server.py
```

看到日志里 MCP / PDF reader 初始化成功即可。

**接入 Cursor**：在 `mcp.json` 增加（把路径改成你的**绝对路径**，Python 用 `python` 或 `py` 以本机为准）：

```json
{
  "mcpServers": {
    "pdf-mcp-server": {
      "command": "python",
      "args": ["C:/Users/<你的Windows用户名>/belllla_web/third_party/pdf-mcp-server/server.py"]
    }
  }
}
```

保存后**重启 Cursor**，在 MCP 面板确认 `pdf-mcp-server` 已连接。向助手提供 PDF 的**绝对路径**即可请求读取/摘要（大文件建议按页范围读取，避免单次对话过长）。

**注意**：加密 PDF 需先解密；路径、权限与 [readme 故障排除](https://github.com/c70311tw/pdf-mcp-server/blob/main/readme.md) 一致。

---

## 方案 C：不装 MCP，用 Python 抽 PDF 文本（仓库内可控）

在任意环境执行（需 `pip install pypdf`）：

```bash
python -c "from pypdf import PdfReader; r=PdfReader(r'D:\path\to\file.pdf'); print('\n'.join(p.extract_text() or '' for p in r.pages[:3]))"
```

将输出保存为 `.txt` 后，可直接用 Cursor 打开或由助手阅读。

---

## 配置位置（Windows）

- 本机已写入：**`C:\Users\Dustin.hou\.cursor\mcp.json`**（键名 **`pdf-mcp-server`**，指向仓库内 `third_party/pdf-mcp-server/server.py`）。  
- 亦常见：`%APPDATA%\Cursor\mcp.json`；或在 Cursor：**Settings → MCP** 图形化添加。  
- 修改后请**完全重启 Cursor**，在 MCP 面板确认 `pdf-mcp-server` 为已连接。  
- 若启动失败：把 `"command": "python"` 改为 **`py`**，args 前加 **`"-3"`**（仅保留 `server.py` 路径在 args 里），或改用 Python 安装目录下的 **`python.exe` 绝对路径**。

---

## 权限说明

多数 MCP 只能访问**允许目录**内的文件；网盘路径若被拒绝，请把 PDF **复制到工作区**（如 `belllla_web/docs/course_pdf/`）再读。
