"""与 mavis 的**唯一**接触面。

本项目把 mavis 当**基础设施层**用，不用它的仿真半边：

| 面       | mavis 接口                        | 本项目用它做什么                       |
|----------|-----------------------------------|----------------------------------------|
| 模型接入 | `create_llm_provider()` → `LLMProvider` | 重试 / 可调超时 / 全局并发闸 / 逐 caller 计数 |
| 提示词   | `prompt.Scratch.build_prompt()`   | 提示词是 `.txt` 数据：可 diff、可逐参谋覆盖、可按领域换包 |
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
from pathlib import Path
from typing import Any, List, Optional

import mavisframework
from mavisframework import create_llm_provider
from mavisframework.plugin import Plugin, PluginManager
from mavisframework.prompt import Scratch

from . import config, prompt_packs, upstream
#: 桥写下的失败哨兵前缀。常量定义在桥那一侧（`llm_bridge.py`）——
#: 它是「桥 ↔ 调用方」之间的约定，不能在两边各写一份字面量。
#: 没有循环导入：`llm_bridge` 只依赖 `config` / `upstream`。
from .llm_bridge import BRIDGE_ERROR_PREFIX

logger = logging.getLogger("mavis_bridge")


# ==========================================================================
# 模型接入（LLMProvider）
# ==========================================================================
class _Failsafe:
    """区分「上游全挂」与「模型答了空」的哨兵。

    mavis 的 `completion()` 会吞掉全部异常（含单次调用超时），重试耗尽后把
    `failsafe` 原样返回。默认 `failsafe=None` 时，两类失败在调用方看来无从区分 ——
    上游连不上返回 `None`，模型返回空内容返回 `''`，差别只是实现副产品，
    任何按空值归并结果的判定（本项目 base.py 的 `out is None or len(out) == 0`）
    都会把两者收进同一分支。塞一个私有哨兵进去，两者就能分开报：
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


def bridge_error(out: Any) -> Optional[str]:
    """`completion()` 的返回值是不是协议桥写下的失败哨兵？是则返回原因。

    背景：mavis 不看 HTTP 状态码（只读 `choices[0].message.content`），
    所以桥在失败时**同时**给两样东西 —— 如实的状态码（给脚本与 curl 看），
    以及 content 里的 `BRIDGE_ERROR_PREFIX`（给 mavis 这条路径看）。

    这里把后者翻成异常，否则空 content 会被当成"模型答了空"，记为
    `status="empty"`，界面上只显示「未返回内容。」—— 与"模型真没话说"
    完全无法区分，而真因只躺在后端日志里。
    """
    if not isinstance(out, str):
        return None
    text = out.strip()
    if not text.startswith(BRIDGE_ERROR_PREFIX):
        return None
    return text[len(BRIDGE_ERROR_PREFIX):].strip() or "上游失败（桥未记录原因）"


def reset_provider() -> None:
    """丢弃当前 provider，下次 `get_provider()` 重建。

    换上游（地址 / 模型）后必须调：mavis 的 provider 在构造时就把 `base_url`
    与 `model` 定死了，之后改不了。而并发闸与逐 caller 计数**挂在实例上** ——
    重建会让它们归零，这是可接受的代价：换上游本来就意味着"之前的统计
    属于另一个模型"，混在一起反而看不懂。
    """
    global _provider
    with _provider_lock:
        _provider = None


def get_provider():
    """惰性创建并复用 provider。

    必须复用：mavis 的并发闸（`_GLOBAL_SEM`，进程级信号量）与调用计数
    （`_summary`）都挂在有状态的实例上。每路参谋各建一个 provider 会让
    并发上限乘以参谋数（对 Ollama 单实例是灾难），计数也会散成好几份。

    地址与模型取**当前生效的上游**（`app/upstream.py`），不是启动时那份环境变量
    —— 界面改了上游之后，下一次调用就该用新的。
    """
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                settings = upstream.current()
                # 见 gap report #1：`cache` 只能对 mavis 自己写死的三个调用名生效，
                # 接入方的调用名加不进去，所以这里如实关掉，不假装有缓存。
                _provider = create_llm_provider({
                    "provider": "openai",                 # mavis 只讲 OpenAI 协议
                    "model": settings.model or config.LLM_MODEL,
                    "base_url": settings.mavis_base_url(),
                    "api_key": "",                        # 桥不校验；上游凭据在桥进程环境变量里
                    "cache": False,
                    "concurrency": int(config.LLM_CONCURRENCY),
                })
                logger.info(
                    "mavis provider 就绪：model=%s base_url=%s concurrency=%s",
                    settings.model or config.LLM_MODEL, settings.mavis_base_url(),
                    config.LLM_CONCURRENCY,
                )
    return _provider


