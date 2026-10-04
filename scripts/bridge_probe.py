#!/usr/bin/env python3
"""协议桥跨站调用取证 / 回归脚本（**零真实消耗**：上游是脚本内起的本地 mock）。

它回答体检（2026-10-04）留下的那个问题
--------------------------------------
`main.py` 把 `/bridge` 整条豁免在 CSRF 守卫之外（调用方 mavis 是服务端进程，
拿不到 `X-Debater-UI` 头）。实测下来这条豁免是空的：

* 桥在转发前不看任何来源，只要上游配了就无条件把 `x-api-key` 带上发出去；
* 浏览器发 `Content-Type: text/plain` 的 POST 属于 CORS「简单请求」，**不发预检、
  用不上自定义头** —— 恶意网页一句 fetch 就能打到 `http://127.0.0.1:8010/bridge/v1/
  completions`，替你烧掉上游额度（回包会被浏览器变 opaque，攻击者读不到，但钱是他花）。

修复（2026-10-04）把桥自己变成第二道防线：跨站来源一律 403，且**在碰上游之前**就拒。

用法
----
    python scripts/bridge_probe.py            # 默认 mock 端口 8041
    python scripts/bridge_probe.py --port 8051

硬指标（脚本自己判 PASS / FAIL，退出码 0 = 通过）
--------------------------------------------------
    跨站（Origin / Referer 非本机）三种形态 → 403 且**上游 0 次**
    本机源 http://127.0.0.1:5173            → 200 且上游 1 次
    无来源（mavis 用 httpx 调桥的自然形态） → 200 且上游 1 次

最后两条是防「修复过头」：mavis / curl / 体检脚本都不带 Origin，误伤了服务就没了。

**它不联网、不调用任何真实模型、零消耗。**
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

HITS: list[dict] = []


class _Mock(BaseHTTPRequestHandler):
    """只记账的 Anthropic 形态假上游：记一笔就回合规 JSON。"""

    def do_POST(self):
        HITS.append({
            "path": self.path,
            "api_key": self.headers.get("x-api-key"),
            "typed": bool(self.headers.get("content-type", "").startswith("application/json")),
        })
        out = json.dumps({
            "id": "probe-mock",
            "type": "message",
            "role": "assistant",
            "model": "probe-mock",
            "content": [{"type": "text", "text": '{"res":{}}'}],
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):  # 静音，别污染输出
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="协议桥跨站调用取证（0 消耗）")
    ap.add_argument("--port", type=int, default=8041, help="本地 mock 上游端口")
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    from fastapi.testclient import TestClient  # noqa: E402  (REPL 里 import 顺序无所谓)

    from app import llm_bridge  # noqa: E402

    llm_bridge.CFG.base = f"http://127.0.0.1:{args.port}"
    llm_bridge.CFG.token = "sk-probe-fake-not-real"
    client = TestClient(llm_bridge.app)

    payload = {"model": "probe", "messages": [{"role": "user", "content": "hi"}]}
    body = json.dumps(payload, ensure_ascii=False)

    cases = [
        # (标签, 期望状态码, 期望打到上游次数, TestClient kwargs)
        ("跨站 Origin=https://evil.example（JSON）", 403, 0,
         {"json": payload, "headers": {"Origin": "https://evil.example"}}),
        ("跨站 Origin=https://evil.example（text/plain，浏览器简单请求，无预检）", 403, 0,
         {"content": body, "headers": {"Origin": "https://evil.example",
                                       "Content-Type": "text/plain"}}),
        ("跨站 Referer=https://evil.example/x", 403, 0,
         {"json": payload, "headers": {"Referer": "https://evil.example/x"}}),
        ("本机源 Origin=http://127.0.0.1:5173（dev server）", 200, 1,
         {"json": payload, "headers": {"Origin": "http://127.0.0.1:5173"}}),
        ("无来源（mavis / curl 的自然形态）", 200, 1, {"json": payload}),
        ("本机 Origin=http://localhost:5173", 200, 1,
         {"json": payload, "headers": {"Origin": "http://localhost:5173"}}),
    ]

    ok = True
    print(f"mock 上游 127.0.0.1:{args.port} / 桥的 CFG 已指向它（0 真实调用）\n")
    for label, want_status, want_hits, kwargs in cases:
        before = len(HITS)
        try:
            resp = client.post("/v1/chat/completions", **kwargs)
            status, detail = resp.status_code, resp.text[:80]
        except Exception as exc:  # starlette 报 JSON 解析错之类的
            status, detail = 0, f"EXC {type(exc).__name__}: {str(exc).splitlines()[0][:60]}"
        hits = len(HITS) - before
        good = status == want_status and hits == want_hits
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {label}")
        print(f"          status={status}(期望{want_status}) 上游命中={hits}(期望{want_hits})  {detail}")

    # 硬指标：跨站调用一次都不许碰到上游
    leaked = [h for h in HITS if not h["typed"]]
    print(f"\n上游总命中 {len(HITS)} 次（全部来自本机源用例）")
    if leaked:
        ok = False
        print("  [FAIL] 有跨站形态打到了上游 —— 额度会被跨站烧掉")
    print("\n结论：" + ("PASS —— 跨站被拒在碰上游之前，正常调用未受影响" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
