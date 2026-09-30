# 决策与踩坑日志（随仓库走）

> **为什么要单独写这份**：原始的讨论记录与记忆文件在 `.workbuddy/memory/`，
> 而 `.workbuddy/` 是 gitignore 的——**换一台电脑 clone 下来就没有了**。
> 本文件把其中**跨会话仍有价值**的部分固化进仓库，保证交接不断线。
>
> 按时间倒序不重要，按主题聚合才有用。

---

## 1. 产品定义是怎么变的（最重要，别改回去）

**起点**：用户给的原始交接文档写的是「正反方 AI 自动互搏 + 裁判打分」。

**转折**：开发中途用户澄清了一句关键的话：

> **「我这个多 Agent 是同时为我出主意的」**

于是产品**整体重新定义**（PLAN v1.0 → v2.0，v1.0 全文保留在提交 `871b0a5`）：

- 不是 AI 打 AI，而是**一支并行参谋团，全部站在用户这一边**；
- AI 只出主意，**用户自己决定用不用**；
- 主场景是**现场辅助**（用户在台上、对方说完一段、系统给建议）。

**为什么这个转向让架构变简单**：没有回合交战，就没有"谁该发言""谁赢了"的问题。
原方案里的**赛制状态机、发言权交替、胜负判定、Elo 全部被砍掉**。

**接手者请注意**：如果不读这段，很容易"好心"把互搏、裁判、赛制加回来——那会推翻整个设计。

### 1.1 第二次修正：从「法学辩论台」放宽为「通用辩手台」

后来用户又澄清了一句：

> **「我还是希望这个平台是个通用的辩手平台，只不过最终落地是 AI + 法学的」**

起点是用户发现**界面上只有一个写死的样例辩题**（`App.tsx` 里的 `SAMPLE_TOPIC` 常量）。顺着查出
"法学"被焊死在**四处**：品牌文案、参谋名册、立场预设、样例辩题。

**结论与做法**：法学是**落地场景**，不是平台的定义。于是：

| 层面 | 做法 |
|---|---|
| 品牌 | 统一为「辩手参谋台」，收进 `config.BRAND_NAME`（前端与 FastAPI title 同源） |
| 辩题 | 从硬编码常量 → `configs/topics.yaml`（入仓预设）+ `data/topics.json`（本机自建） |
| 立场 | 从写死的四选项 → **由辩题带出**（`side_a` / `side_b` 是辩题的一部分） |
| 名册 | 从三份副本（类属性 / 没人读的 YAML label / 前端 `COLUMNS`）→ **一份** `advisors.yaml`，前端读 `/api/health` |
| 场景标注 | 辩题与参谋都带 `domain`，界面按场景分组 / 打标（`通用` / `AI + 法学`） |

**关键是"单一来源"这条原则**：辩题、名册、品牌各只允许定义一次。
判据很具体——**同一个事实在仓库里出现两次以上，就是 bug 的温床**（本轮修的就是这个）。

⚠️ **仍有一层没解耦**：参谋的**角色指令**还是法学措辞。为什么不顺手改？
因为改提示词 = 改模型行为，**必须真跑一轮（5 次上游调用）才能判断好坏**，
按成本红线（§5）不能自作主张。已列为待办，见 `HANDOVER.md` §13 第 3 条。

---

## 2. 用户已经拍板的决策（别再重新讨论）

| 维度 | 决策 | 备注 |
|---|---|---|
| 产品形态 | 多 Agent 并行参谋团给用户出主意 | 无回合制、无胜负判定 |
| 底座 | mavis 框架，**只读依赖、一行不改** | 实际只用到它的模型工厂 |
| 模型 | `deepseek-chat` 单一型号 | 不按角色分模型 |
| 现场输入 | 先文字，**ASR 后置** | ASR 方案尚未选 |
| 参谋团 | 5 路：反驳手 / 质询手 / 逻辑审计员 / 解释方法策略师 / 风险提示员 | 最初只有 3 路，后扩 |
| 检索 | 真实通道**未定**；已做本地语料 + 引用回链核验 | — |
| 部署 | 先本地；队友也要用；**不做登录** | — |
| 设备 | **笔记本浏览器**（桌面优先，不做移动端适配） | 用户明确要求 |
| 导出 | 需要（Word / PDF / Markdown） | PDF 走打印页，见 §5 |
| 辩题库 | 先轻，结构上预留 | — |
| 学科方向 | **未确定 / 可能多方向** | 论证骨架保持中性，不写死民法或刑法 |
| 赛制 | **暂无** | 所以没有状态机 |

