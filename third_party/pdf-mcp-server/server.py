#!/usr/bin/env python3
"""PDF MCP Server - PDF Reading Only Version."""

import asyncio
import logging
import sys
import os
from typing import Any, Dict, List

# Setup logging to stderr (not stdout, as that interferes with MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("pdf-mcp-server")

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    logger.info("MCP imports successful")
except ImportError as e:
    logger.error(f"Failed to import MCP: {e}")
    logger.error("Please install MCP with: pip install mcp")
    sys.exit(1)

try:
    from pdf_reader import PDFReader  # 只需要讀取功能
    logger.info("PDFReader import successful")
except ImportError as e:
    logger.error(f"Failed to import PDFReader: {e}")
    logger.error("Make sure pdf_reader.py is in the same directory")
    sys.exit(1)

# Initialize server and PDF reader only
server = Server("pdf-mcp-server")

try:
    pdf_reader = PDFReader()
    logger.info("PDF reader initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize PDF reader: {e}")
    sys.exit(1)


@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """List available PDF reading tools only."""
    logger.info("Listing available PDF reading tools")
    return [
        Tool(
            name="read_pdf_text",
            description="從PDF檔案中提取文字內容。支援指定頁面範圍。",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "PDF檔案的路徑"
                    },
                    "start_page": {
                        "type": "integer",
                        "description": "起始頁面（可選，從1開始計數）",
                        "minimum": 1
                    },
                    "end_page": {
                        "type": "integer",
                        "description": "結束頁面（可選，包含此頁）",
                        "minimum": 1
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_pdf_metadata",
            description="取得PDF檔案的元數據資訊，包括標題、作者、頁數等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "PDF檔案的路徑"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="extract_pdf_images",
            description="從PDF檔案中提取所有圖片。",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "PDF檔案的路徑"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "圖片輸出目錄（可選）"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_pdf_page_info",
            description="取得PDF每一頁的詳細資訊，包括尺寸、旋轉、內容統計等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "PDF檔案的路徑"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="search_pdf_text",
            description="在PDF檔案中搜尋特定文字內容。",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "PDF檔案的路徑"
                    },
                    "search_term": {
                        "type": "string",
                        "description": "要搜尋的文字"
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "是否區分大小寫（預設為false）",
                        "default": False
                    }
                },
                "required": ["file_path", "search_term"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle PDF reading tool calls only."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    
    try:
        if name == "read_pdf_text":
            return await _handle_read_pdf_text(arguments)
        elif name == "get_pdf_metadata":
            return await _handle_get_pdf_metadata(arguments)
        elif name == "extract_pdf_images":
            return await _handle_extract_pdf_images(arguments)
        elif name == "get_pdf_page_info":
            return await _handle_get_pdf_page_info(arguments)
        elif name == "search_pdf_text":
            return await _handle_search_pdf_text(arguments)
        else:
            error_msg = f"Unknown tool: {name}"
            logger.error(error_msg)
            return [TextContent(type="text", text=f"❌ {error_msg}")]
    except Exception as e:
        error_msg = f"Error executing tool {name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=f"❌ {error_msg}")]


# PDF Reading Tool Handlers (keep all existing functions)
async def _handle_read_pdf_text(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle read_pdf_text tool call."""
    file_path = arguments.get("file_path")
    start_page = arguments.get("start_page")
    end_page = arguments.get("end_page")
    
    if not file_path:
        return [TextContent(type="text", text="錯誤：未提供檔案路徑")]
    
    # Determine page range
    page_range = None
    if start_page is not None or end_page is not None:
        start = start_page if start_page is not None else 1
        end = end_page if end_page is not None else 9999
        page_range = (start, end)
    
    try:
        result = pdf_reader.extract_text(file_path, page_range)
        
        if result["success"]:
            response = f"""✅ PDF文字提取完成

📄 檔案：{result['file_path']}
📊 總頁數：{result['total_pages']}
📝 提取頁數：{result['extracted_pages']}
🔤 總字符數：{result['total_characters']}

📖 提取的文字內容：
{result['full_text']}

📋 頁面詳情："""
            
            for page in result['pages']:
                response += f"\n  • 第{page['page_number']}頁：{page['char_count']} 字符"
            
            return [TextContent(type="text", text=response)]
        else:
            return [TextContent(type="text", text=f"❌ 錯誤：{result['error']}")]
            
    except Exception as e:
        logger.error(f"Error reading PDF text: {e}")
        return [TextContent(type="text", text=f"❌ 處理PDF時發生錯誤：{str(e)}")]


async def _handle_get_pdf_metadata(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle get_pdf_metadata tool call."""
    file_path = arguments.get("file_path")
    
    if not file_path:
        return [TextContent(type="text", text="錯誤：未提供檔案路徑")]
    
    try:
        # Extract just metadata by opening document
        import fitz
        doc = fitz.open(file_path)
        metadata = pdf_reader.extract_metadata(doc)
        doc.close()
        
        response = f"""📋 PDF元數據資訊

📄 檔案：{file_path}
📝 標題：{metadata['title'] or '無'}
👤 作者：{metadata['author'] or '無'}
📖 主題：{metadata['subject'] or '無'}
🛠️ 創建工具：{metadata['creator'] or '無'}
🏭 生產工具：{metadata['producer'] or '無'}
📅 創建日期：{metadata['creation_date'] or '無'}
🔄 修改日期：{metadata['modification_date'] or '無'}
📄 頁數：{metadata['page_count']}
🔒 是否加密：{'是' if metadata['encrypted'] else '否'}
📑 PDF版本：{metadata['pdf_version'] or '未知'}"""
        
        return [TextContent(type="text", text=response)]
        
    except Exception as e:
        logger.error(f"Error getting PDF metadata: {e}")
        return [TextContent(type="text", text=f"❌ 取得PDF元數據時發生錯誤：{str(e)}")]


async def _handle_extract_pdf_images(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle extract_pdf_images tool call."""
    file_path = arguments.get("file_path")
    output_dir = arguments.get("output_dir")
    
    if not file_path:
        return [TextContent(type="text", text="錯誤：未提供檔案路徑")]
    
    try:
        result = pdf_reader.extract_images(file_path, output_dir)
        
        if result["success"]:
            response = f"""🖼️ PDF圖片提取完成

📄 檔案：{result['file_path']}
🖼️ 總圖片數：{result['total_images']}
📁 輸出目錄：{result['output_directory'] or '無（僅返回數據）'}

📋 圖片詳情："""
            
            for img in result['images']:
                response += f"""
  • 第{img['page_number']}頁 圖片{img['image_index']}：
    - 檔名：{img['image_name']}
    - 尺寸：{img['width']}x{img['height']}
    - 色彩空間：{img['colorspace']}
    - 檔案大小：{img['size_bytes']} bytes"""
                if img['file_path']:
                    response += f"\n    - 儲存路徑：{img['file_path']}"
            
            if result['total_images'] == 0:
                response += "\n  • 此PDF沒有找到任何圖片"
            
            return [TextContent(type="text", text=response)]
        else:
            return [TextContent(type="text", text=f"❌ 錯誤：{result['error']}")]
            
    except Exception as e:
        logger.error(f"Error extracting PDF images: {e}")
        return [TextContent(type="text", text=f"❌ 提取PDF圖片時發生錯誤：{str(e)}")]


async def _handle_get_pdf_page_info(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle get_pdf_page_info tool call."""
    file_path = arguments.get("file_path")
    
    if not file_path:
        return [TextContent(type="text", text="錯誤：未提供檔案路徑")]
    
    try:
        result = pdf_reader.get_page_info(file_path)
        
        if result["success"]:
            response = f"""📊 PDF頁面資訊

📄 檔案：{result['file_path']}
📄 總頁數：{result['total_pages']}

📋 各頁面詳情："""
            
            for page in result['pages']:
                response += f"""
  📄 第{page['page_number']}頁：
    - 尺寸：{page['width']:.1f} x {page['height']:.1f} 點
    - 旋轉：{page['rotation']}°
    - 文字長度：{page['text_length']} 字符
    - 圖片數量：{page['image_count']}
    - 連結數量：{page['link_count']}
    - 註解數量：{page['annotation_count']}"""
            
            return [TextContent(type="text", text=response)]
        else:
            return [TextContent(type="text", text=f"❌ 錯誤：{result['error']}")]
            
    except Exception as e:
        logger.error(f"Error getting PDF page info: {e}")
        return [TextContent(type="text", text=f"❌ 取得PDF頁面資訊時發生錯誤：{str(e)}")]


async def _handle_search_pdf_text(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle search_pdf_text tool call."""
    file_path = arguments.get("file_path")
    search_term = arguments.get("search_term")
    case_sensitive = arguments.get("case_sensitive", False)
    
    if not file_path:
        return [TextContent(type="text", text="錯誤：未提供檔案路徑")]
    
    if not search_term:
        return [TextContent(type="text", text="錯誤：未提供搜尋詞")]
    
    try:
        result = pdf_reader.search_text(file_path, search_term, case_sensitive)
        
        if result["success"]:
            response = f"""🔍 PDF文字搜尋結果

📄 檔案：{result['file_path']}
🔍 搜尋詞："{result['search_term']}"
📊 找到：{result['total_matches']} 個匹配項目

📋 搜尋結果："""
            
            if result['total_matches'] > 0:
                for i, match in enumerate(result['matches'], 1):
                    response += f"""
  {i}. 第{match['page_number']}頁：
     位置：({match['bbox'][0]:.1f}, {match['bbox'][1]:.1f})
     內容：{match['context']}"""
            else:
                response += "\n  • 未找到任何匹配的內容"
            
            return [TextContent(type="text", text=response)]
        else:
            return [TextContent(type="text", text=f"❌ 錯誤：{result['error']}")]
            
    except Exception as e:
        logger.error(f"Error searching PDF text: {e}")
        return [TextContent(type="text", text=f"❌ 搜尋PDF文字時發生錯誤：{str(e)}")]


async def main():
    """Main server entry point."""
    logger.info("Starting PDF MCP Server - Reading Only Version...")
    
    try:
        # Use stdin/stdout for communication with Claude
        async with stdio_server() as (read_stream, write_stream):
            logger.info("PDF Reading Server started successfully")
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server failed to start: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())