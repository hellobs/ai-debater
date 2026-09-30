<div align="center">

# ai-debater

### 通用辩手参谋台 · 落地 AI + 法学

**对方说完一段，五路 AI 参谋并行出主意 —— 用不用，你说了算。**

[![License](https://img.shields.io/badge/license-Apache--2.0-3b82f6?style=flat-square&labelColor=1f2328)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-105%20passing-2ea043?style=flat-square&labelColor=1f2328)](backend/tests)
[![Python](https://img.shields.io/badge/python-%E2%89%A5%203.12-3776ab?style=flat-square&labelColor=1f2328)](backend/requirements.txt)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688?style=flat-square&labelColor=1f2328)](backend/app)
[![Frontend](https://img.shields.io/badge/frontend-React%2018%20%2B%20Vite-61dafb?style=flat-square&labelColor=1f2328)](frontend/src)
[![Model](https://img.shields.io/badge/model-deepseek--chat%20%7C%20local%20LLM-8b5cf6?style=flat-square&labelColor=1f2328)](#零成本运行本地模型)

[**简体中文**](README.md) ｜ [English](README.en.md)

</div>

---

> ### 它是什么
>
> 你站在台上打辩论。对方说完一段，系统**并行**跑五路 AI 参谋，各自给你出主意：
> **反驳要点 · 质询问题 · 逻辑谬误 · 解释方法之争 · 风险提示**。
> 全部 Agent 站在你这一边，用不用由你判断。

<table>
<tr><th align="left" width="50%">这是</th><th align="left" width="50%">这不是</th></tr>
<tr>
<td valign="top">

- 多 Agent **并行参谋团**，各出一路主意
- **现场**实时辅助（目标：< 2s 内交付）
- 到点就交付——超预算的那路标 `timeout`，不拖住其余
- AI 只**出主意**，决策权在人

</td>
<td valign="top">

- AI 对 AI 自动互搏
- 裁判打分 / 胜负判定 / Elo
- 辩论赛制状态机、发言权交替
- 替人上台、替人定稿

</td>
</tr>
</table>

**接手开发请先读 [`HANDOVER.md`](HANDOVER.md)** —— 背景 / 决策 / 架构 / 已知坑 / 成本红线 / 待办，一份讲透。

---

## 目录

- [亮点](#亮点)
- [架构](#架构)
- [快速开始](#快速开始)
- [零成本运行：本地模型](#零成本运行本地模型)
- [辩题与立场：提前配置](#辩题与立场提前配置)
- [五路参谋](#五路参谋)
- [两道闸：防立场漂移与引用核验](#两道闸防立场漂移与引用核验)
- [测试与回归评估](#测试与回归评估)
- [项目结构](#项目结构)
- [文档索引](#文档索引)
- [安全红线](#安全红线)
- [已知局限](#已知局限)
- [许可证](#许可证)

---

## 亮点

| | 说明 |
|---|---|
| **真并行** | 五路参谋同时发起，总墙钟 = 最慢那一路。三路实测 **1.34s**，较串行省 **63%** |
| **到点交付** | 关键不是"全部返回"，而是**按时交付已就绪的部分**。超预算的一路标 `timeout` 立刻推送，不阻塞其他 |
| **不改底座** | mavis 框架以**只读依赖**接入，一行未改；所有辩论业务逻辑都在本仓库 |
| **防幻觉** | 引用核验由**程序核对语料**判定三态，不采信模型自称的"我会标注待核验" |
| **零成本迭代** | 一条命令接本地模型，整条链路不产生任何费用，可放心改 prompt / schema |
| **有证据链** | 每个架构决策都有实测报告兜底（阶段 0 报告记录了 mavis 逐轮失败的完整过程） |

---

## 架构

```mermaid
flowchart TB
    FE["前端 · React + Vite · 桌面浏览器<br/>设置面板 / N 列参谋建议 / 台账 / 仪表 / 引用核验 / 导出"]

    subgraph BE["后端 · FastAPI :8010"]
        OR["编排器 orchestrator<br/>并行分发 + 时间预算"]
        ADV["参谋团 advisors × 5"]
        AUX["台账 · 一致性检测 · 引用核验 · 导出"]
    end

    MB["mavis_bridge<br/>与 mavis 的唯一边界 · create_llm_provider()"]
    BR["协议桥 llm_bridge.py :8011<br/>OpenAI ⇄ Anthropic · JSON 形状修复"]
    GW["模型网关<br/>deepseek-chat"]
    OL["Ollama :11434<br/>本地模型 · 零成本"]

    FE -- "POST /api/analyze" --> OR
    OR -. "SSE 流式推送" .-> FE
    OR --> ADV
    ADV --> MB
    MB --> BR
    BR --> GW
    MB -. "本地模式直连（协议桥不参与）" .-> OL
    OR --> AUX
```

**数据流**：对方发言（文本）→ 后端建/取会话 + 注入台账 → 五路参谋**并行**分析 →
各路算完即落库并经 SSE 推送 → 前端多列展示 → 一致性检测与引用核验（独立端点，不进热路径）。

**两个关键判断**（详细证据见 [`docs/spike-0-report.md`](docs/spike-0-report.md)）：

- mavis 在本项目中**只当模型接入层**，不当 Agent 运行时。它的 `Agent.think()` 是"日程 → 感知 → 定行动 → 移动 → 计划 → 反思"的生活仿真管线，产物是行动计划而非建议文本，且只认框架写死的 `prompt_*` 集合——没有"给参谋出主意"这一类。
- 可用网关只提供 **Anthropic 协议**（`POST /v1/messages` + `x-api-key`），而 mavis 的 LLM 层只会说 **OpenAI 协议**——**必须**有一个协议桥，且桥不做不行的那两件事见下。

<details>
<summary><b>为什么必须有一个协议桥（展开）</b></summary>

桥只做协议翻译，**不改 mavis**。它还负责两件 mavis 自己不做的事，缺了会真出事：

1. **永远返回合法的 OpenAI 响应体** —— mavis **不检查 HTTP 状态码**，只读 `choices[0].message.content`。桥若出错时返回非 JSON，mavis 会走 10 次重试 × `sleep(5)` = **50 秒静默失败**（实测过一次 64.9s / 12 次调用）。
2. **结构化输出兜底** —— mavis 靠 `response_format`(json_schema) 拿结构化结果，而 Anthropic 协议没有该字段。桥把 schema 写进系统提示，**并对返回做 JSON 形状修复**（mavis 的 pydantic 模型统一形如 `{"res": ...}`，模型经常丢掉外层包装）。这一项把一步 `think` 从 **64.93s / 12 次调用**降到 **5.6s / 3 次**。

</details>

---

## 快速开始

### 1. 一键引导

```bash
git clone https://github.com/hellobs/ai-debater.git
cd ai-debater
bash scripts/bootstrap.sh
```

脚本只做三件事：克隆 mavis（只读依赖）、装依赖、跑 105 项测试。
**它不会调用任何模型，不产生任何费用。**

可用环境变量覆盖默认值：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PYTHON_BIN` | `python3` | 需要 ≥ 3.12 |
| `VENV` | `<仓库>/.venv` | 虚拟环境目录 |
| `MAVIS_DIR` | `<仓库>/../mavis` | mavis 放在仓库同级 |
| `MAVIS_REPO` | 官方 HTTPS 地址 | 没有 SSH key 时用 HTTPS |

### 2. 凭据（只走环境变量，绝不入仓）

```bash
cp .env.example .env     # 填写后生效；.env 已被 .gitignore 排除
```

协议桥需要 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN`，模型名走 `LLM_MODEL`（默认 `deepseek-chat`）。
**没有凭据也能跑**：105 项测试、引用核验、导出、回归评估全部离线可用，只有"真跑一轮参谋"需要它。

### 3. 起服务

```bash
export VENV=.venv        # Windows: .venv/Scripts/python.exe

# 1) 协议桥（mavis 指向它，必须最先起；本地模型模式下可跳过）
cd backend && LLM_BRIDGE_PORT=8011 "$VENV/bin/python" -m app.llm_bridge

# 2) 后端          → http://127.0.0.1:8010
cd backend && "$VENV/bin/python" -m app.main

# 3) 前端          → http://127.0.0.1:5173
cd frontend && npm run dev
```

### 4. 验证（0 API 消耗）

```bash
curl -s http://127.0.0.1:8011/healthz      # 协议桥
curl -s http://127.0.0.1:8010/api/health   # 后端（含参谋团名册元数据）
curl -s http://127.0.0.1:8010/api/topics   # 辩题库
cd backend && "$VENV/bin/python" -m pytest # 105 项测试
```

---

## 零成本运行：本地模型

不想花 token 时，让 mavis 直连本机 Ollama，**整条链路零费用**：

```bash
ollama serve &                              # 前置：本地模型服务
bash scripts/run_local.sh                   # 后端 :8010，0 消耗
# 可选：OLLAMA_MODEL=qwen3:8b LLM_CONCURRENCY=3 bash scripts/run_local.sh
```

原理：把 `LLM_BRIDGE_URL` 指向 Ollama 的 OpenAI 兼容端点（`http://127.0.0.1:11434/v1`），
**零代码改动**；Ollama 原生支持 `response_format=json_schema`，
所以**这个模式下协议桥不需要启动**。

> **能力边界（实测，重要）**：本地 4B 模型在**逻辑审计员**一路上系统性失效——
> 面对教科书级的以偏概全/滑坡也返回空列表。
> **链路自检、端到端回归、前端联调 ✅ 可用；现场实战 ❌ 不行。**
> 原始证据与延迟数据见 [`docs/local-model-report.md`](docs/local-model-report.md)。

| 用途 | 本地 4B 够用吗 |
|---|---|
| 链路自检、端到端回归、前端联调 | 完全够用，且零成本 |
| 改 prompt / schema 后的快速验证 | 够用（结构正确性可验证，质量不可信） |
| 评估"改动是否变好" | 只能看结构与延迟，质量判断仍须云端模型 |
| 现场实战 | 不行（审计员失效是不可接受的缺口） |

---

## 辩题与立场：提前配置

辩题不是界面上手打的一个字符串，而是**可预置、可复用的一条资产** ——
辩题、双方立场、对方最可能说的第一句话，绑在一起。

```yaml
# configs/topics.yaml（入仓预设，直接改这个文件就是"提前配置"）
topics:
  - id: ai-copyright
    domain: AI + 法学
    title: AI 生成内容是否应享有著作权
    side_a: 控方（主张应享有）      # 选定辩题后自动成为"我方立场"
    side_b: 辩方（主张不应享有）
    opponent_hint: 著作权法只保护自然人的智力成果，AI 不是人……   # 一键填进"对方刚说的话"
    note: 独创性判断标准与权利主体适格性。
```

- **`configs/topics.yaml`** —— 入仓预设，团队共享，手写即配置；
- **`data/topics.json`** —— 界面上「保存为我的辩题」存的那份，**不入仓**（与 `ledger.db` 同一约定）；
- 运行时两者**并集**返回，同 `id` 时本机覆盖预设。**库为空就返回空**，界面退化为纯自由输入。

```bash
curl -s http://127.0.0.1:8010/api/topics          # 取整个辩题库
# 存一条本机辩题（id 留空则按标题自动生成，同标题覆盖）
curl -s -X POST http://127.0.0.1:8010/api/topics \
  -H 'content-type: application/json' \
  -d '{"title":"大学应当把人工智能设为必修课","side_a":"正方","side_b":"反方"}'
curl -s -X DELETE http://127.0.0.1:8010/api/topics/local-1a2b3c4d   # 只删得掉本机那份
```

### 通用平台，而不是法学专用

平台定位是**通用辩手参谋台**，「AI + 法学」是它的落地场景之一。所以：

- **辩题带 `domain`**，界面上按场景分组（`通用` / `AI + 法学` / `我的辩题`）；
- **参谋名册带 `domain`**，标出哪一路是某个场景专用的 —— 五路里只有**解释方法策略师**深度绑定法学，
  界面上会带一个 `法学` 小标，不做静默替换；
- 品牌、导出报告标题、`advisors.yaml`、`topics.yaml` 里都没有"法学"二字的硬编码。

⚠️ **还没解耦的一层**：参谋的**角色指令**仍带法学措辞（反驳手要求"大前提 = 法律规范"、
风险提示员要求"法源不稳"）。通用辩题下这几路会以法律框架去思考。
这是提示词层的领域解耦，**尚未开工** —— 见 [`HANDOVER.md`](HANDOVER.md) 的待办。

---

## 五路参谋

| 参谋 | 产出 | 领域 | 设计依据 |
|---|---|---|---|
| **反驳手** | 涵摄三段式反驳要点（主张 / 大前提 / 小前提 / 结论） | 通用 | 交接文档 §3.1 涵摄结构 |
| **质询手** | 可立即抛出的质询问题 | 通用 | — |
| **逻辑审计员** | 谬误类型 + 原话片段 | 通用 | 交接文档 §5.1 |
| **解释方法策略师** | 对方用了哪种解释方法 → 我方应主张哪种优先 | **法学** | 交接文档 §3.4「争夺解释方法适用优先性」 |
| **风险提示员** | 对方陷阱 / 我方薄弱 / 事实不清 / 法源不稳 | 通用 | 交接文档「坑 1 立场漂移」 |

**加一路参谋**：`backend/app/advisors/` 新增模块（继承 `Advisor` + 定义 `output_model`）→
在 `advisors/__init__.py` 的 `REGISTRY` 注册 → `configs/advisors.yaml` 加一行 →
`AdvisorColumn.tsx` 加渲染分支。**前端不用改名册**（它读 `/api/health`）。

`configs/advisors.yaml` 是名册的**唯一来源**：`label` / `kind` / `domain` 都在这里覆盖，
`enabled: false` 临时停用某一路，**列表顺序即界面顺序**。

---

## 两道闸：防立场漂移与引用核验

**闸一 · 立场一致性**（防"自己打自己"）

1. **预防**：每次分析把台账里仍成立的主张（`standing`）注入参谋提示词；
2. **检测**：`check-consistency` 把新建议与台账比对，找出**不能同时为真**的冲突，前端标红。

检测**刻意不放进 `/api/analyze` 热路径**（现场延迟敏感），由前端在建议返回后再调一次。
实测：故意喂一条与台账相反的主张 → 准确命中冲突，同时**正确放过了无关主张**（未误报）。

**闸二 · 引用核验**（防法条幻觉，三态保守判定）

| 状态 | 含义 |
|---|---|
| **已核验** | 结构化语料里确实有这一条，附原文为证 |
| **存疑** | 该法存在但语料里没这条（可能编造，也可能语料不全）；或只在自由文本里出现 |
| **未核验** | 语料里根本没有这部法 |

只给法名不给条款号 → 存疑，**不能用"该法首条"兜底**（那是假阳性，已踩过一次）。

把法条喂进语料就能启用「已核验」，**零代码改动、零 API 消耗**：

```bash
python scripts/import_corpus.py 著作权法.txt --law 中华人民共和国著作权法   # 全文 → laws.json
curl -s "http://127.0.0.1:8010/api/retrieval?reload=true"                  # 让后端重读语料
```

---

## 测试与回归评估

```bash
cd backend
"$VENV/bin/python" -m pytest                     # 105 项，全绿，0 API 消耗
"$VENV/bin/python" -m benchmarks list            # 回归用例
"$VENV/bin/python" -m benchmarks check <case>    # 结构自检（不调模型）
"$VENV/bin/python" -m benchmarks eval <case>     # 自动指标（0 消耗）
"$VENV/bin/python" -m benchmarks run --live --confirm   # 唯一真跑模型的入口
```

**要点覆盖率是粗信号**：它只回答"话题有没有被碰到"，**不回答"论证好不好"**，关键词可以靠堆术语刷分。
指标口径见 [`benchmarks/README.md`](benchmarks/README.md)——**不要当质量分用**。

---

## 项目结构

```
ai-debater/
├── HANDOVER.md              交接文档（先读这份）
├── PLAN.md                  实施计划 v2.0
├── docs/                    实测报告 · 决策日志 · 导出样例
├── configs/
│   ├── advisors.yaml        参谋团名册（唯一来源：label/kind/domain 都在这改）
│   ├── topics.yaml          预设辩题库（辩题 + 双方立场 + 对方例句）
│   └── mavis/config.json    ⚠️ 历史遗留，运行时不再读取
├── scripts/
│   ├── bootstrap.sh         一键引导（克隆 mavis + 装依赖 + 跑测试）
│   ├── run_local.sh         本地模型零成本启动
│   └── import_corpus.py     法律全文 → data/corpus/laws.json（启用「已核验」）
├── backend/
│   ├── app/
│   │   ├── main.py          入口 + 全部路由 + SSE
│   │   ├── config.py        环境变量与路径
│   │   ├── llm_bridge.py    协议桥
│   │   ├── mavis_bridge.py  与 mavis 的唯一边界
│   │   ├── orchestrator.py  并行编排 + 时间预算
│   │   ├── topics.py        辩题库（预设 + 本机自建）
│   │   ├── advisors/        五路参谋 + REGISTRY
│   │   ├── ledger/          论点台账（SQLite，逐条落库）
│   │   ├── retrieval/       检索与引用核验（纯本地）· statute_text.py 法条文本解析
│   │   └── export/          导出 Markdown / Word / HTML(打印→PDF)
│   ├── benchmarks/          回归评估框架（自动指标 0 消耗）
│   ├── tests/               105 项测试
│   └── spikes/              阶段 0 验证脚本（保留作证据）
├── frontend/src/            React + TS，手写样式，无 UI 框架
└── data/corpus/             法源语料（格式见其中 README）
```

---

## 文档索引

| 文档 | 作用 |
|---|---|
| [`HANDOVER.md`](HANDOVER.md) | 交接全景：背景 / 决策 / 架构 / 已知坑 / 成本红线 / 待办 |
| [`PLAN.md`](PLAN.md) | 实施计划 v2.0，含分阶段路线与验收标准 |
| [`docs/decision-log.md`](docs/decision-log.md) | 决策与踩坑日志——为什么这么定 |
| [`docs/spike-0-report.md`](docs/spike-0-report.md) | 阶段 0 实测：决定架构走向的关键证据 |
| [`docs/local-model-report.md`](docs/local-model-report.md) | 本地模型（零成本）接入实测 |
| [`benchmarks/README.md`](benchmarks/README.md) | 回归指标含义与"改动是否变好"怎么回答 |
| [`data/corpus/README.md`](data/corpus/README.md) | 法源语料格式（放入法条即可启用「已核验」） |

### 导出格式

| 格式 | 端点 | 说明 |
|---|---|---|
| Markdown | `GET /api/session/{sid}/export.md` | 后端直接产出文件 |
| Word | `GET /api/session/{sid}/export.docx` | 后端用 python-docx 产出（含台账表格） |
| PDF | `GET /api/session/{sid}/export.html` | **打印优化页面**，浏览器唤起打印对话框，选"存储为 PDF" |

> PDF 为什么走"打印页"而不是直接生成：中文 PDF 需要内嵌 CJK 字体，缺字体会变成方块；
> 浏览器打印用系统字体，零依赖、排版最好。见 `backend/app/export/report.py` 顶部说明。

---

## 安全红线

`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `LLM_API_KEY` **只从环境变量读取**，
绝不写入代码、配置或文档。仓库内无任何硬编码密钥。

**成本红线**：点一次分析 = 5 次上游调用；**超时也计费**（超时只是本地不等，请求已发出）。
任何会产生真实消耗的测试，先问人。

---

## 已知局限

1. 阶段 0–2 的 API 消耗没有完整账目（账本表是阶段 3 才加的）。
2. 要点覆盖率是粗信号，不代表论证质量。
3. 引用核验只回答"这条引用在所给语料中是否存在"，不判断引用是否恰当、法条是否被正确适用。
4. 前端未做移动端适配（目标设备为笔记本浏览器）。
5. ASR（语音实时转写）与真实法源检索通道**未接入**，两者都已预留接口。

---

## 许可证

[Apache-2.0](LICENSE)

<div align="center">
<sub>所有 Agent 站在你这一边。用不用，你说了算。</sub>
</div>
