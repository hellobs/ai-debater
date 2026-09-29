# 阶段 0 结论报告 —— mavis 底座联通与可行性验证

> 日期：2026-09-29 ｜ 环境：Python 3.13.12（托管 venv）｜ mavis v1.3.3（`511dea0`）
> 结论：**采用 PLAN §3.4 的降级方案** —— 只借 mavis 的公开 LLM 工厂，并行编排自建。mavis 一行未改。

---

## 1. 做了什么

| # | 实验 | 目的 |
|---|---|---|
| A | `create_llm_provider(provider="openai")` 经协议桥直连模型 | 验证"底座联通"是否成立 |
| B | 构造 `Agent` 并驱动 `think()` 一步 | 验证 `Agent` 能否被塑造成"参谋" |
| C | 三路参谋（反驳/质询/审计）并行 | 验证降级方案是否可用、延迟是否达标 |

配套产出：`backend/app/llm_bridge.py`（OpenAI ↔ Anthropic 协议桥）、`backend/spikes/*.py`。

---

## 2. 实测数据

### Spike A —— 底座联通：**PASS**

```
is_available = True
latency      = 0.85s
output       = '法律涵摄是将案件事实置于法律规范构成要件之下，以推导出法律效果。'
```

mavis 的 `OpenAIProvider` → 本桥 → Anthropic 协议网关，链路打通，输出为正确的中文法言法语。

### Spike B —— Agent 当参谋：**FAIL（架构性不成立）**

逐步推进的过程，本身就是证据：

| 轮次 | 结果 | 耗时 / 调用数 |
|---|---|---|
| 第 1 次 | 崩：`'>' not supported between 'str' and 'int'` | **64.93s / 12 次**（10 次重试 + 每次 sleep 5s） |
| 修桥：结构化输出 | 前进到 `schedule_daily` 后崩 | 7.47s / 3 次 |
| 修桥：JSON 形状修复 | 日程装配成功 → 崩在 `time_format_cn` | 5.96s / 3 次 |
| 换真 `Timer` | 前进到 `poignancy_event` → 崩在 `tile.events` | 6.97s / 4 次 |
| 补 tile 属性 | 前进到 `percept` → `determining action` → 崩在空 spatial tree（`IndexError`） | 7.08s / 4 次 |

**每一轮修掉一个洞，立刻冒出下一个隐式接口依赖**。这不是实现瑕疵，是框架的形状：

1. `Agent.completion()` 只认框架写死的 `prompt_*` 集合（`wake_up` / `schedule_*` / `determine_*` /
   `describe_*` / `decide_*` / `summarize_*` / `generate_chat` / `reflect_*` / `retrieve_*`），
   **没有"给参谋建议"这一类**。
2. `MAVIS_PROMPT_DIR` 只能替换模板**文本**，替换不了方法集合；占位符由 Python 方法决定。
3. `Agent.think()` 是"日程 → 感知 → 定行动 → 移动 → 计划 → 反思"的**生活仿真管线**，
   产物是行动计划与移动路径，不是建议文本。
4. 要走通它，必须喂**真实的 `maze` + 完整 `spatial.tree` + 可用的日程**——
   而这些与"现场给用户出主意"这件事毫无关系。

### Spike C —— 降级方案：**PASS**

```
--- 反驳手（1.26s）---
1. 著作权法保护的是"智力成果"而非"人"本身，法人作品即非自然人创作却享有著作权，
   可见主体资格可拟制，AI 同理。
2. 若只问"谁是人"，则 AI 生成内容永远无法保护，但法律应回应现实……

--- 质询手（1.34s）---
1. 法人不是人，为何法人作品能享有著作权？
2. 摄影机自动成像，为何照片仍受著作权保护？
3. 用户对 AI 输出有独创性贡献，为何不能享权？

--- 逻辑审计员（1.05s）---
偷换概念：对方将"著作权主体须为自然人"偷换为"只有自然人直接生成才受保护"……

总墙钟 = 1.34s    最慢一路 = 1.34s    串行估算 = 3.65s    并行收益 = 63% 节省
```

**三路并行，总耗时等于最慢的一路**——这正是现场模式需要的形状。输出质量可直接使用。

---

## 3. 顺带修掉的两个真问题（都在桥里，不在 mavis）

1. **mavis 不检查 HTTP 状态码**：它只读 `choices[0].message.content`，出错时若桥返回非 JSON，
   会触发 10 次重试 × `sleep(5)` = **50 秒静默失败**。⇒ 桥必须永远返回合法 JSON 体。
2. **结构化输出必须桥内兜底**：mavis 靠 `response_format`（json_schema）拿结构化结果，
   而 Anthropic 协议没有该字段。若直接丢弃，模型回自然语言 → mavis 解析退化成字符串 →
   `schedule.update(<字符串>)` 直接崩。⇒ 桥要做两件事：
   把 schema 写进系统提示 + **对返回做 JSON 形状修复**（补 `res` 外壳）。
   修完：**64.93s → 5.6s，12 次调用 → 3 次，零失败**。

---

## 4. 结论与架构影响

| 问题 | 结论 |
|---|---|
| mavis 的 LLM 通道能用吗？ | **能**，`create_llm_provider` + 协议桥，零改框架 |
| mavis 的 `Agent` 能当参谋吗？ | **不能**（架构性），理由见 §2 Spike B |
| mavis 在本项目里的定位 | **模型接入层**（+ 将来可选 Timer / checkpoint），不是 Agent 运行时 |
| 并行参谋怎么做 | 我方自建：共享一个 provider + 线程池 `asyncio`/`ThreadPoolExecutor` |
| 现场延迟达标吗？ | 达标。三路并行 1.34s，目标是 < 2s |

**关键设计决定：`mavis_bridge.py` 是唯一接触面。** 全部辩论业务逻辑在 mavis 之外——
这既符合 mavis 自己的契约红线（框架源码禁止业务词汇），也让我们不被它的空间/日程模型绑架。

---

## 5. 下一步

1. 把三路参谋固化成后端模块（`advisors/`）+ FastAPI `POST /api/analyze` + SSE。
2. 前端按参考图取"左设置 + 右结构化结果（三段式可编辑）"的骨架。
3. 阶段 3 台账、阶段 4 检索与引用核验按 PLAN 推进。

> 注：因为协议桥的存在，"有没有 OpenAI 协议通道"**不再是阻塞项**——
> 只要网关是 Anthropic 协议，桥就能把它翻给 mavis。
