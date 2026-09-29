"""阶段 0 · Spike B：Agent 能否被塑造成"参谋"？

这是 PLAN §3.4 里说的可行性验证。要实测三件事：
1. 不改 mavis 的前提下，Agent 能不能被构造出来并拿到 LLM？
2. Agent.think 一步会打几次 LLM（重点：日程相关的能不能规避）？
3. 产出的东西是不是"参谋建议"的形状？

地图/计时器替身照抄 mavis 自己的契约测试 tests/test_extension_surface.py，
这是框架认可的用法（不起真实 Game 就能构造 Agent）。
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mavisframework import Timer  # noqa: E402
from mavisframework.core import agent_core  # noqa: E402
from mavisframework.core.agent_core import Agent  # noqa: E402

BRIDGE_URL = os.environ.get("LLM_BRIDGE_URL", "http://127.0.0.1:8011/v1")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
STORAGE_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "spike_agent"
)

ROLE_DIRECTIVE = (
    "你是我方（控方）首席反驳手。对方刚说：「AI 生成内容不应享有著作权，"
    "因为著作权法只保护自然人的智力成果。」请给出两条可直接使用的反驳要点。"
)


# --------------------------------------------------------------------------
# 最小替身（与 mavis 契约测试同构）
# --------------------------------------------------------------------------
class _Tile:
    """最小 Tile 替身：补齐框架 Tile 的公开属性（events / is_empty）。"""

    def __init__(self, coord=(0, 0)):
        self.coord = list(coord)
        self.address = ["辩论场", "主厅"]
        self._events = {}

    @property
    def events(self):
        return self._events

    @property
    def is_empty(self):
        return len(self.address) == 1 and not self._events

    def get_address(self, *a, **kw):
        return list(self.address) if kw.get("as_list") else ":".join(self.address)

    def has_address(self, *a):
        return False

    def update_events(self, ev):
        return False

    def add_event(self, ev):
        return None

    def remove_events(self, **kw):
        return None

    def get_events(self):
        return list(self._events.values())

    def abstract(self):
        return {"address": self.address}


class _Maze:
    def __init__(self):
        self._tiles = {}

    def tile_at(self, coord):
        key = tuple(coord)
        if key not in self._tiles:
            self._tiles[key] = _Tile(coord)
        return self._tiles[key]

    def get_scope(self, *a):
        return [self.tile_at((0, 0))]

    def get_around(self, *a):
        return [(0, 0)]

    def get_address_tiles(self, addr):
        return [(0, 0)]

    def update_obj(self, *a, **kw):
        return None


class _TimerPlaceholder:
    """已废弃：改用框架真正的 Timer（见下方 START_TIME）。

    替身计时器会缺方法（实测缺 time_format_cn），说明"自己造替身"这条路
    会持续暴露框架的隐式接口依赖——不如直接用公开 API 的 Timer。
    """


START_TIME = "20260929-20:00"


def _mk_agent(**extra):
    cfg = {
        "name": "反驳手",
        "currently": "在辩论现场待命",
        "coord": [0, 0],
        "initial_tendency": {},
        "percept": {"att_bandwidth": 4},
        "think": {
            "llm": {
                "provider": "openai",
                "model": MODEL,
                "base_url": BRIDGE_URL,
                "api_key": "",
                "cache": False,
            },
            "tendency_window": 15,
        },
        "chat_iter": 1,
        "chat_cooldown_min": 20,
        "chat_retry_prob": 0.5,
        "spatial": {"address": {}, "tree": {}},
        "schedule": {},
        "associate": {"embedding": {"provider": "simple"}},
        "scratch": {
            "age": 30,
            "innate": "严谨、好斗",
            "learned": "民法与著作权法",
            "lifestyle": "全天在辩论场待命",
            "daily_plan": "为控方提供反驳要点",
        },
        "storage_root": os.path.abspath(STORAGE_ROOT),
        "role_type": "user",
        "role_directive": ROLE_DIRECTIVE,
        "no_sleep": True,
    }
    cfg.update(extra)
    return cfg


def main() -> int:
    os.makedirs(os.path.abspath(STORAGE_ROOT), exist_ok=True)

    captured: list[tuple[str, str]] = []

    def _on_chat_line(speaker, text):
        captured.append((speaker, text))

    agent_core.subscribe_chat_line(_on_chat_line)

    print("[spike B] 构造 Agent（替身地图 + no_sleep + role_directive）……")
    t_build = time.time()
    agent = Agent(_mk_agent(), _Maze(), {}, timer=Timer(start=START_TIME))
    print(f"[spike B] 构造耗时 {time.time() - t_build:.2f}s")

    t_reset = time.time()
    agent.reset()
    print(f"[spike B] reset（建 provider）耗时 {time.time() - t_reset:.2f}s")
    print(f"[spike B] llm_available = {agent.llm_available()}")

    status = {"coord": [0, 0]}
    print("[spike B] 驱动 think() 一步（这一步会暴露日程相关的 LLM 调用）……")
    t0 = time.time()
    err = None
    result = None
    try:
        result = agent.think(status, {})
    except Exception as exc:  # noqa: BLE001
        err = repr(exc)
    dt = time.time() - t0

    print(f"[spike B] think 耗时 {dt:.2f}s")
    if err:
        print(f"[spike B] think 抛错：{err}")
    if result is not None:
        try:
            print(f"[spike B] think 返回 keys = {list(result.keys())}")
        except Exception:
            print(f"[spike B] think 返回 = {result!r}"[:400])

    summary = agent._llm.get_summary() if agent._llm else {}
    print(f"[spike B] LLM 调用统计 = {json.dumps(summary, ensure_ascii=False)}")
    n_calls = 0
    for k, v in (summary.get("summary") or {}).items():
        if k == "total":
            continue
        n_calls += int(str(v).split(":")[0].replace("S", "") or 0)
    print(f"[spike B] 非 total 调用数 = {n_calls}")
    print(f"[spike B] chat_line 捕获条数 = {len(captured)}")
    for spk, txt in captured[:3]:
        print(f"[spike B]   {spk}: {txt[:120]}")

    agent_core.unsubscribe_chat_line(_on_chat_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
