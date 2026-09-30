"""与 mavis 的**唯一**接触面。

本项目把 mavis 当**基础设施层**用，不用它的仿真半边：

| 面       | mavis 接口                        | 本项目用它做什么                       |
|----------|-----------------------------------|----------------------------------------|
| 模型接入 | `create_llm_provider()` → `LLMProvider` | 重试 / 90s 超时 / 全局并发闸 / 逐 caller 计数 |
| 提示词   | `prompt.Scratch.build_prompt()`   | 提示词是 `.txt` 数据：可 diff、可逐参谋覆盖 |
| 插件总线 | `plugin.PluginManager`            | 落库 / 推流 / 指标三个观察者，逐插件错误隔离 |

为什么不用 `Agent` / `Simulator` / 记忆 / 日程：见 `docs/spike-0-report.md`
——那是架构性错位（"每个 tick 让所有 Agent 走生活仿真管线" vs "并行出主意"），
不是配置没调好。基础设施半边用到什么程度、还缺什么：见 `docs/mavis-gap-report.md`。

**只依赖 mavis 的公开面**（三条都在 mavis 自己的文档里被声明为公开）：

- `mavisframework.create_llm_provider` —— 顶层 `__all__` 里
- `mavisframework.prompt.Scratch` —— `prompt/__init__.py` 的 `__all__` 里
- `mavisframework.plugin.PluginManager` —— `plugin.py` 模块头声明"任何外部包都能
  作为插件挂进 mavis"

后两条**没有**出现在顶层 `__all__`，只能按模块路径 import —— 记在缺口报告 #3。

`backend/app/` 下**只有本文件**允许 `import mavisframework`；
`tests/test_mavis_usage.py` 会守住这条线（连 `advisors/base.py` 走模板渲染也
只能调本文件的 `render()`）。要换掉 mavis，只需要改本文件。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from mavisframework import create_llm_provider
from mavisframework.plugin import Plugin, PluginManager
from mavisframework.prompt import Scratch

from . import config

logger = logging.getLogger("mavis_bridge")


# ==========================================================================
# 模型接入（LLMProvider）
# ==========================================================================
class _Failsafe:
    """区分「上游全挂」与「模型答了空」的哨兵。

    mavis 的 `completion()` 会吞掉全部异常（含 90s 超时），重试耗尽后把
    `failsafe` 原样返回。默认 `failsafe=None` 时，"上游连不上" 与 "模型返回空"
    在调用方看来**一模一样**。塞一个私有哨兵进去，两者就能分开报：
    哨兵 → `status=error`，空值 → `status=empty`。

    （这在只有 `None` 一种失败表示时是做不到的，也是 `_summary` 里
    `S/F` 计数之外我们能补上的信息。）
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 只为日志里好认
        return "<mavis:all-retries-failed>"


FAILED = _Failsafe()

_provider = None
_provider_lock = threading.Lock()


def is_failed(out: Any) -> bool:
    """`completion()` 的返回值是不是"重试耗尽"哨兵。"""
    return out is FAILED


def get_provider():
    """惰性创建并复用 provider。

    必须复用：mavis 的并发闸（`_GLOBAL_SEM`，进程级信号量）与调用计数
    （`_summary`）都挂在有状态的实例上。每路参谋各建一个 provider 会让
    并发上限乘以参谋数（对 Ollama 单实例是灾难），计数也会散成好几份。
    """
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                # 见 gap report #1：`cache` 只能对 mavis 自己写死的三个调用名生效，
                # 接入方的调用名加不进去，所以这里如实关掉，不假装有缓存。
                _provider = create_llm_provider({
                    "provider": "openai",                 # mavis 只讲 OpenAI 协议
                    "model": config.LLM_MODEL,
                    "base_url": config.LLM_BRIDGE_URL,    # 指向本仓库的协议桥
                    "api_key": "",                        # 桥不校验；上游凭据在桥进程环境变量里
                    "cache": False,
                    "concurrency": int(config.LLM_CONCURRENCY),
                })
                logger.info(
                    "mavis provider 就绪：model=%s base_url=%s concurrency=%s",
                    config.LLM_MODEL, config.LLM_BRIDGE_URL, config.LLM_CONCURRENCY,
                )
    return _provider


