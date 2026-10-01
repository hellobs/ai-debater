#!/usr/bin/env python3
"""把官方网页（HTML）抓成 `data/corpus/sources/<法名>.txt` 的干净纯文本。

只做「抓取 + 去标签 + 行首锚定整理」，不调用 LLM、不内置任何法条内容。
清洗规则（与 import_corpus.py 的 parse_statute_text 配合）：

- 去掉 <script>/<style>/注释，<br>/</p>/</div>/</li>/<tr> 等换成换行；
- 剥掉所有剩余标签、解 HTML 实体；
- 在每个「第X条」「第X章」「第X节」前插入换行，保证行首锚定能切分；
- 标题行（含「法」「条例」等后缀且短）原样保留在正文首部，由 import 时 --law 覆盖。

用法：
    python scripts/fetch_law.py <URL> <法名> [--out <路径>] [--dry-run]

幂等：同一次运行只追加一个文件；是否写 laws.json 交给 import_corpus.py 决定。
"""
from __future__ import annotations

import argparse
import html
import re
import ssl
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.retrieval.statute_text import parse_statute_text  # noqa: E402

_NUM = r"[一二三四五六七八九十百零〇0-9]+"
# 在「第X条 / 第X章 / 第X节」前换行，保证行首锚定。
# 只在**真正的条首**切分：① 前面是句末标点或换行；② 条号后紧跟空白（"第X条　正文"格式）。
# 不能无脑全切 —— 否则「不适用本法第十七条、第十八条第一款」这类**正文内引用**会被
# 当成新条，该条正文随之丢失尾部（实测：反垄断法第二十条、第五十九条等被截断）。
_INSERT_NL = re.compile(
    rf"(?<=[。；！？\n])(?=第{_NUM}[条章节])"
    rf"|(?=第{_NUM}[条章节][\s\u3000])"
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\xa0]+")
_BLANK = re.compile(r"\n{3,}")


def fetch(url: str, no_verify: bool = False) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; corpus-fetch/1.0)"})
    ctx = None
    if no_verify:
        # 仅供沙箱代理对部分官方站点做 TLS 拦截（内容源仍是官方站）时绕过证书校验
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    raw = urlopen(req, timeout=40, context=ctx).read()
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def clean(html_text: str) -> str:
    t = re.sub(r"<!--.*?-->", "", html_text, flags=re.S)
    t = re.sub(r"<script[\s\S]*?</script>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I | re.S)
    # 块级/换行元素换成换行
    t = re.sub(r"(?i)</(p|div|li|tr|br|h[1-6]|section|article|dd|dt|td|th)>", "\n", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = _TAG.sub("", t)
    t = html.unescape(t)
    t = _WS.sub(" ", t)
    # 行首锚定：在每条/每章/每节前换行
    t = _INSERT_NL.sub("\n", t)
    # 去掉「目录」等内部导航残留（简单按行过滤空行与纯标点行）
    lines = [ln.strip() for ln in t.split("\n")]
    lines = [ln for ln in lines if ln and not set(ln) <= set("·•·—-　 ")]
    out = _BLANK.sub("\n\n", "\n".join(lines))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="官方网页 → 干净法条纯文本")
    ap.add_argument("url")
    ap.add_argument("law", help="法名（写进来源头部，import 时建议也用 --law）")
    ap.add_argument("--out", default=str(ROOT / "data" / "corpus" / "sources" / "{law}.txt"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-verify", action="store_true",
                    help="沙箱代理对部分官方站点做 TLS 拦截时绕过证书校验（内容源仍是官方站）")
    args = ap.parse_args()

    print(f"抓取：{args.url}")
    try:
        raw = fetch(args.url, no_verify=args.no_verify)
    except Exception as e:
        sys.exit(f"[失败] 抓取失败：{type(e).__name__}: {e}")
    print(f"  原始字节≈{len(raw.encode('utf-8','ignore'))}")

    text = clean(raw)
    # 来源头部 + 正文
    header = (
        f"# 来源：{args.url}\n"
        f"# 抓取日期：{date.today().isoformat()}\n"
        f"# 清洗：仅去 HTML 标签与 markdown 加粗、按条文换行，内容未改动\n"
        f"{args.law}\n"
    )
    doc = header + text + "\n"

    try:
        res = parse_statute_text(text, law=args.law)
        print(res.summary())
    except Exception as e:
        print(f"[警告] 解析预览失败：{e}")

    out_path = Path(args.out.format(law=args.law))
    if args.dry_run:
        print("（--dry-run：未写文件）")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    print(f"已写入：{out_path}")


if __name__ == "__main__":
    main()