def complete(
    prompt: str,
    return_type=None,
    retry: int = 2,
    caller: str = "advisor",
    callback=None,
    timeout: Optional[float] = None,
) -> Any:
    """调用模型。`return_type` 为 pydantic 模型时走结构化输出。

    相比裸调 `provider.completion()`，这里固定做两件事：

    - **`caller=`**：逐参谋计数。`provider_info()["summary"]` 于是能直接答出
      "这两分钟里是哪一路在失败、哪一路在重试"，而不只是一个总数。
    - **`failsafe=FAILED`**：重试耗尽返回哨兵，让调用方分得清"上游挂了"和
      "模型答了空"。

    **`timeout`** 是单次上游调用的上限，直接落到 mavis 的
    `_completion_timeout(timeout=)`（mavis 自己写死 90s，但它是 `completion()`
    的一个 `**kwargs` 参数，可以传进去 —— 改框架源码是不允许的，传参不算改）。
    为什么必须能调：mavis 超时后会 `sleep(5)` 再重试，**每一次重试都是真的
    上游调用**。若它比本轮预算先到点，结果是"花了两次调用的钱，产出一份
    已经被标 timeout 丢弃的答案"。所以调用方要让它 ≥ 本轮预算（见
    `orchestrator.call_timeout()`）。

    不传 → 用 `config.LLM_TIMEOUT_S`；传 0 或负数 → 不传参，退回 mavis 内置值。

    `callback` 收到的是**已解析**的输出（结构化输出时即 `return_type.res`），
    用来做形状规整。注意 mavis 把 callback 返回 `None` 当成"这次不算数，重试"
    ——所以规整器只做归一化，绝不把"内容质量差"判成"调用失败"，否则一次
    失败会放大成 `retry` 次上游调用。
    """
    kwargs = {}
    seconds = config.LLM_TIMEOUT_S if timeout is None else timeout
    if seconds and seconds > 0:
        kwargs["timeout"] = seconds
    out = get_provider().completion(
        prompt,
        retry=retry,
        return_type=return_type,
        caller=caller,
        callback=callback,
        failsafe=FAILED,
        **kwargs,
    )
    # 桥没法靠状态码通知 mavis（mavis 不读状态码），它把原因写进了 content。
    # 在这里翻成异常，才能落到 `Advisor.run` 的 `status="error"` 分支上。
    reason = bridge_error(out)
    if reason:
        raise RuntimeError(f"协议桥报告上游失败：{reason}")
    return out


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
#: 领域提示词包在 `prompts/` 下的目录名。`render("roles/rebutter", pack="legal")`
#: 会去 `prompts/packs/legal/roles/rebutter.txt` 找模板。
#: 选哪个包是 `prompt_packs.py` 的策略，这里只负责拼路径。
PACKS_SUBDIR = "packs"

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


def _template_rel(template: str, pack: Optional[str] = None) -> str:
    """模板相对 `PROMPT_DIR` 的路径（无扩展名）。

    `pack=None` → 顶层模板（只有 `layout` 走这条）；
    `pack="legal"` → `packs/legal/<template>`。**没有"自动选包"**：
    调用方必须把包名交出来，免得"这次到底用了哪套措辞"变成要读代码才知道的事。
    """
    rel = template.replace("/", os.sep)
    if pack:
        rel = os.path.join(PACKS_SUBDIR, pack, rel)
    return rel


