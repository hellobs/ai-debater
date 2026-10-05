"""辩题库与参谋名册的单元测试。

**全部不调用任何 LLM**：被测的都是本地文件解析与规范化。

辩题内容一律用编造的占位辩题（与 test_retrieval.py / test_statute_text.py 同一约定），
不把真实辩题写进测试 —— 测试要验的是"解析/覆盖/去重"这套机制，
不是某条辩题的内容。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import config

PRESETS = """
topics:
  - id: alpha-topic
    domain: 通用
    title: 甲辩题标题
    side_a: 正方（应当）
    side_b: 反方（不应当）
    opponent_hint: 对方的第一句话。
    note: 争点说明。

  - title: 乙辩题标题
    domain: 测试场景
"""


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """把辩题库两处路径都指到临时目录，测试之间互不干扰。"""
    yaml_path = tmp_path / "topics.yaml"
    json_path = tmp_path / "topics.json"
    monkeypatch.setattr(config, "TOPICS_YAML", str(yaml_path))
    monkeypatch.setattr(config, "TOPICS_JSON", str(json_path))
    return yaml_path, json_path


@pytest.fixture
def client(paths):
    from app.main import app

    yaml_path, _ = paths
    yaml_path.write_text(PRESETS, encoding="utf-8")
    with TestClient(app) as c:
        # 模拟真实 UI：写盘端点要求 CSRF 防护头（main.py csrf_guard）
        c.headers["X-Debater-UI"] = "1"
        yield c


# --------------------------------------------------------------------------
# 读取与规范化
# --------------------------------------------------------------------------
def test_load_presets_from_yaml(paths):
    from app.topics import load_topics

    yaml_path, _ = paths
    yaml_path.write_text(PRESETS, encoding="utf-8")

    topics = load_topics()
    assert [t.title for t in topics] == ["甲辩题标题", "乙辩题标题"]
    assert all(t.source == "preset" for t in topics)
    assert topics[0].side_a == "正方（应当）"
    assert topics[0].opponent_hint == "对方的第一句话。"
    # 没写 domain 时落到默认分组
    assert topics[1].domain == "测试场景"


def test_missing_yaml_yields_empty_not_fallback(paths):
    """库为空就返回空 —— 刻意不内置兜底辩题（兜底等于第二份定义）。"""
    from app.topics import load_topics

    assert load_topics() == []


def test_broken_yaml_yields_empty(paths):
    from app.topics import load_topics

    yaml_path, _ = paths
    yaml_path.write_text("topics: [ 这不是合法 yaml", encoding="utf-8")
    assert load_topics() == []


def test_entry_without_title_is_skipped(paths):
    from app.topics import load_topics

    yaml_path, _ = paths
    yaml_path.write_text(
        "topics:\n  - title: 有效辩题\n  - side_a: 正方\n  - id: x\n    title: '   '\n",
        encoding="utf-8",
    )
    assert [t.title for t in load_topics()] == ["有效辩题"]


def test_auto_id_is_stable_url_safe_and_overwrites(paths):
    """同一标题两次保存 → 同一个 id，覆盖而不是堆重复；且 id 能安全进 URL 路径。"""
    from app.topics import load_topics, save_local_topic

    first = save_local_topic("一条中文辩题标题", side_a="正方")
    second = save_local_topic("一条中文辩题标题", side_a="新的立场")

    assert first.id == second.id
    assert first.id.startswith("local-")
    assert first.id.isascii() and " " not in first.id
    assert len(load_topics()) == 1
    assert load_topics()[0].side_a == "新的立场"


def test_illegal_id_falls_back_to_auto_id(paths):
    from app.topics import save_local_topic

    topic = save_local_topic("辩题", topic_id="含空格 与大写/Bad")
    assert topic.id.startswith("local-")


def test_empty_title_rejected(paths):
    from app.topics import save_local_topic

    with pytest.raises(ValueError):
        save_local_topic("   ")


def test_blank_sides_get_defaults(paths):
    from app.topics import save_local_topic

    topic = save_local_topic("辩题", side_a="", side_b="  ")
    assert (topic.side_a, topic.side_b) == ("正方", "反方")


# --------------------------------------------------------------------------
# 预设与本机的合并
# --------------------------------------------------------------------------
def test_local_overrides_preset_and_keeps_position(paths):
    from app.topics import load_topics, save_local_topic

    yaml_path, _ = paths
    yaml_path.write_text(PRESETS, encoding="utf-8")

    previous = [t.id for t in load_topics()]
    save_local_topic("改写过的一条", topic_id="alpha-topic", side_a="本机立场")

    topics = load_topics()
    assert [t.id for t in topics] == previous        # 位置不动
    assert topics[0].side_a == "本机立场"
    assert topics[0].source == "local"


def test_new_local_topic_appended_last(paths):
    from app.topics import load_topics, save_local_topic

    yaml_path, _ = paths
    yaml_path.write_text(PRESETS, encoding="utf-8")
    save_local_topic("我新加的辩题")

    topics = load_topics()
    assert topics[-1].title == "我新加的辩题"
    assert [t.source for t in topics] == ["preset", "preset", "local"]


def test_local_file_is_written_as_valid_json(paths):
    from app.topics import save_local_topic

    _, json_path = paths
    save_local_topic("落盘检查")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["topics"][0]["title"] == "落盘检查"


def test_delete_only_touches_local(paths):
    from app.topics import delete_local_topic, load_topics, save_local_topic

    yaml_path, _ = paths
    yaml_path.write_text(PRESETS, encoding="utf-8")

    saved = save_local_topic("待删的辩题")
    assert delete_local_topic(saved.id) is True
    assert [t.title for t in load_topics()] == ["甲辩题标题", "乙辩题标题"]

    # 预设不在本机那份里，删不动
    assert delete_local_topic("alpha-topic") is False
    assert len(load_topics()) == 2


def test_corrupt_local_json_does_not_break_presets(paths):
    from app.topics import load_topics

    yaml_path, json_path = paths
    yaml_path.write_text(PRESETS, encoding="utf-8")
    json_path.write_text("{ 半截 json", encoding="utf-8")

    assert len(load_topics()) == 2


# --------------------------------------------------------------------------
# HTTP 接口
# --------------------------------------------------------------------------
def test_topics_endpoint_returns_presets(client):
    data = client.get("/api/topics").json()
    assert data["count"] == 2
    assert data["topics"][0]["id"] == "alpha-topic"
    assert data["topics"][0]["source"] == "preset"


def test_topics_endpoint_save_and_delete(client):
    created = client.post("/api/topics", json={
        "title": "接口存进来的辩题",
        "side_a": "正方（应当）",
        "side_b": "反方（不应当）",
        "opponent_hint": "对方会说：不行。",
    }).json()
    assert created["count"] == 3
    mine = [t for t in created["topics"] if t["source"] == "local"]
    assert len(mine) == 1
    assert mine[0]["side_a"] == "正方（应当）"
    assert mine[0]["domain"] == "我的辩题"      # 从界面存的归到这一组

    removed = client.delete(f"/api/topics/{mine[0]['id']}").json()
    assert removed["ok"] is True
    assert removed["count"] == 2


def test_topics_endpoint_keeps_supplied_domain(client):
    """带上 domain 存 → 原样保留，**不能**被 LOCAL_DOMAIN 顶掉。

    界面「保存为我的辩题」必须把当前辩题的 domain 一起送来：不带它就会落到
    LOCAL_DOMAIN（"我的辩题" → prompt-packs.yaml 映到 general 包），
    一道法学题会在**毫无提示**的情况下换掉整套措辞（legal → general）。
    这条测试盯住后端这一侧：只要前端肯传，后端就不能丢。
    """
    created = client.post("/api/topics", json={
        "title": "带领域的本机辩题",
        "domain": "AI + 法学",
        "side_a": "控方（主张应享有）",
        "side_b": "辩方（主张不应享有）",
    }).json()
    mine = [t for t in created["topics"] if t["source"] == "local"]
    assert len(mine) == 1
    assert mine[0]["domain"] == "AI + 法学"      # 不是 "我的辩题"


def test_topics_endpoint_rejects_blank_title(client):
    resp = client.post("/api/topics", json={"title": "   "})
    assert "error" in resp.json()
    # 被拒的请求不该改动库
    assert client.get("/api/topics").json()["count"] == 2


def test_topics_endpoint_cannot_delete_preset(client):
    data = client.delete("/api/topics/alpha-topic").json()
    assert data["ok"] is False
    assert data["count"] == 2


# --------------------------------------------------------------------------
# 参谋名册：YAML 覆盖生效
# --------------------------------------------------------------------------
ROSTER = """
advisors:
  - name: risk
    enabled: true
    label: 换过名字的风险官
    domain: 法学
  - name: rebutter
    enabled: true
  - name: auditor
    enabled: false
  - name: 不存在的参谋
    enabled: true
