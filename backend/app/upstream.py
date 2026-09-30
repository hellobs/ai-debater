"""当前生效的上游（模型接入）—— **运行时可改，只驻留内存**。

为什么要有这一层
----------------
上游原本只能靠环境变量在**启动前**定好：换模型要改 `.env` 再重启后端，
界面上一个下拉框都做不到。而"用哪个模型"恰恰是最该由使用者当场决定的事
（本机 8B 慢但免费、云端快但计费；同一场辩论里也可能想换着试）。

三种形态，差别只在协议：

| kind        | mavis 连谁                        | 凭据         |
|-------------|-----------------------------------|--------------|
| `ollama`    | 直连本机 Ollama 的 `/v1`（OpenAI 兼容）| 不需要       |
| `openai`    | 直连任意 OpenAI 兼容端点           | Bearer       |
| `anthropic` | 内嵌协议桥 `/bridge/v1` → 上游网关 | x-api-key    |

`anthropic` 是唯一需要转译的一种：mavis 只会讲 OpenAI 协议，而有些网关只认
Anthropic 协议。转译由 `app/llm_bridge.py` 承担 —— 它被 mount 进本进程，
所以这一层改配置**不需要跨进程通信**，也不再强求"先起桥再起后端"。

安全红线（与 `llm_bridge.py` 一致，不因为加了配置界面就松口）
------------------------------------------------------------
**后端这一侧**：凭据**只活在内存** —— 不写文件、不进 `.env`、不出现在任何响应里
（对外只有 `key_set: bool`）、不打进日志（日志只记主机与 kind）。进程重启即失效，
回到环境变量给的初值。这一点没有因为"可以用界面配置"而改变。

**保存发生在前端那一侧**：界面可以把配好的上游（含密钥）存进浏览器的
`localStorage`，下次打开自动回灌到本进程的内存里（见 `frontend/src/upstreamStore.ts`）。
分工是刻意的：后端仍然一行不落盘，持久化交给使用者的浏览器 —— 它不进仓库、
不进 `.env`、不会被提交或分享，清除只需一键。代价是明文存在本机浏览器里，
这事在界面上写明了，不做"看起来安全"的混淆。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import httpx

from . import config

logger = logging.getLogger("upstream")

#: 支持的形态。`anthropic` 之外的两种都是 OpenAI 协议，mavis 直连即可。
KINDS: Tuple[str, ...] = ("ollama", "openai", "anthropic")

#: 探测模型列表的超时。这是"点一下刷新"的交互，不该让人等半分钟。
PROBE_TIMEOUT = 10.0

_OLLAMA_HINT = "http://127.0.0.1:11434/v1"


@dataclass
class Settings:
    """一份上游配置。

    `base_url` 的语义随 kind 变：`ollama` / `openai` 下它就是 mavis 要访问的地址；
    `anthropic` 下它是**上游网关**的地址（mavis 访问的是内嵌桥，见 `mavis_base_url`）。
    这个差别必须在字段名上看不出来，否则填错一个就变成"连上了但协议不对"。
    """

    kind: str = "ollama"
    base_url: str = _OLLAMA_HINT
    model: str = ""
    #: 只内存。对外永不以明文形式出现。
    api_key: str = field(default="", repr=False)

    def mavis_base_url(self) -> str:
        """mavis 实际访问的地址。"""
        if self.kind == "anthropic":
            # 自调用：协议桥就 mount 在本进程上（见 main.py）
            return f"http://{config.API_HOST}:{config.API_PORT}/bridge/v1"
        return self.base_url.rstrip("/")

    def host(self) -> str:
        """日志/UI 展示用的主机部分（不含路径，也就不会带上路径里的 token）。"""
        url = self.base_url if self.kind != "anthropic" else self.mavis_base_url()
        return url.split("//")[-1].split("/")[0]

    def public(self) -> dict:
        """对外快照：凭据只报有没有，不报是什么。"""
        return {
            "kind": self.kind,
            "base_url": self.base_url,
            "model": self.model,
            "key_set": bool(self.api_key),
            "mavis_base_url": self.mavis_base_url(),
            "host": self.host(),
        }


# ----------------------------------------------------------------------
# 初值：仍然来自环境变量（保持"照文档配 .env 就能跑"），之后可被运行时覆盖
# ----------------------------------------------------------------------
def _initial() -> Settings:
    """从环境推断初始形态。

    推断规则刻意保守：**认得出的才算 ollama**，其余一律按 anthropic（走桥）处理
    —— 因为三件套（桥 + 后端 + 前端）是文档里的默认跑法，猜错成"直连"会让
    用户面对一个毫无头绪的 404，而猜成"走桥"至少错误集中在桥的日志里。
    想明确指定就设 `UPSTREAM_KIND`。
    """
    kind = config._env("UPSTREAM_KIND").strip().lower()
    if kind not in KINDS:
        kind = "ollama" if ":11434" in config.LLM_BRIDGE_URL else "anthropic"
    if kind == "anthropic":
        return Settings(
            kind="anthropic",
            base_url=config._env("ANTHROPIC_BASE_URL").rstrip("/"),
            api_key=config._env("ANTHROPIC_AUTH_TOKEN"),
            model=config.LLM_MODEL,
        )
    return Settings(
        kind=kind,
        base_url=config.LLM_BRIDGE_URL,
        api_key="" if kind == "ollama" else config._env("ANTHROPIC_AUTH_TOKEN"),
        model=config.LLM_MODEL,
    )


_current: Settings = _initial()
_lock = threading.Lock()


def current() -> Settings:
    return _current


def update(
    kind: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Settings:
    """改当前上游。只传要改的字段；`api_key=None` 表示**不动**（不是清空）。

    "不动"与"清空"必须分开：界面上常见操作是"只换个模型"，那时它根本不提交
    密钥字段；若把缺失当成清空，用户换一次模型就得重填一次密钥。
    """
    global _current
    with _lock:
        if kind is not None:
            if kind not in KINDS:
                raise ValueError(f"未知上游形态：{kind}（可选 {', '.join(KINDS)}）")
            _current.kind = kind
        if base_url is not None:
            _current.base_url = base_url.strip().rstrip("/")
        if model is not None:
            _current.model = model.strip()
        if api_key is not None:
            _current.api_key = api_key
    # 只记主机与形态：凭据一个字都不进日志
    logger.info("上游已更新：kind=%s host=%s model=%s key_set=%s",
                _current.kind, _current.host(), _current.model, bool(_current.api_key))
    return _current


# ----------------------------------------------------------------------
# 模型探测
# ----------------------------------------------------------------------
def _get_json(url: str, headers: Optional[dict] = None) -> Tuple[Optional[dict], str]:
    try:
        resp = httpx.get(url, headers=headers or {}, timeout=PROBE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - 探测失败要变成界面上的一句话
        return None, f"连不上 {url.split('//')[-1].split('/')[0]}：{type(exc).__name__}"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    try:
        return resp.json(), ""
    except Exception:  # noqa: BLE001
        return None, "返回的不是 JSON"


def _ollama_models(base_url: str) -> Tuple[List[str], str]:
    """Ollama 的模型清单在 `/api/tags`（不是 OpenAI 的 `/v1/models`）。"""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    data, err = _get_json(f"{root}/api/tags")
    if data is None:
        return [], err or "无法解析 /api/tags"
    names = [
        (m.get("name") or m.get("model") or "").strip()
        for m in (data.get("models") or [])
    ]
    return [n for n in names if n], ""


def _openai_models(base_url: str, api_key: str = "") -> Tuple[List[str], str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    data, err = _get_json(f"{base_url.rstrip('/')}/models", headers)
    if data is None:
        return [], err or "无法解析 /models"
    items = data.get("data") or data.get("models") or []
    names = [(i.get("id") or i.get("name") or "").strip() for i in items if isinstance(i, dict)]
    return [n for n in names if n], ""


def _anthropic_models(base_url: str, api_key: str = "") -> Tuple[List[str], str]:
    """Anthropic 协议的 `/v1/models`。

    不是每家网关都实现它 —— 探测不到时**如实报不支持**，由界面退回手填，
    而不是拿一份写死的清单冒充"可用模型"。
    """
    headers = {
        "x-api-key": api_key,
        "anthropic-version": config._env("ANTHROPIC_VERSION", "2023-06-01"),
    }
    root = base_url.rstrip("/")
    if not root.endswith("/v1"):
        root += "/v1"
    data, err = _get_json(f"{root}/models", headers)
    if data is None:
        return [], err or "无法解析 /models"
    items = data.get("data") or data.get("models") or []
    names = [(i.get("id") or i.get("name") or "").strip() for i in items if isinstance(i, dict)]
    return [n for n in names if n], ""


def probe_models(
    kind: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Tuple[List[str], str, dict]:
    """探测某份配置下有哪些模型可用，返回 `(模型列表, 错误说明, 探测目标)`。

    第三个返回值是刻意的：清单**必须连着"它是从哪份配置探来的"一起给**。
    否则界面上会出现最误导人的一种状态 —— 用户改了形态或地址、还没重探，
    屏幕上却摆着上一个端点的模型名，照着点就填了一个这个端点根本没有的模型。

    不带参数 = 探测**当前生效**的上游。传了参数则按那份配置探（界面上"填完先试试"
    就是这样用的 —— 不该先切过去再探）。

    探测**不产生任何推理调用**，只是列清单，不计费。
    """
    s = current()
    kind = (kind or s.kind).strip().lower()
    url = (base_url.strip() if base_url else "") or s.base_url
    key = api_key if api_key is not None else s.api_key
    target = {"kind": kind, "base_url": url}

    if kind not in KINDS:
        return [], f"未知上游形态：{kind}", target
    if not url:
        return [], "还没填地址", target

    if kind == "ollama":
        models, err = _ollama_models(url)
    elif kind == "openai":
        models, err = _openai_models(url, key)
    else:
        models, err = _anthropic_models(url, key)
    return models, err, target


__all__ = [
    "KINDS",
    "Settings",
    "current",
    "probe_models",
    "update",
]