def render(template: str, data: Optional[dict] = None, pack: Optional[str] = None) -> str:
    """填充 `prompts/<template>.txt`（给了 `pack` 则在 `prompts/packs/<pack>/` 下）。

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
    path = _template_rel(template, pack).replace(os.sep, "/")
    text = prompt_renderer().build_prompt(path, data or {})
    return text.replace("\r\n", "\n").rstrip("\n")


def template_file(template: str, pack: Optional[str] = None) -> str:
    """模板的绝对路径（供启动自检与报错信息使用）。"""
    return os.path.join(str(config.PROMPT_DIR), _template_rel(template, pack) + ".txt")


def has_template(template: str, pack: Optional[str] = None) -> bool:
    return os.path.isfile(template_file(template, pack))


# ==========================================================================
# 对外自述：我们到底借了 mavis 什么
# ==========================================================================
# 这三面写死在代码里，而不是只写在文档里 —— 这样 `/api/health`、导出报告、
# README 讲的是**同一个事实**，不会再出现"文档说 6 条缺口、实际 7 条"那种漂移。
SURFACES: tuple = (
    {
        "key": "provider",
        "name": "模型接入",
        "entry": "create_llm_provider() → LLMProvider",
        "used_in": "mavis_bridge.complete()",
        "detail": "重试 / 单次调用超时（LLM_TIMEOUT_S，默认 90s，可由本轮预算抬高）/ 进程级并发闸 / 逐 caller 计数 / 失败哨兵",
    },
    {
        "key": "prompt",
        "name": "提示词模板",
        "entry": "prompt.Scratch.build_prompt()",
        "used_in": "mavis_bridge.render()",
        "detail": "三层 .txt（layout + 领域包 packs/*/{roles,tasks}），提示词是可 diff、可按领域替换的数据",
    },
    {
        "key": "plugin",
        "name": "插件总线",
        "entry": "plugin.PluginManager",
        "used_in": "observers.build_manager()",
        "detail": "落库 / 推流 / 指标三个观察者，逐插件错误隔离",
    },
)

#: 唯一允许 `import mavisframework` 的文件。`tests/test_mavis_usage.py` 用 AST 守着。
CONTACT_MODULE = "backend/app/mavis_bridge.py"

#: mavis 用不上的半边。这是**架构性错位**，证据在 `docs/spike-0-report.md`。
UNUSED_HALF = "Agent / Game / Simulator / 记忆 / 日程 / 空间"

#: 本项目的**基座框架**（发行包名）。"基于 X 开发" 比 "用到 X" 是更强的断言：
#: 前者说的是项目的成型依赖，后者只说明调用过一次。写进代码，以免它只活在文档里。
BASED_ON = "mavisframework"


def version() -> str:
    """mavis 版本号。

    `mavisframework.__version__` 由包自己暴露；取不到就返回 `"unknown"` ——
    健康检查与导出报告都不该因为一个展示字段把整个请求打崩。
    """
    return str(getattr(mavisframework, "__version__", "unknown"))


def prompt_inventory() -> dict:
    """`prompts/` 下的模板清单（健康检查与导出报告共用一份口径）。"""
    root = Path(config.PROMPT_DIR)
    if not root.is_dir():
        return {"dir": str(root), "templates": 0, "names": []}
    names: List[str] = sorted(
        p.relative_to(root).as_posix()[: -len(".txt")] for p in root.rglob("*.txt")
    )
    return {"dir": str(root), "templates": len(names), "names": names}


def runtime_info() -> dict:
    """`/api/health` 用的 mavis 接入快照。

    **不产生任何上游调用**，只读本地状态（包版本 + 模板目录 + 写死的三面清单）。

    `readonly: True` 不是形容词而是前提：mavis 以只读依赖接入、仓库一行未改，
    所以 `docs/mavis-gap-report.md` 里的结论对**框架本身**成立，
    而不是"我们魔改之后的效果"。
    """
    return {
        "framework": "mavis",
        "based_on": BASED_ON,
        "version": version(),
        "readonly": True,
        "contact": CONTACT_MODULE,
        "surfaces": [dict(s) for s in SURFACES],
        "unused": UNUSED_HALF,
        "prompts": prompt_inventory(),
        # 有哪些领域提示词包、哪个是兜底：提示词这一面的"可替换性"自述。
        "packs": prompt_packs.describe(),
    }


def declaration(framework: str | None = None) -> str:
    """归属声明：「本项目与框架是什么关系」的唯一句式。

    `framework` 只用于替换**框架名的呈现形式**（Markdown 链接 / HTML 粗体 / 纯文本），
    句式本身不交给调用方 —— README、导出报告、界面脚注说的必须是同一句话。
    """
    label = framework or BASED_ON
    return f"本项目基于 {label} v{version()} 开发（只读依赖，一行未改）"


def dependency_note() -> str:
    """底座署名里"版本 + 只读声明"那一段。

    **不含框架名与链接** —— 怎么排（Markdown 链接 / HTML / Word 纯文本）
    由调用方决定，这里只保证"mavis 的版本号和只读事实"永远只有一份。
    """
    return f"v{version()}（只读依赖，一行未改）"


__all__ = [
    "BASED_ON",
    "CONTACT_MODULE",
    "FAILED",
    "Plugin",
    "PluginManager",
    "SURFACES",
    "UNUSED_HALF",
    "complete",
    "declaration",
    "dependency_note",
    "get_provider",
    "has_template",
    "is_failed",
    "prompt_inventory",
    "prompt_renderer",
    "provider_info",
    "render",
    "reset_provider",
    "runtime_info",
    "template_file",
    "version",
]
