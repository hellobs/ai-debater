"""守住"我们到底用了 mavis 的哪些面"。

三组断言：

1. **单一接触面** —— `app/` 下只有 `mavis_bridge.py` 允许 import `mavisframework`；
   且它只用公开面（顶层 / `plugin` / `prompt`），不碰 `runtime.llm` 这类内部模块。
2. **模板层是真的** —— 提示词拼装顺序由 `prompts/layout.txt` 决定，改文件就能改
   提示词；领域措辞由 `prompts/packs/<包>/` 提供，改文件就能换领域框架；
   缺模板当场报错，不静默降级。**包是按辩题领域选的，不是按代码里的 if 选的。**
3. **provider 用满了** —— `caller` 逐参谋计数、`failsafe` 哨兵区分"上游挂了"与
   "模型答了空"、`callback` 做结果规整；插件总线的逐插件错误隔离真的生效。
"""
from __future__ import annotations

import ast
import pathlib
import queue
import time

import pytest

from app import config as app_config
from app import mavis_bridge, observers, prompt_packs
from app.advisors import REGISTRY, load_roster
from app.advisors.base import Advisor, DebateContext, PromptTemplateError, preload
from app.mavis_bridge import FAILED, Plugin, PluginManager
from app.orchestrator import run_advisors
from app.schemas import AdvisorResult

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


# ==========================================================================
# 1. 单一接触面
# ==========================================================================
def _mavisframework_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if a.name.split(".")[0] == "mavisframework"]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module.split(".")[0] == "mavisframework":
                hits.append(module)
    return hits


def test_only_the_bridge_imports_mavisframework():
    """`app/` 下只有 mavis_bridge.py 允许 import mavisframework。

    这条线是"要换掉 mavis 只需要改一个文件"这个说法的**唯一**依据。
    没有测试守着的口号会在一周内变成谎话。
    """
    offenders = {
        p.relative_to(APP_DIR).as_posix(): _mavisframework_imports(p)
        for p in sorted(APP_DIR.rglob("*.py"))
        if _mavisframework_imports(p) and p.name != "mavis_bridge.py"
    }
    assert offenders == {}, f"这些文件绕过了 mavis_bridge：{offenders}"


def test_bridge_only_uses_public_surface():
    """桥只用 mavis 的公开面 —— 不碰 `runtime.llm` 这种内部模块。

    历史：本文件改之前是 `from mavisframework.runtime.llm import create_llm_provider`，
    绕过了 mavis 自己在顶层 `__all__` 里声明的推荐入口。
    """
    allowed = {"mavisframework", "mavisframework.plugin", "mavisframework.prompt"}
    used = set(_mavisframework_imports(APP_DIR / "mavis_bridge.py"))
    assert used, "桥居然没有 import mavisframework，测试前提不成立"
    assert used <= allowed, f"用到了非公开面：{sorted(used - allowed)}"
    for module in used:
        assert not any(seg.startswith("_") for seg in module.split("."))


# ==========================================================================
# 2. 模板层
# ==========================================================================
CTX = DebateContext(
    topic="测试辩题",
    our_side="正方",
    opponent_text="对方的发言。",
    our_ledger=["我方第一条主张"],
)

#: CTX 的 domain 是空的 → 落到默认包。测试里要读模板真实内容时用它。
DEFAULT_PACK = prompt_packs.default_pack()


