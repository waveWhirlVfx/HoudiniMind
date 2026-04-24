# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
from __future__ import annotations

import json
import re
from typing import Dict, Optional


REFERENCE_CUE_RE = re.compile(
    r"\b(reference|match this|from this image|based on this image|like the attached|use the attached)\b",
    re.IGNORECASE,
)


def query_has_reference_cues(text: str) -> bool:
    return bool(REFERENCE_CUE_RE.search(str(text or "")))


class ReferenceProxyPlanner:
    @staticmethod
    def _extract_json(raw: str) -> dict:
        text = (raw or "").strip()
        if not text:
            return {}
        if "```" in text:
            text = re.sub(
                r"^```(?:json)?\s*|\s*```$",
                "",
                text.strip(),
                flags=re.IGNORECASE,
            )
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}

    def build_proxy_spec(
        self,
        llm,
        user_message: str,
        vision_description: str,
    ) -> Optional[dict]:
        system = (
            "You convert a reference image description into a procedural proxy spec for Houdini.\n"
            "Return strict JSON only with this shape:\n"
            "{"
            '"object":"name",'
            '"confidence":0.0,'
            '"symmetry":"none|left_right|radial",'
            '"proxy_strategy":"one sentence",'
            '"dimensions":{"width":1.0,"height":1.0,"depth":1.0},'
            '"components":[{"name":"part","primitive":"box","required":true,"relative_scale":[1,1,1],"relative_position":[0,0,0],"notes":"..." }],'
            '"assembly_notes":["note 1","note 2"]'
            "}\n"
            "Use coarse blockout-friendly parts only."
        )
        user = (
            f"User request: {user_message}\n\n"
            f"Reference description:\n{vision_description}\n\n"
            "Focus on recognizable silhouette, major parts, symmetry, contact/support relationships, and a procedural blockout strategy."
        )
        try:
            raw = llm.chat_simple(
                system=system,
                user=user,
                task="proxy",
                temperature=0.1,
            )
        except Exception:
            return None
        spec = self._extract_json(raw)
        return spec or None

    @staticmethod
    def format_prompt_injection(spec: Optional[Dict]) -> str:
        if not spec:
            return ""
        object_name = str(spec.get("object", "") or "reference object").strip()
        symmetry = str(spec.get("symmetry", "") or "unknown").strip()
        strategy = str(spec.get("proxy_strategy", "") or "").strip()
        components = spec.get("components") or []
        assembly = spec.get("assembly_notes") or []

        lines = [
            "[REFERENCE PROXY SPEC]",
            f"Target object: {object_name}",
            f"Symmetry: {symmetry}",
        ]
        if strategy:
            lines.append(f"Proxy strategy: {strategy}")
        if components:
            lines.append("Major proxy components:")
            for component in components[:8]:
                name = str(component.get("name", "") or "part")
                primitive = str(component.get("primitive", "") or "box")
                notes = str(component.get("notes", "") or "").strip()
                line = f"- {name}: {primitive}"
                if notes:
                    line += f" — {notes}"
                lines.append(line)
        if assembly:
            lines.append("Assembly notes:")
            for note in assembly[:6]:
                note = str(note or "").strip()
                if note:
                    lines.append(f"- {note}")
        lines.append(
            "Use this proxy spec to build a recognizable blockout before small details."
        )
        return "\n".join(lines)
