# ADR 0001: Foundational project setup — Python 3.12, uv, spec-aligned layout

## Status

Accepted — 2026-04-21

## Context

The Darwin AI Workbench build began April 21, 2026 with a single solo
developer working against the v5.0 Build Specification. Before writing
application code, three foundational decisions had to be locked in:

1. Which Python version to target
2. Which Python project manager to use
3. How to structure the repository

This ADR records all three together because they were decided as a set and
they constrain each other (particularly #1 and #2).

## Decision 1 — Python 3.12

The project pins Python 3.12 via `.python-version` and
`requires-python = ">=3.12"` in `pyproject.toml`.

### Rationale

- **AWS Lambda first-class runtime.** Section 19 describes 14 Lambda
  functions. Python 3.12 has been a managed Lambda runtime since late 2023.
  Pinning 3.12 means the local .venv matches the production runtime exactly -
  no surprises at deployment.
- **LangGraph 1.1 ecosystem** is validated on 3.12; 3.14 (the dev machine's
  system default in April 2026) is too new for the AWS SDK and LangChain
  stack to have settled on.
- **Pydantic v2 performance** heavily optimizes 3.11+ code paths.

### Rejected

- **3.13** — supported, but not the default managed Lambda runtime yet.
- **3.14** — too new; LangGraph 1.1 release notes name 3.12 and 3.13 as tested.
- **3.11 or older** — misses Pydantic v2 fast paths and newer typing.

### Consequence

A contributor with any Python (or no Python) on their machine can work on this
project: uv downloads 3.12 into a project-local cache on first `uv sync`.

## Decision 2 — uv as Python project manager

The project uses **uv** (https://astral.sh/uv) for dependency resolution,
virtual environment management, and Python interpreter installation.

### Rationale

- **Speed.** uv's Rust-based resolver is 10-100x faster than pip/poetry.
  Tonight's 56-package dependency tree resolved in 274ms and installed in ~1s.
- **Python interpreter management.** uv downloads and manages Python versions
  itself - no pyenv, no conda, no system Python required.
- **PEP 621 compliant.** Reads the standard `[project]` table. Portable to
  pip, Poetry, or PDM if we ever switch.
- **Deterministic, cross-platform lock file** (uv.lock).

### Rejected

- **Poetry** — slower; older proprietary `[tool.poetry]` config.
- **pip + requirements.txt** — no lock file, no Python pinning, no resolver.
  Unacceptable for a production system.
- **conda/mamba** — excessive for a pure-Python project.
- **Hatch** — reasonable, but uv is faster AND manages Python interpreters.

### Consequence

Standard commands for contributors:

- `uv sync` — install all deps from the lock file
- `uv add <package>` — add a dep (writes pyproject.toml + installs)
- `uv run <command>` — run anything in the project .venv
- CI uses `uv sync` followed by `uv run pytest`

## Decision 3 — Repository layout follows v5.0 spec Section 15

The repo does **not** use the conventional Python src-layout
(`src/darwin_workbench/`). It follows the layout prescribed by Section 15
of the v5.0 spec:

    darwin-workbench/
    ├── agents/          # Council system prompts (YAML) + council_config.yaml
    ├── mcp/             # MCP platform servers
    ├── orchestration/   # LangGraph graph, nodes, CIM state, routing
    ├── pipelines/       # Agentic pipeline definitions
    ├── rag/             # Knowledge base source documents
    ├── engagements/     # Per-engagement branches (runtime)
    ├── ui/              # React Workbench UI
    ├── lambdas/         # 14 Lambda functions (Section 19)
    ├── infra/           # Terraform/CDK provisioning
    ├── tests/           # Unit + integration
    ├── docs/            # ADRs, runbooks, SOC 2 mapping
    └── scripts/         # Helper scripts

### Rationale

- **Spec requires it.** Section 15 prescribes this structure as the
  per-organization Layer 2 CodeCommit layout. At provisioning time, this repo
  IS deployed into each customer's Layer 2 account. Diverging from the spec's
  structure would force rename work later.
- **Repo is simultaneously source code and per-org config.** Per-engagement
  branches (`engagements/{id}/`) live in the same repo as the Python source.
  A src-layout would split these artificially.
- **Layout mirrors architectural seams.** Agents, MCP, orchestration,
  pipelines are first-class concerns; each gets a top-level directory.

### Rejected

- **src/darwin_workbench/** (src-layout) — would require rename at Layer 2
  provisioning.
- **Flat package at root** — would become messy past ~10 Python files.

### Consequences

- Python imports: `from orchestration.state import CIM` (package at project root).
- `conftest.py` at the project root puts the project on sys.path for pytest.
- When we eventually build deployable artifacts (Lambda wheels), we specify
  the included directories explicitly in the build config. Deferred until
  needed.

## Notes for future contributors

Two things bit us tonight; recording so the next person doesnt rediscover:

1. **`uv init --bare` does NOT create `.python-version`.** It creates an
   empty pyproject.toml with `requires-python = ">=3.12"` but no
   `.python-version` file. Without that, uv falls back to the system Python.
   Either run `uv python pin 3.12` explicitly after bare init, or use
   `uv init` (non-bare) which creates `.python-version` automatically.

2. **PowerShell windows start at `C:\Windows\System32` by default on Windows.**
   Any scaffolding loop (`$dirs | ForEach-Object { mkdir }`) that assumes
   the current directory will create files in the wrong place. Always `cd`
   to the project root at the top of a script, or validate CWD before doing
   bulk directory operations.

## Related

- Spec sections: 01 (architecture), 02 (MVW), 15 (repo structure), 19 (Lambda)
- Commit 70d06bf — initial scaffold
- Commit 376c9f3 — CIM v0.1 Pydantic model + tests
