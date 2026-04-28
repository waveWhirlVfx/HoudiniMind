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
- **32,768-token context** with sliding compaction for dense node networks.
- **Deep RAG 2.0** — 700+ SOP node docs, 50+ furniture recipes, VEX snippets, and logic workflows queried at planning time.
- **Real-time flight recorder** — every session writes a line-buffered `session.md` that survives hard Houdini crashes.
- **MCP server** — drive Houdini from Cursor, or any MCP client.
- **PySide6 panel** — thread-safe; the viewport never freezes during agent work.

---

## Prerequisites

Before installing HoudiniMind, make sure you have all of the following:

| Requirement | Version | Notes |
|---|---|---|
| [SideFX Houdini](https://www.sidefx.com/download/) | **21.x** | Bundles Python 3.11 — do not use 3.12 or 3.13 |
| [Ollama](https://ollama.com/download) | **0.3+** | Must be running before you open Houdini |
| Python | **3.11 only** | Must match Houdini's bundled Python version |
| Git | any | To clone the repo |
| RAM | **16 GB minimum** | 32 GB recommended for large scenes |

> **Python version is critical.** Houdini 21 ships with Python 3.11. HoudiniMind's package is installed into that same Python, so you must use `python3.11` (not 3.12 or 3.13) throughout the install steps below.

---

## Recommended Model

**`qwen3.5:397b-cloud`** is the recommended model for HoudiniMind. It delivers superior planning and spatial reasoning for Houdini workflows with fast cloud inference.

For the RAG (knowledge retrieval) system, HoudiniMind also requires a local embedding model:

```bash
ollama pull qwen3.5:397b-cloud      # main chat model
ollama pull nomic-embed-text        # required for RAG knowledge search
```

---

## Installation

### Step 1 — Install and start Ollama

Download Ollama from [ollama.com/download](https://ollama.com/download) and install it.

Then open a terminal and start the Ollama server (keep this terminal open):

```bash
ollama serve
```

In a **second terminal**, pull the required models:

```bash
ollama pull qwen3.5:397b-cloud
ollama pull nomic-embed-text
```

Verify Ollama is running:

```bash
curl http://localhost:11434/api/tags
# Should return a JSON list of your downloaded models
```

---

### Step 2 — Clone the repository

```bash
git clone https://github.com/waveWhirlVfx/houdinimind.git
cd houdinimind
```

---

### Step 3 — Install Python dependencies

You must use **Python 3.11** here. Check your version first:

```bash
python3.11 --version
# Should print: Python 3.11.x
```

**macOS / Linux:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

**Windows (PowerShell):**

```powershell
# If you get a policy error, run this first (once):
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -e ".[dev]"
```

---

### Step 4 — Run the installer

The installer detects your Houdini user directory and writes a Houdini package file that automatically loads HoudiniMind every time Houdini starts.

```bash
python install.py
```

Expected output:

```
============================================================
  Houdini Agent Installer
============================================================

✓ Houdini user directory: /path/to/houdini21.0
✓ Data directory ready:   /path/to/houdinimind/data
✓ Package file written:   /path/to/houdini21.0/packages/houdinimind.json
✓ Learned prompt file initialised
✓ Knowledge base ready:   /path/to/houdinimind/data/knowledge/knowledge_base.json
```

> If the installer cannot find your Houdini directory it will print a fallback path. In that case, manually copy the printed `houdinimind.json` package file into your Houdini `packages/` directory.

**Where is my Houdini packages directory?**

| OS | Path |
|---|---|
| macOS | `~/Library/Preferences/houdini21.0/packages/` |
| Linux | `~/houdini21.0/packages/` |
| Windows | `%USERPROFILE%\Documents\houdini21.0\packages\` |

---

### Step 5 — Open Houdini and load the panel

1. **Launch Houdini 21.** The package file from Step 4 is loaded automatically on startup.

2. **Add a Python Panel pane.** In any pane, click the pane-type icon (top-left of the pane) → **Python Panel**.

3. **Select HoudiniMind.** In the Python Panel toolbar, open the panel dropdown and select **HoudiniMind** (it appears automatically because the package registered it).

4. **Dock the panel** wherever you like — most users dock it on the right side or in a floating window.

> **Panel not showing?** See [Troubleshooting](#troubleshooting) below.

---

### Step 6 — Verify the connection

Once the panel opens:

1. Wait for the status bar to change from `Initializing — loading knowledge base…` to `Ready` (takes 5–15 seconds on first launch).
2. The model dropdown should list your Ollama models. Select **qwen3.5:397b-cloud**.
3. The connection indicator (dot in the top bar) should turn green.
4. Type a test prompt and press **Send**:
   > `What nodes are in my scene right now?`

The agent should respond with a list of nodes — this confirms the full pipeline (panel → agent → Houdini tools → response) is working.

---

## Usage

### Inside the panel

Submit any natural-language prompt. Examples:

> `Create a box and scatter 200 points on its surface.`
>
> `Set up a FLIP fluid sim with a sphere emitter inside a box container.`
>
> `Look at my viewport and tell me what's wrong with the geometry.`

The agent plans, calls Houdini tools, observes the result, and iterates until the goal is met or it reports a specific blocker. Every step is saved to `data/debug/sessions/<timestamp>/session.jsonl`.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Send message |
| `Shift+Enter` | New line in message |
| `Ctrl+L` | Clear conversation |

### From the CLI (outside Houdini)

```bash
houdinimind run --prompt "Build a FLIP whitewater setup" --model qwen3.5:397b-cloud
houdinimind eval --suite tests/fixtures/eval_suite.jsonl
```

---

## MCP Setup (optional)

The MCP server lets external editors like Cursor co-drive a live Houdini session.

**Step 1 — Start the MCP server in Houdini.** In the HoudiniMind panel toolbar, click **Toggle MCP Server**. The status bar shows `MCP: 127.0.0.1:9876`.

**Step 2 — Configure your client.** Open `mcp_config_example.json` in the repo root and copy the block for your client (Cursor, Claude Desktop, etc.) into that client's config file. Replace `/path/to/HoudiniMind` with the actual path where you cloned the repo.

**Example for Cursor** (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "houdinimind": {
      "command": "python3",
      "args": ["/path/to/houdinimind/src/houdinimind/agent/mcp_bridge.py"],
      "env": {
        "HOUDINI_HOST": "127.0.0.1",
        "HOUDINI_PORT": "9876",
        "PYTHONPATH": "/path/to/houdinimind/src"
      }
    }
  }
}
```

**Step 3 — Test.** In Cursor, open the MCP tool list — you should see HoudiniMind tools like `create_node`, `get_scene_info`, etc.

---

## Troubleshooting

### Panel does not appear in the Python Panel dropdown

The Houdini package file was not found. Check:

1. `install.py` printed a package path like `…/packages/houdinimind.json` — verify that file actually exists on disk.
2. If it is missing, run `install.py` again, or manually create it:
   - Create `<houdini_user_dir>/packages/houdinimind.json` with this content (replace the path):
   ```json
   {
     "env": [
       {"HOUDINIMIND_ROOT": "/path/to/houdinimind"},
       {"PYTHONPATH": {"value": "/path/to/houdinimind", "method": "prepend"}}
     ],
     "path": "/path/to/houdinimind"
   }
   ```
3. Restart Houdini after creating the file.

### Status bar stays on "Initializing" forever

- Open Houdini's Python console (`Windows → Python Shell`) and look for error messages printed during startup.
- Common cause: `nomic-embed-text` not pulled. Run `ollama pull nomic-embed-text`.
- Common cause: Ollama not running. Run `ollama serve` in a terminal.

### "No models found" / connection dot is red

- Make sure Ollama is running: `curl http://localhost:11434/api/tags`
- Check the Ollama URL in the panel settings matches where Ollama is running (default: `http://localhost:11434`).
- On Windows, Windows Defender firewall sometimes blocks localhost connections — add an exception for port 11434.

### Agent does nothing or returns empty responses

- The model may not have loaded yet. Wait 10–20 seconds after selecting a model and try again.
- Check that `qwen3.5:397b-cloud` was successfully pulled: `ollama list`

### "Tool timed out after 90s" errors

Houdini's main thread was busy cooking when the agent tried to run a tool. Wait for the current cook to finish and retry. You can raise the timeout with an environment variable before launching Houdini:

```bash
export HOUDINIMIND_TOOL_TIMEOUT=180   # seconds
houdini &
```

### Python version mismatch on Windows

If you see `ModuleNotFoundError` or `ImportError` inside Houdini, your install used the wrong Python. Open Houdini's Python shell and run:

```python
import sys; print(sys.version)
```

It should show `3.11.x`. If it shows 3.12 or 3.13, re-run `install.py` using `py -3.11 install.py` explicitly.

---

## Repository layout

```
houdinimind/
├── src/houdinimind/            # installable Python package
│   ├── agent/                  # planner, critic, tool dispatcher
│   │   └── tools/              # curated hou.* wrappers (schema-validated)
│   ├── inference/              # Ollama client + adapters
│   ├── rag/                    # retrieval index + ingestion
│   ├── bridge/                 # MCP server + scene reader
│   ├── memory/                 # long-term memory manager
│   └── debug/                  # flight recorder
├── hm_ui/                      # thin Houdini UI entry point
├── python_panels/              # HoudiniMind.pypanel (auto-loaded by package)
├── data/
│   ├── knowledge/              # RAG corpus (700+ SOP docs + FX recipes)
│   ├── schema/                 # JSON schemas for every tool
│   └── debug/sessions/         # per-session logs (git-ignored)
├── install.py                  # one-time installer
├── mcp_config_example.json     # MCP client config snippets
├── tests/                      # pytest suite (no Houdini required)
└── docs/                       # MkDocs site
```

## Architecture

```
User Prompt ─▶ Planner(LLM) ─▶ Critic ─▶ Tool Dispatcher ─▶ hou.*
                    ▲                           │
                    └───── Observer ◀──── Scene snapshot
                              │
                              └── RAG (data/knowledge)

            session.jsonl ◀── every plan, tool call, and observation
            MCP server    ◀── external clients (Cursor, ...)
```

See [`docs/architecture.md`](docs/architecture.md) for the full walkthrough.

---

## Development

```bash
pip install -e ".[dev]"
pre-commit install
ruff check .
mypy src/houdinimind
pytest -q
```

The test suite does **not** require a Houdini install — `tests/fake_hou.py` stubs `hou`. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Contributing

PRs welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) first. For security issues, see [`SECURITY.md`](SECURITY.md) — **do not** file a public issue.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
