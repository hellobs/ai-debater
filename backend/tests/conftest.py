"""pytest 全局预备。

**必须在任何测试模块导入 `app.*` 之前**把环境变量指向临时路径：
`app.config` 在导入时就会读这些变量，晚一步就固化成真实路径了。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# 独立的测试数据目录（与 pytest 的 basetemp 分开，避免被清掉）
TESTDATA = Path(__file__).resolve().parents[1] / ".testdata"
TESTDATA.mkdir(parents=True, exist_ok=True)

# 直接赋值而不是 setdefault：测试必须是确定性的，不受开发者 shell 环境影响。
# ⚠️ 库名必须带本次运行的 id：早先用固定名 `test_ledger.db`，于是每跑一次全量
# pytest 就往**同一个文件**里再灌几百条假会话（实测一次 875 条会话 / 440 建议 /
# 117 反馈），既胀磁盘又让用例之间隔着上一轮的残留互相影响。
RUN_ID = f"{os.getpid()}-{int(time.time())}"
os.environ["LEDGER_DB"] = str(TESTDATA / f"test_ledger.{RUN_ID}.db")
os.environ["CORPUS_DIR"] = str(TESTDATA / "corpus")
# 辩题库也隔离掉：否则 `POST /api/topics` 会往仓库的 data/topics.json 里写东西
os.environ["TOPICS_YAML"] = str(TESTDATA / "topics.yaml")
os.environ["TOPICS_JSON"] = str(TESTDATA / "topics.json")
# ASR 模型目录指向不存在的测试路径：默认测试集不依赖 230MB 的本地模型
# （要测真模型的是 test_asr.py 里带 skipif 的那条，自己指回真实目录）
os.environ["ASR_MODEL_DIR"] = str(TESTDATA / "asr-models")
os.environ["KNOWLEDGE_DIR"] = str(TESTDATA / "knowledge")

import pytest  # noqa: E402  —— 必须在环境变量就位之后再导入 app.*


@pytest.fixture(scope="module")
def client():
    """真实路由的 TestClient。按模块隔离，避免模块间互相踩状态。"""
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        # 界面发的一切请求都带 CSRF 防护头（见 main.py csrf_guard）；
        # 测试模拟的是真实 UI，所以默认也带。需要测"无头被拒"的用例
        # 自行用不带该头的客户端（见 test_csrf_guard.py）。
        c.headers["X-Debater-UI"] = "1"
        yield c


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """跑完把本次的测试库清掉 —— 测试产物不留在工作区里。"""
    # `test_ledger*.db` 含历史固定名的旧库（早期格式），一并清掉
    for p in TESTDATA.glob("test_ledger*.db"):
        try:
            p.unlink()
        except Exception:  # noqa: BLE001 - 清不掉也不该让测试变红（本机沙箱的 safe-delete
            pass  #     会拦 unlink；清不掉只是多留一个文件，下次运行本来就换个文件名）
