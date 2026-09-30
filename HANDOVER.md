# 通用辩手 AI 参谋台 —— 项目交接文档

> **文档版本**：v3.4 ｜ 最后更新：2026-09-30
> **基座关系**：本项目**基于 [`mavisframework`](https://github.com/hellobs/mavis) v1.3.3 开发**，
> 该框架以只读依赖接入、一行未改。此事实在代码中的唯一来源是 `mavis_bridge.BASED_ON`
> 与 `mavis_bridge.declaration()`；README、`/api/health` 与导出报告的表述均由它派生。
> **定位**：**通用辩手平台**，「AI + 法学」是它的落地场景之一（见 §1、§3 决策 13）
> **交接对象**：接手开发的 AI / 工程师（**未参与原始讨论**，因此背景、决策、架构、
> 已验证结论、已知坑与待确认事项在此完整交代）
> **仓库**：`git@github.com:hellobs/ai-debater.git`（注意拼写是 **ai-debater**，
> 本地目录名是 `ai-debator`，差一个字母，属正常）
> **当前 HEAD**：见 `git log -1`

---

## 0. 先读这五份

| 文档 | 作用 |
|---|---|
| **本文** | 交接全景：背景 / 决策 / 架构 / 坑 / 待办 |
| [`docs/decision-log.md`](docs/decision-log.md) | **决策与踩坑日志**——为什么这么定、踩过哪些坑 |
| [`PLAN.md`](PLAN.md) | 实施计划 v2.0，含分阶段路线与每个阶段的验收标准 |
| [`docs/spike-0-report.md`](docs/spike-0-report.md) | 阶段 0 实测报告——**决定架构走向的关键证据** |
| [`docs/mavis-gap-report.md`](docs/mavis-gap-report.md) | **mavis v1.3.3 适用性评估**（技术报告体）：可用三面、不适用半边、7 处缺口（G1–G7）与 4 条接线注意（N1–N4），含严重度分级、局限与复现命令 |

> 🚪 **第一次接手**：先看 [`CONTRIBUTING.md`](CONTRIBUTING.md)。它只讲两件事 ——
> **按什么顺序读文档**，以及**七条会把项目改坏的硬约束**（每条都注明了"谁在守"）。
> 读完再回到本文，效率高得多。

> ⚠️ **`.workbuddy/` 目录已在 `.gitignore` 中排除，换机器 clone 下来不会有它。**
> 开发过程中写在里面的记忆文件**不随仓库走**，因此其中的关键内容已固化到
> [`docs/decision-log.md`](docs/decision-log.md)。请以那份为准。

---

## 1. 项目概述

**一个现场实时参谋台。** 使用者处于辩论现场，对方陈述结束后，系统**并行**调度五路 AI 参谋，
各自产出一路建议 —— 反驳要点、质询问题、逻辑谬误指认、衡量尺度之争、风险提示 ——
**是否采纳由使用者判断**。

⚠️ **本系统不是 AI 对 AI 互搏，也不是裁判打分系统。** 全部 Agent 与使用者同阵营。

**平台定位为「通用辩手参谋台」**，「AI + 法学」是其**落地场景之一**，而非其定义。
辩题带 `domain` 字段作场景标注，**它唯一的用途是选领域提示词包**（见 §3 决策 14 与 §7）。
架构中不存在将法学写死的位置（详见 §7 与 §13）。

---

## 2. 产品定义的沿革（重要：勿回退）

初始交接文档所述方案为「正反方 AI 自动互搏 + 裁判打分」。开发中途，用户作出关键澄清：

> **「我这个多 Agent 是同时为我出主意的」**

据此，产品**整体重新定义**（PLAN v1.0 → v2.0；v1.0 全文保留于提交 `871b0a5`）：

| 维度 | 结论 |
|---|---|
| 对抗关系 | **不对抗**。全部 Agent 构成**参谋团**，与使用者同阵营 |
| 决策主体 | **使用者**。AI 仅产出建议，不代替上台、不代替定稿 |
| 主场景 | **现场辅助**（而非备赛训练） |
| 多 Agent 的意义 | **并行多视角**，而非多轮相互说服 |

该定义移除了原方案中最复杂的若干部分：赛制状态机、发言权交替、胜负判定、Elo。
**因无回合交战，故不存在"谁该发言""谁获胜"的问题** —— 这是整个架构得以轻量的原因。

---

## 3. 已确认决策（用户已拍板，不要重新讨论）

| # | 维度 | 决策 |
|---|---|---|
| 1 | 产品形态 | 多 Agent 并行**参谋团**给用户出主意 |
| 2 | 基座框架 | 本项目**基于 [`mavisframework`](https://github.com/hellobs/mavis) v1.3.3 开发**（`github.com/hellobs/mavis`）——**只读依赖，一行不改** |
| 3 | 模型 | `deepseek-chat`（单一型号，不按角色分模型） |
| 4 | 现场输入 | **先做文字输入，语音转写（ASR）后置** |
| 5 | 参谋团 | **5 路**：反驳手、质询手、逻辑审计员、**论证策略师**、风险提示员（策略师原名「解释方法策略师」，随领域解耦改名，见决策 14） |
| 6 | 检索 | 真实检索通道**未定**；已做本地语料检索 + 引用回链核验 |
| 7 | 部署 | 先本地跑；队友也要用；**不做登录** |
| 8 | 设备 | **笔记本浏览器**（桌面优先，不做移动端适配） |
| 9 | 导出 | **需要**（Word / PDF / Markdown） |
| 10 | 辩题库 | 先轻，结构上预留（**已落地为 `configs/topics.yaml` + `data/topics.json`**） |
| 11 | 学科方向 | **未确定 / 可能多方向** → 论证骨架保持中性，不写死民法或刑法 |
| 12 | 赛制 | **暂无** → 不做赛制状态机 |
| 13 | 平台定位 | **通用辩手平台**，「AI + 法学」只是**最终落地场景** —— 别把法学写进品牌与架构 |
| 14 | 领域措辞 | **领域提示词包**：`prompts/packs/<包>/`（`legal` / `general`），辩题的 `domain` 精确匹配选包；未认领或自由输入落默认包（`general`）。取"结构化"路线而非"把法学词全局换成中立词"——后者会改掉法学场景的输出风格，前者让两套措辞各留在自己包里 |

---

## 4. 完成度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | mavis 底座联通 + 可行性验证（spike） | ✅ 已完成（含关键结论，见 §6） |
| 1–2 | 三路参谋 → **扩至五路** + 后端 API + 前端界面 | ✅ 已完成 |
| 3 | 论点台账 + 立场一致性（两道闸） | ✅ 已完成 |
| 4 | 检索与引用核验 | 🟡 **本地部分完成**；真实检索通道待接（**阻塞：需用户给通道**） |
| 5 | 导出（MD/Word/PDF）+ 现场保障（预算/仪表/断线恢复） | ✅ 已完成 |
| 6 · 附 | 回归测试与评估框架 | ✅ 已完成 |
| 7 | 语音实时转写（ASR） | ⏸ **阻塞：需用户选 ASR 方案** |
| 8 · 附 | 辩题库配置化 + 参谋名册单一来源 + 品牌去法学化 | ✅ 已完成 |
| 9 · 附 | **mavis 基础设施半边用满**：提示词模板层 + provider 全参数 + 插件总线 | ✅ 已完成（缺口报告见 `docs/mavis-gap-report.md`） |
| 10 · 附 | mavis **可见性**（`/api/health` 自述 + 导出报告署名）+ 引用核验的**引述内容比对** | ✅ 已完成（见 §6.5 末段与 §9.3） |
| 11 · 附 | **基座关系显式化** + 文档语体转为技术报告体 | ✅ 已完成（单一句式 `mavis_bridge.declaration()`，README / `/api/health` / 导出报告同源） |
| 12 · 附 | **缺口报告的证据可机器复核**：探针支持 `--json`，新增 N1/N4 探针，一致性测试守住结论 | ✅ 已完成（`tests/test_mavis_gap_report.py`） |
| 13 · 附 | **提示词层的领域解耦**：领域提示词包 + domain 贯通 + schema 描述中立化 | ✅ 已完成（**法学包逐字节零回归**；换包实测见 §13 第 3 条 —— 已证明"换包改变产出"，**未证明"通用包更好"**） |

**规模不在此写死**（源文件数写过一次"约 77 个"，很快就对不上了）：要数字当场算 ——
`git ls-files | wc -l` 看受控文件数，`cd backend && python -m pytest` 看测试数与结果
（当前全绿，0 API 消耗）。提交历史见 §14。

---

## 5. 架构

```
┌──────────────────── 前端（React + Vite + TS，桌面优先） ────────────────────┐
│ 设置面板(辩题/立场/对方发言/时间预算/服务状态) │ N 列参谋建议(可直接编辑)     │
│ 我方台账 │ 现场仪表 │ 引用核验 │ 导出(MD/Word/PDF)                        │
└──────────────────────────────┬─────────────────────────────────────────────┘
                    SSE 推送 ↑  │  ↓ POST /api/analyze
┌──────────────────── 我方后端（FastAPI，业务层） ───────────────────────────┐
│ 编排器(orchestrator) · 参谋团(advisors) · 台账(ledger) · 引用核验(retrieval)│
│ 一致性检测(consistency) · 导出(export) · 回归评估(benchmarks，独立 CLI)     │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ OpenAI 协议（mavis 只会说这个）
┌──────────────── 协议桥 backend/app/llm_bridge.py ────────────────────────┐
│ 协议翻译 · 保证总是返回合法响应体 · response_format → 系统提示 + JSON 形状修复│
└──────────────────────────────┬─────────────────────────────────────────────┘
                               ↓ Anthropic 协议（/v1/messages + x-api-key）
                         ┌───────────────┐
                         │ 模型网关（外部）│
                         └───────────────┘

   mavis 框架（基座）：提供模型接入 / 提示词模板 / 插件总线三个能力面；仿真半边不使用（见 §6.1）
```

**数据流**：对方发言（文本）→ 后端建/取会话 + 注入台账 → 5 路参谋**并行**分析
→ 各路算完即落库并经 SSE 推送 → 前端多列展示 → 一致性检测 + 引用核验（独立端点，不影响主链路）

---

## 6. 五条承重结论（必须知晓）

### 6.1 mavis 的**仿真半边**架构性不适用，**基础设施半边**已被用满

阶段 0 做了源码级验证（详见 `docs/spike-0-report.md`），结论是 **mavis 的 `Agent` 无法在
不改源码的前提下被塑造成"参谋"**：

- `Agent.completion()` 只认框架写死的 `prompt_*` 集合（`wake_up` / `schedule_*` / `generate_chat` /
  `reflect_*` …），**没有"给参谋建议"这一类**；
- `MAVIS_PROMPT_DIR` 只能替换模板**文本**，换不了方法集合；
- `Agent.think()` 是"日程 → 感知 → 定行动 → 移动 → 计划 → 反思"的**生活仿真管线**，
  产物是行动计划，不是建议文本；
- 驱动它还要真实 `maze` + 完整 `spatial.tree`——与"现场出主意"毫无关系。

逐轮推进时**每修掉一个洞就冒出下一个隐式接口依赖**（计时器方法 → `tile.events` → 空 spatial tree 报
`IndexError`），这本身就是证据。

**⇒ 采用的方案（仍然是"不改 mavis"）：只借它的基础设施半边，并行编排自建。**
所有辩论业务逻辑在本仓库，mavis 一行未改。用到什么程度见 §6.5。

### 6.2 网关只认 Anthropic 协议，所以必须有一个协议桥

实测：`ANTHROPIC_BASE_URL` = `https://api.deepseek.com`，`POST /v1/messages` 返回 200，
而 `/chat/completions`、`/v1/chat/completions` 均 **404**。
mavis 的 `OpenAIProvider` 只会说 OpenAI 协议 ⇒ **必然接不上**。

**⇒ 写了 `backend/app/llm_bridge.py`**，把 OpenAI 协议翻译成 Anthropic 协议。
mavis 侧只需 `provider: "openai"` + `base_url` 指向本桥。

**桥还必须做两件 mavis 不做的事（缺了会真出事）：**

1. **永远返回合法 OpenAI 响应体** —— mavis **不检查 HTTP 状态码**，只读
   `choices[0].message.content`。桥若在出错时返回非 JSON，mavis 会走 10 次重试 × `sleep(5)`
   = **50 秒静默失败**（实测过一次 64.9 秒 / 12 次调用）。
2. **结构化输出兜底** —— mavis 靠 `response_format`（json_schema）拿结构化结果，
   而 Anthropic 协议没有该字段。桥要把 schema 写进系统提示，**并对返回做 JSON 形状修复**
   （mavis 的 pydantic 模型统一形如 `{"res": ...}`，模型经常丢掉外层包装）。
   这一项把一步 `think` 从 **64.93s / 12 次调用**降到 **5.6s / 3 次**。

### 6.3 并行编排的性能实测

三路参谋并行：总墙钟 **1.34s**（= 最慢那一路），串行估算 3.65s，**省 63%**。
现场模式的目标是 < 2s，达标。

### 6.4 时间预算的正确语义

现场的关键不是"全部返回"，而是**到点就交付已经好的部分**。
超预算的参谋标 `timeout` 并立刻推送，**不阻塞**其他几路。

实测（预算 1.6s）：质询手 1.05s ✓ / 审计员 1.22s ✓ / 反驳手 timeout，
总耗时 **1.62s** 返回（而不是等反驳手跑完的 ~2s+）。

**实现要点**：`concurrent.futures.wait(timeout=)` 循环 + **`pool.shutdown(wait=False)`**
—— 不能等线程收尾，否则"按时交付"就失去意义了。
收尾的 `run_end` 事件仍然照发（推流观察者靠它送 `_done` 哨兵，指标观察者靠它打本轮小结），
见 `backend/app/orchestrator.py` 的 `finally`。

### 6.5 mavis 用到什么程度（2026-09-30 起）

> **定位**：这一层构成 mavis 在**真实产品中的实地检验** —— 哪些能力面可承重、哪些不可、尚缺什么。
> 检验前提是 **mavis 零改动**（只读依赖，仓库一行未改），故每条结论对框架本身成立，
> 而非"改动之后的效果"。被完整承载的三个能力面见下表；7 处缺口（G1–G7）与 4 条接线注意（N1–N4）
> 见 [`docs/mavis-gap-report.md`](docs/mavis-gap-report.md)；README 的
> [「1. 框架实地检验」](README.md#1-框架实地检验mavis-field-test)一节是面向外部读者的版本。

**被完整承载的三个能力面** —— 完整清单、证据与复现命令见 [`docs/mavis-gap-report.md`](docs/mavis-gap-report.md)：

| 面 | 接口 | 落点 | 用到的能力 |
|---|---|---|---|
| 模型接入 | `create_llm_provider()` → `LLMProvider` | `backend/app/mavis_bridge.py` | 6 个参数中的 6 个：`prompt` / `return_type` / `retry` / **`caller`** / **`failsafe`** / **`callback`**；另接 `is_available()` / `get_summary()` / `cache_stats()` 进 `/api/health` |
| 提示词模板 | `prompt.Scratch.build_prompt()` | `prompts/` + `advisors/base.py` | 三层模板（`layout` + 领域包 `packs/<包>/{roles,tasks}`）；提示词成为可 diff、可版本化、**可按领域替换**的数据；启动自检 `preload()` **遍历每个包** |
| 插件总线 | `plugin.PluginManager` | `backend/app/observers.py` | 三个观察者（落库 / 推流 / 指标），逐插件错误隔离 + `setup/emit/teardown` |

**两个关键设计点，接手时别改回去：**

1. **`failsafe` 是把"上游挂了"和"模型答了空"分开的唯一开关。**
   mavis 的 `completion()` 吞掉全部异常；默认 `failsafe=None` 时两类失败在调用方看来无从区分
   （返回值只是 `None` 与 `''` 之别，而按空值归并的判定会把两者收进同一分支，见 N1）。
   我们传私有哨兵 `FAILED`（`mavis_bridge.py`），于是 `error` 与 `empty` 是两个不同的状态。
   没有它，现场会把"网络断了"误判成"模型不太会说话"。
2. **`callback` 只做归一化，不做判分。**
   mavis 把 callback 返回 `None` 当作"这次不算数，重试一次"，所以在 callback 里否决内容
   会把"质量一般"放大成 `retry` 倍的上游调用。`Advisor.adapt()` 只去空白、丢全空条目。

**只有 `mavisframework` 一个接触面，且有测试守着**：`backend/tests/test_mavis_usage.py`
用 AST 扫 `backend/app/**`，除 `mavis_bridge.py` 外任何文件 import `mavisframework` 都失败；
再用第二个测试锁住"只用顶层 / `plugin` / `prompt`，不碰 `runtime.llm` 内部模块"。
**要换掉 mavis，改 `mavis_bridge.py` 一个文件。**

**查出的 mavis 缺口（只报告，不改）**：G1 结果缓存白名单写死它自己的调用名（接入方加不进去，
所以本项目 `cache=False`）；G2 全局并发闸按 size 重建（多 provider 会互相顶掉闸门，
本项目靠单例 provider 规避）；G3 退避 `sleep(5)` 硬编码（所以 `retry` 显式压到 2）；
G4 `prompt` / `plugin` 没进顶层 `__all__`；G5 `validate_message` 与 `emit` 契约不一致；
G6 `Scratch` 借用成本偏高；G7 **`get_summary()` 的 `R` 不是重试次数**
（只在成功拿到响应时递增，抛异常的尝试不计入 —— 重试 3 次全失败时 `R` 是 0）。
**前端仪表原本把这列标成"重试"，上游全挂时会显示"重试 0 次"，恰好把最该看见的故障藏起来**；
已改成"请求"并加 tooltip 说明。判断失败性质要看我们自己传 `failsafe` 得到的 `error` / `empty`。

**明确没做的**：C 层（SSE 协议对齐 + `SnapshotMsg`）、D 层（`DecisionEvent` 导出）——
`DecisionEvent` 的 17 个字段只填得上一部分，诚实定性为"部分映射"，不为了用而用。

**"用了 mavis 什么"这件事，代码里有一份权威自述**（2026-09-30 加）：
`mavis_bridge.SURFACES` 是唯一事实来源，`mavis_bridge.runtime_info()` 把它加上真实状态
（`mavisframework.__version__` 的真实版本号、只读标记、唯一接触面、`prompts/` 的真实模板清单、
有哪些领域提示词包）
拼成一份快照，三处消费：

| 出口 | 位置 |
|---|---|
| `GET /api/health` 的 `mavis` 块 | 前端「现场仪表」顶部显示版本 + 三面 |
| 导出报告（Markdown / HTML / Word）页脚署名 | `export/report.py` 的 `_attribution()`（句式取自 `mavis_bridge.declaration()`） |
| README 的「1. 框架实地检验」章节 | 手工维护，数字与上面同源 |

**基座关系也只有一份**（2026-09-30 加）：`mavis_bridge.BASED_ON` 记框架发行包名，
`mavis_bridge.declaration()` 给出唯一句式 ——「本项目基于 `mavisframework` vX 开发（只读依赖，一行未改）」。
调用方只被允许替换**框架名的呈现形式**（Markdown 链接 / HTML 粗体 / 纯文本），换不掉句式本身；
`test_declaration_states_the_project_is_built_on_the_framework` 与
`test_declaration_only_lets_the_call_site_restyle_the_name` 守着这条线。

为什么要写进代码：**同一事实在仓库出现两次以上就是 bug 温床**（本项目已经栽过两回：
README 写"6 条缺口"而报告是 7 条；`R` 被标成"重试"）。写进代码后至少有测试盯着
（`test_surfaces_are_the_real_contact_points` 会核对每一面的 `used_in` 指向真函数）。

**缺口报告同样不许"过期不报"**（2026-09-30 加）。`docs/mavis-gap-report.md` 是对某个
**具体版本**的评估，不是永真命题 —— 框架一旦修掉某处，报告就从结论退化成过期说法，
而文档自己不会报错。因此：

- 探针 `backend/spikes/mavis_bounds.py` 改造为**人读输出与机器断言共用同一份证据**
  （每条探针先算出 `evidence` 字符串与 `reproduced` 结论字段，`main()` 只负责渲染）；
- 新增 `--json` 模式供测试消费（机器读模式下关掉 mavis 的 logger —— 它的日志默认落 stdout，
  会把 JSON 弄脏）；
- **补上 N1 / N4 两个此前缺失的探针**：报告写了 N1–N4，原先只有 N2 / N3 查得到，
  这是证据缺口，现已条条对应；
- `tests/test_mavis_gap_report.py` 在**子进程**里跑探针（探针会动 mavis 的进程级并发闸），
  断言 7 处缺口 + 4 条接线注意**仍能复现**，并核对报告里的编号集合与严重度与探针一致。

---

## 7. 代码地图

```
ai-debator/
├── PLAN.md                   实施计划 v2.0（分阶段路线与验收标准）
├── HANDOVER.md               本文
├── README.md                 技术报告体：摘要 / 框架实地检验 / 架构 / 快速开始 / 局限（中文，默认）
├── README.en.md              同上，英文版（两份内容同步维护）
├── .env.example              只列变量名，不写值
├── docs/
│   ├── spike-0-report.md     阶段 0 实测报告（★ 决定架构的证据）
│   ├── mavis-gap-report.md   ★ mavis 适用性评估（技术报告体）：三面承载 / 7 处缺口（G1–G7）/ 4 条接线注意 + 复现命令
│   ├── decision-log.md       工程决策记录（ADR 式）
│   ├── local-model-report.md 本机 Ollama 接入报告
│   ├── sample-report.md      导出样例
│   └── sample-report.docx    导出样例
├── prompts/                  ★ 提示词（走 mavis 的 Scratch 模板层）
│   ├── layout.txt            总装顺序：$directive / $context / $task（顶层共享，与领域无关）
│   └── packs/<包>/           ★ **领域提示词包**：每包自带完整的 roles/ + tasks/（5×2 份）
│       ├── legal/            法学：法律涵摄 + 法律解释方法（★ 逐字节等于解耦前的 prompts/{roles,tasks}/）
│       └── general/          通用（默认包）：三段论 + 衡量尺度 + 依据核验
├── configs/
│   ├── advisors.yaml         参谋团名册 —— **唯一来源**：label / kind / domain 都在这里覆盖，
│   │                         `enabled: false` 停用某一路，**列表顺序即界面顺序**
│   ├── topics.yaml           预设辩题库（辩题 + 双方立场 + 对方例句 + domain 场景分组）
│   ├── prompt-packs.yaml     ★ domain → 提示词包 的映射 —— **唯一来源**（改包名/认领领域不用动代码）
│   └── mavis/config.json     ⚠️ 历史遗留：Simulator 时代的配置骨架，**运行时不再读取**
│                             （provider 参数现由 mavis_bridge.py 直接构造 dict 传入）
├── scripts/
│   ├── bootstrap.sh          一键引导：克隆 mavis + 装依赖 + 跑测试
│   ├── run_local.sh          本地模型（Ollama）零成本启动
│   └── import_corpus.py      法律全文 → data/corpus/laws.json（启用「已核验」）
├── backend/
│   ├── requirements.txt      后端依赖（mavis 是本地只读依赖，另行安装）
│   ├── pytest.ini            basetemp 指到项目内（见 §10 环境坑）
│   ├── app/
│   │   ├── main.py           FastAPI 入口 + 全部路由 + SSE
│   │   ├── config.py         环境变量与路径（★ 导入时读 env，测试要注意）
│   │   ├── llm_bridge.py     协议桥（★ 见 §6.2）
│   │   ├── mavis_bridge.py   ★ 与 mavis 的**唯一**接触面（provider / Scratch / PluginManager
│   │   │                     都从这里出口；换掉 mavis 只改这个文件）
│   │   │                     · `SURFACES` / `runtime_info()` = "用了 mavis 什么"的唯一事实来源
│   │   │                     · `BASED_ON` / `declaration()` = "基于 mavisframework 开发"的唯一句式
│   │   ├── observers.py      ★ 三个观察者（落库 / 推流 / 指标），挂 mavis 插件总线
│   │   ├── orchestrator.py   并行编排 + 时间预算 + 事件广播
│   │   ├── topics.py         辩题库：预设(configs/topics.yaml) + 本机(data/topics.json)
│   │   ├── prompt_packs.py   ★ 选包策略：domain 精确匹配 → 包名；未认领/自由输入落默认包
│   │   │                     （渲染机制在 mavis_bridge.render(..., pack=)，这里只管「选哪个」）
│   │   ├── schemas.py        pydantic 模型（★ 给 mavis 的必须顶层带 res；★ 字段描述会发给模型，
│   │   │                     必须领域中立 —— 取值枚举写在各包的 tasks/*.txt 里）
│   │   ├── consistency.py    立场一致性检测（调用 LLM）
│   │   ├── advisors/         五路参谋
│   │   │   ├── base.py       Advisor 基类 + DebateContext + 模板渲染 + 启动自检（preload）
│   │   │   ├── rebutter.py   反驳手（四段式三段论）
│   │   │   ├── questioner.py 质询手
│   │   │   ├── auditor.py    逻辑审计员
│   │   │   ├── strategist.py 论证策略师（尺度/方法由提示词包给，见 packs/general|legal/roles）
│   │   │   ├── risk.py       风险提示员
│   │   │   └── __init__.py   REGISTRY 注册表（★ 新参谋加这里，同时**每个包**各补 roles+tasks 两个 .txt）
│   │   ├── ledger/store.py   论点台账 SQLite（★ 逐条落库，供断线恢复）
│   │   ├── retrieval/        检索与引用核验（★ 纯本地，0 API 消耗）
│   │   │   ├── base.py       Retriever 抽象 / LegalSource(带效力位阶) / CitationReport
│   │   │   ├── local_corpus.py  data/corpus 检索器
│   │   │   ├── statute_text.py  法律全文 → {条款: 正文} 解析（导入工具的核心，纯文本）
│   │   │   └── citations.py  引用抽取 + 三态核验 + **引述内容比对**（★ 纯本地，0 消耗）
│   │   └── export/report.py  导出：Markdown / Word / HTML(打印→PDF) · 页脚含基座归属声明
│   ├── benchmarks/runner.py  回归评估框架（自动指标 0 API 消耗）
│   ├── tests/                全量测试（`test_mavis_usage.py` 守接触面与模板包；`test_prompt_packs.py`
│   │                         守选包规则 + 两条领域措辞泄漏路径；`test_mavis_gap_report.py` 守缺口报告不过期）
│   └── spikes/               阶段 0 的三个验证脚本 + `mavis_bounds.py`（G1–G7 / N1–N4 复现入口，支持 `--json`）
├── frontend/src/
│   ├── App.tsx               主容器 + 状态编排
│   ├── api.ts                API 封装（含 SSE）
│   ├── types.ts              前端类型
│   ├── styles.css            全部样式（手写，无 UI 框架）
│   └── components/
│       ├── SettingsPanel.tsx 左侧设置 + 服务状态
│       ├── AdvisorColumn.tsx 参谋列 + 各类渲染（含可编辑字段）
│       ├── LedgerPanel.tsx   我方论点台账
│       ├── MetricsPanel.tsx  现场仪表（延迟分布 + provider 逐参谋计数 + 基座归属行）
│       └── CitationPanel.tsx 引用核验
├── benchmarks/
│   ├── README.md             指标含义 + 怎么回答"改动是否变好"
│   ├── cases/core.yaml       4 个回归用例
│   └── results/              评估产出（gitignore）
└── data/
    ├── ledger.db             台账库（gitignore）
    ├── topics.json           ★ 界面上「保存为我的辩题」存的那些（gitignore，不入仓）
    └── corpus/README.md      ★ 法源语料格式说明（放入法条即可启用「已核验」）
```

---

## 8. 怎么跑起来

### 8.0 在新电脑上从零开始（推荐先跑脚本）

```bash
git clone git@github.com:hellobs/ai-debater.git
cd ai-debater
bash scripts/bootstrap.sh
```

脚本只做三件事：**克隆 mavis（只读依赖）、装依赖、跑一遍全量测试**。
**它不会调用任何模型，不产生任何费用。**

可用环境变量覆盖默认值：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PYTHON_BIN` | `python3` | 需要 ≥ 3.12 |
| `VENV` | `<仓库>/.venv` | 虚拟环境目录 |
| `MAVIS_DIR` | `<仓库>/../mavis` | mavis 放在仓库同级 |
| `MAVIS_REPO` | 官方 HTTPS 地址 | 没有 SSH key 时用 HTTPS |

> ⚠️ **不要照抄任何机器上的绝对路径。** `bootstrap.sh` 建出的 venv 固定在 `<仓库>/.venv`；
> §8.1–8.5 统一用 `$PY` 指代"该 venv 里的 python"，按平台取值即可：
>
> | 平台 | `$PY` |
> |---|---|
> | Windows（Git Bash） | `.venv/Scripts/python.exe` |
> | macOS / Linux | `.venv/bin/python` |
>
> **路径必须写成绝对路径**：下面的命令都带 `cd`，相对路径到那一步就失效了。

### 8.1 环境

不需要任何绝对路径，只要 `bootstrap.sh` 跑通：

```bash
# 在仓库根目录执行
PY="$PWD/.venv/bin/python"        # Windows: PY="$PWD/.venv/Scripts/python.exe"
```

### 8.2 安装（`bootstrap.sh` 已覆盖；手工执行时等价于）

```bash
"$PY" -m pip install ../mavis                          # mavis 只读依赖（路径取 MAVIS_DIR）
"$PY" -m pip install -r backend/requirements.txt

cd frontend && npm install --no-bin-links              # 注意 --no-bin-links，见 §10 第 7 条
```

### 8.3 凭据（只走环境变量，**绝不入仓**）

桥需要 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN`（**用户机器环境里本来就有**），
模型名走 `LLM_MODEL`（默认 `deepseek-chat`）。

### 8.4 起三个服务

```bash
# 1) 协议桥（mavis 指向它；本地模型模式下可跳过）
cd backend && LLM_BRIDGE_PORT=8011 "$PY" -m app.llm_bridge

# 2) 后端
cd backend && "$PY" -m app.main                        # 127.0.0.1:8010

# 3) 前端
cd frontend && npm run dev                             # 127.0.0.1:5173
#   受限环境下 npm 建不出 node_modules/.bin（见 §10 第 7 条），此时直跑：
#   node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173
```

### 8.5 验证

```bash
curl -s --noproxy '*' http://127.0.0.1:8011/healthz     # 桥
curl -s --noproxy '*' http://127.0.0.1:8010/api/health  # 后端（含基座自述与参谋团名册）
cd backend && "$PY" -m pytest                           # 全量测试（0 API 消耗）
```

> `--noproxy '*'`：本机端口不该走系统代理，否则会被拦成 `os error 10061`（见 §10）。

---

## 9. 功能清单（都已实测）

| 功能 | 端点 / 入口 | 消耗 API？ |
|---|---|---|
| 五路并行参谋（SSE 流式推送） | `GET /api/analyze/stream` | **是**（5 路 = 5 次） |
| 一次性分析（非流式） | `POST /api/analyze` | **是** |
| 健康检查 | `GET /api/health` | 否 |
| 会话 / 台账 CRUD | `/api/session`、`/api/session/{sid}`、`/api/cards/{cid}` | 否 |
| 立场一致性检测 | `POST /api/session/{sid}/check-consistency` | **是**（有台账时才调） |
| 引用回链核验（三态） | `POST /api/session/{sid}/verify-citations` | **否** |
| 检索层状态 | `GET /api/retrieval` | 否 |
| 辩题库读 / 增 / 删 | `GET`·`POST /api/topics`、`DELETE /api/topics/{id}` | 否 |
| 延迟指标（导出与评估用；界面已移除仪表面板） | `GET /api/metrics` | 否 |
| 导出 Markdown / Word / PDF | `/api/session/{sid}/export.{md,docx,html}` | 否 |
| 回归评估 | `cd backend && python -m benchmarks <list\|check\|eval\|compare>` | 否 |

### 9.1 参谋团五路

五路在**任何领域**都上场；领域差异由提示词包给（见 §3 决策 14）。

| 参谋 | 产出 | general 包 | legal 包 | 设计依据 |
|---|---|---|---|---|
| 反驳手 | 四段式反驳要点（主张/大前提/小前提/结论） | 大前提 = 公认原则或一般性判断 | 大前提 = 法律规范（条款项） | 交接文档 §3.1 |
| 质询手 | 可立即抛出的质询问题 | 领域无关 | 领域无关 | — |
| 逻辑审计员 | 谬误类型 + 原话片段 | 领域无关 | 领域无关 | 交接文档 §5.1 |
| **论证策略师** | 对方用了哪种尺度/方法 → 我方应主张哪种优先 | 事实认定 / 概念界定 / 价值排序 / 后果权衡 | 文义 / 体系 / 目的 / 历史 / 合宪性解释 | 交接文档 §3.4 |
| **风险提示员** | 对方陷阱 / 我方薄弱 / 事实不清 / 依据是否稳 | 依据不稳 | 法源不稳 | 交接文档「坑 1 立场漂移」 |

**名册只有一个来源**：`configs/advisors.yaml`（`label` / `kind` / `domain` 覆盖 + `enabled` 开关 + 顺序）。
前端**不再抄一份**——它读 `GET /api/health` 返回的 `advisors[].{name,label,kind,domain}`。
（此前名册被定义了多遍：类属性 / YAML 里没人读的 label / `App.tsx` 的 `COLUMNS` 常量。已合并。）

**提示词也只有一个来源**：`prompts/packs/<包>/roles/<name>.txt`（角色指令）+ `.../tasks/<name>.txt`（本次任务），
拼装顺序在 `prompts/layout.txt`（顶层共享，与领域无关）。这三层走 mavis 的 `Scratch` 模板层，
**不再是 Python 里的长字符串常量**；`<包>` 由辩题的 `domain` 经 `configs/prompt-packs.yaml` 选出
（搬迁做过逐字节核对，见 `test_built_prompt_follows_the_layout_contract`）。
`load_roster()` 会做启动自检 `preload()`：**缺模板当场抛 `PromptTemplateError`，不做静默降级**——
降级的表现是"提示词少一段角色指令但模型照样回答"，那是最难发现的一类 bug。

**新参谋怎么加**：在 `backend/app/advisors/` 加一个模块（继承 `Advisor` + 定义 `output_model`），
在 `advisors/__init__.py` 的 `REGISTRY` 注册，**在每一个提示词包里各补 `roles/<name>.txt` 与
`tasks/<name>.txt` 两个文件**（漏了会在 `load_roster()` 就报错，正是想要的效果），
在 `configs/advisors.yaml` 加一行，在 `AdvisorColumn.tsx` 加渲染分支。**前端不用动名册。**

**名册全停用时**：解析成功但 `enabled` 全为 false → 跑零路并告警（尊重显式意图，
不偷偷改回全开——那会在用户不知情时多花五次上游调用）；文件缺失/解析失败/名字全写错 →
回到代码默认全部启用。这两种处置相反，`load_roster()` 里是分开判断的。

### 9.2 防立场漂移做了两道闸

1. **预防**：每次分析把台账里仍成立的主张（`standing`）注入参谋提示词；
2. **检测**：`check-consistency` 把新建议与台账比对，找出**不能同时为真**的冲突，前端标红。

检测**刻意不放进 `/api/analyze` 热路径**（现场延迟敏感），由前端在建议返回后再调一次。

实测：故意喂一条与台账相反的主张 → 准确命中冲突；同时**正确放过了无关主张**（未误报）。

### 9.3 引用核验的三态（保守判定）

| 状态 | 含义 |
|---|---|
| **已核验** | 结构化语料里**确实有这一条**，附原文为证 |
| **存疑** | 该法存在但语料里没这条（可能编造，也可能语料不全）；或只在自由文本里出现 |
| **未核验** | 语料里根本没有这部法 |

**必须保持保守**：只有结构化语料查到条款才给「已核验」。
只给法名不给条款号 → 存疑（**不能用"该法首条"兜底，那是假阳性**，这条已经踩过一次）。

**第二条正交的轴 · 内容一致性**（2026-09-30 加）。条款号真实存在，不代表模型给它配的
条文内容是对的 —— 实测中模型写过真实条款号 + 编造内容，旧版照样判「已核验」。
现在 `citations.py` 会把引用**之后紧跟**的那段"声称内容"抽出来，与语料原文做
**最长公共子串重合度**比对，并随报告下发：`claimed`（模型原话）、`match`（0~1）、
`content_ok`（是否达标）、`match_low`（阈值本身，前端不抄一份）、`content_suspect`（汇总计数）。

三条设计约束，别改回去：

1. **不改变 `status`**。存在性与一致性是两个正交维度；低重合只是"模型的话与原文对不上"，
   可能是编造也可能是合理意译，**裁定权在人**（AI 只出主意）。
2. **抽不出内容就不比对**（`claimed` 为空、或归一化后不足 6 字）—— 宁可不结论，也不给噪声值。
3. **不要顺手加自动降级**。要降级就得先有真实语料的误杀率数据，否则会把"意译概括"
   批量标成"幻觉"，比不标更糟。前端把**模型引述**与**语料原文**并排摆出来即可。

---

## 10. 已知陷阱（按发现顺序，勿重复踩）

### 框架层

1. **mavis 不检查 HTTP 状态码** —— 桥必须永远返回合法 JSON，否则静默重试 50 秒。
2. **mavis 依赖 `response_format` 且模型必须回 `{"res": ...}`** —— 桥内要做形状修复。
3. **mavis 的 `create_llm_provider` 是硬编码 if/elif**（仅 ollama / openai），无注册表。
4. **mavis 契约测试禁止框架源码出现业务词汇** —— 业务逻辑必须在本仓库。
5. **mavis 无流式** —— 前端只能用"建议卡片整块出现"，不做逐字流。

### 业务层

6. **参谋产出是 pydantic 实例，不是 dict** —— 落库 `json.dumps` 会抛
   `TypeError: Object of type Rebuttal is not JSON serializable`。
   已在 `Advisor.run()` 源头用 `schemas.jsonable()` 摊平，别在调用点打补丁。

### 环境层（本机特有，换机器可能不一样）

7. **npm 在本环境创建 `node_modules/.bin` 会被策略拒绝**（`CODEBUDDY_BROKER_DENY`），
   导致 reify 整体中断、**所有包目录为空但退出码是 0**（很隐蔽）。
   解法：`rm -rf node_modules package-lock.json && npm install --no-bin-links`。
   因为没有 `.bin`，构建要直接跑 `node node_modules/vite/bin/vite.js build`。

   **补充（已实测）**：中断后未必全空——本项目停在"只缺 `@vitejs/plugin-react`"的状态，
   `node_modules` 其余 29 个包都在。此时**定向补装单个包不会触发批量删除**，
   一条 `npm install @vitejs/plugin-react --no-audit --no-fund --registry=https://registry.npmmirror.com`
   即可修好，不必推倒重装。**排查手法**：先跑 `tsc --noEmit`，报错会直接点出缺哪个包。
8. **pytest 的 `tmp_path` 默认写系统临时目录会被沙箱拒绝**。
   已在 `backend/pytest.ini` 里 `addopts = -q --basetemp=.pytest_tmp`。
9. **`nohup … &` 起的进程会在那个 shell 退出时被回收** ——
   表现为"刚检查还健康，下一步就 404"。要用受管的后台任务方式启动。
10. **沙箱内默认无网络**（HTTPS 经代理 502）。git 推拉、装包、联网检索都必须显式放行。
11. **`app.config` 在导入时读环境变量** —— 测试必须先设 env 再 import。
    已在 `backend/tests/conftest.py` 用直接赋值处理（不用 `setdefault`，保证确定性）。

### 工具层

12. `dangerouslyDisableSandbox` + 引号嵌套复杂的 curl/python 组合命令会报
    `sandbox-center cmd decisionRecord missing actual resource subject`。
    改成"先 curl 落文件、再单独解析"即可绕过。

---

## 11. ⚠️ 成本红线（**新接手者必须遵守**）

**用户对 API 消耗明确关注，并主动质询过一次。**

| 事实 | 说明 |
|---|---|
| **点一次分析 = 5 次上游调用** | 5 路各 1 次 |
| **超时也计费** | 超时只是本地不等了，上游请求**已经发出去了**，照样计入 |
| **空闲不花钱** | 服务挂着不会轮询，只有点按钮才发请求 |
| **凭据不是我配的** | `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` 是用户机器环境里本来就有的 |
| **从未创建 `.env`** | 仓库内无任何硬编码密钥，`ANTHROPIC` 只出现在 `os.environ.get` 与文档里 |
| **换电脑 = 可能换账户** | 新机器上的 `ANTHROPIC_*` 环境变量可能指向**另一个账户**（甚至不存在）。开跑前先确认，别以为花的还是同一笔钱 |

**必须遵守的工作方式：**

1. **任何会产生真实 API 消耗的测试，先问用户。**（这条是我犯过的错：没问就跑压测，
   而且阶段 0 那轮 JSON 未修好的失败一次烧了 12 次调用。）
2. **优先用 0 消耗的验证手段**：
   - 本地单测与 `python -m benchmarks check/eval`；
   - 用 `ADVISORS_YAML=/tmp/xxx.yaml` 指向**临时名册**，只启用需要验证的那几路
     （实测五路时我只跑了 2 路 = 2 次调用，而不是 5 次）；
   - 用 `CORPUS_DIR=/tmp/xxx` 指向临时语料验证检索链路。
3. **只有 `benchmarks run --live --confirm` 才真跑模型**，且不带 `--live` 时会先报预计调用量再退出。
4. **零成本替代**：mavis 原生支持 `provider: "ollama"`，改 `configs/mavis/config.json` 三行即可。
5. 想彻底杜绝误触：`pkill -f app.main; pkill -f app.llm_bridge`（空闲本就不花钱，但点了就会）。

---

## 12. 待确认事项（阻塞项）

> **换机器后的第一件事**：确认新环境里有没有 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`。
> 没有的话：**协议桥、后端、全量测试、引用核验、导出、回归评估全都能正常跑**（都不联网），
> 只有"真正跑一轮参谋"会失败。所以新机器上可以先做零消耗的验证，再决定凭据怎么办。

### 12.1 真实法源检索通道 ⛔ 阻塞阶段 4 剩余部分

用户此前选择"先不管检索"。现在需要一条真实检索通道（搜索 API / 连接器）。
**接入方式**：实现一个 `Retriever` 子类（见 `backend/app/retrieval/base.py`），
在 `retrieval/__init__.py` 的 `get_retriever()` 加一个分支，**业务代码不需要改**。

也可以先走"本地语料"路线：把法条全文放进 `data/corpus/`（格式见该目录 README），
立刻就能让引用核验从"模型自称"变成"程序核对"。

### 12.2 ASR 方案 ⛔ 阻塞阶段 7

三选一：

| 方案 | 优点 | 代价 |
|---|---|---|
| 浏览器 Web Speech | 零成本零部署 | 中文识别一般、依赖 Chrome 与网络 |
| 本地 Whisper（faster-whisper / whisper.cpp） | 离线、隐私好 | 需装模型，延迟看本机性能 |
| 云 ASR（讯飞 / 腾讯云等） | 中文最准 | 需 API Key + 现场网络 |

### 12.3 其他未定项

- **学科方向**：民 / 刑 / 法理 / 国际法？（决定是否要引入请求权基础或三阶层体系。
  目前论证骨架保持中性，没写死任何一种。）
- **参谋要不要按辩题场景上场/下场**：**已不需要**。此前 `domain` 只是标注、不做过滤，
  通用辩题下论证策略师照样会跑，措辞由提示词包给（法学题拿法律解释方法、通用题拿衡量尺度）
  —— 这是领域的**措辞**问题，不是**上场**问题，已由提示词包解决（见 §3 决策 14）。名册里的 `domain` 字段保留给「真只在一个领域成立的参谋」，
  目前五路**全部留空**。
- **会话没有落库所用提示词包**：`sessions` 表只有 topic / our_side，没有 domain 或 pack。
  后果：复盘导出的报告**无法回溯某一轮用的是哪套措辞**。加列需要一次 `ALTER TABLE` 迁移，
  本轮没做（`_prepare` 的 docstring 里如实标注了）。要做就是一次小迁移 + 导出报告加一行。
- **`domain` 只由前端搬运**：后端不按标题反查辩题库（标题随时可改，反查会静默选错包）。
  代价是**第三方直接调 API 时必须自己带上 `domain`**，否则落默认包。
- **辩题库的运营方式**：现在靠手写 `configs/topics.yaml`。要不要做成可导入（如从赛程表 CSV 批量导入）？
- **赛制细则**：目前"暂无"，因此没有状态机。若后续给到，只需改配置与提示词，架构不动。
- **现场网络条件**：影响是否需要提前做离线降级（当前按"网络稳定"设计）。
- **队友访问方式**：局域网直连还是内网穿透。
- **成本归属**：那个 token 背后是用户个人账户还是环境预置通道，**未确认**。

---

## 13. 后续工作建议（按性价比排序）

1. **给 `data/corpus/` 喂真实法条** —— 立刻让引用核验可判「已核验」，零代码改动、零 API 消耗。
   工具已就位：`python scripts/import_corpus.py 法条.txt --law <法名>`（纯文本解析，不联网）。
   ⚠️ 语料必须来自官方文本（flk.npc.gov.cn），**不要凭记忆录入**——那会把错误固化成"已核验"。
2. **往 `configs/topics.yaml` 里加真实辩题** —— 同样零代码、零消耗，是平台"通用"起来的最短路径。
   手写 YAML 即配置；界面上也能「保存为我的辩题」存到不入仓的 `data/topics.json`。
3. ~~解耦提示词层的领域绑定~~ —— ✅ **已完成**（走的是「领域提示词包」路线，见 §3 决策 14、§4 阶段 13）。
   **阶段 13 附：已跑一轮实测**（2026-09-30，用户确认后 6 次上游调用；复现入口
   `backend/spikes/pack_quality.py`，带 `--dry-run` 可 0 消耗先看提示词）。
   已证明：同一道通用辩题换包后产出**确实改变** —— legal 包会把非法律题拽去找法条
   （且只能标「待核验」，那些条款与此题无关），general 包则落回教育学判断。
   这从反面印证了「不猜包」的必要性。
   ⚠️ **仍未证明**「通用包产出更好」：n=1 题、单次、无盲评，要回答那一问需要多辩题 + 人工盲评。
   详见 §15 第 11 条与 [`docs/decision-log.md`](docs/decision-log.md) §3.10 的实测表。
4. 补齐回归用例（`benchmarks/cases/core.yaml`）到用户实际要打的辩题 —— 用例越贴近实战越有用。
5. 接真实检索通道（需用户先给通道）。
6. ASR（需用户先选方案）。
7. 可选增强：参谋团扩到 7 路、备赛模式（无预算 + 更全输出）、移动端适配（用户当前只要求桌面）。

---

## 14. 提交历史

> **本表只维护「阶段 ↔ 提交」对照，不逐条罗列。**
> 这样不会过期——要看完整历史一律用 `git log --oneline --reverse`。
> （此前这里写死过条数与 HEAD，结果每提交一次就滞后一次，修改过两回。）

```
871b0a5  add plan                             （PLAN v1.0：原始"互搏"方案）
a943136  update plan                          （PLAN v2.0：转向"参谋团"）
49ea80c  stage0: bridge + spikes              （协议桥 + 三个验证脚本 + spike 报告）
48e150e  stage1: advisors api + frontend      （三路参谋 + API + React 前端）
248e48f  stage2: ledger + consistency         （台账 + 立场一致性）
664e602  stage3: export                       （MD/Word/PDF 导出）
2fcd735  stage4: live safeguards              （时间预算 / 延迟仪表 / 断线恢复）
e2630cd  stage5: five advisors                 （扩至五路）
21fd8c2  stage6: citation verify              （检索层 + 引用回链核验）
e020d99  stage7: benchmark harness            （回归评估框架）
a412e2f  stage8: api tests                    （API 端到端测试）
b94ae55  stage9: topics + roster              （辩题库配置化 + 名册单一来源）
7373e8e  └ 前端：辩题选择器 + 参谋列改为从 /api/health 派生
b2b4f3e  └ 去法学化品牌 + 文档同步
23a0727  stage10: mavis depth                 （提示词进 mavis 模板层）
         └ provider 全参数 + 插件总线 + 缺口报告（见 git log 中 stage10 之后的提交）
```

阶段性提交之外还有若干 `chore:` / `docs:` / `fix:` / `feat:` 小提交（清理忽略规则、
交接文档、双语 README、语料导入工具等），不在此列。

> 提交信息按用户要求**写得简略**。仓库名是 **ai-debater**（e），别写成 ai-debator。
> 已知历史瑕疵：`7c8a1b0` 与 `a6f1099` 是两个同名提交（清理 Vite 临时文件时重复执行），
> 内容无影响，未整理历史。

---

## 15. 如实记录的局限

1. **阶段 0–2 的 API 消耗没有完整账目**。账本表是阶段 3 才加的，之前的压测未记录，
   估算约 60–90 次调用。应用侧可核对的累计为 25 次（含一次**来源不明**的完整 5 路分析，
   最可能是用户在预览面板手动点了一次）。
2. **要点覆盖率是粗信号**。它只回答"话题有没有被碰到"，**不回答"论证好不好"**，
   关键词可以靠堆术语刷分。已在 `benchmarks/README.md` 明确标注，**不要当质量分用**。
3. **引用核验回答两件事**：引用在语料中**是否存在**（三态）、模型**引述的内容与原文重合多少**。
   它**不判断**引用是否恰当、法条是否被正确适用，也不替人裁定低重合到底是编造还是意译。
4. **PDF 导出走的是"打印优化页面"**，不是直接生成 PDF。原因：中文 PDF 需内嵌 CJK 字体，
   缺字体会变方块；浏览器打印用系统字体，零依赖且排版最好。已写进代码注释与 README。
5. **前端未做移动端适配**（用户明确只要笔记本浏览器）。
6. **两个同名提交** `7c8a1b0` / `a6f1099`（清理 Vite 临时文件时重复执行），内容无影响，未整理历史。
7. **结果缓存未启用**。mavis 的缓存白名单 `_CACHEABLE_CALLERS` 写死了它自己的三个调用名，
   接入方加不进去（缺口 G1），所以"同辩题 + 同对方发言"的重跑不会命中缓存，白花 5 次调用。
   已在 `/api/health` 与前端仪表上如实显示"结果缓存未启用"，没有假装有。
8. **`Advisor.adapt()` 的规整刻意保守**：只去空白、丢整条全空的条目，不做字段齐备性判分。
   原因是 mavis 把 callback 返回 `None` 当作"重试一次"，在那里判分会把"质量一般"
   放大成 `retry` 倍成本。更严的规整需要先用真实数据量误杀率 —— 见该方法的 docstring。
9. **引述内容比对有误报空间**。它用的是"最长公共子串 / 声称内容长度"，模型的**意译概括**
   可能掉到 45% 阈值以下而被标「引述待查」。这是刻意的取向：**宁可多提示，也不自动判错**
   （不改 `status`，只把两侧原文并排给人看）。真实语料 + 云端模型下的误报率**尚未测量**，
   因为 `data/corpus/` 目前是空的，本地 4B 模型也几乎不引法条。
10. **框架实地检验属单案例观测**。结论基于单案例、单版本、单任务形态，**不宜直接外推**至
    框架的全部使用场景；外部效度的边界见
    [`docs/mavis-gap-report.md`](docs/mavis-gap-report.md) §6。
11. **提示词包的"通用"只做到措辞层，"更好"仍未被证明**。已证明：选包正确、通用包里无法学措辞、
    发给模型的 json_schema 里无法学措辞、法学包逐字节零回归。已**实测**（2026-09-30，6 次调用）：
    换包确实改变产出 —— legal 包会把非法律题拽去找法条，属错配。
    ⚠️ **仍未证明**"通用包产出的建议真的比法学措辞下更好"：n=1 题、单次、无盲评；
    要回答这一问需要多辩题 + 人工盲评，不是几次调用能给的。见 §13 第 3 条。
    另外 `retrieval/`（法源检索与引用核验）**按设计就是法学专用**的，没有、也不该被这个包机制覆盖；
    通用辩题下这一面板不适用（它只核验引用，不参与生成，所以不会误导）。

---

_本文档不写任何凭据。所有密钥只从环境变量读取。_
