# 法学辩论 AI Agent — 实施计划（PLAN v2.0）

> 版本 v2.0 · 2026-09-29 · **对 v1.0 的重大转向**
> 状态：待你确认后进入阶段 0
>
> **v1.0 → v2.0 的转向原因**：本轮澄清后，产品定义从"正反方 AI 自动互搏 + 裁判打分"
> 改为"**多 Agent 并行参谋团，现场为你出主意**"。底座从"FastAPI 自建"改为"**mavis 框架**"。
> v1.0 全文见 git 提交 `871b0a5`。
>
> ⚠️ **后续修正（2026-09-30，本文件未改写）**：本文写作时的定位是"法学辩论"，
> 现已放宽为**通用辩手平台**，「AI + 法学」只是落地场景。本文与 §0 的"法学"字样
> 属**历史快照**，以 [`HANDOVER.md`](HANDOVER.md) §1 与 [`docs/decision-log.md`](docs/decision-log.md) §1.1 为准。
>
> 另：项目的**基座关系**现表述为「**本项目基于 [`mavisframework`](https://github.com/hellobs/mavis) 开发**」
> （只读依赖、一行未改），其唯一事实来源为 `mavis_bridge.BASED_ON` 与 `declaration()`。
> 本文作为历史快照未同步该表述。

---

## 0. 一句话定义（v2.0）

> 一个**现场实时参谋台**：你在台上打法学辩论，对方说完一段，系统**并行**跑几路 AI 参谋，
> 各自给你出主意——反驳要点、质询问题、对方逻辑谬误——你自己判断要不要用。

**关键定性：**

| 维度 | 结论 |
|---|---|
| 谁对抗谁 | **不对抗**。所有 Agent 站在你这一边，是**参谋团**，不是对手 |
| 谁做决策 | **你**。AI 只出主意，不替你上台、不替你定稿 |
| 什么时候用 | **现场辅助**（主场景）；备赛训练为后续可能的扩展 |
| 多 Agent 的意义 | **并行多视角**（进攻 / 审逻辑 / …），不是多轮互相说服 |

> 这个定义直接砍掉了 v1.0 里最复杂的几块：赛制状态机、发言权交替、胜负判定、Elo。
> 因为没有回合交战，就没有"谁该发言""谁赢了"的问题。

---

## 1. 已确认决策（全部，不再重复讨论）

| # | 维度 | 决策 | 对架构的直接影响 |
|---|---|---|---|
| 1 | 产品形态 | **多 Agent 并行参谋团给用户出主意** | 不做 AI vs AI 互搏；无回合制 |
| 2 | 底座 | **使用 mavis 框架**（`hellobs/mavis`，v1.3.3） | 见第 3 节；并行调度复用其 `Simulator` |
| 3 | mavis 变更 | **不改 mavis 源码** | 只能靠"喂配置 + 外部适配"接入；业务逻辑必须放在 mavis 之外 |
| 4 | LLM 通道 | **有 OpenAI 协议可用通道** | mavis 的 `OpenAIProvider` 可零改直连 |
| 5 | 模型 | `deepseek-chat`（单一型号） | 所有参谋同一模型 |
| 6 | 现场输入 | **先做文字输入，语音转写（ASR）后置** | 首期不打 ASR；链路是"文本进 → 建议出" |
| 7 | 参谋团 | **5 路**：反驳手、质询手、逻辑审计员、**解释方法策略师**、**风险提示员** | 3 路跑通后扩至 5 路（见 §6 阶段 1–2） |
| 8 | 检索 | **先留接口**，暂不接真实检索 | 阶段 1-3 靠模型内置知识，法源标注"未核验" |
| 9 | 部署 | 先本地；队友也要用；**不做登录** | 桌面浏览器优先，局域网内可直接访问 |
| 10 | 设备 | 笔记本浏览器 | 桌面优先，不做移动端适配 |
| 11 | 导出 | **需要**（复盘可下载） | 后期加 Word/PDF/Markdown 导出 |
| 12 | 辩题库 | 先轻，结构上预留 | 初期临时输入辩题 |

---

## 2. 架构

```
┌──────────────────────────── 前端（React + Vite，桌面优先） ─────────────────────────────┐
│  对方发言输入框 │ 参谋建议面板（多路并列，每路一列卡片流） │ 对局时间轴 │ 导出按钮        │
└───────────────────────────────────┬─────────────────────────────────────────────────────┘
                       SSE 推送 ↑      ↓ POST /api/analyze（提交对方发言）
┌──────────────────────────── 我方后端（FastAPI，业务层） ────────────────────────────────┐
│  发言分段 · 参谋并行编排（ThreadPoolExecutor）· 建议聚合排序 · 台账落库 · 导出             │
└───────────────────────────────────┬─────────────────────────────────────────────────────┘
                                    │ 唯一的 mavis 接触面（mavis_bridge.py）
┌────────── mavis 框架（只读依赖，一行不改）· 定位＝模型接入层 ──────────────────────────┐
│  ✅ create_llm_provider(provider="openai") → 指向我方协议桥                              │
│  ✅ Timer / checkpoint（可选复用）                                                       │
│  ⛔ Agent / Simulator / 记忆：阶段 0 已验证不适用                                        │
│     （生活仿真管线 + 空间/日程绑定，与"并行出主意"语义错位，详见 §3.4）                   │
└───────────────────────────────────┬─────────────────────────────────────────────────────┘
                                    │ OpenAI 协议（/chat/completions + Bearer）
┌──────────────────────── 协议桥 backend/app/llm_bridge.py ──────────────────────────────┐
│  协议翻译 · 保证总是返回合法响应体 · response_format → 系统提示 + JSON 形状修复           │
└───────────────────────────────────┬─────────────────────────────────────────────────────┘
                                    ↓ Anthropic 协议（/v1/messages + x-api-key）
                              ┌───────────────┐
                              │ 模型网关（外部）│
                              └───────────────┘
```

**数据流**：对方发言（文本）→ 后端分段 → 交给 mavis 参谋 Agent 并行分析 → 各路产出经事件总线回到后端
→ 聚合为建议卡片 → SSE 推给前端。

---

## 3. mavis 接入方案（零改框架）

### 3.1 为什么能零改：加一层协议桥

mavis 的 `runtime/llm.py::create_llm_provider` 是硬编码的 `provider == "openai"` 分支，
`OpenAIProvider` 会往 `{base_url}/chat/completions` 发 `Authorization: Bearer`。

而实测发现：**本项目可用的网关只提供 Anthropic 协议**（`POST /v1/messages` + `x-api-key`），
OpenAI 协议端点不存在。所以做法是：

> 在 mavis 与网关之间加一层**协议桥**（`backend/app/llm_bridge.py`）——
> mavis 以为自己在跟 OpenAI 说话，桥把请求翻译成 Anthropic 协议。
> **mavis 源码一行不改**，桥是我们自己的代码。

桥还负责两件 mavis 不做的事（缺了会真出事）：

1. **永远返回合法 OpenAI 响应体**——mavis 不检查 HTTP 状态码，失败会被它静默重试
   10 次 × 5 秒（实测 64.9s 静默失败）。
2. **结构化输出兜底**——把 `response_format` 的 JSON Schema 写进系统提示，
   并对返回做 JSON 形状修复（补 `res` 外壳），否则 `dict.update(<字符串>)` 会直接崩。

密钥来源：桥从环境变量读 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`；
mavis 侧的 `LLM_API_KEY` 留空即可（桥不校验）。
两者都符合"凭据只从环境变量读"的红线。

### 3.2 配置骨架（`configs/mavis/config.json`，不含任何密钥）

```json
{
  "agent": {
    "think": {
      "llm": {
        "provider": "openai",
        "model": "deepseek-chat",
        "base_url": "<OpenAI 协议端点前缀，需能拼出 /chat/completions>",
        "api_key": ""
      }
    }
  }
}
```

密钥走环境变量 `LLM_API_KEY`，**绝不入仓**。

### 3.3 必须绕开的三处 mavis 包袱

mavis 是"空间化生成式智能体仿真"框架，直接拿来做参谋会带上三处无关负担。**不改源码的前提下**，
用配置与外部编排绕开：

| 包袱 | 表征 | 绕开方式 |
|---|---|---|
| 空间 / 迷宫 | `Game` 强制要求真实 `Maze`；`Agent` 绑 `coord` | 喂一张**退化最小地图**（≥3×3、单格可达），所有参谋钉在同一格 |
| 日程 | `Agent.think` 首步会调 LLM 生成日程 | `no_sleep: true` + 预置 `schedule.daily_schedule`；**阶段 0 必须实测**是否仍触发 LLM |
| 生活化提示词 | 内置模板是"起床 / 日程 / 闲聊"语境 | 用环境变量 `MAVIS_PROMPT_DIR` 指向**我方模板目录**，替换为参谋语境 |

### 3.4 ✅ 可行性验证已完成（2026-09-29）：结论是"降级方案"

阶段 0 已按计划执行完毕，完整数据见 [`docs/spike-0-report.md`](docs/spike-0-report.md)。结论：

**mavis 的 `Agent` 无法在不改源码的前提下被塑造成"参谋"。** 证据是逐轮推进的过程本身——
每修掉一个洞就冒出下一个隐式接口依赖（计时器方法 → `tile.events` → 空 spatial tree 的 `IndexError`），
而且：

- `Agent.completion()` 只认框架写死的 `prompt_*` 集合，**没有"给参谋建议"这一类**；
- `MAVIS_PROMPT_DIR` 只能换模板**文本**，换不了方法集合；
- `think()` 是"日程 → 感知 → 定行动 → 移动 → 计划 → 反思"的**生活仿真管线**，
  产物是行动计划，不是建议文本。

**因此正式采用降级方案（仍然一行不改 mavis）：**

> 只借 mavis 的公开工厂 `create_llm_provider()` 做模型接入，
> **并行参谋编排由我方自建**（共享一个 provider + `ThreadPoolExecutor`）。

**mavis 在本项目里的定位 = 模型接入层**（将来可选的 `Timer` / checkpoint），不是 Agent 运行时。

实测结果（Spike C）：

| 指标 | 数值 |
|---|---|
| 三路参谋并行总墙钟 | **1.34s**（= 最慢那一路） |
| 串行估算 | 3.65s |
| 并行收益 | **省 63%** |
| 输出质量 | 可直接使用（反驳手打出"法人作品主体可拟制"，审计员准确指认"偷换概念"） |

> 附带收益：因为有了协议桥，"有没有 OpenAI 协议通道"**不再是阻塞项**——
> 只要网关是 Anthropic 协议，桥就能把它翻给 mavis。

### 3.5 契约红线（来自 mavis 自身）

- `tests/test_extension_surface.py` **冻结**了 `Game` / `Simulator` / `load_config` 等签名与默认值。
- 框架源码**禁止出现业务词汇**。
- ⇒ **所有辩论业务逻辑必须放在 mavis 之外**（本仓库 `backend/` 内）。

---

## 4. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 多 Agent 底座 | **mavisframework**（只读依赖，`pip install`） | 一行不改；定位＝模型接入层（见 §3.4） |
| 协议桥 | **backend/app/llm_bridge.py**（FastAPI） | OpenAI 协议 ⇄ Anthropic 协议；含结构化输出兜底 |
| 后端 | **FastAPI + Uvicorn**（Python 3.13） | SSE 推建议、REST 收发言 |
| 结构化模型 | **pydantic v2** | 参谋建议、台账卡片强类型 |
| LLM | mavis `create_llm_provider(provider="openai")` → 本桥 | 凭据只在桥的环境变量里 |
| 并行编排 | **自建**（共享 provider + `ThreadPoolExecutor`） | 实测三路并行 1.34s，省 63% |
| 台账存储 | **SQLite** | 外置（mavis 记忆塞不下结构化卡片） |
| 前端 | **React + Vite + TypeScript** | 桌面优先，多栏建议流 |
| 通信 | **SSE** | ⚠️ mavis 无流式 → 前端用"建议卡片整块出现"，不做逐字流 |

---

## 5. 目录结构

```
ai-debator/
├── PLAN.md
├── README.md
├── .env.example                  # 只列变量名，不写值（已建）
├── docs/
│   └── spike-0-report.md         # 阶段 0 实测报告（已建）
├── configs/
│   ├── mavis/                    # 喂给 mavis 的配置（不是 mavis 的代码）
│   │   ├── config.json           # ✅ agent_base：provider=openai → 指向本桥
│   │   ├── assets/               # （阶段 1 起：退化最小地图 + 参谋角色）
│   │   └── prompts/              # MAVIS_PROMPT_DIR 预留
│   └── advisors.yaml             # 参谋团名单 + role_directive（待建）
├── backend/
│   ├── app/
│   │   ├── __init__.py           # ✅
│   │   ├── config.py             # ✅ 环境变量 / 路径
│   │   ├── llm_bridge.py         # ✅ 协议桥（OpenAI ⇄ Anthropic）+ 结构化输出兜底
│   │   ├── mavis_bridge.py       # ★ 与 mavis 的唯一边界（阶段 1）
│   │   ├── main.py               # ✅ FastAPI 入口 + SSE + 台账接口
│   │   ├── advisors/             # ✅ 参谋业务逻辑（mavis 之外）
│   │   │   ├── base.py
│   │   │   ├── rebutter.py       # 反驳手
│   │   │   ├── questioner.py     # 质询手
│   │   │   └── auditor.py        # 逻辑审计员
│   │   ├── orchestrator.py       # ✅ 并行调度
│   │   ├── consistency.py        # ✅ 立场一致性检测（阶段 3）
│   │   ├── ledger/store.py       # ✅ 论点台账（SQLite，外置）
│   │   ├── retrieval/            # ✅ 检索抽象 + 本地语料 + 引用回链核验（纯本地零消耗）
│   │   │   ├── base.py           #    Retriever 抽象 / LegalSource(带效力位阶) / CitationReport
│   │   │   ├── local_corpus.py   #    data/corpus 检索器（结构化法条 + 自由文本）
│   │   │   └── citations.py      #    引用抽取 + 三态核验 + 引述内容比对
│   │   └── export/report.py      # ✅ 复盘导出：Markdown / Word / HTML(打印→PDF)
│   ├── tests/                    # ✅ 单测（当前 156 项，计数见 README 徽章）
│   │   ├── conftest.py           #    ★ 在导入 app 之前把 LEDGER_DB/CORPUS_DIR 指向临时路径
│   │   ├── test_retrieval.py     #    23 项（引用抽取/归一/三态核验）
│   │   ├── test_benchmarks.py    #    9 项（用例校验/指标计算/对比判定）
│   │   └── test_api.py           #    15 项（API 端到端，TestClient，0 LLM 调用）
│   ├── benchmarks/runner.py      # ✅ 回归评估框架（自动指标 0 API 消耗）
│   ├── pytest.ini                # ✅ basetemp 指到项目内（本机沙箱不允许写系统临时目录）
│   ├── requirements.txt          # ✅ 后端依赖（mavis 为本地只读依赖，另行安装）
│   └── spikes/                   # ✅ 阶段 0 的三个验证脚本
│       ├── spike_01_provider.py
│       ├── spike_02_agent.py
│       └── spike_03_parallel_advisors.py
├── frontend/                     # ✅ React + Vite，桌面优先
│   └── src/components/{SettingsPanel,AdvisorColumn,LedgerPanel}.tsx
├── data/                         # ledger.db / checkpoints
│   └── corpus/README.md          # ✅ 法源语料格式说明（放入法条即可启用「已核验」）
└── benchmarks/                   # ✅ 回归用例与评估（结果目录已 gitignore）
    ├── README.md                 #    指标含义 + 怎么回答"改动是否变好"
    ├── cases/core.yaml           #    4 个初始用例
    └── results/                  #    评估产出（可随时重生成）
```

---

## 6. 分阶段路线

### 阶段 0 — mavis 底座联通 + 可行性验证 ✅ **已完成（2026-09-29）**

- **做了什么**：只读安装 mavis（v1.3.3）；建协议桥；验证 provider 直连；构造 Agent 并驱动 `think()`；
  验证三路并行参谋。
- **实测结论**：见 §3.4 与 [`docs/spike-0-report.md`](docs/spike-0-report.md)。
  - 底座联通 ✅（0.85s，输出正确）；
  - `Agent` 当参谋 ❌（架构性，每修一洞冒一洞）；
  - 降级方案 ✅（三路并行 1.34s，省 63%，输出可用）。
- **关键修复**：桥的结构化输出兜底，把一步 `think` 从 **64.93s / 12 次调用**降到 **5.6s / 3 次**。
- **产出**：`backend/app/llm_bridge.py`、`backend/app/config.py`、`backend/spikes/spike_0{1,2,3}_*.py`、
  `docs/spike-0-report.md`、`.env.example`、`README.md`。

### 阶段 1 — 单路参谋：反驳手（下一步）
- **做什么**：输入"辩题 + 我方立场 + 对方发言"→ 输出结构化反驳建议（pydantic）：
  反驳要点、依据、置信度。
- **交付**：`POST /api/analyze` 返回 JSON；prompt 模板与 `role_directive` 定稿。
- **验收**：给定一段对方发言，产出 ≥2 条直接可用的反驳要点；空话/复读视为不合格。

### 阶段 2 — 三路并行参谋 + 前端面板 ✅ 已扩至五路
- **做什么**：反驳手 + 质询手 + 逻辑审计员**同时**跑；建议经 SSE 推前端，多路并列展示。
- **验收**：一次提交后各路建议在可接受延迟内并行返回；前端能区分来源并标出谬误类型。
- **后续扩充（已完成）**：新增 **解释方法策略师**（争夺解释方法适用优先性，交接文档 §3.4）
  与 **风险提示员**（唱反调：对方陷阱 / 我方薄弱 / 事实不清 / 法源不稳），共 5 路。
  实测（只跑新增两路，2 次调用）：策略师正确识别"对方用文义解释 → 我方主张目的解释优先"；
  风险提示员给出 3 类风险。前端改为自适应网格，导出报告同步支持两路新结构。

### 阶段 3 — 论点台账 + 立场一致性
- **做什么**：建议卡片落 SQLite；记录"我方已主张过什么"，检测**立场漂移**
  （参谋建议不得与用户此前立场冲突）。
- **验收**：台账可查；出现自相矛盾建议时能标红。

### 阶段 3 — 论点台账 + 立场一致性 ✅ **已完成（2026-09-29）**
- **做了什么**：SQLite 台账（`ledger/store.py`：sessions / turns / cards / suggestions 四表）+
  立场一致性检测（`consistency.py`）+ 前端台账面板。
- **两道闸防立场漂移**：
  1. **预防**：每次分析都把台账里"我方已主张"（仅 standing）注入参谋提示词；
  2. **检测**：新增端点 `POST /api/session/{sid}/check-consistency`，把新生成的建议与台账比对，
     找出**不能同时为真**的冲突，前端高亮标红。
- **实测**：故意喂入一条与台账相反的主张 → 准确命中冲突并给出理由；
  同时正确放过了无关主张（"AI 训练数据应当付费"未被误报）——即"宁可漏报不可误报"的纪律生效。
- **设计取舍**：一致性检测**不放进 `/api/analyze` 热路径**（现场延迟敏感），
  由前端在建议返回后再调一次。
- **新增接口**：`POST /api/session`、`GET /api/sessions`、`GET /api/session/{sid}`、
  `POST /api/session/{sid}/cards`、`PATCH /api/cards/{cid}`、`DELETE /api/cards/{cid}`、
  `POST /api/session/{sid}/check-consistency`。
- **踩坑**：参谋的结构化输出是 pydantic 实例（`list[Rebuttal]`），落库 `json.dumps` 会
  `TypeError`。修法是在源头用 `schemas.jsonable()` 摊平，落库与出参一并干净。

### 阶段 4 — 检索与引用核验 🟡 **本地部分已完成；真实检索通道待接**
- **已完成（纯本地，零 API 消耗）**：
  - `retrieval/base.py` —— `Retriever` 抽象、`LegalSource`（**带效力位阶**，防"把学说当法条"）、
    `CitationCheck` / `CitationReport`、`NullRetriever` 兜底；
  - `retrieval/local_corpus.py` —— 本地语料检索器：`data/corpus/*.json` 结构化法条（**可判"已核验"**）
    + `*.md/.txt` 自由文本（只能判"存疑"）；条款号中文/阿拉伯数字归一（`第11条`＝`第十一条`）、
    法名容忍（`《著作权法》`＝`《中华人民共和国著作权法》`）；
  - `retrieval/citations.py` —— 引用抽取 + **回链核验**，三级状态：已核验 / 存疑 / 未核验；
  - `GET /api/retrieval`、`POST /api/session/{sid}/verify-citations`（**不调用任何 LLM**）；
  - 前端「引用核验」面板：计数 + 逐条状态 + 原文证据 + 重载语料；
  - `data/corpus/README.md` 写明语料格式与三种状态的含义。
- **判定原则（保守）**：**只有结构化语料里确实查到该条款才给「已核验」并附原文**；
  只给法名不给条款号 → 存疑（**不能用"该法首条"兜底，那是假阳性**）；
  自由文本命中 → 存疑（无法证明条款号与内容对应）；无语料 → 一律未核验。
- **实测**：23 项单元测试全绿（`backend/tests/test_retrieval.py`，用**编造的假法名**做语料，
  避免把可能有误的真实法条写进仓库）；三态核验经 HTTP 端到端验证通过。
- **仍待接**：真实法源检索通道（搜索 API / 连接器）。接入方式＝新增一个 `Retriever` 子类，
  业务代码不动。语料来源与格式见 `data/corpus/README.md`。

### 阶段 5 — 导出 + 现场保障
- **做什么**：复盘导出（Word / PDF / Markdown）；延迟预算与降级（模型超时 → 退避 → 降级；
  建议按置信度截断）；断线重连。
- **验收**：导出可用；降级演练不崩。

### 阶段 5 — 导出 + 现场保障 ✅ **已完成（2026-09-29）**
- **已完成：复盘导出**（`export/report.py`）：把「对方发言 + 三路参谋建议 + 我方台账」
  整理成报告，支持三种格式：
  - `GET /api/session/{sid}/export.md` —— Markdown，后端直接产出（实测 2.8KB，结构完整）；
  - `GET /api/session/{sid}/export.docx` —— Word，python-docx 产出，含台账表格
    （实测 38KB，OOXML 合法，31 段 + 1 张 4 列表）；
  - `GET /api/session/{sid}/export.html` —— **打印优化页**，前端唤起打印对话框另存为 PDF。
- **PDF 的设计取舍**：不直接生成 PDF。中文 PDF 需内嵌 CJK 字体，缺字体会变方块；
  浏览器打印用系统字体，零依赖且排版最好。已在代码与 README 中写明理由。
- **现场保障（三件）**：
  1. **时间预算与超时降级** —— `orchestrator.run_advisors(..., budget_s=)`：
     到点即交付已好的结果，超预算的参谋标 `timeout` 并立刻推送，**不阻塞**其他几路。
     实测：预算 1.6s → 质询手(1.05s)/审计员(1.22s) 正常返回、反驳手标超时，
     总耗时 1.62s 返回（而不是等反驳手跑完的 ~2s+）。前端有预算下拉（8s/12s/20s/不限）。
  2. **延迟仪表** —— `GET /api/metrics`：各路参谋的 P50 / P95 / 最慢 / ok / timeout / error，
     数据来自 `suggestions` 表历史全量；前端「现场仪表」面板展示。
  3. **断线恢复** —— 参谋**算完一路就落库**（`store.save_suggestion`），
     SSE 断开时前端从会话快照把已算好、但没推到的路补齐，**不必重花一次 token**。
     刻意不做"自动重跑"：重连会再花钱，改为提示 + 一键重跑。

### 阶段 6 · 附 — 回归测试与评估框架 ✅ **已完成（2026-09-30）**
对应交接文档「坑 5：评估缺位」——没有固定测试集，就无法判断改动是变好了还是只是变长了。
- **核心原则：能自动算的指标一律不花 API。**
  | 指标 | 算法 | 消耗 |
  |---|---|---|
  | 涵摄完整率 | 反驳手每条论点的四段是否都非空 | 0 |
  | 要点覆盖率 | 用例声明的 `focus` 关键词命中率 | 0 |
  | 引用核验率 | 走本地法源语料 | 0 |
  | 延迟 P50/P95、超时/失败数 | 从 `suggestions` 表算 | 0 |
  | 建议可用率 | **需人判断**，框架不代劳 | — |
- **命令**（`backend/` 下）：`list` / `check` / `eval <sid>` / `compare a.json b.json` 全为 0 消耗；
  只有 `run --live --confirm` 会真跑模型，**不带 `--live` 时只报预计调用量然后退出**（防手滑）。
- **产物**：`benchmarks/cases/core.yaml`（4 个初始用例，覆盖民法/刑法/个人信息/法理）、
  `benchmarks/README.md`、`backend/benchmarks/runner.py`、结果写入 `benchmarks/results/`（已 gitignore）。
- **实测（0 消耗）**：对已有会话评估 → 涵摄完整率 **1.0**、要点覆盖率 **0.8**、引用核验率 0.0
  （无语料，如实为 0）、P50 1.99s / P95 3.03s、0 超时 0 失败。
- **诚实说明**：要点覆盖率是**粗信号**，只回答"话题有没有被碰到"，**不回答"论证好不好"**；
  关键词可用堆术语刷出来。已在 README 中明确标注，不当质量分用。

### 阶段 7（后置）— 语音实时转写（ASR）
- **做什么**：麦克风采集 + ASR → 自动分段 → 触发参谋。
- **前置**：需先定 ASR 方案（浏览器 Web Speech / 本地 Whisper / 云 ASR）。

---

## 7. 核心数据结构

### 7.1 参谋建议 `AdvisorSuggestion`
```json
{
  "id": "S-0007",
  "advisor": "rebutter | questioner | auditor",
  "针对发言": "对方发言片段或轮次号",
  "内容": "建议正文",
  "类型": "反驳 | 质询问题 | 谬误指认",
  "谬误类型": "稻草人 | 滑坡 | 循环论证 | 诉诸权威 | null",
  "依据": { "规范": "《民法典》第XXX条", "来源ID": "SRC-3", "核验状态": "未核验" },
  "置信度": 0.0,
  "时间戳": "2026-09-29T20:53:00+08:00"
}
```

### 7.2 台账卡片 `LedgerCard`（我方已主张，防立场漂移）
```json
{
  "id": "A-01",
  "立场": "我方",
  "主张": "...",
  "依据": "《民法典》第XXX条",
  "被质疑次数": 0,
  "状态": "standing | weakened | abandoned"
}
```

### 7.3 参谋团配置 `configs/advisors.yaml`
```yaml
advisors:
  - name: rebutter    # 反驳手：涵摄三段式反驳要点
    label: 反驳手
    enabled: true
  - name: questioner  # 质询手：可立即抛出的问题
    label: 质询手
    enabled: true
  - name: auditor     # 逻辑审计员：只指认谬误
    label: 逻辑审计员
    enabled: true
  - name: strategist  # 解释方法策略师：争夺解释方法优先性（交接文档 §3.4）
    label: 解释方法策略师
    enabled: true
  - name: risk        # 风险提示员：唱反调（对方陷阱/我方薄弱/事实不清/法源不稳）
    label: 风险提示员
    enabled: true
```

---

## 8. 风控与降级

| 风险 | 触发 | 处置 |
|---|---|---|
| 幻觉引用 | 编造法条 / 判例 | 阶段 1-3 一律标注"未核验"；阶段 4 加回链核验 |
| 立场漂移 | 建议与用户此前主张冲突 | 台账比对 + 标红 |
| 谄媚式附和 | 输出"对方也有道理"类空话 | prompt 黑名单 + 命中重写 |
| mavis 无流式 | 用户以为会逐字出 | 前端改为"卡片整块出现"，用短输出 + 并行压延迟 |
| 日程 LLM 开销 | `Agent.think` 首步调 LLM 生成日程 | 阶段 0 实测；规避不掉则走 3.4 降级方案 |
| 模型超时 / 限流 | 网关不稳 | 退避重试 → 降级 → 部分结果先行展示 |
| 现场延迟超预算 | 单次分析过慢 | 按置信度截断建议、减少路数、缩短输出上限 |

---

## 9. 评估

- **回归用例**：`benchmarks/` 下固定"辩题 + 对方发言样本 + 期望建议要点"，改动后跑批对比。
- **两个核心指标**：① 建议可用率（人工判定"能直接用"的比例）；② 引用核验通过率。
- **延迟指标**：单次分析的 P50 / P95（现场模式的生死线）。

---

## 10. 环境与运行

| 项 | 值 |
|---|---|
| Python（托管） | `/Users/ruige/.workbuddy/binaries/python/versions/3.13.12/bin/python3` |
| 虚拟环境 | `/Users/ruige/.workbuddy/binaries/python/envs/default` |
| Node（托管） | `/Users/ruige/.workbuddy/binaries/node/versions/22.22.2-3/bin/node` |
| mavis 本地仓库 | `/Users/ruige/Documents/GTC/mavis`（已快进到 v1.3.3 / `511dea0`） |
| mavis 安装方式 | `pip install /Users/ruige/Documents/GTC/mavis`（非 editable，仓库不受污染） |
| 模型密钥 | 环境变量 `LLM_API_KEY`（mavis 原生读取）**绝不入仓** |
| 沙箱限制 | 本环境无网络（HTTPS 经代理 502），联网操作需显式放行 |

---

## 11. 待你确认 / 风险登记

1. ~~OpenAI 协议通道的 `base_url`~~ **已解除阻塞**：协议桥把 Anthropic 协议端点翻给了 mavis，
   不需要额外的 OpenAI 通道。只需在环境变量里配 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`。
2. **ASR 方案**（阶段 7 前置）：浏览器 Web Speech / 本地 Whisper / 云 ASR，三选一。
3. **现场麦克风与收音条件**：多人辩论现场收音是 ASR 成败的关键。
4. **队友访问方式**：先本地跑通后，"局域网直连"还是需要内网穿透？
5. **赛制与学科方向**：目前仍是"暂无 / 不确定"，不影响阶段 0-3；一旦确定，
   只需改 `advisors.yaml` 与提示词模板，架构不动。

---

_本计划不写任何凭据；mavis 以只读依赖接入，全部辩论业务逻辑位于本仓库内。_
