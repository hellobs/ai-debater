"""阶段 0 · Spike A：验证 mavis 的 OpenAIProvider 能经本桥直连模型。

结论只有两种：通 / 不通。通了才谈后面。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mavisframework.runtime.llm import create_llm_provider  # noqa: E402

BRIDGE_URL = os.environ.get("LLM_BRIDGE_URL", "http://127.0.0.1:8011/v1")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

PROMPT = (
    "你是法学辩论参谋。用一句话（不超过60字）说明什么叫法律涵摄。"
    "只输出那句话本身，不要任何前缀。"
)


def main() -> int:
    cfg = {
        "provider": "openai",
        "model": MODEL,
        "base_url": BRIDGE_URL,
        "api_key": "",          # 桥不校验 key；上游凭据在桥进程的环境变量里
        "cache": False,
        "concurrency": 4,
    }
    print(f"[spike A] bridge={BRIDGE_URL} model={MODEL}")
    llm = create_llm_provider(cfg)
    print(f"[spike A] is_available = {llm.is_available()}")

    t0 = time.time()
    out = llm.completion(PROMPT, retry=2)
    dt = time.time() - t0

    print(f"[spike A] latency = {dt:.2f}s")
    print(f"[spike A] output  = {out!r}")
    print(f"[spike A] summary = {json.dumps(llm.get_summary(), ensure_ascii=False)}")

    ok = bool(out and str(out).strip())
    print(f"[spike A] RESULT  = {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
