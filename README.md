# ai-debater — 法学辩论现场参谋台

> 你在台上打法学辩论，对方说完一段，系统**并行**跑几路 AI 参谋，各自给你出主意
> （反驳要点 / 质询问题 / 逻辑谬误），你自己判断要不要用。
>
> **不是** AI 对 AI 互搏，**不是**裁判打分系统。所有 Agent 站在你这一边。

完整方案见 [`PLAN.md`](PLAN.md)（v2.0）；阶段 0 实测结论见
[`docs/spike-0-report.md`](docs/spike-0-report.md)。

---

## 架构（一句话）

```
前端 (React) ──SSE──> 我方后端 (FastAPI) ──> mavis_bridge（唯一接触面）
                                                └─> mavis 的 LLM 工厂 ──> 协议桥 ──> 模型网关
```

mavis 以**只读依赖**接入，一行不改。阶段 0 实测结论：它在本项目里充当**模型接入层**，
不是 Agent 运行时（原因见阶段 0 报告）。

---

## 目录

```
configs/            喂给 mavis 的配置（不是 mavis 的代码）
  mavis/config.json
backend/app/        llm_bridge.py（协议桥）· config.py
backend/spikes/     阶段 0 的三个验证脚本
docs/               实测报告
frontend/           （待建）
```

---

## 快速开始

### 1. 依赖

```bash
export VENV=/Users/ruige/.workbuddy/binaries/python/envs/default
"$VENV/bin/pip" install /Users/ruige/Documents/GTC/mavis      # mavis 只读依赖
"$VENV/bin/pip" install fastapi "uvicorn[standard]" httpx pyyaml jinja2 pytest
```

### 2. 凭据（只走环境变量，绝不入仓）

```bash
cp .env.example .env      # 然后填写；.env 已被 .gitignore 排除
```

桥需要 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN`；模型名走 `LLM_MODEL`。

### 3. 起协议桥

```bash
cd backend
LLM_BRIDGE_PORT=8011 "$VENV/bin/python" -m app.llm_bridge
curl -s http://127.0.0.1:8011/healthz     # 健康检查
```

### 4. 跑验证

```bash
"$VENV/bin/python" backend/spikes/spike_01_provider.py           # 底座联通
"$VENV/bin/python" backend/spikes/spike_03_parallel_advisors.py  # 三路并行参谋
```

---

## 为什么需要一个协议桥

mavis 的 LLM 层只说 **OpenAI 协议**（`POST {base_url}/chat/completions` + `Authorization: Bearer`），
而本项目可用的网关只提供 **Anthropic 协议**（`POST /v1/messages` + `x-api-key`）。
桥只做协议翻译，**不改 mavis**。它还负责两件 mavis 不做的事：

1. 永远返回合法的 OpenAI 响应体——mavis **不检查 HTTP 状态码**，
   否则失败会被它静默重试 10 次 × 5 秒；
2. 把 `response_format` 里的 JSON Schema 写进系统提示，并**修复返回的 JSON 形状**
   （补 `res` 外层包装）。实测这一项把一步 `think` 从 64.9s / 12 次调用降到 5.6s / 3 次。

---

## 安全红线

`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `LLM_API_KEY` **只从环境变量读取**，
绝不写入代码、配置或文档。