---

## 3. mavis 相关结论（有证据链，别推翻重来）

阶段 0 做了源码级验证，完整报告见 `docs/spike-0-report.md`。

### 3.1 结论：mavis 只能当模型接入层

**它的 `Agent` 无法在不改源码的前提下被塑造成"参谋"**：

1. `Agent.completion()` 只认框架写死的 `prompt_*` 集合
   （`wake_up` / `schedule_*` / `determine_*` / `generate_chat` / `reflect_*` / `retrieve_*`），
   **没有"给参谋建议"这一类**；
2. `MAVIS_PROMPT_DIR` 只能替换模板**文本**，换不了**方法集合**——占位符由 Python 方法决定；
3. `Agent.think()` 是"日程 → 感知 → 定行动 → 移动 → 计划 → 反思"的**生活仿真管线**，
   产物是行动计划与移动路径，不是建议文本；
4. 要走通它还必须喂真实 `maze` + 完整 `spatial.tree`——与"现场出主意"毫无关系。

**逐轮推进的过程本身就是证据**：每修掉一个洞就冒出下一个隐式接口依赖
（替身计时器缺 `time_format_cn` → `tile.events` → 空 spatial tree 报 `IndexError`）。

### 3.2 采用的方案：只借基础设施半边，编排自建

最初只取 `create_llm_provider` 一个工厂做模型接入。**2026-09-30 扩到三面**
（模型接入 + 提示词模板 + 插件总线），完整清单与证据见 `docs/mavis-gap-report.md`：

| 面 | 接口 | 落点 |
|---|---|---|
| 模型接入 | `mavisframework.create_llm_provider`（顶层 `__all__`） | `backend/app/mavis_bridge.py` |
| 提示词模板 | `mavisframework.prompt.Scratch` | `prompts/*.txt` + `advisors/base.py` |
| 插件总线 | `mavisframework.plugin.PluginManager` | `backend/app/observers.py` |

**并行编排仍然由我们自己写**（共享单例 provider + `ThreadPoolExecutor`）。
mavis 一行未改，且 `backend/app/` 下只有 `mavis_bridge.py` 允许 import `mavisframework`
（`tests/test_mavis_usage.py` 用 AST 扫，守住这条线）。

### 3.3 并行编排实测

三路并行总墙钟 **1.34s**（= 最慢那一路），串行估算 3.65s，**省 63%**。

### 3.4 网关只认 Anthropic 协议 ⇒ 必须有协议桥

实测 `ANTHROPIC_BASE_URL` = `https://api.deepseek.com`：
`POST /v1/messages` → **200**；`POST /chat/completions` 与 `/v1/chat/completions` → **404**。

而 mavis 的 `OpenAIProvider` 只会说 OpenAI 协议 ⇒ 必然接不上。
**⇒ 自建 `backend/app/llm_bridge.py` 做协议翻译。**

### 3.5 桥必须兜住的两件事（缺了会真出事）

1. **永远返回合法 OpenAI 响应体**：mavis **不检查 HTTP 状态码**，只读
   `choices[0].message.content`。桥出错时若返回非 JSON，mavis 会走 10 次重试 × `sleep(5)`
   = **50 秒静默失败**（实测最惨一次 64.9 秒 / 12 次调用）。
2. **`response_format` 要翻译成系统提示 + 对返回做 JSON 形状修复**：
   mavis 的 pydantic 模型统一形如 `{"res": ...}`，但模型经常把内层对象直接当顶层吐出来，
   pydantic 校验失败后 mavis 退化成字符串，紧接着 `schedule.update(<字符串>)` 直接崩。
   修完：**64.93s → 5.6s，12 次调用 → 3 次，零失败**。

### 3.6 mavis 的契约红线

- `tests/test_extension_surface.py` 冻结了 `Game` / `Simulator` / `load_config` 的签名与默认值；
- 框架源码**禁止出现业务词汇**；
- ⇒ **所有辩论业务逻辑必须放在本仓库**。

