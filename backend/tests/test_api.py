"""API 层端到端测试。

用 FastAPI TestClient 打真实路由，数据库指向临时文件（见 conftest.py）。

**全部不调用任何 LLM**：被测的都是本地端点
（会话 / 台账 / 检索 / 引用核验 / 导出 / 指标），
唯一涉及模型的一致性检测只测"没有台账时直接返回空"这条零调用路径。
"""
from __future__ import annotations

import io
import json

import pytest

from tests.conftest import TESTDATA

SAMPLE_OPPONENT = "著作权法只保护自然人的智力成果，AI 不是人，所以 AI 生成内容不应享有著作权。"


@pytest.fixture(scope="module")
def session_id(client) -> str:
    resp = client.post("/api/session", json={
        "topic": "AI 生成内容是否应享有著作权",
        "our_side": "控方（主张应享有）",
    })
    assert resp.status_code == 200
    return resp.json()["session"]["id"]


@pytest.fixture(scope="module")
def corpus_ready(client):
    """写入一份临时语料并热加载（用编造的假法名，不写真实法条）。"""
    corpus = TESTDATA / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "laws.json").write_text(
        json.dumps({"《测试法》": {"第三条": "本法所称之成果，指具有独创性者。"}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    client.get("/api/retrieval?reload=true")
    yield


# --------------------------------------------------------------------------
# 健康检查
# --------------------------------------------------------------------------
def test_health_lists_advisors(client):
    data = client.get("/api/health").json()
    assert data["ok"] is True
    names = [a["name"] for a in data["advisors"]]
    assert names == ["rebutter", "questioner", "auditor", "strategist", "risk"]
    assert "budget_s" in data
    # 前端靠这几个字段渲染参谋列，不再自己抄一份名册
    assert data["brand"]
    assert all({"label", "kind", "domain"} <= set(a) for a in data["advisors"])
    kinds = {a["name"]: a["kind"] for a in data["advisors"]}
    assert kinds["rebutter"] == "rebuttal"
    # 领域差异**不再**靠"这一路要不要上场"表达：五路都留空（任何辩题都上场），
    # 换领域框架是提示词包的事（见 test_prompt_packs.py）。
    # 这条曾经断言 strategist == "法学" —— 那正是被解耦掉的那层耦合。
    domains = {a["name"]: a["domain"] for a in data["advisors"]}
    assert set(domains.values()) == {""}
    # 提示词包是新的自述面
    assert data["mavis"]["packs"]["default"] == "general"
    assert {p["name"] for p in data["mavis"]["packs"]["packs"]} >= {"general", "legal"}


def test_topics_endpoint_is_reachable_without_corpus(client):
    """辩题库接口不依赖语料也不依赖模型，应当永远可用（哪怕库是空的）。"""
    data = client.get("/api/topics").json()
    assert isinstance(data["topics"], list)
    assert data["count"] == len(data["topics"])


def test_domain_from_the_request_reaches_the_prompt_pack(client):
    """`domain` 一路走到提示词包，且**只**影响包的选择。

    这条不走模型（只调 `_prepare`），所以能进常规测试：
    它守的是"领域信息不会在 API 层被丢掉"—— 丢了的话，
    法学辩题会静默地用通用措辞，而界面上一切正常。
    """
    from app.main import _prepare

    ctx, sid = _prepare(
        None, "AI 生成内容是否应享有著作权", "控方（主张应享有）", SAMPLE_OPPONENT,
        "AI + 法学",
    )
    assert ctx.domain == "AI + 法学"
    assert ctx.pack == "legal"
    # 自由输入（没有领域）落到默认包，不是"报错"也不是"猜一个"
    ctx2, _ = _prepare(None, "随便一个辩题", "正方", "对方说完了。")
    assert ctx2.domain == "" and ctx2.pack == "general"
    # domain 不是落库字段：会话快照里不该多出一个 domain 列
    assert "domain" not in (client.get(f"/api/session/{sid}").json()["session"])


def test_health_self_reports_the_mavis_dependency(client):
    """"底座是 mavis"要能被程序读到，不能只活在 README 里。"""
    mavis = client.get("/api/health").json()["mavis"]
    assert mavis["framework"] == "mavis"
    assert mavis["based_on"] == "mavisframework"   # 基座关系也要能被程序读到
    assert mavis["version"]
    assert mavis["readonly"] is True          # 只读依赖，结论才对框架本身成立
    assert mavis["contact"].endswith("mavis_bridge.py")
    assert [s["key"] for s in mavis["surfaces"]] == ["provider", "prompt", "plugin"]
    assert mavis["prompts"]["templates"] > 0
    # 挂在 mavis 插件总线上的观察者，必须是真挂载的 Plugin 子类
    assert mavis["observers"] == ["ledger", "stream", "metrics"]


def test_openapi_surface_has_no_llm_probe(client):
    """确保没有留下会误触模型调用的调试端点。"""
    paths = client.get("/openapi.json").json()["paths"]
    for p in paths:
        assert "debug" not in p and "echo" not in p


# --------------------------------------------------------------------------
# 会话与台账
# --------------------------------------------------------------------------
def test_session_roundtrip(client, session_id):
    data = client.get(f"/api/session/{session_id}").json()
    assert data["session"]["id"] == session_id
    assert data["cards"] == []


def test_unknown_session_returns_404(client):
    """不存在的会话必须走错误码，不能是 200 + `{"error": ...}`。

    200 会让只看状态码的调用方（脚本、前端的 `res.ok`）把失败当成功 ——
    项目自己已在 `patch_card` 与导出接口上修过这个反模式，这里把剩下的补齐。
    """
    resp = client.get("/api/session/deadbeef0000")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "session not found"


def test_card_lifecycle(client, session_id):
    created = client.post(f"/api/session/{session_id}/cards", json={
        "claim": "著作权法保护的是智力成果的表达",
        "major_premise": "《测试法》第三条",
        "source": "test",
    }).json()
    card_id = created["card"]["id"]
    assert len(created["cards"]) == 1

    patched = client.patch(f"/api/cards/{card_id}", json={"status": "weakened"}).json()
    assert patched["ok"] is True

    cards = client.get(f"/api/session/{session_id}").json()["cards"]
    assert cards[0]["status"] == "weakened"

    assert client.delete(f"/api/cards/{card_id}").json()["ok"] is True
    assert client.get(f"/api/session/{session_id}").json()["cards"] == []


def test_card_invalid_status_is_rejected(client, session_id):
    created = client.post(f"/api/session/{session_id}/cards", json={"claim": "X"}).json()
    card_id = created["card"]["id"]
    resp = client.patch(f"/api/cards/{card_id}", json={"status": "瞎写"})
    # 必须报错码：早先返回 200 + body 里的 error，只看状态码的调用方会当成改成功
    assert resp.status_code == 400
    assert "status" in resp.text
    client.delete(f"/api/cards/{card_id}")


def test_consistency_without_cards_costs_nothing(client, session_id):
    """没有台账时一致性检测直接返回空——这条路径不调用模型。"""
    resp = client.post(f"/api/session/{session_id}/check-consistency",
                       json={"claims": ["任意主张"]}).json()
    assert resp["conflicts"] == []


# --------------------------------------------------------------------------
# 检索与引用核验
# --------------------------------------------------------------------------
def test_retrieval_status(client, corpus_ready):
    data = client.get("/api/retrieval").json()
    assert data["available"] is True
    assert data["laws"] == 1 and data["articles"] == 1


def test_verify_citations_three_states(client, corpus_ready, session_id):
    resp = client.post(f"/api/session/{session_id}/verify-citations", json={
        "texts": [
            "依《测试法》第三条。",
            "依《测试法》第九十九条。",
            "依《不存在法》第一条。",
        ]
    }).json()
    assert resp["total"] == 3
    statuses = sorted(i["status"] for i in resp["items"])
    assert statuses == ["dubious", "unverified", "verified"]
    verified = next(i for i in resp["items"] if i["status"] == "verified")
    assert "独创性" in verified["evidence"]


def test_verify_citations_on_empty_session_texts(client, corpus_ready, session_id):
    """该会话没有参谋产出时应返回 0 条，而不是报错。"""
    resp = client.post(f"/api/session/{session_id}/verify-citations", json={
        "texts": ["没有引用的普通句子。"]
    }).json()
    assert resp["total"] == 0


def test_verify_citations_separates_existence_from_content(client, corpus_ready, session_id):
    """条款真实存在、但模型引述的内容是编的 —— 两件事要分开报。

    旧版只看条款号，这种幻觉会被判成「已核验」并一路带到导出报告里。
    """
    resp = client.post(f"/api/session/{session_id}/verify-citations", json={
        "texts": ["《测试法》第三条：AI 生成的内容一律享有著作权，因为 AI 是作者。"]
    }).json()
    item = resp["items"][0]
    assert item["status"] == "verified"        # 存在性：这一条确实在语料里
    assert item["content_ok"] is False         # 一致性：但引述对不上
    assert item["claimed"]                     # 模型原话要留着，人才看得见差在哪
    assert resp["content_suspect"] == 1
    assert resp["match_low"] > 0               # 阈值由后端下发，前端不抄一份


# --------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------
def test_metrics_shape(client):
    data = client.get("/api/metrics").json()
    assert "budget_s" in data
    assert isinstance(data["advisors"], dict)


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
def test_export_markdown_headers(client, session_id):
    resp = client.get(f"/api/session/{session_id}/export.md")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "text/markdown" in resp.headers["content-type"]
    assert "# 辩论参谋复盘" in resp.text


def test_export_docx_is_valid_ooxml(client, session_id):
    resp = client.get(f"/api/session/{session_id}/export.docx")
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"          # OOXML 就是 zip
    assert "wordprocessingml" in resp.headers["content-type"]


def test_export_html_is_print_ready(client, session_id):
    resp = client.get(f"/api/session/{session_id}/export.html")
    assert resp.status_code == 200
    assert "window.print()" in resp.text
    assert "@media print" in resp.text


def test_export_unknown_session(client):
    # 三个导出端点都必须回 404：md/docx 曾以 200 + JSON 报错体交付，
    # 前端 <a href> 下载会存下扩展名为 .md/.docx 的假文件。
    assert client.get("/api/session/deadbeef0000/export.html").status_code == 404
    assert client.get("/api/session/deadbeef0000/export.md").status_code == 404
    assert client.get("/api/session/deadbeef0000/export.docx").status_code == 404


def test_exports_credit_the_dependency(client, session_id):
    """交付物里要署名基座 —— 复盘报告会被交出去，读者有权知道基础设施来自哪。

    不仅写"用了什么"，还要写清**基座关系**：本项目基于该框架开发，而非只调用过一次。
    """
    md = client.get(f"/api/session/{session_id}/export.md").text
    assert "mavis" in md and "只读依赖" in md
    assert "基于" in md and "开发" in md
    assert "底座" in client.get(f"/api/session/{session_id}/export.html").text


def test_exports_carry_no_domain_specific_wording(client, session_id):
    """导出是**平台级**交付物，措辞必须与辩题领域无关。

    守的是一次真实泄漏：三个出口的「使用提示」里写死了
    「标注「待核验」的**法源**引用尚未经过回链核验，**上庭前**请自行确认」，
    于是每一份**通用**辩题的复盘都带着法庭措辞。

    `session_id` 这条会话**没有任何参谋产出**，所以渲染出来的正文只可能是
    "固定文案"那部分 —— 正是这里要查的。参谋产出里的措辞由模型负责，不在此断言。
    源码级守卫（扫全部字符串字面量）在 `tests/test_export.py`。
    """
    from docx import Document

    def _docx_text(raw: bytes) -> str:
        return "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)

    bodies = {
        "md": client.get(f"/api/session/{session_id}/export.md").text,
        "html": client.get(f"/api/session/{session_id}/export.html").text,
        "docx": _docx_text(client.get(f"/api/session/{session_id}/export.docx").content),
    }

    for name, text in bodies.items():
        hits = [w for w in ("法源", "上庭", "法庭", "法条", "法律涵摄", "解释方法")
                if w in text]
        assert not hits, f"{name} 导出里出现领域措辞：{hits}"

    # 正向：中立的提示句三个出口都得有（不能靠"整段删掉"来通过）
    from app.export import report as report_mod
    for name, text in bodies.items():
        assert "尚未经过回链核验" in text, f"{name} 缺少中立的核验提示句"
    assert report_mod.NOTE_UNVERIFIED


import os  # noqa: E402
import sqlite3  # noqa: E402


def test_delete_session_cascades(client):
    """删一条会话要把它下面的卡一起清掉。

    这条测试补的是体检发现的老问题：**台账只会增** —— 后端既没有 DELETE /api/session/{id}、
    界面里也没有会话列表，于是自己打过的辩题与对方发言原文一直躺在 SQLite 里，用户删不掉。
    自己建会话再删，不去动 module 级 fixture 共享的那条。
    """
    created = client.post("/api/session", json={
        "topic": "体检：删会话要级联", "our_side": "yes", "opponent_text": "对方说了一句",
    }).json()
    sid = created["session"]["id"]

    client.post(f"/api/session/{sid}/cards", json={"claim": "体检造的卡"})

    db = os.environ.get("LEDGER_DB")
    assert db, "conftest 应该把 LEDGER_DB 指到临时库"

    def cards_count():
        conn = sqlite3.connect(db)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM cards WHERE session_id=?", (sid,)
            ).fetchone()[0]
        finally:
            conn.close()

    assert cards_count() == 1
    resp = client.delete(f"/api/session/{sid}")
    assert resp.json()["ok"] is True
    assert cards_count() == 0, "卡没跟着会话一起删 —— 台账里会留下孤儿行"
    assert client.get(f"/api/session/{sid}").status_code == 404