def _mirror_packs(
    root: pathlib.Path,
    *,
    packs: tuple[str, ...] | None = None,
    skip: tuple[str, ...] = (),
    role_body: str | None = None,
    task_body: str | None = None,
) -> None:
    """把提示词目录的骨架铺到 `root` 下：每个包一份 roles/ + tasks/。

    为什么要铺**所有**配置里的包（而不是只有默认包）：`preload()` 会遍历全部包做自检，
    `prompt_packs.all_packs()` 又是配置驱动的 —— 测试跟着配置走，配置加一个包时
    这里不用改。`skip` 用来故意漏掉某一路，验证"缺模板必须炸"。
    """
    names = tuple(packs if packs is not None else prompt_packs.all_packs())
    for pack in names:
        for layer in ("roles", "tasks"):
            (root / "packs" / pack / layer).mkdir(parents=True, exist_ok=True)
        for name in REGISTRY:
            if name in skip:
                continue
            body_role = role_body
            body_task = task_body
            if body_role is None or body_task is None:
                src_dir = pathlib.Path(app_config.PROMPT_DIR) / "packs" / names[0]
                body_role = body_role if body_role is not None else (
                    src_dir / "roles" / f"{name}.txt"
                ).read_text(encoding="utf-8")
                body_task = body_task if body_task is not None else (
                    src_dir / "tasks" / f"{name}.txt"
                ).read_text(encoding="utf-8")
            (root / "packs" / pack / "roles" / f"{name}.txt").write_text(
                body_role, encoding="utf-8"
            )
            (root / "packs" / pack / "tasks" / f"{name}.txt").write_text(
                body_task, encoding="utf-8"
            )
    (root / "layout.txt").write_text("$directive\n\n$context\n\n$task", encoding="utf-8")


def test_every_registry_advisor_has_both_templates_in_every_pack():
    """五路 × 每个包 × 两层，一个都不能少。

    这条是 preload 的静态版：缺一块的表现是提示词里少了一整段角色指令，
    模型照样会返回一段看起来正常的话 —— 那种降级不报错，只是质量悄悄变差。
    """
    for pack in prompt_packs.all_packs():
        for name in REGISTRY:
            assert mavis_bridge.has_template(f"roles/{name}", pack=pack), (
                f"缺 prompts/packs/{pack}/roles/{name}.txt"
            )
            assert mavis_bridge.has_template(f"tasks/{name}", pack=pack), (
                f"缺 prompts/packs/{pack}/tasks/{name}.txt"
            )
    # layout 是全领域共享的顶层模板，不在任何包里
    assert mavis_bridge.has_template("layout")


def test_built_prompt_follows_the_layout_contract():
    """总装结果 == 角色 + 空行 + 上下文 + 空行 + 任务。

    这条锁住的是"从 Python 字符串常量搬到 .txt 是逐字节等价的"。
    尾换行被 `render()` 剥掉，所以这里用 `rstrip` 对齐。
    """
    root = pathlib.Path(app_config.PROMPT_DIR) / "packs" / CTX.pack
    for advisor in load_roster():
        role = root / "roles" / f"{advisor.name}.txt"
        task = root / "tasks" / f"{advisor.name}.txt"
        expected = (
            f"{role.read_text(encoding='utf-8').rstrip(chr(10))}\n\n"
            f"{advisor.context_block(CTX)}\n\n"
            f"{task.read_text(encoding='utf-8').rstrip(chr(10))}"
        )
        assert advisor.build_prompt(CTX) == expected


def test_domain_selects_the_prompt_pack_not_the_layout():
    """换一个领域，只换 roles / tasks，`layout` 还是那一份。

    这是"解耦"的定义：领域差异被关在包里，总装骨架不动。
    """
    legal = DebateContext(topic="AI 生成内容是否应享有著作权", our_side="控方",
                          opponent_text="对方说 AI 不是人。", domain="AI + 法学")
    general = DebateContext(topic="大学应当把人工智能设为必修课", our_side="正方",
                            opponent_text="对方说有道理。", domain="通用")
    assert legal.pack == "legal" and general.pack == "general"

    adv = REGISTRY["strategist"]()
    assert "法律解释方法" in adv.role_directive(legal.pack)
    assert "法律解释方法" not in adv.role_directive(general.pack)
    # 两个包的提示词都不是空的，且都真的走了各自的模板
    assert adv.build_prompt(legal) != adv.build_prompt(general)
    assert legal.pack in mavis_bridge.template_file("roles/strategist", legal.pack)


def test_unclaimed_and_empty_domains_fall_back_to_the_default_pack():
    """没认领的领域不猜，一律落到默认包 —— 猜错是无声的。"""
    default = prompt_packs.default_pack()
    for domain in ("", "   ", "量子力学", "法学史"):
        assert prompt_packs.pack_for_domain(domain) == default
    # 认领过的领域精确命中
    assert prompt_packs.pack_for_domain("AI + 法学") == "legal"