### 3.7 用满基础设施半边（2026-09-30）

**触发**：用户要求"多用 mavis，体现出我的 mavis 工作"，并拍板两件事 ——
① 接入深度取 "provider 用满 + 插件总线"；② **只出报告，不改 mavis 仓库**。

**做法**：

1. **`LLMProvider` 从 3 个参数用到 6 个**。新增 `caller=`（逐参谋计数）、
   `failsafe=`（失败哨兵）、`callback=`（结果规整）；`is_available()` /
   `get_summary()` / `cache_stats()` 接进 `/api/health`。
2. **提示词搬进 mavis 模板层**。`prompts/layout.txt` + `roles/*.txt` + `tasks/*.txt`，
   提示词从 Python 长字符串变成可 diff、可版本化、可逐参谋覆盖的数据。
   **搬迁做了逐字节核对**：与 git HEAD 里旧的 f-string 拼接输出完全一致
   （`test_built_prompt_follows_the_layout_contract` 锁住）。
3. **三个观察者改挂 `PluginManager`**。落库 / 推流 / 指标从内联回调链改成插件，
   拿到逐插件错误隔离 —— 指标插件抛异常不再把落库和推流一起带走。

**关键判断：`failsafe` 是把"上游挂了"和"模型答了空"分开的唯一开关。**
mavis 的 `completion()` 吞掉全部异常（`llm_providers.py:81-95`），默认 `failsafe=None`，
两种失败同形。传私有哨兵后拆成 `error` / `empty` 两个状态 —— 现场不会再误判成
"模型不太会说话"。

**顺带查出的 mavis 缺口**（只报告，不改）：G1 结果缓存白名单写死调用名（接入方加不进去）；
G2 全局并发闸按 size 重建（两个不同 concurrency 的 provider 会互相顶掉闸门）；
G3 退避 `sleep(5)` 硬编码；G4 `prompt` / `plugin` 没进顶层 `__all__`；
G5 `validate_message` 与 `emit` 契约不一致；G6 `Scratch` 借用成本偏高；
G7 **`get_summary()` 的 `R` 不是重试次数**（只在成功拿到响应时递增，抛异常的尝试不计入，
重试 3 次全失败时 `R` 是 0）—— 前端仪表原先把这列标成"重试"，会直接读错，已改成"请求"。
清单、证据与建议改法见 `docs/mavis-gap-report.md`，复现入口
`backend/spikes/mavis_bounds.py`。

**没做的**：C 层（SSE 协议对齐 + snapshot 事件）、D 层（`DecisionEvent` 导出）。
`DecisionEvent` 的 17 个字段只填得上一部分 —— 诚实定性为"部分映射"，
不为了用而用。仿真半边（`Agent` / `Simulator` / 记忆 / 日程）仍然排除，理由见 §3.1。

### 3.8 把 mavis 从"文档里的说法"变成"代码里的事实"（2026-09-30）

**触发**：用户要求 README 更突出 mavis（"ai-debater 有点像 mavis 的 field test"），
并继续推进项目。三个决定：

**① 「用了 mavis 什么」写进代码，不再只写在文档里。**
`mavis_bridge.SURFACES` 是唯一事实来源，`runtime_info()` 把真实状态拼进去
（`mavisframework.__version__` 的真版本号、只读标记、唯一接触面、`prompts/` 的真实清单），
`/api/health` 的 `mavis` 块、导出报告页脚、前端「现场仪表」都读它。

判据来自本项目已经栽过的两次：README 写"6 条缺口"而报告实际 7 条；
仪表把 `R` 标成"重试"（上游全挂时显示"重试 0 次"，恰好藏住故障）。
**同一事实在仓库出现两次以上就是 bug 温床**，所以这次让它只剩一份，
并加测试核对每一面的 `used_in` 指向真函数。

**② 引用核验补上第二个维度：内容一致性，但只披露、不自动降级。**
条款号真实存在，不代表模型配的条文内容是对的 —— 实测中模型写过真实条款号 + 编造内容，
旧版照样判「已核验」。现在抽引用后紧跟的"声称内容"，与语料原文比
**最长公共子串重合度**，结果并排展示。

