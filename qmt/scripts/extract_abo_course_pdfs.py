# -*- coding: utf-8 -*-
"""将「量化阿波·量化投资实战特训营」网盘目录下全部 PDF 抽取为纯文本，供检索与归档。"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError as e:
    raise SystemExit("需要 PyMuPDF: pip install pymupdf") from e

# 默认网盘根目录（可按本机修改）
DEFAULT_ROOT = Path(r"d:\BaiduNetdiskDownload\2026.1 量化阿波·量化投资实战特训营")
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "量化阿波特训营_PDF全文"


def safe_stem(name: str, max_len: int = 120) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "_", name)
    s = s.strip(" .")
    if len(s) > max_len:
        s = s[: max_len // 2] + "…" + s[-(max_len // 2 - 2) :]
    return s or "unnamed"


def extract_one(pdf_path: Path) -> tuple[str, int, str | None]:
    err: str | None = None
    parts: list[str] = []
    page_count = 0
    try:
        doc = fitz.open(pdf_path)
        page_count = doc.page_count
        for i in range(page_count):
            page = doc.load_page(i)
            t = page.get_text("text") or ""
            parts.append(f"\n\n===== 第 {i + 1} 页 =====\n\n{t}")
        doc.close()
    except Exception as e:
        err = str(e)
    return "".join(parts), page_count, err


def main() -> None:
    root = DEFAULT_ROOT
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(root.rglob("*.pdf"), key=lambda p: str(p).lower())
    manifest: list[dict] = []

    for pdf_path in pdfs:
        rel = pdf_path.relative_to(root)
        stem = safe_stem(pdf_path.stem)
        out_name = f"{safe_stem(str(rel).replace('/', '__'))}.txt"
        out_path = OUT_DIR / out_name

        text, pages, err = extract_one(pdf_path)
        header = (
            f"源文件: {pdf_path}\n"
            f"相对路径: {rel}\n"
            f"页数: {pages}\n"
            + (f"提取错误: {err}\n" if err else "")
            + "\n"
            + "=" * 60
            + "\n"
        )
        out_path.write_text(header + text, encoding="utf-8", errors="replace")

        manifest.append(
            {
                "relative_path": str(rel).replace("\\", "/"),
                "absolute_path": str(pdf_path),
                "pages": pages,
                "output_txt": str(out_path.relative_to(OUT_DIR.parent.parent)),
                "error": err,
            }
        )

    (OUT_DIR / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 人类可读的索引
    lines = [
        "# 量化阿波特训营 PDF 全文提取索引",
        "",
        f"- 源目录: `{root}`",
        f"- 输出目录: `{OUT_DIR}`",
        f"- PDF 数量: {len(pdfs)}",
        "",
        "| 相对路径 | 页数 | 输出 txt | 错误 |",
        "|----------|------|----------|------|",
    ]
    for m in manifest:
        err = m["error"] or ""
        lines.append(
            f"| {m['relative_path']} | {m['pages']} | `{Path(m['output_txt']).name}` | {err} |"
        )
    (OUT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")

    ok = sum(1 for m in manifest if not m["error"])
    print(f"完成: {ok}/{len(manifest)} 成功, 输出: {OUT_DIR}")


if __name__ == "__main__":
    main()
