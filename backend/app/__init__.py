"""`app` 包。

这里只有一件事：**保证任何 `app.*` 入口被导入时，`<仓库>/.env` 都已生效。**

为什么放在包级而不是各入口自己 import：本项目有四个入口 ——
`app.main`（后端）、`app.llm_bridge`（协议桥）、`app.advisors`（脚本/测试直接调）、
以及 `spikes/` 下的临时脚本。凭据只被**协议桥**真正使用，而桥此前既不 import config、
也不读 `.env`，于是用户照 `.env.example` 把凭据写进 `.env`、起桥，
会得到 `upstream_configured: false`，且上游侧只表现为**空响应 + 静默重试**
—— 这是最难查的一类故障。放在包级，四个入口自动一致，也不会有人"忘了加"。

实现仍在 `app/config.py`（单一来源）：`_load_dotenv` / `_apply_dotenv` / `ENV_FILE`。
测试见 `tests/test_config.py`。
"""
from . import config as _config  # noqa: F401  —— 导入即副作用：应用 .env

__all__: list[str] = []