**刻意不改变 `status`**：存在性（有没有这条）与一致性（内容对不对）是正交的；
低重合可能来自编造，也可能来自合理意译，**裁定权在人**（与产品定位一致：AI 只出主意）。
自动降级会把"意译概括"批量标成"幻觉"，比不标更糟 —— 要降级得先有真实语料下的误杀率数据。
抽不出内容（或归一化后不足 6 字）就不比，宁可不结论也不给噪声值。

**③ README 的章节顺序按叙事权重排。**
「mavis 实战检验」从第 3 章提到第 2 章（紧跟「亮点」之后、`架构`之前），
mavis 徽章放到徽章行第一位，架构图里 `mavis_bridge` 加紫色描边并在图注点名。

---

## 4. 架构上的关键取舍

### 4.1 为什么台账必须外置

mavis 的记忆是**非结构化情景记忆**（三因子检索：近因 / 重要性 / 相关性），
metadata 是固定 schema，**塞额外字段会直接 `TypeError`**——结构化论点卡片进不去。
⇒ 台账放在我们自己的 SQLite（`backend/app/ledger/store.py`）。

### 4.2 防立场漂移做了两道闸

1. **预防**：每次分析把台账里仍成立（`standing`）的主张**注入参谋提示词**；
2. **检测**：`check-consistency` 端点把新建议与台账比对，找出**不能同时为真**的冲突，前端标红。

**检测刻意不放进 `/api/analyze` 热路径**——现场延迟敏感，由前端在建议返回后再调一次。

实测：故意喂一条与台账相反的主张 → 准确命中；同时**正确放过了无关主张**（未误报）。
"宁可漏报不可误报"是刻意的：一个乱报冲突的检测器等于没有。

### 4.3 时间预算的正确语义

现场的关键不是"全部返回"，而是**到点就交付已经好的部分**。

- 超预算的参谋标 `timeout` 并立刻推送，**不阻塞**其他几路；
- **实现要点**：`concurrent.futures.wait(timeout=)` 循环 + **`pool.shutdown(wait=False)`**
  —— 不能等线程收尾，否则"按时交付"失去意义。
- 实测（预算 1.6s）：质询手 1.05s ✓ / 审计员 1.22s ✓ / 反驳手 timeout，**总耗时 1.62s 返回**。

### 4.4 引用核验为什么走"打印页"这条弯路之外还保守判定

三级状态**必须保守**：

| 状态 | 含义 |
|---|---|
| **已核验** | **结构化语料**里确实有这一条，附原文为证 |
| **存疑** | 该法存在但语料里没这条；或只命中自由文本 |
| **未核验** | 语料里根本没有这部法 |

**踩过的两个 bug（都是测试逼出来的）**：

1. 只引法名不给条款号时，`lookup(law, "")` 会返回该法**首条** → 被误判「已核验」。
   修法：无条款号一律「存疑」，**绝不能拿首条兜底**（那是假阳性）。
2. 条款缺失时把"该法首条"当 `evidence` 显示 → 看起来像在给那一条件证。
   修法：不显示证据。

**补上的第二个维度（2026-09-30，见 §3.8）**：上面三条只回答**存在性**。
条款号真实存在、内容却是编的，是完全可能的 —— 旧版在这种情形下照样判「已核验」。
现在另有一组**内容一致性**字段（`claimed` / `match` / `content_ok` / `match_low` /
`content_suspect`），只披露不自动降级，理由见 §3.8 第 ② 条。

### 4.5 PDF 为什么不直接生成

中文 PDF 需内嵌 CJK 字体（fpdf2 / reportlab 都得挂一个 TTF），**缺字体会变成一排方块**。
⇒ 后端产出**打印优化页面**，前端唤起打印对话框让用户选"存储为 PDF"。
浏览器打印用系统字体，零依赖、排版最好。理由已写进代码注释与 README。

### 4.6 Word 导出的中文字体坑

python-docx 只设 `style.font.name` **不够**，必须显式设置 `rPr/rFonts` 的 **eastAsia** 属性，
否则 Word 打开后中文观感会回退。

---

## 5. 成本红线（用户明确关注，且主动质询过）

### 5.1 事实