def test_general_pack_carries_no_legal_framing():
    """通用包的措辞里不该再出现法律框架 —— 否则"通用"只是标签。

    只查会决定模型视角的词：法律涵摄 / 法条 / 法源 / 法律效果 / 解释方法。
    「大前提」「小前提」「结论」不算（它们是三段论词，任何领域都成立）。
    """
    banned = ("法律涵摄", "法条", "法源", "法律效果", "法律解释", "法理")
    root = pathlib.Path(app_config.PROMPT_DIR) / "packs" / "general"
    for path in sorted(root.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        hit = [w for w in banned if w in text]
        assert not hit, f"{path.name} 里还有法学措辞：{hit}"


def test_context_block_reports_ledger_only_when_present():
    assert "【我方已经主张过】" not in Advisor().context_block(
        DebateContext(topic="t", our_side="a", opponent_text="b")
    )
    assert "我方第一条主张" in Advisor().context_block(CTX)


def test_layout_order_is_data_not_code(tmp_path, monkeypatch):
    """把 layout.txt 换个顺序，提示词顺序就跟着换 —— 证明这层不是装饰。

    同时验证 `prompt_renderer()` 会跟着 `PROMPT_DIR` 重建（否则会读上一个目录）。
    """
    _mirror_packs(tmp_path)
    (tmp_path / "layout.txt").write_text("$task\n\n$context\n\n$directive", encoding="utf-8")

    monkeypatch.setattr(app_config, "PROMPT_DIR", tmp_path)
    prompt = REGISTRY["questioner"]().build_prompt(CTX)

    assert prompt.startswith(REGISTRY["questioner"]().task_block(DEFAULT_PACK))
    assert prompt.endswith(REGISTRY["questioner"]().role_directive(DEFAULT_PACK))


def test_render_normalizes_crlf_and_trailing_newline(tmp_path, monkeypatch):
    """模板存成 CRLF 或带尾换行，渲染结果不受影响。"""
    _mirror_packs(tmp_path, role_body="占位\n", task_body="t")
    (tmp_path / "packs" / DEFAULT_PACK / "roles" / "questioner.txt").write_bytes(
        "第一行\r\n第二行\r\n".encode("utf-8")
    )
    (tmp_path / "layout.txt").write_bytes(b"$directive|$context|$task\r\n")

    monkeypatch.setattr(app_config, "PROMPT_DIR", tmp_path)
    out = REGISTRY["questioner"]().role_directive()
    assert out == "第一行\n第二行"
    assert REGISTRY["questioner"]().build_prompt(CTX).endswith("|t")


def test_missing_template_raises_instead_of_degrading(tmp_path, monkeypatch):
    """缺模板必须炸，不能悄悄发一条没有角色指令的提示词。

    降级的表现是"模型照样返回一段看起来正常的话"，这类 bug 最难发现。
    """
    _mirror_packs(tmp_path, skip=("auditor",))  # 故意每个包都漏掉一路

    monkeypatch.setattr(app_config, "PROMPT_DIR", tmp_path)
    with pytest.raises(PromptTemplateError) as exc:
        preload([REGISTRY["auditor"]()])
    assert "auditor" in str(exc.value)


def test_missing_pack_raises_even_when_the_default_pack_is_fine(tmp_path, monkeypatch):
    """非默认包缺一个文件，也必须炸 —— 否则要等第一个法学辩题进来才发现。

    这正是"遍历所有包做自检"的理由：选包发生在请求里，那时才发现就只能 500。
    """
    _mirror_packs(tmp_path, packs=("general", "legal"), skip=("risk",))
    # 只把 legal 包的 risk 补回来，general 包继续缺
    for layer in ("roles", "tasks"):
        src = pathlib.Path(app_config.PROMPT_DIR) / "packs" / "legal" / layer / "risk.txt"
        (tmp_path / "packs" / "legal" / layer / "risk.txt").write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8"
        )

    monkeypatch.setattr(app_config, "PROMPT_DIR", tmp_path)
    with pytest.raises(PromptTemplateError) as exc:
        preload([REGISTRY["risk"]()])
    assert "general" in str(exc.value) and "risk" in str(exc.value)


def test_preload_is_idempotent_and_cached_across_same_dir():
    roster = load_roster()
    assert preload(roster) == len(roster)
    assert preload(roster) == len(roster)  # 第二次走缓存，不重复渲染


