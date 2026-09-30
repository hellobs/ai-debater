"""领域提示词包：选包规则 + "领域措辞只有一份"的守门测试。

这一组守两件事：

1. **选包是可预期的**：精确命中、未认领落默认包、配置坏了也只降级不崩。
   "猜"在这里是被禁止的 —— 猜错时提示词会安静地换成另一套框架。
2. **法学措辞不得从别处漏回来**。`schemas.py` 的字段描述会被 mavis 塞进
   `response_format.json_schema` 一起发给模型（见该模块 docstring），
   它和提示词包是**两条独立进入模型的路**。只改提示词、不管 schema，
   通用辩题下模型照样会被要求去找法条 —— 而且没人体检得出来。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app import config as app_config
from app import prompt_packs
from app.schemas import (
    MethodNote,
    RebutterOut,
    RiskItem,
    StrategistOut,
)

#: 判定"这是法学框架"的词。只收会改变模型视角的，不收三段论的通用词
#: （大前提 / 小前提 / 结论 在任何领域的论证里都成立）。
LEGAL_WORDS = ("法条", "法源", "法律涵摄", "法律效果", "法律解释", "法理", "判例", "合宪性")


# ==========================================================================
# 1. 选包规则
# ==========================================================================
def test_pack_for_domain_hits_and_falls_back():
    default = prompt_packs.default_pack()
    assert prompt_packs.pack_for_domain("AI + 法学") == "legal"
    # 没认领的、空的、只有空白的，一律落默认包（不猜）
    for domain in (None, "", "   ", "量子力学"):
        assert prompt_packs.pack_for_domain(domain) == default


def test_legal_topics_actually_get_the_legal_pack():
    """预设里的法学辩题必须真的落到 legal 包。

    这条错了的症状最隐蔽：法学辩题静默地走了通用措辞 ——
    输出照样通顺，只是不再讲法律涵摄了。
    （用"领域名里带'法'"当判据，够用且写死在测试里，不动生产代码。）
    """
    import yaml

    # 注意：conftest 把 TOPICS_YAML 指到了空的 .testdata，所以这里读**入仓的**
    # 那份预设辩题库 —— 要校验的正是"仓库里配的辩题落在哪个包"。
    presets = app_config.ROOT / "configs" / "topics.yaml"
    topics = (yaml.safe_load(presets.read_text(encoding="utf-8")) or {}).get("topics") or []
    legal = [t for t in topics if isinstance(t, dict) and "法" in str(t.get("domain") or "")]
    assert legal, "预设辩题里居然没有法学辩题，测试前提不成立"
    for t in legal:
        assert prompt_packs.pack_for_domain(t["domain"]) == "legal", t["title"]


def test_unclaimed_domain_falls_back_to_default_pack():
    """没人认领的 domain 落到兜底包 —— 兜底这条路径不能只活在文档里。

    为什么不再从预设库里挑"非法学辩题"当对照组：预设库已收敛为「AI + 法学」
    单一领域（见 configs/topics.yaml），拿生产配置当测试数据的前提是脆弱的 ——
    改一次题库就会挂，而它要验的其实是"精确匹配 + 兜底"这条映射规则本身。
    构造一个没人认领的 domain 就够了，也不必再要求题库必须是混合的。
    """
    default = prompt_packs.default_pack()
    for domain in ("通用", "", "没人认领的领域"):
        assert prompt_packs.pack_for_domain(domain) == default, domain
    # 首尾空白会被吃掉再匹配：yaml 里手写的 domain 常带空格，不该因此落到兜底包
    assert prompt_packs.pack_for_domain("  AI + 法学  ") == "legal"


def test_broken_config_degrades_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "PROMPT_PACKS_YAML", str(tmp_path / "nope.yaml"))
    prompt_packs.reset_cache()
    try:
        assert prompt_packs.all_packs() == [prompt_packs.FALLBACK_PACK]
        assert prompt_packs.pack_for_domain("AI + 法学") == prompt_packs.FALLBACK_PACK
        assert prompt_packs.describe()["default"] == prompt_packs.FALLBACK_PACK
    finally:
        prompt_packs.reset_cache()


def test_default_pointing_at_a_missing_pack_is_repaired(tmp_path, monkeypatch):
    """default 写错时用第一个包，而不是让整个服务起不来。"""
    cfg = tmp_path / "packs.yaml"
    cfg.write_text(
        "default: 不存在的包\npacks:\n  - name: general\n    label: 通用\n    domains: [通用]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "PROMPT_PACKS_YAML", str(cfg))
    prompt_packs.reset_cache()
    try:
        assert prompt_packs.default_pack() == "general"
        assert prompt_packs.pack_for_domain("谁也不是") == "general"
    finally:
        prompt_packs.reset_cache()


def test_label_of_unknown_pack_returns_the_name():
    """名字本身就是未知值时原样返回 —— 界面上不该出现空白标签。"""
    assert prompt_packs.label_of("legal")
    assert prompt_packs.label_of("查无此包") == "查无此包"


def test_describe_points_at_the_packs_directory():
    assert prompt_packs.describe()["dir"].replace("\\", "/").endswith("prompts/packs")


# ==========================================================================
# 2. 领域措辞只活在包里
# ==========================================================================
def test_output_schema_descriptions_carry_no_legal_framing():
    """发给模型的 json_schema 描述里不许有法学措辞。

    这些描述和提示词是**两条独立的路**，都会到达模型。漏改这里，
    通用辩题下模型照样被要求「大前提 = 法律规范」。
    """
    for model in (RebutterOut, StrategistOut):
        blob = json.dumps(model.model_json_schema(), ensure_ascii=False)
        hit = [w for w in LEGAL_WORDS if w in blob]
        assert not hit, f"{model.__name__} 的 schema 描述里还有法学措辞：{hit}"


def test_output_schema_keeps_the_field_names_the_frontend_reads():
    """中立化只动 description，不动字段名 —— 字段名是前端与台账的契约。"""
    assert set(MethodNote.model_fields) == {
        "opponent_method", "opponent_effect", "our_method", "counter"
    }
    assert set(RiskItem.model_fields) == {"risk", "kind", "suggestion"}
    assert set(RebutterOut.model_fields) == {"res"}


def test_every_pack_has_the_same_template_names():
    """一个包缺哪一路，就有一类辩题会少一段角色指令 —— 启动自检会拦，
    这里再静态确认一次，免得配置文件写了个不存在的包名（那样目录全缺）。"""
    root = pathlib.Path(app_config.PROMPT_DIR) / "packs"
    per_pack: dict[str, set[str]] = {}
    for pack in prompt_packs.all_packs():
        per_pack[pack] = {
            p.relative_to(root / pack).as_posix() for p in (root / pack).rglob("*.txt")
        }
        assert per_pack[pack], f"提示词包 {pack!r} 的目录是空的：{root / pack}"
    reference = per_pack[prompt_packs.default_pack()]
    for pack, names in per_pack.items():
        assert names == reference, (
            f"包 {pack!r} 与默认包的文件集合不一致，缺 {sorted(reference - names)}，"
            f"多 {sorted(names - reference)}"
        )


@pytest.mark.parametrize("pack", prompt_packs.all_packs())
def test_each_pack_renders_all_five_advisors(pack):
    """每一路的角色指令与任务都能在这个包里渲染出来（未定义占位符会抛 KeyError）。"""
    from app.advisors import REGISTRY

    for advisor in REGISTRY.values():
        inst = advisor()
        assert inst.role_directive(pack).strip()
        assert inst.task_block(pack).strip()
