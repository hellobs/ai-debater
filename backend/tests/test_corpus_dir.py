"""corpus_dir 的 env 读取走 config._env 约定（空白值一律视为未设置）。

与 v1.1.1 的「环境变量读取统一用 config._env」长期约定对齐：
检索层不得再裸用 os.environ.get + `or` 兜底，否则会与 config._env 的防线分裂。
"""
import os
from pathlib import Path

from app.retrieval import DEFAULT_CORPUS_DIR, corpus_dir


def test_corpus_dir_default_when_unset(monkeypatch):
    monkeypatch.delenv("CORPUS_DIR", raising=False)
    assert corpus_dir() == Path(DEFAULT_CORPUS_DIR)


def test_corpus_dir_empty_treated_as_unset(monkeypatch):
    # 行尾留空（如 .env 里 `CORPUS_DIR=` ）必须回退默认，不能解析成当前目录
    monkeypatch.setenv("CORPUS_DIR", "")
    assert corpus_dir() == Path(DEFAULT_CORPUS_DIR)


def test_corpus_dir_override(monkeypatch):
    monkeypatch.setenv("CORPUS_DIR", "/tmp/custom-corpus")
    assert corpus_dir() == Path("/tmp/custom-corpus")