def test_load_roster_runs_the_prompt_selfcheck(tmp_path, monkeypatch):
    """`load_roster()` 必须带上自检 —— 否则缺模板时会以空名册悄悄上线。"""
    monkeypatch.setattr(app_config, "PROMPT_DIR", tmp_path)
    (tmp_path / "layout.txt").write_text("$directive", encoding="utf-8")
    with pytest.raises(PromptTemplateError):
        load_roster()


# ==========================================================================
# 3. provider 采用率
# ==========================================================================
class FakeProvider:
    """记录每次调用参数、并按脚本返回结果的假 provider。"""

    def __init__(self, result=None):
        self._result = result
        self.calls: list[dict] = []

    def completion(self, prompt, retry=10, callback=None, failsafe=None,
                   return_type=None, caller="llm_normal", **kwargs):
        self.calls.append({
            "prompt": prompt, "retry": retry, "caller": caller,
            "failsafe": failsafe, "return_type": return_type,
            "timeout": kwargs.get("timeout"),
        })
        out = self._result(prompt) if callable(self._result) else self._result
        if out is None:
            return failsafe          # 复刻 mavis 的失败语义
        return callback(out) if callback else out

    def is_available(self):
        return True

    def get_summary(self):
        return {"model": "fake", "summary": {c["caller"]: "S:1,F:0/R:0" for c in self.calls}}


