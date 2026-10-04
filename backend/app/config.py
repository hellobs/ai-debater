"""项目配置读取层：只从环境变量取，绝不落盘凭据。

两项前置处理，都是为了同一个目标 —— **照着文档做，不会得到一个指向别处的错误**：

1. **先加载 `<仓库>/.env`（若存在）。** 文档教的是 `cp .env.example .env` 后填写生效，
   那就必须真的有人读它；此前仓库里没有任何代码加载过 `.env`，填了等于没填、还不报错。
   这里不引入 `python-dotenv`：实际用到的语法只有 `KEY=VALUE` 与 `#` 注释，
   多一个依赖不如多二十行注释。**已存在的环境变量优先**，命令行 `export` 要压得过文件
   （否则临时换网关、换账户就换不动）。

2. **空白值一律视为未设置**（见 `_env`）。`os.environ.get(name, default)` 只在键
   *不存在* 时才回默认值；而 `.env.example` 里 `MAVIS_PROMPT_DIR=` 写的就是空值 ——
   于是 `Path("")` 等于 `Path(".")`，提示词目录跑到当前目录去，启动自检报
   「参谋 'rebutter' 在提示词包 'general' 里缺模板：`.\\packs\\general\\roles\\rebutter.txt`」。
   报错指向当前目录，而用户的动作只是"照 `.env.example` 填了一份 `.env`"。
   同类的 `int("")` / `float("")` 更直接：import 期就抛 `ValueError`，服务根本起不来。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 本机配置文件（不入仓，见 .gitignore 的 `.env`）。只列变量名、不含凭据的样例是 `.env.example`。
ENV_FILE = ROOT / ".env"


def _env(name: str, default: str = "") -> str:
    """读环境变量，**空白值一律视为未设置**（理由见模块 docstring 第 2 条）。

    只判"整串是否空白"，不做 trim —— 路径里带空格是合法的，
    本项目自己的路径就带中文和空格。
    """
    value = os.environ.get(name)
    return value if value is not None and value.strip() else default


def _load_dotenv(path) -> dict[str, str]:
    """极简 `.env` 解析，返回 `{键: 值}`，**不含空值**。

    只支持项目实际用到的语法：`#` 注释、空行、可选的 `export ` 前缀、
    值两侧成对的单/双引号、值里含 `=`。
    **没有** `$VAR` 插值、多行值、转义 —— 需要那些时再换 `python-dotenv`，
    别在这里半吊子实现一遍。

    读不了（不存在 / 无权限 / 编码不对）一律返回空，不当错误：`.env` 是可选文件。
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue                      # 没有 `=` 的行忽略，不是错误
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # 行尾 `#` 注释（标准 dotenv 行为）：引号外剥除，引号内保留。
        # 必须放在引号剥离**之前**，否则 `"hello" # comment` 会先把引号剥掉再丢值。
        if not (value.startswith('"') or value.startswith("'")):
            if "#" in value:
                value = value.split("#", 1)[0].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not value.strip():
            continue                      # 空值不注入（见 _env）
        out[key] = value
    return out


def _apply_dotenv(path) -> int:
    """把 `.env` 里**环境尚未提供**的键补进 `os.environ`，返回补了几条。

    "环境优先"是有代价的：已经 `export` 过的变量改不动 `.env` 的值。
    这是刻意的 —— 否则临时指定另一个网关就得先删掉监控程的环境变量。
    """
    added = 0
    for key, value in _load_dotenv(path).items():
        if key not in os.environ:
            os.environ[key] = value
            added += 1
    return added


#: 必须在读取任何配置**之前**执行 —— 下面每一行都依赖它已经跑过。
DOTENV_APPLIED = _apply_dotenv(ENV_FILE)

# 站点品牌名。前端顶栏与 FastAPI title 同源，避免两处各写一遍。
# 平台是**通用辩手参谋台**；「AI + 法学」是它的落地场景之一，不作为品牌。
BRAND_NAME = _env("BRAND_NAME", "辩手参谋台")

# 注：mavis 的 provider 配置**不在**这里读取。项目只借它的 create_llm_provider()，
# 参数由 backend/app/mavis_bridge.py 直接构造 dict 传入（见该文件）。
# 此前为 mavis 的 Simulator 预留的 MAVIS_CONFIG_PATH / ASSETS_ROOT /
# CHECKPOINTS_ROOT 三个环境变量从未被任何代码读取，已删除。

# 我方桥（mavis 指向它）
LLM_BRIDGE_HOST = _env("LLM_BRIDGE_HOST", "127.0.0.1")
LLM_BRIDGE_PORT = int(_env("LLM_BRIDGE_PORT", "8011"))
LLM_BRIDGE_URL = _env(
    "LLM_BRIDGE_URL", f"http://{LLM_BRIDGE_HOST}:{LLM_BRIDGE_PORT}/v1"
)

# 模型（非敏感）
LLM_MODEL = _env("LLM_MODEL", "deepseek-chat")