def complete(
    prompt: str,
    return_type=None,
    retry: int = 2,
    caller: str = "advisor",
    callback=None,
) -> Any:
    """调用模型。`return_type` 为 pydantic 模型时走结构化输出。

    相比裸调 `provider.completion()`，这里固定做两件事：

    - **`caller=`**：逐参谋计数。`provider_info()["summary"]` 于是能直接答出
      "这两分钟里是哪一路在失败、哪一路在重试"，而不只是一个总数。
    - **`failsafe=FAILED`**：重试耗尽返回哨兵，让调用方分得清"上游挂了"和
      "模型答了空"。

    `callback` 收到的是**已解析**的输出（结构化输出时即 `return_type.res`），
    用来做形状规整。注意 mavis 把 callback 返回 `None` 当成"这次不算数，重试"
    ——所以规整器只做归一化，绝不把"内容质量差"判成"调用失败"，否则一次
    失败会放大成 `retry` 次上游调用。
    """
    return get_provider().completion(
        prompt,
        retry=retry,
        return_type=return_type,
        caller=caller,
        callback=callback,
        failsafe=FAILED,
    )


def provider_info() -> dict:
    """给 `/api/health` 用的 provider 快照（不产生任何上游调用）。

    `cache_stats()` **不在** `LLMProvider` 抽象基类的契约里（基类只有
    `completion` / `is_available` / `get_summary` 三个），所以按"可选能力"取：
    换一个只满足基类契约的 provider 不会把健康检查打崩。
    """
    try:
        provider = get_provider()
    except Exception as exc:  # noqa: BLE001
        logger.warning("provider 创建失败", exc_info=True)
        return {"ready": False, "error": repr(exc)}

    info: dict = {"ready": True}
    try:
        info["is_available"] = bool(provider.is_available())
        info["summary"] = provider.get_summary()
    except Exception as exc:  # noqa: BLE001
        info["error"] = repr(exc)
        return info

    stats = getattr(provider, "cache_stats", None)
    try:
        info["cache"] = stats() if callable(stats) else None
    except Exception as exc:  # noqa: BLE001
        info["cache"] = {"error": repr(exc)}
    return info


# ==========================================================================
# 提示词模板（Scratch）
# ==========================================================================
_renderer: Optional[Scratch] = None
_renderer_dir: Optional[str] = None
_renderer_lock = threading.Lock()


def prompt_renderer() -> Scratch:
    """借 mavis 的 `Scratch` 做模板渲染。

    两处别扭，都因为 `Scratch` 是给"角色生活仿真"设计的：

    1. 构造签名是 `(name, currently, config, timer=None)` —— 我们只用
       `build_prompt()`，前三个位置参数完全用不上，但必须传。
    2. 模板目录在 `__init__` 时从 `MAVIS_PROMPT_DIR` 读**一次**，之后不再变。
       所以这里先把环境变量指到 `config.PROMPT_DIR`，再构造；并按目录缓存，
       目录一变（测试会 monkeypatch 它）就重建，免得读到上一个目录的模板。

    顺带一个好处：模板目录沿用 `MAVIS_PROMPT_DIR` 而不是自造变量名 ——
    "提示词从哪来"在 mavis 和本项目里是同一个名字。
    """
    global _renderer, _renderer_dir
    target = str(config.PROMPT_DIR)
    if _renderer is None or _renderer_dir != target:
        with _renderer_lock:
            if _renderer is None or _renderer_dir != target:
                os.environ["MAVIS_PROMPT_DIR"] = target
                _renderer = Scratch(name="advisor", currently="", config={})
                _renderer_dir = target
    return _renderer


def render(template: str, data: Optional[dict] = None) -> str:
    """填充 `prompts/<template>.txt`。

    占位符是 `string.Template` 的 `$var`（**不是** Python format 的 `{}`），
    未知占位符会直接抛 `KeyError` —— 这是好事，模板写错当场就报，不会带着
    `$foo` 进入提示词。

    出口处统一做两件事，都是为了让"从 Python 字符串常量搬到 .txt"
    **逐字节等价**，而不是悄悄改了提示词：

    - **CRLF → LF**：用记事本 / VS Code 在 Windows 上编辑过就是 CRLF，
      而原来的 Python 常量是 `\\n`。不归一化，同一份模板在两个编辑器下
      会渲染出不同提示词。
    - **去掉尾部换行**：文本文件按约定以换行结尾，但那个换行是文件格式的
      产物，不是提示词内容。不剥掉的话，`layout.txt` 会和它引用的两个
      子模板各多贡献一个空行。
    """
    text = prompt_renderer().build_prompt(template, data or {})
    return text.replace("\r\n", "\n").rstrip("\n")


def template_file(template: str) -> str:
    """模板的绝对路径（供启动自检与报错信息使用）。"""
    return os.path.join(str(config.PROMPT_DIR), template.replace("/", os.sep) + ".txt")


def has_template(template: str) -> bool:
    return os.path.isfile(template_file(template))


__all__ = [
    "FAILED",
    "Plugin",
    "PluginManager",
    "complete",
    "get_provider",
    "has_template",
    "is_failed",
    "prompt_renderer",
    "provider_info",
    "render",
    "template_file",
]