@pytest.fixture
def fake_provider(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(mavis_bridge, "_provider", provider)
    return provider


def test_completion_passes_caller_and_failsafe(fake_provider):
    """caller 是逐参谋的，failsafe 是我们的哨兵 —— 两个都不能丢。"""
    mavis_bridge.complete("hi", caller="rebutter", retry=3)
    call = fake_provider.calls[-1]
    assert call["caller"] == "rebutter"
    assert call["failsafe"] is FAILED
    assert call["retry"] == 3
    # 不传 timeout 时用 config.LLM_TIMEOUT_S —— mavis 那层硬编码的 90s 由此可配
    assert call["timeout"] == app_config.LLM_TIMEOUT_S


def test_completion_timeout_is_overridable_per_call(fake_provider):
    """预算比内层默认还宽时，内层要跟着放宽，否则 mavis 会先超时并重试（重试要钱）。"""
    mavis_bridge.complete("hi", caller="rebutter", timeout=200)
    assert fake_provider.calls[-1]["timeout"] == 200


def test_advisor_run_uses_its_own_name_as_caller(fake_provider):
    fake_provider._result = [{"claim": "x"}]
    REGISTRY["strategist"]().run(CTX)
    assert fake_provider.calls[-1]["caller"] == "strategist"


def test_retries_exhausted_becomes_error_not_empty(fake_provider):
    """这是 `failsafe` 哨兵存在的全部理由。

    没有哨兵时，两类失败在调用方看来无从区分（`None` / `''` 只是实现副产品），
    都会被记成 `empty` —— 现场会误判成"模型不太会说话"。
    """
    fake_provider._result = None      # 假 provider 会返回 failsafe
    result = REGISTRY["questioner"]().run(CTX)
    assert result.status == "error"
    assert "重试耗尽" in (result.error or "")


def test_blank_but_valid_output_is_empty_not_error(fake_provider):
    fake_provider._result = []        # 有应答，只是内容为空
    result = REGISTRY["questioner"]().run(CTX)
    assert result.status == "empty"
    assert result.error is None


def test_adapt_trims_and_drops_blank_entries():
    adapt = Advisor.adapt
    assert adapt("  x  ") == "x"
    assert adapt(["  a ", "", "   ", "b"]) == ["a", "b"]
    assert adapt([{"claim": "  c  ", "note": ""}]) == [{"claim": "c", "note": ""}]
    assert adapt([]) == []
    assert adapt(None) is None
    # 整条全空的条目要丢掉，否则前端会渲染一张空卡片
    assert adapt([{"claim": "", "note": "  "}]) == []


def test_health_reports_provider_snapshot(client):
    """health 只是读计数器，不该产生上游调用。"""
    data = client.get("/api/health").json()
    provider = data["provider"]
    assert provider["ready"] is True
    assert provider["is_available"] is True
    assert "summary" in provider
    assert "model" in provider["summary"]
    assert data["observers"]["runs"] >= 0


def test_provider_info_tolerates_a_minimal_provider(monkeypatch):
    """只满足 `LLMProvider` 基类契约的 provider（没有 cache_stats）不能让 health 崩。

    `cache_stats` / `disable` 不在抽象基类里（缺口 N2），所以只能当可选能力取。
    """
    class Minimal:
        def completion(self, *a, **kw):
            return ""

        def is_available(self):
            return False

        def get_summary(self):
            return {"model": "minimal", "summary": {}}

    monkeypatch.setattr(mavis_bridge, "_provider", Minimal())
    info = mavis_bridge.provider_info()
    assert info["ready"] is True
    assert info["is_available"] is False
    assert info["cache"] is None      # 没有就当没有，不编造


def test_provider_info_survives_a_broken_provider(monkeypatch):
    class Broken:
        def is_available(self):
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(mavis_bridge, "_provider", Broken())
    info = mavis_bridge.provider_info()
    assert info["ready"] is True      # 实例建出来了
    assert "error" in info            # 但读状态失败，如实报


# ==========================================================================
# 3b. 插件总线（mavis PluginManager）
# ==========================================================================
def test_plugin_manager_isolates_a_failing_plugin():
    """一个插件抛错不影响其它插件 —— 这是改用总线最直接的理由。"""
    seen: list[str] = []

    class Exploding(Plugin):
        name = "exploding"

        def on_event(self, evt):
            seen.append("exploding")
            raise RuntimeError("boom")

    class Recorder(Plugin):
        name = "recorder"

        def on_event(self, evt):
            seen.append("recorder")

    manager = PluginManager([Exploding(), Recorder()])
    manager.emit({"type": "anything"})   # 不该抛
    assert seen == ["exploding", "recorder"]


class _FakeAdvisor:
    """只满足 `run_advisors` 用到的接口，不碰模型。"""

    def __init__(self, name, status="ok"):
        self.name = name
        self.label = name.upper()
        self.kind = "text"
        self._status = status

    def run(self, ctx, retry=2, timeout=None):
        return AdvisorResult(
            advisor=self.name, label=self.label, status=self._status,
            latency_s=0.0, kind=self.kind,
        )


def test_orchestrator_broadcasts_lifecycle_events():
    events: list[str] = []

    class Spy(Plugin):
        name = "spy"

        def on_event(self, evt):
            events.append(evt["type"])

    run_advisors(
        CTX, [_FakeAdvisor("a"), _FakeAdvisor("b")],
        budget_s=5, plugins=PluginManager([Spy()]),
    )
    assert events[0] == observers.EVENT_RUN_START
    assert events[-1] == observers.EVENT_RUN_END
    assert events.count(observers.EVENT_RESULT) == 2


def test_legacy_on_result_still_works():
    """老的 `on_result` 参数没有被砍掉，只是改从总线上走。"""
    got: list[str] = []
    run_advisors(CTX, [_FakeAdvisor("a")], on_result=lambda r: got.append(r.advisor))
    assert got == ["a"]


def test_single_plugin_failure_does_not_lose_other_results(tmp_path, monkeypatch):
    """指标插件炸了，落库和推流照样得完成 —— 这就是错误隔离的实际价值。"""
    monkeypatch.setattr(app_config, "LEDGER_DB", str(tmp_path / "t.db"))

    class Exploding(Plugin):
        name = "exploding"

        def on_event(self, evt):
            raise RuntimeError("metrics is broken")

    out: queue.Queue = queue.Queue()
    manager = observers.build_manager(
        session_id="s1", out_queue=out, done_payload={"session_id": "s1", "latency_s": 0.0},
    )
    manager.mount(Exploding())

    results, total = run_advisors(
        CTX, [_FakeAdvisor("a"), _FakeAdvisor("b")], budget_s=5, plugins=manager,
    )
    assert {r.advisor for r in results} == {"a", "b"}
    assert total >= 0

    pushed = []
    while not out.empty():
        pushed.append(out.get())
    # 结果以 AdvisorResult 本体过队列，收尾哨兵是 dict —— SSE 消费端据此分流
    names = [p["advisor"] if isinstance(p, dict) else p.advisor for p in pushed]
    assert names == ["a", "b", "_done"]


def test_ledger_plugin_writes_one_row_per_result(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "LEDGER_DB", str(tmp_path / "t.db"))
    from app.ledger import store

    store.create_session("t", "s")
    plugin = observers.LedgerPlugin("s1")
    plugin.on_event({"type": observers.EVENT_RESULT,
                     "result": _FakeAdvisor("a").run(CTX)})
    plugin.on_event({"type": observers.EVENT_RUN_START})     # 非结果事件要忽略
    assert plugin.saved == 1


def test_metrics_plugin_counts_per_advisor():
    plugin = observers.MetricsPlugin()
    plugin.on_event({"type": observers.EVENT_RUN_START, "advisors": ["a", "b"], "budget_s": 5})
    plugin.on_event({"type": observers.EVENT_RESULT,
                     "result": _FakeAdvisor("a").run(CTX)})
    plugin.on_event({"type": observers.EVENT_RESULT,
                     "result": _FakeAdvisor("b", status="error").run(CTX)})
    plugin.on_event({"type": observers.EVENT_RUN_END, "total_latency_s": 1.5})

    report = plugin.report()
    assert report["runs"] == 1
    assert report["by_advisor"]["a"]["ok"] == 1
    assert report["by_advisor"]["b"]["error"] == 1
    assert report["last_run"]["counts"] == {"ok": 1, "error": 1}
    assert report["last_run"]["total_latency_s"] == 1.5


def test_process_metrics_is_shared_across_runs():
    """进程级指标观察者必须是同一个实例，否则 /api/health 只能看到最近一次。"""
    a = observers.build_manager(session_id="x")
    b = observers.build_manager()
    assert any(p is observers.PROCESS_METRICS for p in a.plugins)
    assert any(p is observers.PROCESS_METRICS for p in b.plugins)


def test_call_timeout_is_never_tighter_than_the_budget():
    """两把刀的对齐：内层（单次调用）必须不比外层（预算）更早落下。

    内层先落 → mavis 重试 → 多花一次上游调用的钱，产出却已被外层判死。
    """
    from app.orchestrator import call_timeout

    # 预算比默认内层窄：保持默认（外层那把刀切割，内层不该动）
    assert call_timeout(12) == app_config.LLM_TIMEOUT_S
    # 预算比默认内层宽：内层跟着放宽，否则"放宽预算"根本不生效
    assert call_timeout(app_config.LLM_TIMEOUT_S + 60) == app_config.LLM_TIMEOUT_S + 60
    # 不限预算不是真的无限：仍由内层保险丝封顶
    assert call_timeout(0) == app_config.LLM_TIMEOUT_S


def test_orchestrator_passes_call_timeout_down():
    seen: list[float | None] = []

    class Recorder(_FakeAdvisor):
        def run(self, ctx, retry=2, timeout=None):
            seen.append(timeout)
            return super().run(ctx, retry, timeout)

    run_advisors(CTX, [Recorder("a")], budget_s=app_config.LLM_TIMEOUT_S + 60)
    assert seen == [app_config.LLM_TIMEOUT_S + 60]


def test_budget_timeout_still_marks_pending_advisors():
    class Slow(_FakeAdvisor):
        def run(self, ctx, retry=2, timeout=None):
            time.sleep(0.3)
            return super().run(ctx, retry, timeout)

    results, _ = run_advisors(CTX, [Slow("slow"), _FakeAdvisor("fast")], budget_s=0.05)
    by_name = {r.advisor: r for r in results}
    assert by_name["slow"].status == "timeout"


# ==========================================================================
# 4. 对外自述：/api/health、导出报告、README 讲的是同一个事实
#
# 这一组守住的是"别只把 mavis 写进 README"。自述写在代码里，读的是真实状态：
# 版本来自包本身，模板清单来自真实目录，三面清单来自真实用到的入口。
# ==========================================================================
def test_runtime_info_reports_version_and_three_surfaces():
    info = mavis_bridge.runtime_info()
    assert info["framework"] == "mavis"
    assert info["version"] and info["version"] != "unknown"
    # 只读依赖不是修辞，是"结论对框架本身成立"的前提
    assert info["readonly"] is True
    assert info["contact"] == "backend/app/mavis_bridge.py"
    assert [s["key"] for s in info["surfaces"]] == ["provider", "prompt", "plugin"]
    # 每一面都要说得出"mavis 的入口"和"我们的落点"，否则只是一句空话
    for s in info["surfaces"]:
        assert s["entry"] and s["used_in"] and s["detail"]
    assert "Simulator" in info["unused"]


def test_runtime_info_lists_the_prompt_packs():
    """提示词这一面的自述里要答得出"有哪些领域包、哪个兜底"。"""
    packs = mavis_bridge.runtime_info()["packs"]
    assert packs["default"] == prompt_packs.default_pack()
    assert packs["count"] == len(packs["packs"]) == len(prompt_packs.all_packs())
    names = [p["name"] for p in packs["packs"]]
    assert prompt_packs.default_pack() in names
    for p in packs["packs"]:
        assert p["label"]
        assert isinstance(p["domains"], list)


def test_surfaces_are_the_real_contact_points():
    """自述里写的落点必须真的存在 —— 否则就只是文档里的装饰。

    这是"把自述放进代码"的全部意义：每一面都指得出一个真函数。
    """
    for s in mavis_bridge.SURFACES:
        module, _, func = s["used_in"].partition(".")
        path = APP_DIR / f"{module}.py"
        assert path.is_file(), f"落点模块不存在：{module}"
        assert f"def {func.rstrip('()')}(" in path.read_text(encoding="utf-8"), (
            f"落点函数不存在：{s['used_in']}"
        )


def test_prompt_inventory_matches_the_real_directory():
    inv = mavis_bridge.prompt_inventory()
    assert inv["templates"] == len(inv["names"]) > 0
    assert "layout" in inv["names"]
    for pack in prompt_packs.all_packs():
        for name in REGISTRY:
            assert f"packs/{pack}/roles/{name}" in inv["names"]
            assert f"packs/{pack}/tasks/{name}" in inv["names"]


def test_missing_version_degrades_instead_of_breaking_health(monkeypatch):
    """展示字段不该有失败模式：版本号取不到就报 unknown，不打崩健康检查。"""
    monkeypatch.delattr(mavis_bridge.mavisframework, "__version__", raising=False)
    assert mavis_bridge.version() == "unknown"
    assert mavis_bridge.runtime_info()["version"] == "unknown"


def test_dependency_note_pins_the_readonly_fact():
    note = mavis_bridge.dependency_note()
    assert "只读依赖" in note and "一行未改" in note


def test_observer_names_are_actually_mounted_classes():
    """health 里列的观察者名字，必须是真挂得上的 `Plugin` 子类。"""
    for name in observers.OBSERVER_NAMES:
        cls = getattr(observers, {"ledger": "LedgerPlugin", "stream": "StreamPlugin",
                                  "metrics": "MetricsPlugin"}[name])
        assert issubclass(cls, Plugin)
        assert cls.name == name


def test_declaration_states_the_project_is_built_on_the_framework():
    """「基于 X 开发」比「用到 X」是更强的断言，句式只允许有一份。

    判据同 §3.8：同一事实在仓库出现两次以上就是 bug 温床。
    README / 导出报告 / 界面脚注都从这里取，避免出现"文档说基于框架开发、
    交付物说只调用过一次"这种分裂。
    """
    assert mavis_bridge.BASED_ON == "mavisframework"
    assert mavis_bridge.runtime_info()["based_on"] == mavis_bridge.BASED_ON

    text = mavis_bridge.declaration()
    assert "本项目基于" in text and mavis_bridge.BASED_ON in text
    assert "开发" in text and "只读依赖" in text and "一行未改" in text
    # 版本号来自包本身，不是写死的字符串
    assert f"v{mavis_bridge.version()}" in text


def test_declaration_only_lets_the_call_site_restyle_the_name():
    """调用方只换呈现形式（Markdown 链接 / 粗体 / 纯文本），换不掉句式。"""
    md = mavis_bridge.declaration("**[mavis](https://github.com/hellobs/mavis)**")
    assert md.startswith("本项目基于 **[mavis]")
    assert md.endswith("开发（只读依赖，一行未改）")