# 模型并发上限（mavis provider 的全局信号量大小）。
# 默认 = 参谋满编 5 路：云端模式下 4 会让第 5 路排队，总耗时≈2×单路
# （体检 2026-09-30 确认的缺陷）。本地 Ollama 单实例请调小
# （scripts/run_local.sh 预设 2）——超出的请求只是排队，无害。
LLM_CONCURRENCY = _env("LLM_CONCURRENCY", "5")

# 单次分析的时间预算（秒）。超过预算仍未返回的参谋会被标 timeout 并立刻交付。
# 现场模式建议 12s；备赛/宽松模式可放宽到 30s 甚至 0（=不限）。
#
# 这是**整轮的墙钟预算**，不是单次上游调用的上限（那条在下面的 LLM_TIMEOUT_S）。
# 两层的关系是刻意的：外层先到点 → 该路标 timeout 交付；内层若先到点 → mavis
# 会重试，而重试是**真花钱**的，结果却没人要了。所以内层必须 ≥ 外层
# （见 orchestrator 里的 `call_timeout()`），外层预算才是真正生效的那一个。
#
# 前端的默认档位跟随这个值（`/api/health.budget_s`），不再在界面里另写一个默认，
# 免得"把 ADVISOR_BUDGET_S 调宽了却没生效" —— 那种故障看不出来，只表现为超时变多。
ADVISOR_BUDGET_S = float(_env("ADVISOR_BUDGET_S", "30"))

# 单次上游调用的上限（秒），传给 mavis 的 `completion(timeout=)`。
# mavis 内部默认 90s（防上游挂起把整条管线拖死），这里把它变成可配的。
#
# 注意"不限预算"（budget=0）**不等于真的不限**：单路仍然受这个值封顶，
# 因为它就是 mavis 那层唯一的保险丝；想放得更宽就调它，不要指望 0 能解开。
LLM_TIMEOUT_S = float(_env("LLM_TIMEOUT_S", "90"))

# 参谋团名册
ADVISORS_YAML = _env("ADVISORS_YAML", str(ROOT / "configs" / "advisors.yaml"))

# 提示词模板目录。
# 提示词走 mavis 的模板层（`mavisframework.prompt.Scratch.build_prompt`），
# 所以目录直接复用 mavis 自己认的环境变量名 `MAVIS_PROMPT_DIR`。
# 这里把它读进 config，是为了让"模板从哪来"只有一个来源（下面 assign 给 Scratch）。
#
# 目录结构：顶层 `layout.txt` 是总装骨架；各领域包在 `packs/<包名>/{roles,tasks}/` 下。
# 哪个包上场由辩题的 domain 决定，映射写在下面这份配置里（见 app/prompt_packs.py）。
PROMPT_DIR = Path(_env("MAVIS_PROMPT_DIR", str(ROOT / "prompts")))

# 领域提示词包配置：domain → 用哪一套参谋措辞
PROMPT_PACKS_YAML = _env(
    "PROMPT_PACKS_YAML", str(ROOT / "configs" / "prompt-packs.yaml")
)

# 后端自身
API_HOST = _env("API_HOST", "127.0.0.1")
API_PORT = int(_env("API_PORT", "8010"))

# 数据
DATA_DIR = ROOT / "data"
LEDGER_DB = _env("LEDGER_DB", str(DATA_DIR / "ledger.db"))

# 辩题库：入仓预设（可提交）+ 本机自建（不入仓）
TOPICS_YAML = _env("TOPICS_YAML", str(ROOT / "configs" / "topics.yaml"))
TOPICS_JSON = _env("TOPICS_JSON", str(DATA_DIR / "topics.json"))

# 通用参考知识库（无结构 .txt/.md，非法条专用）：上传后切块检索，
# 注入参谋上下文的【参考知识】段。文件不入仓（data/knowledge/ 已 gitignore）。
KNOWLEDGE_DIR = Path(_env("KNOWLEDGE_DIR", str(DATA_DIR / "knowledge")))

# 语音转写（阶段 7 一期：批式，纯本地推理，0 API 消耗）。
# 引擎：sherpa = 本地 sherpa-onnx + SenseVoice；none = 界面关闭语音输入。
# 引擎是本地的，但**模型不入仓**：bash scripts/fetch_asr_model.sh 下载到
# ASR_MODEL_DIR（默认 data/asr-models/）。没下模型时 /api/health 如实报
# asr.available=false，界面收音按钮禁用并说明原因——不做静默降级。
ASR_ENGINE = _env("ASR_ENGINE", "sherpa")
ASR_MODEL_DIR = Path(_env("ASR_MODEL_DIR", str(DATA_DIR / "asr-models")))


def upstream_configured() -> bool:
    """上游凭据是否就位（只报布尔，不泄露值）。"""
    return bool(_env("ANTHROPIC_BASE_URL")) and bool(_env("ANTHROPIC_AUTH_TOKEN"))
