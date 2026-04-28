# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Skills Platform
Loadable skill plugins that extend the agent's tool set at runtime.

A skill is a Python file placed in houdinimind/agent/skills/ or the user-configured
skills_dir (defaults to data/skills/).

Each skill file must expose a register() function:

    def register() -> dict:
        return {
            "name": "my_skill",
            "version": "1.0",
            "description": "What this skill does",
            "tools": {
                "my_tool_name": my_tool_function,
            },
            "schemas": [
                {
                    "type": "function",
                    "function": {
                        "name": "my_tool_name",
                        "description": "...",
                        "parameters": { ... }
                    }
                }
            ],
        }

Skills are loaded by SkillLoader.load_all() which is called from the panel
backend after AgentLoop is initialized.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from typing import Dict, List, Optional


class SkillLoader:
    """
    Scans skill directories, imports each skill module, calls register(),
    and injects the returned tools/schemas into the live agent.
    """

    def __init__(self, agent, config: dict):
        self.agent = agent
        self.config = config
        self._loaded: dict[str, dict] = {}  # name → registration dict
        self._errors: dict[str, str] = {}  # name → error string

    # ── Public API ────────────────────────────────────────────────────

    def load_all(self) -> dict:
        """
        Discover and load all skills.  Returns a summary dict.
        """
        dirs = self._skill_dirs()
        for skill_dir in dirs:
            if not os.path.isdir(skill_dir):
                continue
            for fname in sorted(os.listdir(skill_dir)):
                if not fname.endswith(".py") or fname.startswith("_"):
                    continue
                skill_name = fname[:-3]
                self._load_skill(skill_name, os.path.join(skill_dir, fname))
        return self.status()

    def status(self) -> dict:
        return {
            "loaded": list(self._loaded.keys()),
            "errors": dict(self._errors),
            "total_loaded": len(self._loaded),
            "total_errors": len(self._errors),
        }

    def reload_skill(self, name: str) -> bool:
        """Re-load a single skill by name (hot-reload)."""
        dirs = self._skill_dirs()
        for skill_dir in dirs:
            path = os.path.join(skill_dir, f"{name}.py")
            if os.path.exists(path):
                self._load_skill(name, path)
                return True
        return False

    # ── Internal ──────────────────────────────────────────────────────

    def _skill_dirs(self) -> list[str]:
        """Return ordered list of directories to scan for skills."""
        dirs = []
        # 1. Built-in skills shipped with HoudiniMind
        builtin = os.path.join(os.path.dirname(__file__))
        dirs.append(builtin)
        # 2. User-configured skills directory (data/skills/)
        data_dir = self.config.get("data_dir", "data")
        user_skills = self.config.get("skills_dir", os.path.join(data_dir, "skills"))
        if user_skills not in dirs:
            dirs.append(user_skills)
        return dirs

    def _load_skill(self, name: str, path: str) -> None:
        try:
            spec = importlib.util.spec_from_file_location(f"houdinimind_skill_{name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "register"):
                self._errors[name] = "missing register() function"
                return

            reg = module.register()
            if not isinstance(reg, dict):
                self._errors[name] = "register() must return a dict"
                return

            self._inject(name, reg)
            self._loaded[name] = reg
            self._errors.pop(name, None)
            print(f"[HoudiniMind Skills] Loaded skill: {name} v{reg.get('version', '?')}")
        except Exception as e:
            self._errors[name] = str(e)
            traceback.print_exc()
            print(f"[HoudiniMind Skills] Failed to load skill '{name}': {e}")

    def _inject(self, name: str, reg: dict) -> None:
        """Inject tool functions and schemas from a skill into the live agent."""
        tools = reg.get("tools") or {}
        schemas = reg.get("schemas") or []

        if not self.agent:
            return

        # Inject into TOOL_FUNCTIONS (the live dispatch table)
        try:
            from houdinimind.agent.tools import TOOL_FUNCTIONS

            for tool_name, fn in tools.items():
                if callable(fn):
                    TOOL_FUNCTIONS[tool_name] = fn
        except Exception as e:
            print(f"[HoudiniMind Skills] TOOL_FUNCTIONS injection failed for '{name}': {e}")

        # Inject into TOOL_SCHEMAS (the LLM-facing schema list)
        try:
            from houdinimind.agent.tools import TOOL_SCHEMAS

            existing_names = {(s.get("function") or {}).get("name") for s in TOOL_SCHEMAS}
            for schema in schemas:
                sname = (schema.get("function") or {}).get("name")
                if sname and sname not in existing_names:
                    TOOL_SCHEMAS.append(schema)
                    existing_names.add(sname)
        except Exception as e:
            print(f"[HoudiniMind Skills] TOOL_SCHEMAS injection failed for '{name}': {e}")
