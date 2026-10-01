#!/usr/bin/env python3
"""零成本全链路验证用的 mock 上游（OpenAI 协议）。

用途
----
验证"生成参谋建议"整条热路径（SSE / 落库 / 推流 / 一致性检测）而**不花一次
真实 API 调用**。它按请求里 response_format 的 schema 名返回对应形状的
合规 JSON —— mavis 的结构化输出会校验顶层 `res`，形状对不上会被判 empty。

用法
----
    # 终端 1：起 mock（默认 127.0.0.1:8031）
    python scripts/mock_upstream.py

    # 终端 2：把上游切到 mock（界面上选「OpenAI 兼容端点」填 http://127.0.0.1:8031/v1，
    #          或直接 POST /api/upstream），点「生成参谋建议」
    # 验完把上游切回去（或重启后端，自动恢复环境变量那份）。

**它不联网、不调用任何真实模型、零消耗。** 数据是编造的占位内容，
只用于验证链路连通性与界面渲染，不代表参谋产出质量。
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: 按输出模型名给固定假数据（形状与 app/schemas.py 一一对应）
CANNED: dict[str, dict] = {
    "RebutterOut": {
        "res": [
            {
                "claim": "【mock】AI 生成内容的独创性认定应回到创作过程本身",
                "major_premise": "【mock】一般性原则：独创性来自人的选择与安排",
                "minor_premise": "依据《著作权法》第三条，作品是人的智力成果。【mock】对方把生成形态当成了创作行为",
                "conclusion": "【mock】不能仅以结果存在独创性外观就认定作品",
            },
            {
                "claim": "【mock】主体资格与保护必要性应当分开讨论",
                "major_premise": "【mock】一般性原则：权利主体与受保护对象可以分离",
                "minor_premise": "【mock】对方以主体不适格直接否定了讨论必要性",
                "conclusion": "【mock】应当先讨论对象再讨论主体归属",
            },
        ]
    },
    "QuestionerOut": {
        "res": [
            "【mock】你所说的独创性判断针对的是过程还是结果？",
            "【mock】如果不是人创作，权利应当归属给谁？",
            "【mock】你的标准是否会导致大量人类作品失去保护？",
        ]
    },
    "AuditorOut": {
        "res": [
            {
                "fallacy": "以偏概全",
                "quote": "【mock】AI 都不会创作",
                "explain": "【mock】用个别情形概括全部 AI 生成行为",
            }
        ]
    },
    "StrategistOut": {
        "res": [
            {
                "opponent_method": "概念界定",
                "opponent_effect": "【mock】通过收窄「创作」概念排除 AI 生成内容",
                "our_method": "价值排序",
                "counter": "【mock】先承认概念分歧，再比较两种界定的制度后果",
            }
        ]
    },
    "RiskOut": {
        "res": [
            {
                "risk": "【mock】对方可能追问独创性的判断标准",
                "kind": "对方陷阱",
                "suggestion": "【mock】提前准备两级标准回应",
            }
        ]
    },
    # 一致性检测（check-consistency）：无台账冲突时返回空
    "ConsistencyOut": {"res": []},
}
DEFAULT = {"res": []}


def pick(body: dict) -> tuple[dict, str]:
    rf = (body or {}).get("response_format") or {}
    # mavis 的形态：{"type":"json_schema","json_schema":{"name":模型名,"schema":{...}}}
    # 名字在 json_schema.name（第一版写成了 json_schema.schema.name，实测咬到）
    name = (rf.get("json_schema") or {}).get("name") or ""
    return CANNED.get(name, DEFAULT), name


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802 - http.server 命名约定
        size = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except json.JSONDecodeError:
            body = {}
        content_obj, name = pick(body)
        content = json.dumps(content_obj, ensure_ascii=False)
        self._send({
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model") or "mock-canned",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {},
        })
        print(f"[mock] schema={name or '?'} model={body.get('model')}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        # 探测模型清单用（/api/models 探针走的就是它）
        if self.path.rstrip("/").endswith("models"):
            self._send({"data": [{"id": "mock-canned"}]})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:  # 静默访问日志
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="mock OpenAI 协议上游（零成本全链路验证）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8031)
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[mock] 上游就绪：http://{args.host}:{args.port}/v1（Ctrl+C 停止）", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
