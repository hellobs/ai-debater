# 接手与贡献指南

本文件只解决一件事：**让第一次接触本仓库的人，安全地改出第一个提交，并且不把项目改坏。**
它不重复项目背景 —— 背景在 [`HANDOVER.md`](HANDOVER.md)（下文简称「交接文档」）。

> 只想读一份的话：交接文档 **§3（已确认决策）+ §10（已知陷阱）+ §11（成本红线）**。
> 这三节读完，你就不会犯绝大多数"好心改坏"的错。

---

## 1. 阅读顺序

按这个顺序读，**别跳**（每一步都写明"不读会怎样"，那是真实发生过的）：

| # | 读什么 | 读完能知道 | 不读会怎样 |
|---|---|---|---|
| 1 | 本文件 | 硬约束 + 最小改动闭环 | 容易踩「改一处不算改完」那类坑 |
| 2 | 交接文档 §0–§6 | 定位、**已拍板的 14 条决策**、架构、五条承重结论 | 会重新讨论已经定过的事及已经付过代价的事 |
| 3 | 交接文档 §7–§11 | 代码地图、怎么跑、已知陷阱、成本红线 | 会重复踩已知的坑，甚至白花钱 |
| 4 | [`docs/decision-log.md`](docs/decision-log.md) | 每条决策**为什么**这么定、备选路线为何被否 | 会「好心改回去」—— 有几条正是为此写下的 |
| 5 | [`docs/mavis-gap-report.md`](docs/mavis-gap-report.md) | 基座框架能承受到什么程度、还缺什么（G1–G7 / N1–N4） | 会误以为框架能做它做不到的事 |
| 6 | [`PLAN.md`](PLAN.md) · [`docs/spike-0-report.md`](docs/spike-0-report.md) | 分阶段路线与验收标准 · 阶段 0 的关键证据 | 按需读，不必通读 |

**定位一句话**：这是**通用辩手参谋台**；「AI + 法学」只是它的落地场景之一（决策 13）。
写下任何"法学"字样前，先确认它是不是该待在领域提示词包里（见硬约束 5）。

---

## 2. 七条硬约束

违反其中任何一条都会把项目改坏，且**多数不会报错** —— 这正是它们被写成清单的原因。

| # | 约束 | 为什么 | 谁在守 |
|---|---|---|---|
| 1 | **不修改 mavis 仓库**（`D:/zzr/小项目/mavis`，或 `MAVIS_DIR`） | 它是**只读依赖**。「本项目基于它开发」这个结论只有在"一行未改"时才成立 | 交接文档 §3 决策 1；`mavis_bridge.py` 的 `readonly: True` 自述 |
| 2 | **`backend/app/` 下只有 `mavis_bridge.py` 可以 `import mavisframework`** | 换掉基座只需改一个文件；这条被打破就再也不是一句话的事 | `tests/test_mavis_usage.py`（AST 扫描） |
| 3 | **真实 API 消耗前先问用户** | 点一次分析 = **5 次**上游调用，**超时也计费** | 交接文档 §11；`benchmarks run` 不带 `--live` 只报预计量 |
| 4 | **同一份事实只写一处** | 已经付过代价：参谋名册曾被定义三遍、显示名被定义两遍（导出报告因此印着过期的名字） | 各处测试 + 交接文档 §3 决策 8/14 |
| 5 | **领域措辞只活在领域提示词包里**（`prompts/packs/<包>/`） | 平台是通用的；法律措辞漏一处，通用辩题就被拽进法律框架 | `tests/test_prompt_packs.py`、`tests/test_export.py` |
| 6 | **每个包必须自包含**（5 路 × roles/tasks 各一份） | 一个包能被单独替换的前提就是它自带完整模板 | `load_roster()` → `preload()` 启动自检，缺文件**开不了机** |
| 7 | **文档不写死会烂掉的数字**（测试项数、提交数、当前 HEAD） | 已经烂过三次：文档写 192 → 实际 201 → 实际 212，每次都要全仓替换十几处。写命令，不写结果 | 人工；写文档时自查这条 |

> 关于约束 7：想说"测试很全"就写 `cd backend && python -m pytest`（读者自己跑就有数），
> 别写"共 N 项"；想说"提交历史"就给 `git log`，别写"HEAD 是 abc1234"。
> 徽章同理 —— `tests-passing` 比 `tests-201 passing` 活得久。

> 关于约束 4 的"第二遍定义"：加一路参谋、或改任何一处**显示名 / 枚举取值 / 领域措辞**时，
> 先问「这个事实在仓库里还有别的副本吗？」。已知的副本位置：
> `configs/advisors.yaml`（显示名唯一来源）、`prompts/packs/*`（措辞唯一来源）、
> `app/export/report.py`（**已经从名册取，请勿再写死**）、`frontend/src/App.tsx`（只读 `/api/health`）。

---

## 3. 最小改动闭环（全程 0 API 消耗）

