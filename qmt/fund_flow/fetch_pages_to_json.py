# -*- coding: utf-8 -*-
"""
自动按页请求东方财富 push2 接口，把每一页的原始 JSON 保存到本地。
之后用 run_once_from_json 合并这些 JSON 生成汇总（无需在浏览器里一页一页复制保存）。

用法：
  py -m qmt.fund_flow.fetch_pages_to_json
  py -m qmt.fund_flow.fetch_pages_to_json --max-pages 10 --output-dir qmt/fund_flow/output
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_here = Path(__file__).resolve().parent
if __name__ == "__main__" and __package__ is None:
    _root = _here.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from qmt.fund_flow.fetcher import (
    CLIST_URL,
    FIELDS,
    FS_ALL_A,
    HEADERS,
    MAX_RETRIES,
    RETRY_DELAYS,
)


def _request_page(pn: int, pz: int = 5000, timeout: int = 30) -> dict | None:
    """请求单页，返回原始 JSON 或 None。"""
    params = {
        "fs": FS_ALL_A,
        "pn": pn,
        "pz": pz,
        "fid": "f62",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fields": FIELDS,
    }
    # 优先 curl_cffi
    try:
        from curl_cffi import requests as curl_requests
        for i in range(MAX_RETRIES):
            try:
                if i > 0:
                    time.sleep(RETRY_DELAYS[i - 1])
                r = curl_requests.get(
                    CLIST_URL, params=params, headers=HEADERS, timeout=timeout,
                    impersonate="chrome",
                )
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if i == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAYS[i])
    except ImportError:
        import requests
        for i in range(MAX_RETRIES):
            try:
                if i > 0:
                    time.sleep(RETRY_DELAYS[i])
                r = requests.get(CLIST_URL, params=params, headers=HEADERS, timeout=timeout)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if i == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAYS[i])
    return None


def fetch_pages_to_json(
    output_dir: str | Path,
    max_pages: int = 60,
    delay_between_pages: float = 1.0,
) -> list[Path]:
    """
    按页请求并保存为 page1.json, page2.json, ...
    返回成功保存的文件路径列表。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total_fetched = 0

    for pn in range(1, max_pages + 1):
        out_file = output_dir / f"page{pn}.json"
        if out_file.exists():
            # 已存在则跳过（可后续改为 --force 覆盖）
            try:
                data = json.loads(out_file.read_text(encoding="utf-8"))
                diff = (data.get("data") or {}).get("diff") or []
                total_fetched += len(diff)
                print(f"  第{pn}页已存在，跳过（本页 {len(diff)} 条）", flush=True)
                saved.append(out_file)
                if len(diff) < 100:
                    print(f"  上一页不足 100 条，视为最后一页，停止。", flush=True)
                    break
                continue
            except Exception:
                pass

        print(f"  正在请求第 {pn} 页…", flush=True)
        try:
            data = _request_page(pn)
        except Exception as e:
            print(f"  第 {pn} 页请求失败: {e}", flush=True)
            if pn == 1:
                raise
            break

        if not data:
            print(f"  第 {pn} 页返回空，停止。", flush=True)
            break

        diff = (data.get("data") or {}).get("diff") or []
        total_fetched += len(diff)
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        saved.append(out_file)
        print(f"  已保存 {out_file.name}，本页 {len(diff)} 条，累计 {total_fetched} 条。", flush=True)

        if len(diff) < 100:
            print(f"  本页不足 100 条，视为最后一页，停止。", flush=True)
            break

        if pn < max_pages:
            time.sleep(delay_between_pages)

    return saved


def main():
    parser = argparse.ArgumentParser(description="按页拉取东方财富资金流 API 并保存为 JSON")
    parser.add_argument(
        "--output-dir", "-o",
        default=str(_here / "output"),
        help="保存目录，默认 qmt/fund_flow/output",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=60,
        help="最多拉取页数，默认 60（约 6000 条）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="每页之间的间隔秒数，默认 1",
    )
    args = parser.parse_args()
    print("开始按页拉取并保存 JSON…", flush=True)
    saved = fetch_pages_to_json(args.output_dir, max_pages=args.max_pages, delay_between_pages=args.delay)
    print(f"完成，共保存 {len(saved)} 个文件。", flush=True)
    print("下一步运行: py -m qmt.fund_flow.run_once_from_json --input", args.output_dir, "--date 2026-03-11", flush=True)


if __name__ == "__main__":
    main()
