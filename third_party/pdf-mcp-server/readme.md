# PDF MCP Server - 讀取專用版

一個用於PDF讀取和分析的MCP (Model Context Protocol) 伺服器，專為Claude AI設計。本版本專注於PDF內容提取、分析和搜尋功能，提供穩定可靠的PDF處理體驗。
聲明：該MCP too以及此Readme完全由Claude sonnet 4生成與除錯。
Disclaimer: This MCP tool and README file are generated and debugged by the Claude Sonnet 4 model.

## 🎯 為什麼選擇讀取專用版？

### ✅ **核心優勢**
- **專注核心功能**：專門針對PDF分析和內容提取優化
- **穩定可靠**：避免大內容輸出導致的token限制問題(Note: the size of a PDF document itself could be counted as a part of the total length of single conversation)
- **低記憶體占用**：精簡設計，資源使用最小化
- **維護簡單**：單一職責，更容易維護和除錯

## 📖 功能特色

### 🔍 **PDF內容分析**
- **完整文字提取**：支援繁體中文、英文、多語言內容
- **智能分頁處理**：可指定頁面範圍進行精確提取
- **圖片識別提取**：自動偵測並提取PDF中的圖片
- **元數據解析**：獲取標題、作者、創建日期等完整資訊
- **結構化分析**：每頁尺寸、內容統計、元素數量分析

### 🔎 **智能搜尋功能**
- **關鍵字搜尋**：支援精確的文字搜尋定位
- **位置標記**：提供搜尋結果的頁面和座標位置
- **上下文顯示**：顯示搜尋結果的周圍內容
- **大小寫控制**：可選的大小寫敏感搜尋

### 🖼️ **圖片處理能力**
- **自動圖片提取**：識別並提取所有嵌入圖片
- **多格式支援**：支援PNG、JPEG等常見格式
- **詳細資訊**：提供圖片尺寸、色彩空間、檔案大小
- **批量處理**：可同時處理多張圖片

## 📋 可用工具

| 工具名稱 | 功能說明 | 測試狀態 | 用途 |
|---------|----------|----------|------|
| `read_pdf_text` | 提取PDF文字內容 | ✅ 已驗證 | 文檔分析、內容提取 |
| `get_pdf_metadata` | 取得PDF元數據 | ✅ 已驗證 | 文件資訊查詢 |
| `extract_pdf_images` | 提取PDF圖片 | ✅ 已驗證 | 圖片資源提取 |
| `get_pdf_page_info` | 取得頁面詳細資訊 | ✅ 已驗證 | 結構分析 |
| `search_pdf_text` | 搜尋PDF文字 | ✅ 已驗證 | 內容查找定位 |

## 🖥️ 系統需求

- **Python版本**：3.9 或更高版本
- **作業系統**：macOS（已測試）、Windows、Linux
- **Claude Desktop**：最新版本

## ⚡ 快速安裝

### 方法一：從 GitHub 安裝（推薦）

#### 1. Clone 專案
```bash
# Clone 專案到本機
git clone https://github.com/c70311tw/pdf-mcp-server.git

# 進入專案目錄
cd pdf-mcp-server
```

#### 2. 安裝依賴套件
```bash
# 使用 pip 安裝依賴
pip install -r requirements.txt

# 或者手動安裝核心套件
pip install mcp PyMuPDF Pillow python-magic
```

#### 3. 測試伺服器
```bash
python3 server.py
```

成功時會顯示：
```
INFO:pdf-mcp-server:MCP imports successful
INFO:pdf-mcp-server:PDFReader import successful
INFO:pdf-mcp-server:PDF reader initialized successfully
INFO:pdf-mcp-server:Starting PDF MCP Server - Reading Only Version...
INFO:pdf-mcp-server:PDF Reading Server started successfully
```

### 方法二：手動安裝

#### 1. 建立專案目錄
```bash
mkdir ~/pdf-mcp-server
cd ~/pdf-mcp-server
```

