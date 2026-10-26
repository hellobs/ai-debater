"""自动辩论流程构建与提示词组装测试（0 消耗——不打真实上游）。"""
from __future__ import annotations

from app.prep_debate import PER_STAGE, build_flow, build_turn_prompt


def test_flow_counts_and_order():
    """rounds=3 → 6 个固定环节 + 6 条自由辩论 + 2 条结辩 = 14；反方四辩先于正方。"""
    flow = build_flow(3)
    assert len(flow) == 14
    stages = [s["stage"] for s in flow]
    assert stages[:6] == ["立论陈词", "立论陈词", "驳论反驳", "驳论反驳",
                          "质询与小结", "质询与小结"]
    assert stages[-2:] == ["结辩陈词", "结辩陈词"]
    # 反方四辩先于正方四辩（标准赛制）
    assert flow[-2]["side"] == "con" and flow[-1]["side"] == "pro"
    # 自由辩论正反交替
    free = [s for s in flow if s.get("free")]
    assert len(free) == 6
    assert [f["side"] for f in free] == ["pro", "con"] * 3


def test_flow_rounds_clamped():
    # 6 固定环节 + rounds*2 自由辩论 + 2 结辩
    assert len(build_flow(0)) == 12    # 下限 2 轮
    assert len(build_flow(9)) == 18    # 上限 5 轮


def test_turn_prompt_carries_stage_requirement_and_transcript():
    flow = build_flow(2)
    transcript = [
        {"stage": "立论陈词", "side": "pro", "speaker": "正方一辩", "text": "正方立论正文。"},
    ]
    prompt = build_turn_prompt("测试辩题", flow[1], transcript)
    # 反方一辩的立论陈词：带环节字数要求 + 已有实录（正方立论）
    assert "立论陈词" in prompt and "280" in prompt
    assert "正方一辩" in prompt and "正方立论正文。" in prompt
    # 环节字数要求全部有定义（五个 stage 全覆盖）
    for stage in {"立论陈词", "驳论反驳", "质询与小结", "自由辩论", "结辩陈词"}:
        assert stage in PER_STAGE
    # 自由辩论步骤带「·第N轮」后缀：提示词查表必须回退到基础环节名
    # （否则 KeyError → SSE 在自由辩论段整体断流——实测咬人）
    free = build_flow(2)[6]
    prompt = build_turn_prompt("T", free, [])
    assert "自由辩论" in prompt and "130" in prompt
