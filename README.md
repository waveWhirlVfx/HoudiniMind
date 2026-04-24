<div align="center">

# HoudiniMind

**Agentic AI for SideFX Houdini 21 — local-first, tool-using, zero-hallucination.**

[![CI](https://github.com/waveWhirlVfx/houdinimind/actions/workflows/ci.yml/badge.svg)](https://github.com/waveWhirlVfx/houdinimind/actions)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![Houdini 21](https://img.shields.io/badge/houdini-21-orange.svg)](https://www.sidefx.com/)

</div>

HoudiniMind is a multi-agent framework that drives SideFX Houdini 21 via a curated, schema-validated tool API. It runs LLMs through Ollama — the primary model is **qwen3.5:397b-cloud** — uses a retrieval index over hundreds of SOP docs and FX recipes, and exposes itself over the Model Context Protocol so external editors can co-drive a live Houdini session.

---

## Features

- **Plan → Act → Observe loop** with a critic that gates tool calls before they touch the scene.
- **Zero-hallucination tool layer** — every call is validated against a JSON Schema in `data/schema/`; unknown keys and out-of-range values are rejected before any `hou.*` call.
- **16,384-token context** with sliding compaction for dense node networks.
- **Deep RAG 2.0** — 700+ SOP node docs, 50+ furniture recipes, VEX snippets, and logic workflows queried at planning time.
- **Real-time flight recorder** — every session writes a line-buffered `session.md` that survives hard Houdini crashes.
- **MCP server** — drive Houdini from Claude Desktop, Cursor, or any MCP client.
- **PySide6 panel** — thread-safe (`QThreadPool`/`QRunnable`); the viewport never freezes.

## Prerequisites

- Houdini **21.x** (bundles Python 3.11)
- [Ollama](https://ollama.com) 0.3+
- 16 GB RAM minimum;

## Installation

### macOS / Linux

```bash
git clone https://github.com/waveWhirlVfx/houdinimind.git
cd houdinimind
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python install.py                         # wires the panel into $HOUDINI_USER_PREF_DIR
ollama pull qwen3.5:397b-cloud
ollama pull gemma4:e4b                      # optional, for vision tools
```

### Windows (PowerShell)

```powershell
git clone https://github.com/waveWhirlVfx/houdinimind.git
cd houdinimind
py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python install.py
ollama pull qwen3.5:397b-cloud
```

### Launching in Houdini

1. `Windows → Python Panel Editor → New`.
2. Paste the contents of `python_panels/HoudiniMind.pypanel`.
3. Dock the **HoudiniMind** panel, pick a model from the dropdown, click **Connect**.

## Usage

### Inside the panel

Submit a prompt. Example:

> Create a procedural table with adjustable legs and apply a wood material.

The agent plans, emits tool calls, observes the scene, and iterates until the goal is met. Every step is appended to `sessions/<timestamp>/session.md`.

### From the CLI (standalone, outside Houdini)

```bash
houdinimind run --prompt "Build a FLIP whitewater setup" --model llama3.1:8b
houdinimind eval --suite tests/fixtures/eval_suite.jsonl
```

### Over MCP

Copy the relevant block from `mcp_config_example.json` into your MCP client's config, start the MCP server from the panel's toolbar, and the client can call HoudiniMind tools remotely.

## Repository layout

```
houdinimind/
├── src/houdinimind/            # installable package
│   ├── agent/                  # planner, critic, tool dispatcher
│   │   └── tools/              # curated hou.* wrappers (schema-validated)
│   ├── inference/              # Ollama client, tokenizer, adapters
│   ├── rag/                    # retrieval index + ingestion
│   ├── bridge/                 # MCP server, scene reader
│   ├── memory/                 # long-term memory manager
│   ├── debug/                  # flight recorder
│   └── ui/                     # PySide6 widgets (no hou imports)
├── hm_ui/panel.py              # thin Houdini entry point
├── python_panels/              # Houdini .pypanel wrappers
├── data/
│   ├── knowledge/              # RAG corpus (source-of-truth)
│   ├── schema/                 # JSON schemas for every tool
│   ├── prompts/                # system prompts
│   └── db/                     # generated artefacts (git-ignored)
├── tests/                      # pytest suite (uses tests/fake_hou.py)
├── scripts/                    # build-kb, eval harness, etc.
└── docs/                       # MkDocs site
```

## Architecture

```
User Prompt ─▶ Planner(LLM) ─▶ Critic ─▶ Tool Dispatcher ─▶ hou.*
                    ▲                           │
                    └───── Observer ◀──── Scene snapshot
                              │
                              └── RAG (data/knowledge)

            session.md ◀── every plan, tool call, and observation
            MCP server ◀── external clients (Claude Desktop, Cursor, ...)
```

See [`docs/architecture.md`](docs/architecture.md) for the full walkthrough.

## Development

```bash
pip install -e ".[dev]"
pre-commit install
ruff check .
mypy src/houdinimind
pytest -q
```

The test suite does **not** require a Houdini install — `tests/fake_hou.py` stubs `hou`. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Roadmap

- **v7.1** — streaming tool calls, partial-observation replanning
- **v7.2** — deterministic scene-diff eval harness
- **v8.0** — Karma render-loop agent, USD write path

## Contributing

PRs welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) first. For security issues, see [`SECURITY.md`](SECURITY.md) — **do not** file a public issue.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
