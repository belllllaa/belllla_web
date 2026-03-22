# 临时脚本：读入 page4 的 JSON 并格式化成与 page1 一致后写入 page4.json
# 用法：把完整 JSON 存为 page4_paste.txt 后运行 py format_page4.py
import json, re
from pathlib import Path
here = Path(__file__).resolve().parent
raw_path = here / "page4_paste.txt"
out_path = here / "page4.json"
if not raw_path.exists():
    print("请先将第4页完整 JSON 粘贴保存为 page4_paste.txt")
    raise SystemExit(1)
data = json.loads(raw_path.read_text(encoding="utf-8-sig"))
s = json.dumps(data, ensure_ascii=False, indent=2)
out = re.sub(r"^\s+", "", s, flags=re.MULTILINE)
out_path.write_text(out, encoding="utf-8")
print("已写入 page4.json，行数:", len(out.splitlines()))