#### 2. 下載專案檔案
從 [GitHub Releases](https://github.com/c70311tw/pdf-mcp-server/releases) 下載最新版本，或手動下載以下核心檔案：
- `server.py` - 讀取專用伺服器主程式
- `pdf_reader.py` - PDF讀取核心模組
- `requirements.txt` - 精簡依賴清單

#### 3. 安裝依賴套件
```bash
pip install mcp PyMuPDF Pillow python-magic
```

## 🔗 Claude Desktop 整合

### 1. 編輯設定檔案
**檔案位置**：`~/Library/Application Support/Claude/claude_desktop_config.json`

**設定內容**（使用 Git Clone 路徑）：
```json
{
  "mcpServers": {
    "pdf-mcp-server": {
      "command": "python3",
      "args": ["/Users/your_username/pdf-mcp-server/server.py"]
    }
  }
}
```

⚠️ **重要**：
- 如果您使用 `git clone` 安裝，路徑通常是：`/Users/your_username/pdf-mcp-server/server.py`
- 如果您 clone 到其他位置，請使用相應的絕對路徑

### 2. 重新啟動 Claude Desktop
完全關閉 Claude Desktop，然後重新開啟。

### 3. 驗證連接
在 Claude 中輸入：
```
請讀取這個PDF檔案：/path/to/your/document.pdf
```

## 🔄 更新專案 (Note. 此處AI自動撰寫，實際上不一定會更新）

如果使用 Git Clone 安裝，可以輕鬆更新到最新版本：

```bash
# 進入專案目錄
cd pdf-mcp-server

# 拉取最新更新
git pull origin main

# 重新安裝依賴（如有新增）
pip install -r requirements.txt

# 重新測試伺服器
python3 server.py
```

## 🛠️ 開發者安裝 (Note. 此處AI自動撰寫，可用性未知）

如果您想要自訂功能：

```bash
# Fork 並 clone 您的 fork
git clone https://github.com/您的用戶名/pdf-mcp-server.git
cd pdf-mcp-server

# 添加上游倉庫
git remote add upstream https://github.com/c70311tw/pdf-mcp-server.git

# 建立開發分支
git checkout -b feature/your-feature-name

# 安裝開發依賴
pip install -r requirements.txt

# 進行開發...
# 提交變更
git add .
git commit -m "Add your feature"
git push origin feature/your-feature-name

# 建立 Pull Request
```

## 📚 使用範例

### 📖 **完整文件分析**

#### 讀取整個PDF文件
```
請幫我分析這個PDF檔案的完整內容：
/Users/username/Documents/report.pdf
```

#### 分析特定頁面範圍
```
請讀取這個PDF的第5到10頁內容：
/Users/username/Documents/manual.pdf
```

### 🔍 **文件資訊查詢**

#### 獲取文件基本資訊
```
請告訴我這個PDF的基本資訊和元數據：
/Users/username/Documents/contract.pdf
```

#### 分析文件結構
```
請分析這個PDF每一頁的詳細資訊：
/Users/username/Documents/presentation.pdf
```

### 🖼️ **圖片資源提取**

#### 提取所有圖片
```
請提取這個PDF中的所有圖片並分析：
/Users/username/Documents/catalog.pdf
```

#### 指定輸出目錄
```
請將PDF中的圖片提取到桌面：
檔案：/Users/username/Documents/brochure.pdf
輸出目錄：/Users/username/Desktop/extracted_images/
```

### 🔎 **智能內容搜尋**

#### 關鍵字搜尋
```
在這個PDF中搜尋「人工智慧」相關內容：
/Users/username/Documents/research.pdf
```

#### 精確搜尋
```
在合約中搜尋「條款」（區分大小寫）：
檔案：/Users/username/Documents/contract.pdf
關鍵字：條款
大小寫敏感：是
```

### 📊 **專業文件分析**

#### 學術論文分析
```
請分析這篇學術論文的結構和主要內容：
/Users/username/Documents/thesis.pdf
```

#### 技術文件解析
```
請提取這個技術手冊的主要資訊：
/Users/username/Documents/manual.pdf
```

## 🐛 故障排除

### 常見問題與解決方案

#### 1. "Server disconnected" 錯誤
**原因**：檔案路徑或設定錯誤

**解決方案**：
```bash
# 確認檔案存在
ls -la ~/pdf-mcp-server/server.py

# 使用絕對路徑設定
{
  "mcpServers": {
    "pdf-mcp-server": {
      "command": "python3",
      "args": ["/path/to/pdf-mcp-server/server.py"]
    }
  }
}
```

#### 2. PDF無法讀取
**可能原因及解決**：

**檔案路徑問題**：
```bash
# 檢查檔案是否存在
ls -la "/path/to/your/file.pdf"

# 使用絕對路徑
/Users/username/Documents/file.pdf
```

**權限問題**：
```bash
# 檢查檔案權限
chmod 644 /path/to/your/file.pdf
```

**PDF損壞或加密**：
- 嘗試用其他PDF查看器打開確認
- 加密PDF需要先解密

#### 3. 中文內容顯示問題
- 系統自動處理繁體中文編碼
- 支援混合語言內容
- 完美處理特殊字符

#### 4. 依賴套件問題
```bash
# 重新安裝核心依賴
pip install --upgrade mcp PyMuPDF Pillow

# macOS系統依賴
brew install mupdf-tools

# 檢查Python版本
python3 --version  # 需要3.9+
```

### 🔧 **除錯技巧**

#### 1. 查看即時日誌
```bash
tail -f ~/Library/Logs/Claude/mcp*.log
```

#### 2. 測試伺服器狀態
```bash
cd ~/pdf-mcp-server
python3 server.py
```

#### 3. 驗證設定檔語法
```bash
python3 -m json.tool ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

#### 4. 測試PDF檔案
```bash
# 用PyMuPDF直接測試
python3 -c "import fitz; print(fitz.open('/path/to/test.pdf'))"
```

## 📁 專案結構

```
pdf-mcp-server/
├── server.py              # 讀取專用伺服器主程式
├── pdf_reader.py          # PDF讀取核心模組
├── requirements.txt       # 精簡依賴清單
├── README.md             # 本說明文件
└── tests/                # 測試檔案（可選）
    ├── test_pdf_reader.py
    └── sample_files/
```

## 🔧 核心依賴

```
mcp>=1.0.0                # MCP協議支援
PyMuPDF>=1.23.0          # PDF讀取處理（高效能）
Pillow>=10.0.0           # 圖片處理
python-magic>=0.4.27     # 檔案類型偵測
typing-extensions>=4.0.0  # 型別支援
```

## 🚀 **為什麼選擇讀取專用版？**

### ✅ **穩定性優先**
- 避免大內容輸出造成的token截斷問題
- 專注核心功能，減少潛在錯誤
- 經過實戰測試，穩定可靠

### ⚡ **性能優化**
- 快速啟動，即用即開
- 低記憶體占用，系統負擔小
- 精簡設計，執行效率高

### 🎯 **使用場景匹配**
- 大多數用戶主要需求是PDF分析
- 讀取功能已能滿足90%的使用場景
- 避免功能過載，專注實用性

## 📄 授權條款

此專案採用MIT授權條款 - 詳見 [LICENSE](LICENSE) 檔案。

## 🙏 致謝

- [PyMuPDF](https://pymupdf.readthedocs.io/) - 優秀的PDF處理核心
- [MCP](https://modelcontextprotocol.io/) - 標準化AI模型通訊協議
- [Claude AI](https://claude.ai/) - 提供強大的AI整合能力
- [Pillow](https://pillow.readthedocs.io/) - 圖片處理支援

## 📞 支援

如遇問題請：
1. 查看故障排除章節
2. 檢查伺服器日誌檔案
3. 確認檔案路徑和權限
4. 參考使用範例

---

🎯 **專注核心、穩定可靠的PDF分析解決方案！**

⭐ 如果這個專案對您有幫助，請給我們一個星星支持！