"""


def test_roster_yaml_overrides_label_and_domain(tmp_path, monkeypatch):
    from app.advisors import load_roster

    path = tmp_path / "advisors.yaml"
    path.write_text(ROSTER, encoding="utf-8")
    monkeypatch.setattr(config, "ADVISORS_YAML", str(path))

    roster = load_roster()
    # 列表顺序即展示顺序；disabled 的下场；未知名字忽略
    assert [a.name for a in roster] == ["risk", "rebutter"]
    assert roster[0].label == "换过名字的风险官"
    assert roster[0].domain == "法学"
    # 没覆盖的字段保留代码默认值
    assert roster[1].label == "反驳手"
    assert roster[0].meta()["kind"] == "risk"


def test_roster_missing_file_enables_all(tmp_path, monkeypatch):
    from app.advisors import REGISTRY, load_roster

    monkeypatch.setattr(config, "ADVISORS_YAML", str(tmp_path / "nope.yaml"))
    assert [a.name for a in load_roster()] == list(REGISTRY.keys())


def test_roster_all_disabled_returns_empty(tmp_path, monkeypatch):
    """全停用是显式意图 —— 返回空并告警，不偷偷改回全开（那会多花五次调用）。"""
    from app.advisors import load_roster

    path = tmp_path / "advisors.yaml"
    path.write_text(
        "advisors:\n" + "".join(
            f"  - name: {n}\n    enabled: false\n"
            for n in ("rebutter", "questioner", "auditor", "strategist", "risk")
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ADVISORS_YAML", str(path))
    assert load_roster() == []


def test_roster_all_unrecognized_falls_back_to_all(tmp_path, monkeypatch):
    """YAML 能解析但一条都认不出来（名字全写错）→ 回到全开默认值。

    与「显式全停用」是相反处置，所以这条和下面那条要分开断言。
    """
    from app.advisors import REGISTRY, load_roster

    path = tmp_path / "advisors.yaml"
    path.write_text("advisors:\n  - name: 没这个人\n", encoding="utf-8")
    monkeypatch.setattr(config, "ADVISORS_YAML", str(path))
    assert [a.name for a in load_roster()] == list(REGISTRY.keys())
