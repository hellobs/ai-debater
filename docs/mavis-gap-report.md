# mavis 使用面与缺口报告

> 日期：2026-09-30 ｜ 环境：Python 3.13.12（托管 venv）｜ mavis v1.3.3（`511dea0`，**一行未改**）
> 复现入口：`.venv/Scripts/python.exe backend/spikes/mavis_bounds.py`
> 结论：**基础设施半边用满（provider / 提示词模板 / 插件总线），仿真半边架构性用不上。**
> 发现 7 处缺口（G1–G7）与 4 处接线注意（N1–N4）。缺口**只报告，不改 mavis**。

---

## 0. 这份报告回答什么

上一版的结论是"mavis 只当模型接入层用"，并且只用了 `create_llm_provider().completion()`
的 3 个参数（`prompt` / `return_type` / `retry`）。这一版把**能用的面用满**，并逐条记录：

1. 用上了哪几面、落在哪个文件、证据在哪；
2. 哪一面用不上，为什么（附架构证据，不是"感觉不合适"）；
3. 现有的面还缺什么 —— 每条都能用上面那条命令复现。

---

## 1. 用上了的三面

| 面 | mavis 接口 | 落点 | 具体用到了什么 |
|---|---|---|---|
| 模型接入 | `create_llm_provider()` → `LLMProvider` | `backend/app/mavis_bridge.py` | `caller=` 逐参谋计数、`failsafe=` 失败哨兵、`callback=` 结果规整、`is_available()` / `get_summary()` / `cache_stats()` 接进 `/api/health`；靠它自带的 90s 超时与进程级并发闸 |
| 提示词模板 | `prompt.Scratch.build_prompt()` | `prompts/*.txt` + `advisors/base.py` | 三层模板（`layout` / `roles/*` / `tasks/*`），提示词从 Python 长字符串变成**可 diff、可版本化、可逐参谋覆盖**的数据；启动自检 `preload()` |
| 插件总线 | `plugin.PluginManager` | `backend/app/observers.py` | 三个观察者 `LedgerPlugin` / `StreamPlugin` / `MetricsPlugin`，拿到**逐插件错误隔离**与 `setup / emit / teardown` 生命周期 |

### 1.1 关键设计点

**`failsafe` 是唯一能把"上游挂了"和"模型答了空"分开的开关。**
mavis 的 `completion()` 吞掉全部异常（见 G3），默认 `failsafe=None`，重试耗尽后返回 `None`
—— 调用方无法区分这两种失败。我们传入私有哨兵 `FAILED`，于是：

| 返回 | 我们的 `status` | 含义 |
|---|---|---|
| `FAILED` 哨兵 | `error` | 上游连接失败或超时，重试已耗尽 |
| `None` / `[]` / `""` | `empty` | 上游应答正常，只是内容为空 |

这也是为什么不靠 mavis 的 `R` 计数判断故障：上游全挂时 `R` 是 0，看不出问题（见 G7）。

**`callback` 只做归一化，不做判分。** mavis 把 callback 返回 `None` 当作"这次不算数，重试一次"，
所以在 callback 里否决内容会把"质量一般"放大成 `retry` 倍的上游调用。`Advisor.adapt()` 只
去空白、丢全空条目，代价为零。

**插件总线换掉的是内联回调链。** 原来"落库 + 推流 + 指标"挤在一个 `_on(r)` 里，
任一处抛错整条链路一起断。改成总线后，指标插件抛异常只记一条 warning，
`ledger` 与 `stream` 照常完成（`tests/test_mavis_usage.py::test_single_plugin_failure_does_not_lose_other_results`）。

**"只有 `mavisframework` 一个接触面"这条线有测试守着。**
`test_only_the_bridge_imports_mavisframework` 用 AST 扫 `backend/app/**`，
除 `mavis_bridge.py` 外任何文件 import `mavisframework` 都会失败；
`test_bridge_only_uses_public_surface` 再锁一层：只允许顶层 / `plugin` / `prompt`，
不许碰 `runtime.llm` 这类内部模块（这正是本次修掉的旧写法）。

