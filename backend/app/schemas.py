"""对外数据结构（pydantic v2）。

注意：mavis 的 provider 解析结构化输出时，要求模型顶层带 `res` 字段
（`return_type.model_validate(obj).res`），所以所有"给 mavis 用"的输出模型
都必须有 `res`。对外返回给前端的结构不带这个约束。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# 给 mavis 用的输出模型（顶层必须是 res）
# --------------------------------------------------------------------------
class Rebuttal(BaseModel):
    claim: str = Field(description="反驳要点的主句，一句话，不超过40字")
    major_premise: str = Field(
        description="大前提：所依据的法律规范（法条名称+条款号）。"
        "若不确切知道出处，写「待核验」并在其后简述规范内容"
    )
    minor_premise: str = Field(description="小前提：本题事实层面的特征")
    conclusion: str = Field(description="结论：由大小前提推出的法律效果，一句话")


class RebutterOut(BaseModel):
    res: list[Rebuttal] = Field(description="2 条反驳要点，每条都必须是完整的涵摄三段式")


class QuestionerOut(BaseModel):
    res: list[str] = Field(description="3 个质询问题，每个不超过40字，不加解释")


class AuditFinding(BaseModel):
    fallacy: str = Field(description="谬误类型，如 偷换概念/以偏概全/循环论证/诉诸权威/稻草人")
    quote: str = Field(description="对方原话中最能体现该谬误的片段，不超过30字")
    explain: str = Field(description="一句话说明该谬误所在，不超过60字")


class AuditorOut(BaseModel):
    res: list[AuditFinding] = Field(description="识别出的谬误，最多2条；没有则返回空列表")


# --------------------------------------------------------------------------
# 对外返回给前端的结构
# --------------------------------------------------------------------------
AdvisorStatus = Literal["ok", "error", "empty"]


class AdvisorResult(BaseModel):
    advisor: str
    label: str
    status: AdvisorStatus
    latency_s: float
    payload: Any = None                 # 结构化结果（各参谋形状不同）
    raw: Optional[str] = None           # 原始文本（结构化失败时的兜底）
    error: Optional[str] = None
    kind: str = "text"                  # "rebuttal" | "questions" | "audit" | "text"


class AnalyzeResponse(BaseModel):
    session_id: str
    topic: str
    our_side: str
    opponent_text: str
    total_latency_s: float
    results: list[AdvisorResult]
    our_ledger: list[str] = []      # 本次注入提示词的我方已主张（供前端核对）


def jsonable(obj: Any) -> Any:
    """把 pydantic 模型 / 嵌套结构摊平成可 JSON 序列化的普通数据。

    为什么需要：mavis 的结构化输出返回的是**模型的 `.res`**，
    对 `list[Rebuttal]` 而言就是一堆 pydantic 实例——
    直接 json.dumps 会抛 `TypeError: Object of type Rebuttal is not JSON serializable`。
    在源头摊平，落库与出参就都干净了。
    """
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (list, tuple)):
        return [jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    return obj
