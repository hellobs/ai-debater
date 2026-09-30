<div align="center">

# ai-debater

### A General Debater's Console · Landing on AI + Law

**They finish speaking. Five AI advisors weigh in — in parallel. You decide what to use.**

[![License](https://img.shields.io/badge/license-Apache--2.0-3b82f6?style=flat-square&labelColor=1f2328)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-131%20passing-2ea043?style=flat-square&labelColor=1f2328)](backend/tests)
[![mavis](https://img.shields.io/badge/mavis-1.3.3%20%C2%B7%20field%20test-7c3aed?style=flat-square&labelColor=1f2328)](docs/mavis-gap-report.md)
[![Python](https://img.shields.io/badge/python-%E2%89%A5%203.12-3776ab?style=flat-square&labelColor=1f2328)](backend/requirements.txt)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688?style=flat-square&labelColor=1f2328)](backend/app)
[![Frontend](https://img.shields.io/badge/frontend-React%2018%20%2B%20Vite-61dafb?style=flat-square&labelColor=1f2328)](frontend/src)
[![Model](https://img.shields.io/badge/model-deepseek--chat%20%7C%20local%20LLM-8b5cf6?style=flat-square&labelColor=1f2328)](#zero-cost-mode-local-models)

[简体中文](README.md) ｜ [**English**](README.en.md)

</div>

---

> ### What it is
>
> You are on stage in a debate. The moment your opponent finishes a point, the system runs
> **five AI advisors in parallel**, each contributing on its own axis:
> **rebuttal points · cross-examination questions · logical fallacies · methods-of-interpretation
> conflict · risk warnings**. Every agent is on *your* side. Whether to use any of it is your call.
>
> *Chinese is the primary documentation language; [`README.md`](README.md) is the canonical version.*
>
> ### It is also a field test
>
> It doubles as a **field test of [`mavis`](https://github.com/hellobs/mavis)**
> (a generative-agent simulation framework, v1.3.3) inside a real product: which parts carry weight,
> which do not, and what is still missing. The test is **zero-modification** — mavis is consumed as a
> read-only dependency, not a line changed — so the conclusions hold for the framework itself.
> → [mavis field test](#mavis-field-test) ｜ [report](docs/mavis-gap-report.md)

<table>
<tr><th align="left" width="50%">This is</th><th align="left" width="50%">This is not</th></tr>
<tr>
<td valign="top">

- A parallel **advisory panel** of multiple agents
- **Live** in-round assistance (target: deliver in < 2s)
- Deliver-on-deadline — an over-budget advisor is marked `timeout` and pushed immediately, without blocking the rest
- AI only **advises**; the human decides

</td>
<td valign="top">

- AI vs. AI autonomous sparring
- Judging, scoring, or Elo ratings
- Competition state machines or turn-taking
- Speaking or drafting on your behalf

</td>
</tr>
</table>

**Taking over development? Read [`HANDOVER.md`](HANDOVER.md) first** — background, decisions,
architecture, known traps, cost guardrails, and outstanding work, all in one document (Chinese).

---

## Contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [**mavis field test**](#mavis-field-test)
- [Quick start](#quick-start)
- [Zero-cost mode: local models](#zero-cost-mode-local-models)
- [Topics and sides: configured up front](#topics-and-sides-configured-up-front)
- [The five advisors](#the-five-advisors)
- [Two guardrails](#two-guardrails)
- [Tests and benchmarks](#tests-and-benchmarks)
- [Project layout](#project-layout)
- [Documentation index](#documentation-index)
- [Security guardrails](#security-guardrails)
- [Known limitations](#known-limitations)
- [License](#license)

---

## Highlights

| | |
|---|---|
| **mavis field test** | This project doubles as a **field test of mavis v1.3.3**: the simulation half is architecturally unusable here (with evidence), while the infrastructure half is used to the full. Zero modifications, yielding a [7-gap report](docs/mavis-gap-report.md) — see [mavis field test](#mavis-field-test). |
| **Genuinely parallel** | All five advisors are dispatched at once; total wall-clock equals the slowest one. Measured **1.34s** for three advisors — **63%** saved versus serial. |
| **Deliver on deadline** | The goal is not "wait for everything", but **deliver what is ready on time**. An over-budget advisor is marked `timeout` and pushed instantly, without blocking the others. |
| **Foundation untouched** | The mavis framework is consumed as a **read-only dependency**, not a single line modified. Inside `backend/app/`, only one file may import it — enforced by an AST test. |
| **Hallucination control** | Citations are verified **programmatically against a corpus**, in three states — never trusting a model's self-reported "I'll flag unverified claims". |
| **Free iteration** | One command wires in a local model; the whole pipeline runs at zero cost, so prompt/schema changes are cheap to test. |
| **Evidence-backed** | Every architectural decision is backed by a measurement report (the Stage 0 report documents mavis failing round after round). |

---

## Architecture

```mermaid
flowchart TB
    FE["Frontend · React + Vite · desktop browser<br/>settings / N advisor columns / ledger / metrics / citations / export"]

    subgraph BE["Backend · FastAPI :8010"]
        OR["Orchestrator<br/>parallel dispatch + time budget"]
        ADV["Advisor panel × 5<br/>prompts from prompts/*.txt"]
        OBS["Observers<br/>ledger / stream / metrics"]
        AUX["Ledger · consistency · citation check · export"]
    end

    MB["mavis_bridge<br/>the only boundary to mavis<br/>provider · template layer · plugin bus"]
    BR["Protocol bridge llm_bridge.py :8011<br/>OpenAI ⇄ Anthropic · JSON shape repair"]
    GW["Model gateway<br/>deepseek-chat"]
    OL["Ollama :11434<br/>local model · zero cost"]

    FE -- "POST /api/analyze" --> OR
    OR -. "SSE stream" .-> FE
    OR --> ADV
    OR -- "broadcast per result" --> OBS
    ADV --> MB
    MB --> BR
    BR --> GW
    MB -. "local mode, bridge bypassed" .-> OL
    OR --> AUX
```

**Data flow**: opponent's statement (text) → backend creates/reuses a session and injects the ledger →
five advisors analyze **in parallel** → each result is broadcast over mavis's plugin bus to three
observers (ledger / stream / metrics) as soon as it lands → frontend renders one column per advisor →
consistency check and citation verification run as separate endpoints, off the hot path.

**Two load-bearing conclusions** (full evidence in [`docs/spike-0-report.md`](docs/spike-0-report.md)
and [`docs/mavis-gap-report.md`](docs/mavis-gap-report.md)):

- mavis serves here as an **infrastructure layer only**, never as an agent runtime. Its `Agent.think()` is a
  life-simulation pipeline (schedule → perceive → act → move → plan → reflect) that emits action plans,
  not advice; and it only recognizes the framework's hard-coded `prompt_*` set — there is no
  "give the debater advice" category.
- Its **infrastructure half, however, is used to the full**: model access (retry / timeout / concurrency
  gate / per-caller counters / failure sentinel via `LLMProvider`), prompt templates (three `.txt` layers
  via `Scratch`), and the plugin bus (`PluginManager`'s per-plugin error isolation). Inside
  `backend/app/`, **only `mavis_bridge.py`** may import `mavisframework`, and a test enforces that with AST.
- The available gateway speaks **Anthropic protocol** (`POST /v1/messages` + `x-api-key`), while mavis's
  LLM layer speaks **OpenAI protocol** — so a protocol bridge is **mandatory**. What the bridge must do
  beyond translating is below.

<details>
<summary><b>Why a protocol bridge is unavoidable (expand)</b></summary>

The bridge only translates protocols; **mavis itself is not modified**. It also handles two things
mavis does not, and skipping either causes real trouble:

1. **Always return a valid OpenAI response body** — mavis **never checks HTTP status codes**; it only
   reads `choices[0].message.content`. If the bridge returns non-JSON on failure, mavis silently retries
   10 times × `sleep(5)` = **a 50-second silent stall** (we measured one at 64.9s / 12 calls).
2. **Structured-output backstop** — mavis relies on `response_format` (json_schema), a field the
   Anthropic protocol lacks. The bridge writes the schema into the system prompt **and repairs the JSON
   shape on the way back** (mavis's pydantic models are all shaped `{"res": ...}`, and models frequently
   drop the outer wrapper). This alone cut one `think` step from **64.93s / 12 calls** to
   **5.6s / 3 calls**.

</details>

---

## mavis field test

[`mavis`](https://github.com/hellobs/mavis) is a **generative-agent simulation framework** (v1.3.3).
This project uses it as infrastructure — and consequently doubles as a **field test inside a real product**:

- A framework that runs its own examples is **not** automatically able to carry a production pipeline with
  concurrency, a time budget, and failure semantics;
- The test is **zero-modification** — mavis is consumed as a read-only dependency (editable install),
  **not a line changed**. Every conclusion below therefore holds for mavis itself, not for "our fork";
- Conclusions, evidence, and repro commands all live in the repo:
  **[`docs/mavis-gap-report.md`](docs/mavis-gap-report.md)** (Chinese).

### The three surfaces used to the full

| Surface | mavis interface | Where | What we use |
|---|---|---|---|
| **Model access** | `create_llm_provider()` → `LLMProvider` | `backend/app/mavis_bridge.py` | All of `completion()`'s `caller` / `failsafe` / `callback`, plus `is_available()` / `get_summary()` / `cache_stats()` wired into `/api/health`; its built-in 90s timeout and process-level concurrency gate |
| **Prompt templates** | `prompt.Scratch.build_prompt()` | `prompts/*.txt` + `advisors/base.py` | Three template layers (`layout` / `roles/*` / `tasks/*`), turning prompts from long Python strings into **diffable, versionable, per-advisor-overridable** data; validated at startup via `preload()` |
| **Plugin bus** | `plugin.PluginManager` | `backend/app/observers.py` | Three observers `LedgerPlugin` / `StreamPlugin` / `MetricsPlugin`, gaining **per-plugin error isolation** and the `setup / emit / teardown` lifecycle |

Two details that genuinely earned their keep:

- **The `failsafe` sentinel**: mavis's `completion()` swallows every exception (see G3), so with the default
  `failsafe=None` "the upstream is down" and "the model answered nothing" are **indistinguishable**.
  Passing a private sentinel `FAILED` is what lets us split the two into `error` / `empty`.
- **`callback` normalizes, it does not judge**: mavis treats a `None` return from the callback as
  "this one does not count, retry once", so vetoing content inside the callback multiplies a "mediocre
  answer" into `retry` extra upstream calls. `Advisor.adapt()` therefore only trims whitespace and drops
  fully blank entries.

### The half that does not apply: simulation

mavis's core is `Agent` / `Game` / `Simulator` / memory / schedule / spatial — a **life-simulation pipeline**.
Here that half is **architecturally misaligned**, not merely misconfigured:

- `Simulator` means "every tick, walk every agent through life simulation", a different semantics from
  "run five advisors in parallel";
- `Agent.think()` only recognizes the framework's hard-coded `prompt_*` set and emits action plans rather
  than advice — there is **no "give the debater advice" category**.

Round-by-round measurements are in [`docs/spike-0-report.md`](docs/spike-0-report.md) (Chinese).

### What is missing: 7 gaps (G1–G7)

All reproduced with `backend/spikes/mavis_bounds.py`; **reported, never patched into mavis**.
Each proposed fix follows mavis's own extension conventions (purely additive / off by default /
semantically neutral / unit-tested).

| # | Gap | Nature |
|---|---|---|
| **G1** | The result-cache caller whitelist is hard-coded (`_CACHEABLE_CALLERS`); integrators cannot register their own deterministic calls | Affects this project |
| **G2** | The global concurrency gate is a class attribute rebuilt whenever `size` changes, so two providers with different `concurrency` knock out each other's gate | Latent correctness |
| **G3** | `completion()` swallows every exception and hard-codes a `sleep(5)` backoff — up to a 50s stall before giving up | Affects the time budget |
| **G4** | `Scratch` / `Plugin` / `PluginManager` are absent from the top-level `__all__` — the "recommended usage" hides the extension entry points | Affects integrators |
| **G5** | `validate_message()` accepts only the 7 built-in messages, inconsistent with `PluginManager.emit()` (which never validates) | Missing docs |
| **G6** | `Scratch` is costly to borrow: three positional args you never use, and the template directory is frozen on the instance | Ergonomics |
| **G7** | `get_summary()`'s `R` is not a retry count (it increments only on a successful response), so its literal reading misleads | Misleading readout |

Plus 4 **wiring notes (N1–N4)**: omitting `failsafe` makes failure types indistinguishable;
`cache_stats()` is not on the abstract base class; a bare `$` in a template raises; `discover()` only
auto-instantiates no-arg factories. Details in the report.

### The boundary mechanism

"**Replacing mavis touches only one file**" is not a slogan — a test enforces it:

- Inside `backend/app/`, **only `mavis_bridge.py`** may import `mavisframework` —
  `test_only_the_bridge_imports_mavisframework` sweeps the whole tree with AST to enforce it;
- And only the top level / `plugin` / `prompt` public paths are allowed —
  `test_bridge_only_uses_public_surface` locks this second layer, forbidding internal modules such as `runtime.llm`.

### Reproduce

```bash
# 7 gap probes (read-only, no mavis file touched)
.venv/Scripts/python.exe backend/spikes/mavis_bounds.py

# 26 tests for "public surface only / single contact point"
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_mavis_usage.py -v
```

### Stance

Public, stable surfaces only; the framework source is never touched. None of the 7 gaps is "unavoidable" —
G1, G4, and G7 are worth fixing upstream, G2 is a latent correctness issue, and the rest are documentation
and ergonomics. Recording the conclusions and evidence in the repo is what makes the next "should we patch
mavis / should we replace mavis" debate an evidence-based one, instead of a fresh read of the source.

---

## Quick start

### 1. One-command bootstrap

```bash
git clone https://github.com/hellobs/ai-debater.git
cd ai-debater
bash scripts/bootstrap.sh
```

The script does exactly three things: clone mavis (read-only dependency), install dependencies, run the
131 tests. **It never calls a model and costs nothing.**

Overridable environment variables:

| Variable | Default | Notes |
|---|---|---|
| `PYTHON_BIN` | `python3` | Requires ≥ 3.12 |
| `VENV` | `<repo>/.venv` | Virtual environment location |
| `MAVIS_DIR` | `<repo>/../mavis` | mavis is expected alongside the repo |
| `MAVIS_REPO` | official HTTPS URL | Use HTTPS when no SSH key is available |

### 2. Credentials (environment variables only, never committed)

```bash
cp .env.example .env     # fill it in; .env is excluded by .gitignore
```

The bridge needs `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`; the model name comes from `LLM_MODEL`
(default `deepseek-chat`). **It runs fine without credentials**: all 131 tests, citation verification,
export, and benchmarks work offline — only a real advisor run needs them.

### 3. Start the services

```bash
export VENV=.venv        # Windows: .venv/Scripts/python.exe

# 1) Protocol bridge (mavis points at it; must start first — skippable in local-model mode)
cd backend && LLM_BRIDGE_PORT=8011 "$VENV/bin/python" -m app.llm_bridge

# 2) Backend       -> http://127.0.0.1:8010
cd backend && "$VENV/bin/python" -m app.main

# 3) Frontend      -> http://127.0.0.1:5173
cd frontend && npm run dev
```

### 4. Verify (0 API spend)

```bash
curl -s http://127.0.0.1:8011/healthz      # protocol bridge
curl -s http://127.0.0.1:8010/api/health   # backend (includes the advisor roster)
cd backend && "$VENV/bin/python" -m pytest # 131 tests
```

---

## Zero-cost mode: local models

When you would rather not spend tokens, point mavis straight at a local Ollama instance —
**the entire pipeline runs at zero cost**:

```bash
ollama serve &                              # prerequisite: local model server
bash scripts/run_local.sh                   # backend on :8010, 0 spend
# optional: OLLAMA_MODEL=qwen3:8b LLM_CONCURRENCY=3 bash scripts/run_local.sh
```

How it works: `LLM_BRIDGE_URL` is repointed at Ollama's OpenAI-compatible endpoint
(`http://127.0.0.1:11434/v1`) — **zero code changes**. Ollama natively supports
`response_format=json_schema`, so **the protocol bridge is not needed in this mode**.

> **Capability boundary (measured — important)**: the local 4B model fails **systematically** on the
> **logical auditor** axis — it returns an empty list even for textbook straw-manning and slippery-slope
> arguments. **Pipeline self-checks, end-to-end regression, and frontend integration ✅ fine;
> live in-round use ❌ not viable.** Raw evidence and latency data:
> [`docs/local-model-report.md`](docs/local-model-report.md) (Chinese).

| Use case | Is the local 4B model enough? |
|---|---|
| Pipeline self-check, end-to-end regression, frontend integration | Yes — and free |
| Fast verification after prompt/schema changes | Yes (structure is verifiable; quality is not) |
| Deciding "did this change make it better?" | Structure and latency only; quality still needs a cloud model |
| Live in-round use | No — the auditor failure is a blocking gap |

---

## Topics and sides: configured up front

A topic is not a string you type into the UI. It is a **presettable, reusable asset** — the motion, both
sides, and the opponent's most likely opening line, bound together.

```yaml
# configs/topics.yaml (a committed preset library — edit the file, that IS the configuration)
topics:
  - id: ai-copyright
    domain: AI + Law
    title: Should AI-generated content enjoy copyright?
    side_a: Prosecutor (should enjoy)      # becomes "our side" once the topic is selected
    side_b: Defence (should not enjoy)
    opponent_hint: Copyright protects the intellectual output of natural persons only...  # one-click fill
    note: The crux is the originality test and whether AI can be a rights holder.
```

- **`configs/topics.yaml`** — committed presets, shared with the team;
- **`data/topics.json`** — whatever you saved via "Save as my topic" in the UI, **never committed**
  (same convention as `ledger.db`);
- At runtime the two are **merged** by `id`, local overriding preset. **An empty library returns empty** —
  the UI degrades gracefully to plain free-text input.

```bash
curl -s http://127.0.0.1:8010/api/topics          # fetch the whole library
# save a local topic (omit id → derived from the title; same title overwrites)
curl -s -X POST http://127.0.0.1:8010/api/topics \
  -H 'content-type: application/json' \
  -d '{"title":"AI should be a mandatory university course","side_a":"For","side_b":"Against"}'
curl -s -X DELETE http://127.0.0.1:8010/api/topics/local-1a2b3c4d   # only local entries are deletable
```

### A general platform, not a law-only one

This is a **general debater's console**; "AI + Law" is one landing scenario among several. Hence:

- **Topics carry a `domain`** and are grouped in the UI (`General` / `AI + Law` / `My topics`);
- **Advisor entries carry a `domain`**, marking which one is scenario-specific — of the five, only the
  **interpretation strategist** is deeply law-bound. The UI shows a small `法学` tag; nothing is silently swapped;
- The word "law" is no longer hardcoded in the brand, the exported report titles, `advisors.yaml`, or `topics.yaml`.

⚠️ **One layer is still coupled**: the advisors' **role directives** still use legal phrasing (the rebutter
demands "major premise = legal norm", the risk advisor looks for "shaky legal sources"). On a general topic
those two will reason through a legal frame. Decoupling the prompts is **not started yet** — see the TODO
list in [`HANDOVER.md`](HANDOVER.md).

---

## The five advisors

| Advisor | Output | Domain | Design basis |
|---|---|---|---|
| **Rebutter** | Syllogistic rebuttal points (claim / major premise / minor premise / conclusion) | General | Handover §3.1, subsumption structure |
| **Questioner** | Questions you can pose immediately | General | — |
| **Logical auditor** | Fallacy type + verbatim fragment | General | Handover §5.1 |
| **Interpretation strategist** | Which interpretive method the opponent used → which one you should argue for | **Law** | Handover §3.4, "contesting the priority of interpretive methods" |
| **Risk advisor** | Opponent traps / our weak spots / unclear facts / shaky sources | General | Handover, "trap 1: position drift" |

**Adding an advisor**: add a module under `backend/app/advisors/` (subclass `Advisor`, define
`output_model`) → register it in `REGISTRY` inside `advisors/__init__.py` → add a line to
`configs/advisors.yaml` → add a render branch in `AdvisorColumn.tsx`.
**The frontend never lists advisors by name** — it reads them from `/api/health`.

---

## Two guardrails

**Guardrail 1 — position consistency** (against contradicting yourself)

1. **Prevention**: every analysis injects still-standing claims from the ledger into the advisor prompts.
2. **Detection**: `check-consistency` compares new advice against the ledger and surfaces claims that
   **cannot both be true**, highlighted in the frontend.

Detection is deliberately kept **off the `/api/analyze` hot path** (latency-sensitive) and called by the
frontend after advice arrives. Measured: feeding a claim that contradicts the ledger hit the conflict
precisely, while **correctly ignoring unrelated claims** (no false positives).

**Guardrail 2 — citation verification** (against fabricated statute text; three conservative states)

| State | Meaning |
|---|---|
| **Verified** | The structured corpus genuinely contains this provision, quoted as evidence |
| **Uncertain** | The statute exists but this provision is absent from the corpus (could be fabricated, could be an incomplete corpus); or it appears only in free text |
| **Unverified** | The corpus does not contain this statute at all |

A statute name without a provision number → Uncertain; **falling back to "the first article of that
statute" is not allowed** (that is a false positive, and we already stepped on that rake once).

Feed statute text into the corpus to enable **Verified** — zero code changes, zero API spend:

```bash
python scripts/import_corpus.py copyright-law.txt --law 中华人民共和国著作权法  # full text → laws.json
curl -s "http://127.0.0.1:8010/api/retrieval?reload=true"                       # make the backend re-read it
```

---

## Tests and benchmarks

```bash
cd backend
"$VENV/bin/python" -m pytest                     # 131 tests, all green, 0 API spend
"$VENV/bin/python" -m benchmarks list            # regression cases
"$VENV/bin/python" -m benchmarks check <case>    # structural self-check (no model calls)
"$VENV/bin/python" -m benchmarks eval <case>     # automatic metrics (0 spend)
"$VENV/bin/python" -m benchmarks run --live --confirm   # the only entry point that calls a model
```

**Coverage of key points is a coarse signal**: it answers "was the topic touched at all", **not "is the
argument any good"** — keyword stuffing can game it. Metric definitions live in
[`benchmarks/README.md`](benchmarks/README.md) — **do not treat it as a quality score**.

---

## Project layout

```
ai-debater/
├── HANDOVER.md              Handover document (read this first)
├── PLAN.md                  Implementation plan v2.0
├── docs/                    Measurement reports · decision log · mavis gap report · export samples
├── prompts/                 Prompt templates (rendered through mavis's Scratch layer)
│   ├── layout.txt           Assembly order: $directive / $context / $task
│   ├── roles/<name>.txt     Role directives
│   └── tasks/<name>.txt     Per-run task instructions
├── configs/
│   ├── advisors.yaml        Advisor roster — the single source (label / kind / domain)
│   ├── topics.yaml          Preset topic library (motion + both sides + opponent hint)
│   └── mavis/config.json    ⚠️ Historical leftover, no longer read at runtime
├── scripts/
│   ├── bootstrap.sh         One-command bootstrap (clone mavis + deps + tests)
│   ├── run_local.sh         Zero-cost local-model launcher
│   └── import_corpus.py     Statute full text → data/corpus/laws.json (enables Verified)
├── backend/
│   ├── app/
│   │   ├── main.py          Entry point + all routes + SSE
│   │   ├── config.py        Environment variables and paths
│   │   ├── llm_bridge.py    Protocol bridge
│   │   ├── mavis_bridge.py  The only contact surface for mavis (provider / templates / plugin bus)
│   │   ├── observers.py     Three observers: ledger / stream / metrics
│   │   ├── orchestrator.py  Parallel dispatch + time budget + event broadcast
│   │   ├── topics.py        Topic library (presets + local)
│   │   ├── advisors/        Five advisors + REGISTRY
│   │   ├── ledger/          Argument ledger (SQLite, row-by-row persistence)
│   │   ├── retrieval/       Retrieval and citation verification (fully local) · statute_text.py parser
│   │   └── export/          Export to Markdown / Word / HTML (print → PDF)
│   ├── benchmarks/          Regression harness (automatic metrics, 0 spend)
│   ├── tests/               131 tests
│   └── spikes/              Stage 0 verification scripts + mavis_bounds.py (gap repro entry point)
├── frontend/src/            React + TS, hand-written styles, no UI framework
└── data/corpus/             Legal source corpus (format documented inside)
```

---

## Documentation index

| Document | Purpose |
|---|---|
| [`HANDOVER.md`](HANDOVER.md) | Full handover: background / decisions / architecture / traps / cost guardrails / open items |
| [`PLAN.md`](PLAN.md) | Implementation plan v2.0 — phased roadmap and acceptance criteria |
| [`docs/decision-log.md`](docs/decision-log.md) | Decision and pitfall log — why things are the way they are |
| [`docs/spike-0-report.md`](docs/spike-0-report.md) | Stage 0 measurements — the evidence that set the architecture |
| [`docs/mavis-gap-report.md`](docs/mavis-gap-report.md) | mavis field test: three surfaces used to the full / 7 gaps (G1–G7) / 4 wiring notes (with repro commands) |
| [`docs/local-model-report.md`](docs/local-model-report.md) | Local model (zero-cost) integration report |
| [`benchmarks/README.md`](benchmarks/README.md) | Regression metric definitions and how to answer "did this change help?" |
| [`data/corpus/README.md`](data/corpus/README.md) | Legal source corpus format (enables **Verified**) |

*Documents are written in Chinese.*

### Export formats

| Format | Endpoint | Notes |
|---|---|---|
| Markdown | `GET /api/session/{sid}/export.md` | Produced directly by the backend |
| Word | `GET /api/session/{sid}/export.docx` | Produced with python-docx (includes the ledger table) |
| PDF | `GET /api/session/{sid}/export.html` | **Print-optimized page**; the browser opens the print dialog, choose "Save as PDF" |

> Why PDF goes through a "print page" rather than direct generation: Chinese PDFs require an embedded CJK
> font, and a missing font renders as tofu boxes. Browser printing uses system fonts — zero dependencies,
> best typography. See the header comment in `backend/app/export/report.py`.

---

## Security guardrails

`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `LLM_API_KEY` are **read from environment variables
only**, never written into code, config, or documentation. The repository contains no hard-coded keys.

**Cost guardrail**: one analysis click = 5 upstream calls; **timeouts are still billed** (the timeout only
means the client stops waiting — the request was already sent). Always ask before running anything with
real spend.

---

## Known limitations

1. API spend for stages 0–2 has no complete accounting (the ledger table only arrived in stage 3).
2. Key-point coverage is a coarse signal and does not represent argument quality.
3. Citation verification only answers "does this citation exist in the given corpus" — it does not judge
   whether the citation is apt or whether the statute was applied correctly.
4. No mobile layout (target device is a laptop browser).
5. ASR (live speech transcription) and a real legal-source retrieval channel are **not integrated**;
   both have interfaces reserved.

---

## License

[Apache-2.0](LICENSE)

<div align="center">
<sub>Every agent is on your side. Whether to use any of it is your call.</sub>
</div>