```bash
bash scripts/bootstrap.sh        # 首次：装依赖 + 装 mavis + 跑测试（不调模型、不花钱）

cd backend && python -m pytest   # 每次改完必跑；全绿再提交（Windows: ../.venv/Scripts/python.exe -m pytest）
```

改了前端再加三条：

```bash
cd frontend
npm test                                        # vitest run：纯函数 + 组件级（jsdom）
node node_modules/typescript/bin/tsc --noEmit    # 类型检查（比截图更快发现缺依赖）
node node_modules/vite/bin/vite.js build         # 构建
```

> 新写的一组 UI 用例，**至少挑两条做一次变异检验**：把实现改坏，看是不是只有对应那
> 一两条变红。全绿往往意味着用例在测快照而不在测行为（详见 HANDOVER §13 续七）。

⚠️ **`pytest` 必须在非沙箱的前台跑。** 后台 / 沙箱里跑会拦 `backend/.pytest_tmp` 与
`backend/.testdata/` 的写盘，一大批用例报 `ERROR … - AssertionError`（**setup 阶段**）——
看起来像大面积回归，其实是假故障。判据：**前台 exit=0 即全绿**。

---

## 4. 想真跑一轮模型？（会产生费用）

```bash
cd backend
python -m benchmarks run                 # 不带 --live：只报预计调用量后退出
python -m benchmarks run --live --confirm   # 真跑，按用例数 × 路数计费
python spikes/pack_quality.py --dry-run     # 只渲染提示词对比，0 消耗（先跑这个）
```

跑之前先确认（交接文档 §11）：**超时照样计费**；只验证某几路时用临时名册
（`ADVISORS_YAML=/tmp/x.yaml`）可以少花钱。

---

## 5. 常见的「加一个东西」

| 想做什么 | 动哪里 | 注意 |
|---|---|---|
| 加一路参谋 | `backend/app/advisors/` 新建模块 → 在 `__init__.py` 的 `REGISTRY` 注册 → `configs/advisors.yaml` 增一行 → 前端 `AdvisorColumn.tsx` 增渲染分支 | **每个领域包都要补 `roles/` + `tasks/` 两份模板**（硬约束 6） |
| 加一个领域提示词包 | `prompts/packs/<新包>/{roles,tasks}/`（自包含）→ `configs/prompt-packs.yaml` 登记 | 改配置即可，**不用动代码** |
| 加辩题 | `configs/topics.yaml`（入仓预设）或界面上「保存为我的辩题」（存入不入仓的 `data/topics.json`） | `domain` 是**逐字**匹配提示词包的键 |
| 让引用核验能判「已核验」 | 把法条全文放进 `data/corpus/`（格式见其中 README） | 零代码改动、零 API 消耗；**语料必须来自官方文本，不许凭记忆录入** |
| 改提示词措辞 | `prompts/packs/<包>/…` | 这是**数据**，一次可 diff 的提交；别改回 Python 字符串常量 |

---

## 6. 提交与推送

- **按主题拆成小提交**，提交信息写简略（如 `fix: bootstrap 支持 Windows venv 布局`）。
- 提交前把"顺带被工具改动的无关文件"还原掉（例如 `npm install` 会顺带改 `package.json` 的范围与 lock 里的 registry 域名）。
- 推送：`git push origin main`。**代理偶发瞬时失败**（`Failed to connect … over proxy` 或
  `schannel: failed to receive handshake`）**不代表代理挂了** —— 先 `curl -x http://127.0.0.1:7890 https://github.com/`
  与 `git ls-remote origin` 实测，通了直接**重试**，别改配置。
- **提交前先看一眼"会烂掉的数字"**（约束 7）。加/删过测试后，文档里写死的测试计数就过期了
  —— 已经烂过三次（192 → 201 → 212），每次都是全仓替换十几处。
  **首选是把它删掉**：写成"跑一遍全量测试"或直接给命令，读者自己跑就有数。
  确实要留数字的（如徽章），改前先找出所有写死它的地方：

  ```bash
  grep -rn "201\|212" README.md README.en.md HANDOVER.md
  ```

---

## 7. 发版

版本号写在**两处**，必须一起动（Python 与 npm 各不认识对方的文件，没法合成一份）：

| 位置 | 用途 |
|---|---|
| `backend/app/main.py` 的 `FastAPI(version=…)` | OpenAPI 文档与 `/api/health` 同源的服务版本 |
| `frontend/package.json`（及其 `package-lock.json`） | 前端产物版本 |

```bash
git tag -a v1.1.1 -m "v1.1.1" && git push origin v1.1.1
gh release create v1.1.1 --title "v1.1.1" --notes-file <(...)   # 或 --notes "…"
```

发版前跑一遍 §3 的最小闭环（测试 + `tsc --noEmit` + `vite build`），
**不要为了发版而真跑一轮模型** —— 那要花 5 次上游调用（约束 3）。
