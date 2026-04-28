# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [7.0.0] - Unreleased

### Added
- Complete rewrite of the codebase for `src/houdinimind`
- Multi-agent framework for driving SideFX Houdini 21 via a curated, schema-validated tool API
- Local LLM support through Ollama
- Retrieval index over hundreds of SOP docs and FX recipes
- MCP server for external editors to co-drive a live Houdini session
- `pyproject.toml` support for `ruff`, `mypy`, `pytest`, `coverage`

### Changed
- Refactored `hm_python` structure into standard `src/houdinimind` layout
- Moved logic into `agent/`, `inference/`, `rag/`, `bridge/`, `memory/`, `debug/`, and `ui/`

### Removed
- Legacy components (`AGENTS.md`, `GEMINI.md`, `update_knowledge.command`)
