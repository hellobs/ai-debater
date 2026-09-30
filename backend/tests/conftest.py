"""pytest 全局预备。

**必须在任何测试模块导入 `app.*` 之前**把环境变量指向临时路径：
`app.config` 在导入时就会读这些变量，晚一步就固化成真实路径了。
"""
from __future__ import annotations

import os
from pathlib import Path

# 独立的测试数据目录（与 pytest 的 basetemp 分开，避免被清掉）
TESTDATA = Path(__file__).resolve().parents[1] / ".testdata"
TESTDATA.mkdir(parents=True, exist_ok=True)

# 直接赋值而不是 setdefault：测试必须是确定性的，不受开发者 shell 环境影响
os.environ["LEDGER_DB"] = str(TESTDATA / "test_ledger.db")
os.environ["CORPUS_DIR"] = str(TESTDATA / "corpus")
# 辩题库也隔离掉：否则 `POST /api/topics` 会往仓库的 data/topics.json 里写东西
os.environ["TOPICS_YAML"] = str(TESTDATA / "topics.yaml")
os.environ["TOPICS_JSON"] = str(TESTDATA / "topics.json")
