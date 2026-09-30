"""论证策略师：争夺"拿什么尺度衡量这件事"。

为什么需要这一路（来自交接文档第 3.4 节）：
「当法条文义有歧义时，辩论的实质就是争夺解释方法的适用优先性。」
对方用文义解释、我方主张目的解释优先 —— 这是最容易出彩、也最容易被忽略的战场。
普通辩论 Agent 不会专门去争这个。

这个洞察本身与领域无关：任何辩题的深层分歧都是"用哪把尺子量"。所以这一路的
**身份是中立的**（`label = 论证策略师`），尺子的名字由领域提示词包提供：

    legal 包    文义 / 体系 / 目的 / 历史 / 合宪性解释
    general 包  事实认定 / 概念界定 / 价值排序 / 后果权衡

这也是它此前在 `configs/advisors.yaml` 里被标成「法学专用」的那个 ⚠️ 的由来 ——
标记解除了：它现在在任何领域的辩题上都上场，只是措辞跟着包走。

角色指令与任务说明在 `prompts/packs/<包>/roles/strategist.txt` 与 `.../tasks/strategist.txt`。
"""
from __future__ import annotations

from .base import Advisor
from ..schemas import StrategistOut


class StrategistAdvisor(Advisor):
    name = "strategist"
    label = "论证策略师"
    kind = "strategy"
    output_model = StrategistOut