---

## 2. 用不上的：仿真半边

见 `docs/spike-0-report.md`。一句话版：`Simulator` 是"每 tick 让所有 Agent 走
生活仿真管线"，与"并行出主意"语义错位；`Agent` 只认框架写死的一组 `prompt_*`，
没有"给建议"这一类。**这是架构性错位，不是配置没调好**，所以不硬凑。

---

## 3. 缺口（G）—— 建议 mavis 侧修

每条格式：现象 → 证据 → 对本项目的影响 → 我们怎么绕 → 建议改法。
建议改法都符合 mavis 自己的扩展约定（纯新增 / 默认关闭 / 语义中立 / 带单测）。

### G1 结果缓存的调用名白名单写死 ✅ 影响本项目

- **现象**：缓存只对 mavis 自己写死的三个调用名生效，接入方无法把自己的确定性调用加成可缓存。
- **证据**：`runtime/llm_providers.py:107-111` 的 `_CACHEABLE_CALLERS` 是硬编码 set；
  `:60-65` 只在 `caller in self._CACHEABLE_CALLERS` 时算缓存键。实测：

  ```
  白名单: ['generate_chat_check_repeat', 'poignancy_chat', 'poignancy_event']
  caller='poignancy_chat'  同 prompt 调两次 → 上游被调 1 次（命中）
  caller='rebutter'        同 prompt 调两次 → 上游被调 2 次（不命中）
  ```

- **对本项目的影响**：`同辩题 + 同对方发言 + 同我方台账` 的重跑是确定性的，
  本该命中缓存，现在白花 5 次上游调用。现场"再生成一次"是个常见动作。
- **我们怎么绕**：`cache=False`，如实关掉，不假装有缓存；`/api/health` 里显示
  "结果缓存未启用"并在前端注明原因。
- **建议改法**：加一个 `cacheable_callers` 配置项（默认仍为原三个），
  或提供 `provider.register_cacheable(caller)`。纯新增、默认行为不变。

### G2 全局并发闸是类属性，size 一变就整体重建 ⚠️ 潜在

- **现象**：`_semaphore(size)` 发现 size 与上次不同就直接换一个新的 `threading.Semaphore`，
  于是两个 `concurrency` 不同的 provider 会互相顶掉对方的闸门。
- **证据**：`runtime/llm_providers.py:28-35`。实测：

  ```
  _semaphore(4) 两次是同一对象：True
  换成 8 再回到 4，还是当初那个吗：False
  ```

- **对本项目的影响**：**暂时不受影响** —— `mavis_bridge.get_provider()` 是单例，
  全进程只有一个 provider。但这是"进程级闸"与"实例级配置"的语义错配，
  多 provider 场景会静默降级限流（Ollama 单实例下就是排队变并发）。
- **我们怎么绕**：强制单例复用 provider，并在 `get_provider()` 的 docstring 里
  写明"必须复用"及理由，防止后来者顺手改成多实例。
- **建议改法**：信号量按 size 分桶（`dict[size, Semaphore]`），
  或把 size 固定为进程级配置、不再随实例变。

### G3 异常全吞 + 退避硬编码 ⚠️ 已绕开

- **现象**：`completion()` 捕获所有异常并 `continue`，重试耗尽后返回 `failsafe`；
  每次重试之间 `time.sleep(5)` 写死。
- **证据**：`runtime/llm_providers.py:81-95`。实测（retry=3）：

  ```
  failsafe=None       → 返回 None        上游被调 3 次，退避 sleep 参数 [5, 5, 5]
  failsafe='SENTINEL' → 返回 'SENTINEL'  上游被调 3 次，退避 sleep 参数 [5, 5, 5]
  ```

