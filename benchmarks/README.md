# 回归测试与评估

对应交接文档「坑 5：评估缺位」——**没有固定测试集，就无法判断改动是变好了，还是只是变长了。**

## 核心原则：能自动算的指标，一律不花钱

| 指标 | 怎么算 | 消耗 |
|---|---|---|
| **三段论完整率** | 反驳手的每条论点，`claim / 大前提 / 小前提 / 结论` 四段是否都非空 | 0 |
| **要点覆盖率** | 用例声明的 `focus` 关键词有多少在产出中出现 | 0 |
| **引用核验率** | 走本地法源语料核验（见 `data/corpus/README.md`） | 0 |
| **延迟 P50 / P95** | 从 `suggestions` 表的历史记录算 | 0 |
| **超时 / 失败数** | 同上 | 0 |
| 建议可用率 | **需要人判断**，框架不代劳 | — |

只有最后一项需要人，其余全是本地计算。**只有真正要跑模型的那条命令才花钱。**

## 命令

在 `backend/` 目录下运行：

```bash
# 解释器就在仓库根的 .venv 里（Windows / Git Bash 用 ../.venv/Scripts/python.exe）
PY=../.venv/bin/python

$PY -m benchmarks list                    # 列出用例
$PY -m benchmarks check                   # 校验用例自身（0 消耗）
$PY -m benchmarks eval <session_id> ...   # 算指标（0 消耗）
$PY -m benchmarks compare a.json b.json   # 对比两次评估（0 消耗）

# ⚠️ 下面这条会真实调用模型并产生费用，必须显式加两个开关
$PY -m benchmarks run --live --confirm
```

`run` 不带 `--live` 时只会告诉你**预计要花多少次调用**然后退出，防止手滑。

## 用例格式

见 `benchmarks/cases/core.yaml`：

```yaml
cases:
  - id: ip-ai-authorship
    topic: AI 生成内容是否应享有著作权
    our_side: 控方（主张：应享有）
    opponent_text: 对方的一段真实感发言……
    focus: [法人作品, 独创性, 主体拟制]     # 应当触及的要点关键词
    discipline: 民法 / 知识产权
    note: 争点说明
```

## 怎么用它回答"改动是不是变好了"

1. 改代码/prompt **之前**，跑一次 `run --live --confirm`，存下结果（`benchmarks/results/live-*.json`）；
2. 改完之后，**用同一批用例**再跑一次；
3. `compare` 两次结果，它会把每个指标标成 **变好 / 变差 / 不变**。

```
$PY -m benchmarks compare benchmarks/results/live-A.json benchmarks/results/live-B.json
```

同时盯住**指标组合**，别只看单项：

- 三段论完整率↑ 但 P95 延迟↑↑ → 质量上去了，现场可能撑不住；
- 要点覆盖率持平但输出明显变长 → 典型的"只是变长了"，没变好。

## ⚠️ 关于"要点覆盖率"的诚实说明

它是**粗信号**，只回答"这个话题有没有被碰到"，**不回答"论证好不好"**。
关键词命中可以通过堆砌术语刷出来。别把它当质量分用，它只是防止"改完之后连要点都不提了"。

真正的质量判断还是得靠人看——这也正是它没被自动化掉的原因。

## 用例从哪来

`benchmarks/cases/core.yaml` 里是 4 个初始用例，覆盖民法/知识产权、刑法、个人信息保护、法理四个方向
（学科方向尚未最终确定，`discipline` 只是标注）。
建议把你实际要打的辩题补进去——**用例越贴近实战，这个框架越有用**。
