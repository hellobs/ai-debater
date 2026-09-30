"""语料导入：把法条全文结构化进语料库（界面入口，阶段 4 的补充）。

引用核验判「已核验」的**唯一**依据是结构化语料里的「条款号 → 原文」对应关系。
此前唯一的导入通道是命令行 `scripts/import_corpus.py` —— 队友在现场不会开终端，
本模块把同一件事搬进界面：粘贴或上传法条全文 → 结构化 → 合并进 laws.json →
由端点热重载检索层，立刻生效。

两条入口**共用同一套解析**（`retrieval.statute_text`），逻辑只写一遍：
本模块只补「读旧语料 → 合并 → 写回」这一段文件操作。

写盘策略与红线：

1. **同名法整体替换**，其他已导入的法不动 —— 重导一部法就是修订它，
   逐条合并反而会留下删不掉的旧条。
2. 已有 laws.json 损坏时**如实报错**，绝不静默清空重建 —— 那会把用户
   此前导入的全部语料一次洗掉。
3. 本模块**不联网、不调用 LLM、不补全条文**；语料内容对不对由来源文件负责
   （官方文本见 flk.npc.gov.cn，不要凭记忆录入——那会把错误固化成「已核验」）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .retrieval import corpus_dir
from .retrieval.statute_text import (
    StatuteParseError,
    article_no,
    parse_statute_text,
)


def _store_path() -> Path:
    return corpus_dir() / "laws.json"


def _load_store() -> dict:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"现有语料 {path} 不是合法 JSON（{exc}）。请先修复或删除该文件再导入"
        ) from exc
    if isinstance(data, list):
        raise ValueError(
            f"现有语料 {path} 是数组写法，本工具只合并对象写法（{{法名: {{条款: 原文}}}}）。"
            "请手工转换或删除后重导"
        )
    if not isinstance(data, dict):
        raise ValueError(f"现有语料 {path} 结构无法识别：{type(data).__name__}")
    return data


def import_text(text: str, law: str = "") -> dict:
    """结构化一段法条全文并合并进语料库。失败抛 `StatuteParseError` / `ValueError`。

    `law` 留空时从正文首行识别（《XX法》）；识别不到就报错——法名是核验
    对齐的键，猜错比报错贵得多。
    """
    text = (text or "").strip()
    if not text:
        raise StatuteParseError("正文为空：请粘贴或选择一份法条全文")

    parsed = parse_statute_text(text, law=(law or "").strip())
    if not parsed.law:
        raise StatuteParseError(
            "无法识别法名：请在正文首行保留「《XX法》」标题，或在「法名」框里填写"
        )

    store = _load_store()
    store[parsed.law] = dict(
        sorted(parsed.articles.items(), key=lambda kv: article_no(kv[0]))
    )

    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 与 import_corpus.py 同款排序：按法名排序，条款内序保留「第一条、第二条…」，
    # 不用 sort_keys——那会按字符串把条号排乱。
    ordered = {name: store[name] for name in sorted(store)}
    path.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "law": parsed.law,
        "articles": parsed.count,
        "missing": parsed.missing,
        "warnings": parsed.warnings,
        "total_laws": len(store),
        "total_articles": sum(len(v) for v in store.values()),
    }
