"""配置读取层：空值与 `.env` 的两条真实踩坑。

这两个 bug 都属于同一类 —— **照文档做，却得到一个指向别处的错误**：

1. `.env.example` 里 `MAVIS_PROMPT_DIR=` 写的是**空值**。`os.environ.get(name, default)`
   只在键**不存在**时才回默认值；键存在但为空会原样返回 `""`，于是
   `Path("")` == `Path(".")`，提示词目录变成当前目录，
   启动自检报「缺 `.packs/general/roles/rebutter.txt`」。
   同类的 `int("")` / `float("")` 更直接：import 期就抛 `ValueError`。
2. 文档教 `cp .env.example .env` 后填写生效，但仓库里**从未加载过 `.env`** ——
   填了等于没填，且不报错。

第 1 条用单元测试守；第 2 条要靠子进程真起一次解释器才能验（`.env` 是 import 期读的）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import config

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


# ---------------------------------------------------------------------------
# _env：空白值一律视为未设置
# ---------------------------------------------------------------------------
def test_env_falls_back_when_unset(monkeypatch):
    monkeypatch.delenv("ZZ_PROBE", raising=False)
    assert config._env("ZZ_PROBE", "dflt") == "dflt"


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n", " \t \n "])
def test_env_treats_blank_as_unset(monkeypatch, blank):
    """这是本文件要守的核心：`KEY=` 不能把默认值顶掉。"""
    monkeypatch.setenv("ZZ_PROBE", blank)
    assert config._env("ZZ_PROBE", "dflt") == "dflt"


def test_env_returns_the_value_when_present(monkeypatch):
    monkeypatch.setenv("ZZ_PROBE", "hello")
    assert config._env("ZZ_PROBE", "dflt") == "hello"


def test_env_keeps_inner_whitespace(monkeypatch):
    """只判"整串是否空白"，不 trim —— 路径里带空格是合法的（本项目路径就带中文与空格）。"""
    monkeypatch.setenv("ZZ_PROBE", " /a b/c ")
    assert config._env("ZZ_PROBE", "dflt") == " /a b/c "


# ---------------------------------------------------------------------------
# _load_dotenv：极简解析，已存在的环境变量优先
# ---------------------------------------------------------------------------
def test_dotenv_parses_basic_pairs(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "# 注释\n"
        "\n"
        "A=1\n"
        "B=hello world\n"
        "export C=3\n"
        "D='quoted'\n"
        'E="dq"\n'
        "F=a=b=c\n",
        encoding="utf-8",
    )
    got = config._load_dotenv(f)
    assert got == {"A": "1", "B": "hello world", "C": "3", "D": "quoted", "E": "dq", "F": "a=b=c"}


def test_dotenv_skips_blank_values(tmp_path):
    """`.env.example` 里 `MAVIS_PROMPT_DIR=` / `ANTHROPIC_BASE_URL=` 都是空值。
    空值必须**不注入**环境，否则会把 config 的默认值顶掉（见本文件开头第 1 条）。"""
    f = tmp_path / ".env"
    f.write_text("KEEP=x\nMAVIS_PROMPT_DIR=\nANTHROPIC_BASE_URL=   \n", encoding="utf-8")
    assert config._load_dotenv(f) == {"KEEP": "x"}


def test_dotenv_missing_file_is_not_an_error(tmp_path):
    assert config._load_dotenv(tmp_path / "nope.env") == {}


def test_dotenv_tolerates_junk_lines(tmp_path):
    f = tmp_path / ".env"
    f.write_text("no_equals_sign\n=novalue\n\n#hash\nOK=1\n", encoding="utf-8")
    assert config._load_dotenv(f) == {"OK": "1"}


def test_dotenv_strips_inline_trailing_comments(tmp_path):
    """行尾 `# 注释` 是标准 dotenv 行为；之前不实现会让
    `ADVISOR_BUDGET_S=30 # 整轮墙钟` 被 float() 当成值崩溃（import 期 ValueError）。"""
    f = tmp_path / ".env"
    f.write_text(
        "NUMBER=30 # this is a comment\n"
        "PLAIN=hello world # also comment\n"
        "QUOTED=\"hello # preserved inside quotes\"\n"
        "URL='https://example.com/a#frag'\n"            # 单引号包裹的 # 保留
        "BARE_HASH=color#red\n",                        # 未引号包裹的 # 视为注释起点（dotenv 标准）
        encoding="utf-8",
    )
    got = config._load_dotenv(f)
    assert got["NUMBER"] == "30"
    assert got["PLAIN"] == "hello world"
    assert got["QUOTED"] == "hello # preserved inside quotes"
    assert got["URL"] == "https://example.com/a#frag"
    assert got["BARE_HASH"] == "color"


def test_dotenv_does_not_override_the_real_environment(tmp_path, monkeypatch):
    """命令行 export 必须能压过 `.env` —— 否则临时换网关/换账户会换不动。"""
    f = tmp_path / ".env"
    f.write_text("ZZ_PROBE=from_file\n", encoding="utf-8")
    monkeypatch.setenv("ZZ_PROBE", "from_shell")
    config._apply_dotenv(f)
    assert os.environ["ZZ_PROBE"] == "from_shell"


def test_dotenv_fills_what_the_environment_lacks(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("ZZ_PROBE=from_file\n", encoding="utf-8")
    monkeypatch.delenv("ZZ_PROBE", raising=False)
    config._apply_dotenv(f)
    assert os.environ["ZZ_PROBE"] == "from_file"


# ---------------------------------------------------------------------------
# 端到端：真的起一次解释器，验证两份文档教的动作不会把服务弄崩
# ---------------------------------------------------------------------------
def _run_py(code: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_extra}
    # 不把测试自己的临时配置带进去，免得干扰
    env.pop("MAVIS_PROMPT_DIR", None)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", env=env,
    )


def test_blank_mavis_prompt_dir_still_resolves_to_the_repo_prompts():
    """`MAVIS_PROMPT_DIR=`（照 `.env.example` 原样）不能把提示词目录变成当前目录。"""
    proc = _run_py(
        "from app import config; print(config.PROMPT_DIR)",
        {"MAVIS_PROMPT_DIR": ""},
    )
    assert proc.returncode == 0, proc.stderr
    resolved = Path(proc.stdout.strip()).resolve()
    assert resolved == (REPO / "prompts").resolve()


def test_blank_mavis_prompt_dir_does_not_break_the_roster_selfcheck():
    """同一条输入下，`load_roster()` 的启动自检不能失败。"""
    proc = _run_py(
        "from app.advisors import load_roster; print(len(load_roster()))",
        {"MAVIS_PROMPT_DIR": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip()) == 5


def test_importing_the_app_package_applies_dotenv():
    """任何 `app.*` 入口被导入时，`.env` 都必须已经应用过。

    断言的是**接线**，不是算法：`import app`（只导入包自身）就会拉进 `app.config`，
    而 config 在 import 期执行 `_apply_dotenv(ENV_FILE)`。
    只测 `_apply_dotenv` 本身不够 —— 少了这行接线，`.env` 会安静地不生效，
    而凭据只被协议桥使用，症状是"上游一片空白 + 静默重试"，极难定位。
    """
    proc = _run_py("import app, sys; print('app.config' in sys.modules)", {})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "True"


def test_dotenv_application_is_recorded_at_import():
    assert isinstance(config.DOTENV_APPLIED, int)


def test_blank_numeric_env_does_not_crash_at_import():
    """`int("")` / `float("")` 会在 import 期直接抛 —— 空值必须走默认。

    期望值**不写死数字**，而是拿本进程的 `config` 作参照：默认值是可调的
    （`ADVISOR_BUDGET_S` 就放宽过一次），写死就成了"改默认值要连带改测试"，
    而这条测试关心的根本不是那个数是多少，是"空值不会让服务起不来"。
    """
    proc = _run_py(
        "from app import config; print(config.LLM_BRIDGE_PORT, config.ADVISOR_BUDGET_S)",
        {"LLM_BRIDGE_PORT": "", "ADVISOR_BUDGET_S": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["8011", repr(config.ADVISOR_BUDGET_S)]