- **对本项目的影响**：两层。① 失败信号丢失（要传 `failsafe` 才能区分，见 §1.1）；
  ② 退避吃掉时间预算 —— `retry` 取 mavis 默认值 10 时，最坏先睡 50s 才放弃，
  而 `ADVISOR_BUDGET_S` 默认才 20s，超时标记根本轮不到。
- **我们怎么绕**：`retry` 显式压到 2（最坏 10s，仍在预算内），并传 `failsafe=` 哨兵。
- **建议改法**：`completion(..., backoff: float = 5)` 或读配置；异常可选往上抛
  （例如 `raise_on_error=True`），让调用方自己决定要不要吞。

### G4 `prompt` / `plugin` 两个扩展面没进顶层 `__all__` ⚠️ 影响接入方

- **现象**：`mavisframework/__init__.py` 的文档说"顶层 API 一览（推荐用法）"，
  但它导出的只有 config / core / scene / runtime / protocol —— 提示词与插件面不在其中，
  只能按模块路径 import。
- **证据**：实测

  ```
  Scratch        在顶层 __all__ 里：False；顶层直接可访问：False
  Plugin         在顶层 __all__ 里：False；顶层直接可访问：False
  PluginManager  在顶层 __all__ 里：False；顶层直接可访问：False
  ```

  而 `prompt/__init__.py` 的 `__all__ = ["Scratch", "Result"]`、`plugin.py` 的模块头
  写明"任何外部包都能作为插件挂进 mavis" —— **声明是公开的，入口不在推荐位置上**。
- **对本项目的影响**：接入方按"推荐用法"找扩展点会找不到，容易误以为得去 import
  `runtime.*` 内部模块（我们上一版就是这么写的）。
- **我们怎么绕**：按模块路径 import `mavisframework.plugin` / `mavisframework.prompt`，
  并用测试把"只用这三个公开路径"钉死。
- **建议改法**：把 `Plugin` / `PluginManager` / `Scratch` 加进顶层 `__all__`。

### G5 `validate_message()` 与 `PluginManager.emit()` 契约不一致 ℹ️ 已绕开

- **现象**：协议校验只认框架内建的 7 种消息；自定义事件校验为 `False`。
  而插件总线的 `emit()` 完全不校验，任意 dict 都广播。两条线的契约不同，但没有文档说明。
- **证据**：`runtime/protocol.py:118-127`（未知 type 返回 `False`，**不抛异常**）；
  `plugin.py:180-188`。实测：

  ```
  validate_message({'type': 'snapshot'})       → True
  validate_message({'type': 'chat_line'})      → True
  validate_message({'type': 'advisor_result'}) → False
  ```

- **对本项目的影响**：自定义事件（`run_start` / `advisor_result` / `run_end`）走协议线会被判不合规。
- **我们怎么绕**：走插件总线（不校验），不走协议线。这也是 §1 里"插件总线用满"的一部分。
- **建议改法**：在 `protocol.py` 的文档里写明"只覆盖框架内建消息，扩展事件请走插件总线"，
  或在 `validate_message` 里给未知 type 一个可配置的放行策略。**纯文档改动即可**。

### G6 `Scratch` 的借用成本偏高 ℹ️ 已绕开

- **现象**：`Scratch(name, currently, config, timer=None)` 要求三个位置参数，
  而 `build_prompt(template, data)` 一个都不用；模板目录在 `__init__` 时读一次并固化成实例属性。
- **证据**：`prompt/scratch.py:21-36`。实测：

  ```
  改完文件内容后 build_prompt → 'V2'（文件每次重读，改措辞不用重启）
  改环境变量后 template_path 仍是 → C:\...\mavis-tmpl-xxx（目录冻结，换目录得重建实例）
  ```

  （顺带确认一件好事：**模板文件内容是每次重读的**，改措辞不需要重启进程。）
- **对本项目的影响**：只想用模板填充的接入方得传三个无意义参数；想要两套模板目录必须建两个实例。
- **我们怎么绕**：`mavis_bridge.prompt_renderer()` 里按目录缓存实例，目录变了自动重建；
  把三个占位参数集中在一个地方传。
