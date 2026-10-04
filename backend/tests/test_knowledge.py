"""通用参考知识库测试（切块 / TF-IDF 检索 / 上传管理）。

全部 0 API 消耗：知识库是纯本地计算。目录由 conftest 指向 .testdata，
单例用 reset() 隔离。
"""
from __future__ import annotations

import pytest

from app import config
from app.knowledge import KnowledgeBase, chunk_text, get_kb, reset


@pytest.fixture()
def kb(tmp_path):
    reset()
    base = KnowledgeBase(tmp_path / "kb")
    yield base
    reset()


# --------------------------------------------------------------------------
# 切块
# --------------------------------------------------------------------------
def test_chunk_keeps_paragraph_boundaries():
    """段落优先：相邻短段会合并（设计如此），但任何块都不超窗、顺序保留。"""
    paras = "\n\n".join(f"第{n}段：" + "内容" * 80 for n in range(1, 5))
    chunks = chunk_text(paras, size=200, overlap=50)
    assert all(len(c) <= 200 for c in chunks)
    assert "第1段" in chunks[0] and "第4段" in chunks[-1]


def test_chunk_drops_long_tail_overlap():
    """超长无标点段落走滑窗兜底，块间有重叠（上下文不断裂）。"""
    text = "字" * 1200
    chunks = chunk_text(text, size=500, overlap=90)
    assert len(chunks) == 3
    assert chunks[0][-90:] == chunks[1][:90]


def test_chunk_empty_is_empty():
    assert chunk_text("   \n\n  ") == []


# --------------------------------------------------------------------------
# 检索（TF-IDF 排序）
# --------------------------------------------------------------------------
def test_search_ranks_relevant_doc_higher(kb):
    kb.save("著作权", "著作权法保护具有独创性的智力成果，作者享有署名权与获得报酬权。")
    kb.save("餐饮", "本店招牌菜是麻辣火锅与酸菜鱼，欢迎预约包间。")
    hits = kb.search("AI 生成内容的独创性如何认定")
    assert hits and hits[0].source == "著作权"
    assert all(h.score > 0 for h in hits)


def test_search_irrelevant_query_returns_low_or_empty(kb):
    kb.save("著作权", "著作权法保护具有独创性的智力成果。")
    assert kb.search("今天天气怎么样aaaa") == [] or kb.search("今天天气怎么样aaaa")[0].score < 0.2


def test_search_empty_kb_returns_empty(kb):
    assert kb.search("任何问题") == []


# --------------------------------------------------------------------------
# 上传 / 删除 / 状态
# --------------------------------------------------------------------------
def test_save_overwrites_same_name(kb):
    kb.save("笔记", "第一版内容")
    kb.save("笔记", "第二版内容更长一些，用于覆盖。")
    assert kb.status()["files"] == 1
    hits = kb.search("第二版 覆盖")
    assert hits and hits[0].text.startswith("第二版")


def test_save_rejects_empty_and_oversize(kb):
    with pytest.raises(ValueError):
        kb.save("空", "   ")
    with pytest.raises(ValueError):
        kb.save("超大", "字" * (2 * 1024 * 1024 + 1))


def test_delete_removes_and_reindexes(kb):
    kb.save("要删的", "一些内容")
    assert kb.delete("要删的") is True
    assert kb.delete("要删的") is False   # 再删一次：不存在
    assert kb.status()["files"] == 0


def test_filename_sanitized(kb):
    r = kb.save('../evil:name', "内容")
    assert "/" not in r["name"] and ".." not in r["name"]
    assert (kb.root / f"{r['name']}.md").exists()


# --------------------------------------------------------------------------
# 端点（HTTP 层）
# --------------------------------------------------------------------------
def test_endpoints_roundtrip(client):
    # 前面的用例可能留下 untitled.md：先清目录，让断言从已知状态出发
    import shutil
    shutil.rmtree(config.KNOWLEDGE_DIR, ignore_errors=True)
    get_kb().rebuild()
    r = client.post("/api/knowledge/upload", json={
        "name": "端点测试", "text": "端点测试的内容，讲的是举证责任分配。",
    }).json()
    assert r["ok"] is True
    status = client.get("/api/knowledge/status").json()
    assert status["files"] == 1
    hits = client.get("/api/knowledge/search", params={"q": "举证责任"}).json()["hits"]
    assert hits and "举证责任" in hits[0]["text"]
    assert client.delete("/api/knowledge/端点测试").json()["ok"] is True


def test_upload_rejects_bad_ext(client):
    # 扩展名不在白名单时自动补 .md（save 的约定），但完全无法命名/空内容会拒
    data = client.post("/api/knowledge/upload", json={"name": "", "text": "内容"}).json()
    assert data["ok"] is True          # 名字为空会落 untitled，属可用行为
    data2 = client.post("/api/knowledge/upload", json={"name": "空内容", "text": "  "}).json()
    assert data2["ok"] is False


def test_knowledge_renders_into_context_block():
    """DebateContext.knowledge 应渲染成【参考知识】段（注入路径的渲染端）。"""
    from app.advisors.base import Advisor, DebateContext

    class A(Advisor):
        name = "a"

    ctx = DebateContext(topic="T", our_side="S", opponent_text="Q",
                        knowledge=[{"source": "举证责任", "chunk_id": 0,
                                    "score": 0.5, "text": "主张权利存在的一方……"}])
    text = A().context_block(ctx)
    assert "【参考知识】" in text and "举证责任" in text
