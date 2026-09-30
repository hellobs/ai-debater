"""回归测试与评估框架。

入口：
    python -m benchmarks.runner <list|check|eval|compare|run>
    python -m benchmarks <同上>

刻意**不在本文件里 re-export** `runner` 的符号：那会让 `python -m benchmarks.runner`
触发 runpy 的 "found in sys.modules" 警告。
直接 `from benchmarks.runner import evaluate` 即可。
"""
