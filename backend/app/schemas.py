"""对外数据结构（pydantic v2）。

注意：mavis 的 provider 解析结构化输出时，要求模型顶层带 `res` 字段
（`return_type.model_validate(obj).res`），所以所有"给 mavis 用"的输出模型
都必须有 `res`。对外返回给前端的结构不带这个约束。

字段描述为什么必须是**领域中立**的
----------------------------------
`return_type.model_json_schema()` 会被 mavis 塞进 `response_format.json_schema`
**一起发给模型**（`mavisframework/runtime/llm_providers.py`）。所以这里的
`description` 不是给人看的注释，它是提示词的一部分：

    这里写「大前提：所依据的法律规范（法条名称+条款号）」
    → 通用辩题下模型也被要求去找法条。

因此本文件只写**跨领域都成立**的话（"大前提" / "结论" / "三段论" 不是法学专有词），
学科词汇与取值枚举一律交给领域提示词包（`prompts/packs/<包>/tasks/*.txt`）——
「取值见任务说明」指的就是它。把枚举写在这里等于让它压过任务说明，
还会和包里的措辞打架（例如法律包写「法源不稳」、通用包写「依据不稳」）。
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
        description="大前提：所依据的规范、原则或一般性判断。"
        "出处不确切时写「待核验」并在其后简述其内容"
    )
    minor_premise: str = Field(description="小前提：本题事实层面的特征")
    conclusion: str = Field(description="结论：由大小前提推出的我方主张，一句话")


class RebutterOut(BaseModel):
    res: list[Rebuttal] = Field(description="2 条反驳要点，每条都必须填满四个字段")


class QuestionerOut(BaseModel):
    res: list[str] = Field(description="3 个质询问题，每个不超过40字，不加解释")


class AuditFinding(BaseModel):
    fallacy: str = Field(description="谬误类型，如 偷换概念/以偏概全/循环论证/诉诸权威/稻草人")
    quote: str = Field(description="对方原话中最能体现该谬误的片段，不超过30字")
    explain: str = Field(description="一句话说明该谬误所在，不超过60字")


class AuditorOut(BaseModel):
    res: list[AuditFinding] = Field(description="识别出的谬误，最多2条；没有则返回空列表")


class MethodNote(BaseModel):
    opponent_method: str = Field(description="对方主要依赖的方法或衡量尺度（取值见任务说明）")
    opponent_effect: str = Field(description="该方法在对方论证中起了什么作用，一句话")
    our_method: str = Field(description="我方应当主张优先的方法或衡量尺度（取值见任务说明）")
    counter: str = Field(description="为什么我方主张的方法应当优先，一句话")


class StrategistOut(BaseModel):
    res: list[MethodNote] = Field(description="方法/尺度争夺点，最多2条")


class RiskItem(BaseModel):
    risk: str = Field(description="风险点，一句话，不超过40字")
    kind: str = Field(description="风险类型（取值见任务说明）")
    suggestion: str = Field(description="一句话应对建议，不超过40字")


class RiskOut(BaseModel):
    res: list[RiskItem] = Field(description="风险清单，最多3条")


# --------------------------------------------------------------------------
# 对外返回给前端的结构
# --------------------------------------------------------------------------
AdvisorStatus = Literal["ok", "error", "empty", "timeout"]


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
    #: 本轮用的领域提示词包包名（legal / general）。辩题的 domain 决定它，
    #: 但两者不是一回事 —— 界面上要显示的是**实际生效**的那个。
    prompt_pack: str = ""


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
