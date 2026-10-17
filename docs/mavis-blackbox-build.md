# mavis 编译黑箱构建与分发

mavis 现在以**编译黑箱**形式分发：不公开源码、不依赖能访问 GitHub，同学
`clone` 本仓库后跑 `bootstrap.sh` 即可，无需 clone mavis 仓库。

## 为什么是黑箱 wheel

- mavis 仓库已设为私有，部分同学无法访问；
- 框架有保密需求，源码不应随交付物流出；
- 因此用 [Nuitka](https://nuitka.net/) 把整个 `mavisframework` 包编译成
  原生扩展模块（`.pyd`），与随附的 prompts 模板一起打成**平台特定的 wheel**。

## wheel 里有什么

- `mavisframework.cp313-win_amd64.pyd` —— 整个框架，编译成原生代码，**无明文源码**；
- `mavisframework_prompts/prompts/*.txt` 与 `prompts_zh/*.txt` —— 运行时加载的提示词模板。

mavis 读取模板本来就支持 `MAVIS_PROMPT_DIR` 环境变量覆盖默认路径；`backend/app/mavis_bridge.py`
在导入 mavis 前自动把该变量指到随 wheel 附带的 `mavisframework_prompts` 包，因此学生机
不需要任何额外配置。

## 平台约束（重要）

wheel 文件名里的 `cp313-cp313-win_amd64` 表示它**只能在 Windows + CPython 3.13（AMD64）**
上安装。本项目的运行时正是这个解释器，所以直接可用。其它平台 / Python 版本需要重建
对应 wheel（见下），不能跨平台混用。

## 如何重建 wheel

仓库已附带可复现脚本，**不需要 Visual Studio / Windows SDK / `reg.exe`**——Nuitka 走
**zig 后端**（自带 LLVM 编译器）。首次运行会下载 Nuitka 与 zig 二进制，请保证能联网
（必要时设置 `HTTP_PROXY` / `HTTPS_PROXY`）。

```bash
# MAVIS_SRC 指向你本地能访问的 mavis 源码（含 mavisframework/ 包与 prompts）
MAVIS_SRC=/path/to/mavis bash scripts/build_mavis_wheel.sh
```

产物写入 `vendor/mavisframework-<version>-cp313-cp313-win_amd64.whl`。
换版本时同步改 `MAVIS_VERSION` 与 `scripts/bootstrap.sh` 里的 wheel 路径。

脚本做的事情：隔离构建 venv → `pip install nuitka` →
`python -m nuitka --module --zig --assume-yes-for-downloads --include-package=mavisframework
--include-package-data=mavisframework` → 用 `scripts/build_mavis_wheel.py` 打包。

> 踩坑备忘：本机 `reg.exe` 被安全策略硬性拦截，导致 Nuitka 自带的 MSVC 检测拿不到
> Windows SDK，编译器始终定位失败。zig 后端完全绕开 MSVC/SDK/注册表，是唯一能跑通的路。
> Nuitka 对 Python 3.13 **禁用 `--mingw64`**，所以 gcc 路线也走不通。

## 分发到同学（Gitee）

1. 在 Gitee 新建仓库（建议公开，避开协作人数上限；mavis 源码不在本仓库内，无需担心泄露）；
2. 把本仓库（已含 `vendor/` 下的 wheel）推送 / 镜像到 Gitee；
3. 同学：`git clone <Gitee 地址>` → `bash scripts/bootstrap.sh`。
   bootstrap 会自动从 `vendor/` 安装 mavis wheel，不会再碰 GitHub 或 mavis 私有仓。

## 版本一致性

`backend/spikes/mavis_bounds.py` 探针是按 mavis **内部调用签名**打桩的，版本不能随意跟随
默认分支。wheel 版本钉死在文件名与 `bootstrap.sh` 里；升级 mavis 后必须重建 wheel 并
重跑 `tests/test_mavis_gap_report.py` 确认 12 处缺口结论仍成立。
