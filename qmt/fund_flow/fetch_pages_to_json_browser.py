# -*- coding: utf-8 -*-
"""
用真实浏览器按页打开东方财富接口 URL，把每页返回的 JSON 保存到本地。
适合「直连/curl 被断开、但浏览器能打开」的情况，全自动翻页保存，无需手动一页一页复制。

依赖（一次性）：
  pip install playwright
  py -m playwright install chromium
  若已手动保存过某几页（如 page1.json），脚本会跳过已有页、只拉取缺失页。

用法：
  py -m qmt.fund_flow.fetch_pages_to_json_browser
  py -m qmt.fund_flow.fetch_pages_to_json_browser --max-pages 56 --headed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_here = Path(__file__).resolve().parent
if __name__ == "__main__" and __package__ is None:
    _root = _here.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

# 与东方财富 push2 一致
BASE_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    "&pn={pn}&pz=5000&fid=f62&po=1&np=1&fltt=2&invt=2"
    "&fields=f12,f14,f2,f3,f20,f21,f62,f184,f6"
)


def _extract_json_from_page(text: str) -> dict | None:
    """从页面文本中提取 JSON（浏览器可能包在 <pre> 或直接是 body 文本）。"""
    text = (text or "").strip()
    if not text:
        return None
    # 去掉可能的 HTML 包裹
    if "<" in text and ">" in text:
        # 取 <pre>...</pre> 或 body 内第一段连续 { ... }
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def fetch_pages_with_browser(
    output_dir: str | Path,
    max_pages: int = 60,
    delay_between_pages: float = 1.2,
    headed: bool = False,
    proxy: str | None = None,
) -> list[Path]:
    """
    用 Playwright 启动浏览器，逐页打开 URL，把每页 body 里的 JSON 保存为 page1.json, page2.json ...
    返回成功保存的文件列表。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("请先安装: pip install playwright  然后执行: playwright install chromium")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total_fetched = 0

    proxy_url = proxy or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("SOCKS_PROXY")
    if proxy_url:
        proxy_url = proxy_url.strip()
        if not proxy_url.startswith("http") and not proxy_url.startswith("socks"):
            proxy_url = "http://" + proxy_url
        proxy_config = {"server": proxy_url}
        print(f"  使用代理: {proxy_url}", flush=True)
    else:
        proxy_config = None

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=not headed)
        except Exception:
            browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            extra_http_headers={"Accept": "application/json, text/plain, */*"},
            proxy=proxy_config,
        )
        page = context.new_page()
        try:
            for pn in range(1, max_pages + 1):
                out_file = output_dir / f"page{pn}.json"
                if out_file.exists():
                    try:
                        data = json.loads(out_file.read_text(encoding="utf-8"))
                        diff = (data.get("data") or {}).get("diff") or []
                        total_fetched += len(diff)
                        print(f"  第{pn}页已存在，跳过（本页 {len(diff)} 条）", flush=True)
                        saved.append(out_file)
                        if len(diff) < 100:
                            print("  上一页不足 100 条，视为最后一页。", flush=True)
                            break
                        continue
                    except Exception:
                        pass

                url = BASE_URL.format(pn=pn)
                print(f"  正在打开第 {pn} 页…", flush=True)
                # 用 load 代替 networkidle，避免接口返回后仍有请求导致超时/ERR_EMPTY_RESPONSE
                try:
                    page.goto(url, wait_until="load", timeout=25000)
                except Exception as e:
                    print(f"  第 {pn} 页加载失败: {e}", flush=True)
                    if pn == 1:
                        raise
                    break

                # 页面 body 里就是接口返回的 JSON 文本
                try:
                    body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception:
                    body_text = ""
                if not body_text:
                    body_text = page.content()

                data = _extract_json_from_page(body_text)
                if not data:
                    print(f"  第 {pn} 页未能解析出 JSON，停止。", flush=True)
                    break

                diff = (data.get("data") or {}).get("diff") or []
                total_fetched += len(diff)
                out_file.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
                saved.append(out_file)
                print(f"  已保存 {out_file.name}，本页 {len(diff)} 条，累计 {total_fetched} 条。", flush=True)

                if len(diff) < 100:
                    print("  本页不足 100 条，视为最后一页。", flush=True)
                    break

                if pn < max_pages:
                    time.sleep(delay_between_pages)
        finally:
            browser.close()

    return saved


def main():
    parser = argparse.ArgumentParser(
        description="用浏览器按页打开东方财富接口并保存每页 JSON（无需手动复制）",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=str(_here / "output"),
        help="保存目录",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=60,
        help="最多拉取页数",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.2,
        help="每页间隔秒数",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="显示浏览器窗口（默认无头）",
    )
    parser.add_argument(
        "--proxy", "-x",
        default=None,
        metavar="URL",
        help="代理地址，如 http://127.0.0.1:18081 或 socks5://127.0.0.1:18080（狗急加速 SOCKS）",
    )
    args = parser.parse_args()
    print("使用浏览器按页拉取并保存 JSON…", flush=True)
    saved = fetch_pages_with_browser(
        args.output_dir,
        max_pages=args.max_pages,
        delay_between_pages=args.delay,
        headed=args.headed,
        proxy=args.proxy,
    )
    print(f"完成，共保存 {len(saved)} 个文件。", flush=True)
    print("下一步运行: py -m qmt.fund_flow.run_once_from_json --input", args.output_dir, "--date 2026-03-11", flush=True)


if __name__ == "__main__":
    main()