| 事实 | 说明 |
|---|---|
| **点一次分析 = 5 次上游调用** | 5 路各 1 次 |
| **超时也计费** | 超时只是本地不等了，上游请求**已经发出去了** |
| **空闲不花钱** | 服务挂着不轮询，只有点按钮才发请求 |
| **凭据不是开发方配的** | `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` 是用户机器环境里本来就有的 |
| **从未创建 `.env`** | 仓库内无任何硬编码密钥；`ANTHROPIC` 只出现在 `os.environ.get` 与文档中 |
| **换电脑 = 换账单** | 另一台机器上的环境变量可能是**另一个账户**，先确认清楚再跑 |

### 5.2 开发方犯过的错（引以为戒）

**没有先问就跑真实压测**，而且阶段 0 那轮 JSON 未修好的失败一次烧了 12 次调用。

### 5.3 正确的省法

1. **能本地算就算本地算**：47 项单测、`python -m benchmarks check/eval` 全是 0 消耗；
2. **用临时名册只启用要验证的路**：
   `ADVISORS_YAML=/tmp/xxx.yaml python -m app.main`（实测五路时只跑 2 路 = 2 次调用而非 5 次）；
3. **用临时语料验证检索**：`CORPUS_DIR=/tmp/xxx`；
4. `benchmarks run` **不带 `--live` 只报预计调用量然后退出**，防手滑；
5. 零成本替代：mavis 原生支持 `provider: "ollama"`，改 `configs/mavis/config.json` 三行即可；
6. 想彻底杜绝误触：`pkill -f app.main; pkill -f app.llm_bridge`。

---

## 6. 环境与工具坑（本机特有，换机器可能不同）

1. **npm 创建 `node_modules/.bin` 被策略拒绝**（`CODEBUDDY_BROKER_DENY`）→ reify 整体中断、
   **所有包目录为空但退出码是 0**（极隐蔽）。
   解法：`rm -rf node_modules package-lock.json && npm install --no-bin-links`；
   因为没有 `.bin`，构建要直接跑 `node node_modules/vite/bin/vite.js build`。
2. **pytest 的 `tmp_path` 写系统临时目录被沙箱拒绝**
   → 已设 `backend/pytest.ini` 的 `addopts = -q --basetemp=.pytest_tmp`。
3. **`nohup … &` 起的进程随 shell 退出被回收** → 表现为"刚检查还健康，下一步就 404"。
   要用受管的后台任务方式启动。
4. **沙箱内默认无网络**（HTTPS 经代理 502）→ git 推拉 / 装包 / 联网检索都要显式放行。
5. **`app.config` 在导入时读环境变量** → 测试必须**先设 env 再 import**。
   已用 `backend/tests/conftest.py` 直接赋值处理（不用 `setdefault`，保证确定性）。
6. `dangerouslyDisableSandbox` + 引号嵌套复杂的 curl/python 组合命令会报
   `sandbox-center cmd decisionRecord missing actual resource subject`；
   改成"先 curl 落文件、再单独解析"即可绕过。

---

## 7. 业务层踩坑

**参谋的结构化输出是 pydantic 实例，不是 dict**：
`list[Rebuttal]` 直接 `json.dumps` 会抛
`TypeError: Object of type Rebuttal is not JSON serializable`，表现为 `/api/analyze` 500。

**修法**：在 `Advisor.run()` **源头**用 `schemas.jsonable()` 摊平，
而不是在每个调用点打补丁。落库与出参一次性干净。

---

## 8. 可核对的数据

> 具体条数**不写死在这**（写死必过期，见 `HANDOVER.md` §14 的教训）。要用命令取：
>
> ```bash
> git log --oneline --reverse | wc -l                        # 提交总数
> cd backend && ../.venv/Scripts/python.exe -m pytest -q      # 测试条数
> ```

- 测试覆盖：检索 / 辩题库与名册 / 引用核验 / 法条解析 / API 端到端 / 回归框架
- 台账库累计：多次完整分析（含下面这条来源不明的记录）
- **5 条来源不明**：2026-09-30 08:01:18 有一次完整 5 路分析不是开发方命令发出的
  （当时用的是只启用 2 路的临时名册），最可能是用户自己点了一次。
  **未查明，如实记录。**