- **建议改法**：给 `Scratch` 加 `template_dir` 关键字参数；或把渲染拆成
  不需要 `name/currently/config` 的类方法（`Scratch.render(template, data, dir=...)`）。

### G7 `get_summary()` 的 `R` 语义会误导使用者 ⚠️ 已绕开

- **现象**：`get_summary()` 返回 `S:成功,F:失败/R:?`。字面上 `R` 最像 "Retry"，
  实际它只在**成功拿到响应**时递增（`_summary[caller][0] += 1` 写在 `try` 里 `_completion_timeout` 之后），
  抛异常的尝试**完全不计入**。所以它不是重试次数，也不等于尝试总数。
- **证据**：`runtime/llm_providers.py:70-94、125-129`。实测：

  ```
  一次成功                 → S:1,F:0/R:1     （R = 完成的请求数）
  3 次异常后放弃（retry=3） → S:0,F:1/R:0     ← 实际发了 3 次请求，R 却是 0
  ```

- **对本项目的影响**：前端仪表最初把这一列标成"重试"，会直接读错 ——
  上游全挂时显示 "重试 0 次"，恰好把最需要看见的故障藏起来。已改成"请求"并加 tooltip 说明。
- **我们怎么绕**：① 前端标签改为"请求"并注明"抛异常的尝试不计入"；
  ② 需要判断失败性质时不看 `R`，看我们自己传 `failsafe` 得到的 `error` / `empty` 状态
  （见 §1.1）；③ 要算成功率就用 `S/(S+F)`。
- **建议改法**：把 `get_summary` 的输出键改成自解释的名字（`success` / `failed` / `completed`），
  或在返回值里加一个 `attempts` 字段把异常尝试也记上。**纯输出格式改动，不影响逻辑**。

---

## 4. 接线注意（N）—— 不必改框架，但接线方要知道

| # | 事项 | 说明 |
|---|---|---|
| N1 | `failsafe` 不传就分不清失败类型 | 默认 `None` 与"模型答空"同形。传私有哨兵即可区分（见 §1.1）。`LLMProvider` 签名 `runtime/llm.py:15-24` 里已有这个参数，属于"用对了就没问题" |
| N2 | `cache_stats()` / `disable()` 不在抽象基类里 | `LLMProvider` 只声明 `completion` / `is_available` / `get_summary`（`llm.py:11-34`），实测实现多出这两个。按契约编程拿不到，我们的 `provider_info()` 用 `getattr` 当可选能力取 |
| N3 | 模板里裸 `$` 会炸 | `build_prompt` 用 `Template.substitute`（非 safe）。实测 `'$undefined_var'` → `KeyError`，`'单价 $100'` → `ValueError`。好处是模板写错当场报，坏处是写金额/公式要转义成 `$$`。`preload()` 启动时真渲染一次，把这类错误提前到启动 |
| N4 | `PluginManager.discover()` 只自动实例化"可无参构造"的工厂 | `plugin.py:56-71,117-142`。我们的插件都需要 `session_id` / `out_queue`，因此走 `mount()` 手工挂载。这是有意设计且已写进文档，记一条**已知边界** |

---

## 5. 复现

```bash
# 全部探针（只读，不改 mavis 任何文件）
.venv/Scripts/python.exe backend/spikes/mavis_bounds.py

# 守住"只用 mavis 公开面、只有一个接触面"的测试
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_mavis_usage.py -v
```

---

## 6. 立场声明

本项目对 mavis 的策略是**只走已公开的稳定面，不碰框架源码**。

上面 7 条缺口都没有"绕不过去"的性质 —— G1、G4、G7 值得修，G2 是潜在正确性问题，
其余属于文档与人体工程。这份报告的作用是把结论与证据留在仓库里，
让下一次"要不要改 mavis / 要不要换掉 mavis"的讨论有依据，而不是重新读一遍源码。
