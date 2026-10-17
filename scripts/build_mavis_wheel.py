#!/usr/bin/env python3
"""把 Nuitka 编译出的 mavisframework .pyd + prompts 打成平台特定 wheel。

用法：
    python scripts/build_mavis_wheel.py \
        --mavis-src <含 mavisframework/ 与 compiled/*.pyd 的目录> \
        --out-dir vendor --version 1.3.3

黑箱分发：mavisframework 是二进制 .pyd（无明文源码），prompts 随附在
独立的 mavisframework_prompts 包里；ai-debater 的 mavis_bridge 通过
MAVIS_PROMPT_DIR 环境变量指向它。
"""
import argparse
import hashlib
import os
import zipfile


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def discover_pyd(mavis_src: str) -> str:
    compiled = os.path.join(mavis_src, "compiled")
    if not os.path.isdir(compiled):
        raise SystemExit(f"找不到 compiled 目录：{compiled}（先跑 nuitka --module）")
    for fn in os.listdir(compiled):
        if fn.endswith(".pyd"):
            return os.path.join(compiled, fn)
    raise SystemExit(f"{compiled} 下没有 .pyd")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mavis-src", required=True,
                    help="含 mavisframework/ 包与 compiled/*.pyd 的目录")
    ap.add_argument("--out-dir", required=True, help="wheel 输出目录（如 vendor/）")
    ap.add_argument("--version", default="1.3.3")
    ap.add_argument("--tag", default="cp313-cp313-win_amd64",
                    help="wheel 平台标签（须与 .pyd 的 ABI/平台匹配）")
    args = ap.parse_args()

    mavis_src = os.path.abspath(args.mavis_src)
    prompts = os.path.join(mavis_src, "mavisframework", "prompts")
    prompts_zh = os.path.join(mavis_src, "mavisframework", "prompts_zh")
    pyd = discover_pyd(mavis_src)

    # wheel 文件名里的扩展模块名须与 .pyd 标签一致：mavisframework.<tag>.pyd
    ext_name = f"mavisframework.{args.tag}.pyd"
    dist_info = f"mavisframework-{args.version}.dist-info"
    wheel_name = f"mavisframework-{args.version}-{args.tag}.whl"
    os.makedirs(args.out_dir, exist_ok=True)

    metadata = f"""\
Metadata-Version: 2.1
Name: mavisframework
Version: {args.version}
Summary: MAVIS generative multi-agent simulation framework (compiled black-box build)
Requires-Python: >=3.12
License: Apache-2.0
Requires-Dist: pydantic>=2.0
Requires-Dist: requests>=2.31
Description-Content-Type: text/markdown

# mavisframework (compiled black-box build)

Platform-specific, pre-compiled distribution of the MAVIS framework, produced
with Nuitka. Contains no plain-text Python source -- the package ships as a
single native extension module (`.pyd`).

Inside:
- `{ext_name}` -- the whole framework, compiled to native code.
- `mavisframework_prompts/prompts/*.txt` and `prompts_zh/*.txt` -- prompt
  templates loaded at runtime via the `MAVIS_PROMPT_DIR` env var, which
  ai-debater's `mavis_bridge` sets automatically.

Platform: built on Windows with CPython 3.13 (AMD64). Install only on a
matching interpreter; recompile from source for other platforms/Pythons.

License: Apache-2.0 (same as upstream mavisframework).
"""

    wheel_meta = f"""\
Wheel-Version: 1.0
Generator: ai-debater black-box build (manual)
Root-Is-Purelib: false
Tag: {args.tag}
"""

    stage = []  # (arcname, data: bytes)
    with open(pyd, "rb") as f:
        stage.append((ext_name, f.read()))
    stage.append(("mavisframework_prompts/__init__.py",
                  b"# prompt templates shipped alongside the compiled wheel\n"))
    for sub, srcdir in (("prompts", prompts), ("prompts_zh", prompts_zh)):
        if not os.path.isdir(srcdir):
            continue
        for fn in sorted(os.listdir(srcdir)):
            if fn.endswith(".txt"):
                with open(os.path.join(srcdir, fn), "rb") as f:
                    stage.append((f"mavisframework_prompts/{sub}/{fn}", f.read()))
    stage.append((f"{dist_info}/METADATA", metadata.encode("utf-8")))
    stage.append((f"{dist_info}/WHEEL", wheel_meta.encode("utf-8")))
    stage.append((f"{dist_info}/top_level.txt",
                  b"mavisframework\nmavisframework_prompts\n"))

    out_path = os.path.join(args.out_dir, wheel_name)
    record = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, data in stage:
            z.writestr(arcname, data)
            record.append(f"{arcname},sha256={sha256_of(data)},{len(data)}")
        record.append(f"{dist_info}/RECORD,,")
        z.writestr(f"{dist_info}/RECORD", "\n".join(record) + "\n")

    print(f"WROTE {out_path}  ({os.path.getsize(out_path)} bytes, {len(stage)} files)")


if __name__ == "__main__":
    main()
