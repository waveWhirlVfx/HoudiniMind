# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""Task-specific contracts for high-risk Houdini build requests.

These contracts sit between intent routing and generic verification. They give
the agent a concrete acceptance target for requests that are otherwise easy to
"complete" with superficial containers or wrong node families.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskContract:
    contract_id: str
    title: str
    domains: tuple[str, ...]
    rag_categories: tuple[str, ...]
    acceptance: tuple[str, ...]
    repair_hint: str
    # Generic-verifier hooks (optional).  When present, any contract without a
    # bespoke verifier falls through to ``_verify_generic`` which flags missing
    # required node types / terms.  Bespoke verifiers (dust, particle) ignore
    # these and run their existing logic.
    required_types: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    forbidden_types: tuple[str, ...] = ()


_DUST_RE = re.compile(r"\b(dust|dirt|sand|debris|smoke|particles?)\b", re.IGNORECASE)
_EMIT_RE = re.compile(
    r"\b(emit|emits|emitter|emission|source|spawn|generate|birth|spray)\b",
    re.IGNORECASE,
)
_CONTACT_RE = re.compile(
    r"\b(touch|touching|contact|collid(?:e|ing|es)|hit|hits|ground|floor|feet|foot|"
    r"impact|impacts)\b",
    re.IGNORECASE,
)
_PARTICLE_RE = re.compile(r"\b(particles?|popnet|pop\s*network|points?)\b", re.IGNORECASE)
_PYRO_RE = re.compile(r"\b(pyro|fire|flame|explosion|explode|smoke|burn(?:ing)?)\b", re.IGNORECASE)
_FLIP_RE = re.compile(r"\b(flip|fluid|water|liquid|splash|pool|ocean|river|wave)\b", re.IGNORECASE)
_RBD_RE = re.compile(
    r"\b(rbd|rigid\s*body|destruction|destroy|fracture|shatter|break(?:ing)?)\b",
    re.IGNORECASE,
)
_CLOTH_RE = re.compile(r"\b(cloth|fabric|drape|flag|banner|curtain)\b", re.IGNORECASE)


DUST_CONTACT_EMISSION_CONTRACT = TaskContract(
    contract_id="dust_contact_emission",
    title="Dust emission from ground-contact points",
    domains=("nodes", "vex", "fx"),
    rag_categories=("workflow", "recipe", "best_practice", "nodes", "vex", "sim", "general"),
    acceptance=(
        "The build must identify or create contact points where the source geometry touches the ground/floor.",
        "The build must create a dust/particle source from those contact points, not only object containers.",
        "The build must end on a visible final output node for the contact/emission result.",
        "If a POP node type request is auto-corrected to an unrelated VOP network, reject it and repair with a valid SOP/DOP/VEX workflow.",
    ),
    repair_hint=(
        "Build contact extraction first, then feed those points into a dust source/emitter. "
        "Use exact node-type resolution before creating uncertain FX nodes, and do not claim "
        "completion until the final output is visible and tied to the contact source."
    ),
)


PARTICLE_EMISSION_CONTRACT = TaskContract(
    contract_id="particle_emission",
    title="Particle emission/source setup",
    domains=("nodes", "vex", "fx"),
    rag_categories=("workflow", "recipe", "best_practice", "nodes", "vex", "sim", "general"),
    acceptance=(
        "The build must create an actual source/emitter node chain.",
        "The build must connect the source/emitter into a visible final output.",
        "The build must not stop at empty OBJ containers or unconfigured object merges.",
    ),
    repair_hint=(
        "Create the source geometry and emission/output chain directly. Verify the visible output "
        "has geometry before final response."
    ),
)


PYRO_EXPLOSION_CONTRACT = TaskContract(
    contract_id="pyro_explosion",
    title="Pyro fire/explosion simulation",
    domains=("nodes", "vex", "fx", "sim"),
    rag_categories=("workflow", "recipe", "best_practice", "nodes", "sim", "general"),
    acceptance=(
        "The build must include a pyro source node (pyrosource) feeding density/temperature/flame fields.",
        "The build must include a pyro solver inside a DOP network or use a sparse pyro setup.",
        "The build must end on a visible final output that displays the simulated fields, not the source.",
    ),
    repair_hint=(
        "Create the source geometry, scatter or rasterize it into a pyrosource, then wire it into a "
        "pyro/sparse pyro solver. Ensure the visible output is the simulated cache/dop_import, not the source."
    ),
    required_types=("pyrosource",),
    required_terms=("pyro", "fire", "explosion", "smoke"),
)


FLIP_FLUID_CONTRACT = TaskContract(
    contract_id="flip_fluid",
    title="FLIP fluid simulation",
    domains=("nodes", "fx", "sim"),
    rag_categories=("workflow", "recipe", "best_practice", "nodes", "sim", "general"),
    acceptance=(
        "The build must include a FLIP source (flipsource or volumerasterizeparticles) and a FLIP solver in a DOP network.",
        "The build must define a collision/container so the fluid has a domain.",
        "The build must end on a visible mesh-from-particles or particlefluid output, not the raw emitter.",
    ),
    repair_hint=(
        "Build the fluid container, source the fluid into FLIP particles, run the FLIP solver, then mesh "
        "the result. Display the meshed output, not the source."
    ),
    required_types=("flipsource", "flipsolver"),
    required_terms=("flip", "fluid", "water", "liquid"),
)


RBD_DESTRUCTION_CONTRACT = TaskContract(
    contract_id="rbd_destruction",
    title="RBD destruction / fracture",
    domains=("nodes", "fx", "sim"),
    rag_categories=("workflow", "recipe", "best_practice", "nodes", "sim", "general"),
    acceptance=(
        "The build must fracture the source geometry (voronoi, boolean shatter, or rbdmaterialfracture).",
        "The build must run the fractured pieces through an RBD/Bullet solver in a DOP network.",
        "The build must end on a visible final output that shows the simulated/animated pieces, not the unfractured source.",
    ),
    repair_hint=(
        "Fracture the source, run rbdbulletsolver or DOP rigidbodysolver on the pieces, then display the simulated cache."
    ),
    required_types=("voronoifracture", "rbdmaterialfracture", "rbdbulletsolver"),
    required_terms=("fracture", "shatter", "rbd", "destruction"),
)


CLOTH_SIM_CONTRACT = TaskContract(
    contract_id="cloth_sim",
    title="Cloth simulation",
    domains=("nodes", "fx", "sim"),
    rag_categories=("workflow", "recipe", "best_practice", "nodes", "sim", "general"),
    acceptance=(
        "The build must use a vellumcloth or cloth solver in a DOP/SOP simulation chain.",
        "The build must define constraints (pin or stitch) so the cloth doesn't free-fall.",
        "The build must end on a visible simulated cloth output.",
    ),
    repair_hint=(
        "Convert the cloth panel to vellum cloth, add pin constraints, solve, then display the cooked output."
    ),
    required_types=("vellumcloth", "vellumsolver"),
    required_terms=("cloth", "vellum"),
)


def build_task_contract(query: str) -> TaskContract | None:
    text = (query or "").strip()
    if not text:
        return None

    if _DUST_RE.search(text) and _EMIT_RE.search(text) and _CONTACT_RE.search(text):
        return DUST_CONTACT_EMISSION_CONTRACT

    if _PYRO_RE.search(text):
        return PYRO_EXPLOSION_CONTRACT

    if _FLIP_RE.search(text):
        return FLIP_FLUID_CONTRACT

    if _RBD_RE.search(text):
        return RBD_DESTRUCTION_CONTRACT

    if _CLOTH_RE.search(text):
        return CLOTH_SIM_CONTRACT

    if (_DUST_RE.search(text) or _PARTICLE_RE.search(text)) and _EMIT_RE.search(text):
        return PARTICLE_EMISSION_CONTRACT

    return None


def task_contract_rag_categories(contract: TaskContract | None) -> list[str]:
    if not contract:
        return []
    return list(contract.rag_categories)


def format_task_contract_guidance(contract: TaskContract | None) -> str | None:
    if not contract:
        return None

    lines = [
        f"[TASK CONTRACT: {contract.title}]",
        "This request has a binding production acceptance contract.",
        "Retrieve and use the relevant RAG context for these domains: "
        + ", ".join(contract.domains)
        + ".",
        "Acceptance criteria:",
    ]
    lines.extend(f"- {item}" for item in contract.acceptance)
    lines.extend(
        [
            "Cook/reasoning requirement: before final response, mentally simulate the node graph cook and repair syntax, type, wiring, and missing-output problems.",
            "Repair hint: " + contract.repair_hint,
        ]
    )
    return "\n".join(lines)


def verify_task_contract(
    contract: TaskContract | None,
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any] | None,
    parent_paths: list[str],
    outputs: list[str],
) -> list[dict[str, Any]]:
    if not contract or not after_snapshot:
        return []

    if contract.contract_id == "dust_contact_emission":
        return _verify_dust_contact_emission(before_snapshot, after_snapshot, parent_paths, outputs)
    if contract.contract_id == "particle_emission":
        return _verify_particle_emission(before_snapshot, after_snapshot, parent_paths, outputs)
    return _verify_generic(contract, before_snapshot, after_snapshot, parent_paths, outputs)


def _verify_generic(
    contract: TaskContract,
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any],
    parent_paths: list[str],
    outputs: list[str],
) -> list[dict[str, Any]]:
    """Required-types / required-terms based verifier driven by the contract data."""
    nodes = _contract_nodes(before_snapshot, after_snapshot, parent_paths)
    target = (parent_paths or outputs or ["/obj"])[0]
    issues: list[dict[str, Any]] = []

    if not nodes:
        return [
            _issue(
                target,
                f"{contract.title}: no nodes were created or scoped for this request.",
            )
        ]

    if contract.required_types:
        if not _has_type(nodes, contract.required_types):
            issues.append(
                _issue(
                    target,
                    (
                        f"{contract.title}: required node type missing — expected one of "
                        f"{', '.join(contract.required_types)}."
                    ),
                )
            )

    if contract.required_terms:
        if not _has_any(nodes, contract.required_terms):
            issues.append(
                _issue(
                    target,
                    (
                        f"{contract.title}: no node references the required terms "
                        f"({', '.join(contract.required_terms)})."
                    ),
                )
            )

    if contract.forbidden_types:
        for node in nodes:
            t = str(node.get("type", "") or "").lower()
            if t in contract.forbidden_types:
                issues.append(
                    _issue(
                        str(node.get("path", target)),
                        f"{contract.title}: forbidden node type '{t}' is present.",
                    )
                )
                break

    if not outputs:
        issues.append(
            _issue(
                target,
                f"{contract.title}: no visible final output node exists for the result.",
            )
        )

    return issues


def _node_text(node: dict[str, Any]) -> str:
    return " ".join(
        str(node.get(key, "") or "")
        for key in ("path", "name", "type", "category", "label", "comment")
    ).lower()


def _before_paths(before_snapshot: dict[str, Any] | None) -> set[str]:
    return {
        str(node.get("path"))
        for node in (before_snapshot or {}).get("nodes", []) or []
        if node.get("path")
    }


def _path_under(path: str | None, parent: str | None) -> bool:
    if not path or not parent:
        return False
    parent = parent.rstrip("/")
    return path == parent or path.startswith(parent + "/")


def _contract_nodes(
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any],
    parent_paths: list[str],
) -> list[dict[str, Any]]:
    before = _before_paths(before_snapshot)
    nodes = list(after_snapshot.get("nodes", []) or [])
    scoped = []
    for node in nodes:
        path = str(node.get("path", "") or "")
        if not path:
            continue
        if path not in before:
            scoped.append(node)
            continue
        if parent_paths and any(_path_under(path, parent) for parent in parent_paths):
            scoped.append(node)
    return scoped


def _has_any(nodes: list[dict[str, Any]], terms: tuple[str, ...]) -> bool:
    return any(any(term in _node_text(node) for term in terms) for node in nodes)


def _has_type(nodes: list[dict[str, Any]], types: tuple[str, ...]) -> bool:
    return any(str(node.get("type", "") or "").lower() in types for node in nodes)


def _output_is_relevant(outputs: list[str], terms: tuple[str, ...]) -> bool:
    if not outputs:
        return False
    return any(any(term in str(path).lower() for term in terms) for path in outputs)


def _issue(path: str, message: str) -> dict[str, Any]:
    return {"severity": "repair", "path": path or "/obj", "message": message}


def _verify_dust_contact_emission(
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any],
    parent_paths: list[str],
    outputs: list[str],
) -> list[dict[str, Any]]:
    nodes = _contract_nodes(before_snapshot, after_snapshot, parent_paths)
    target = (parent_paths or outputs or ["/obj"])[0]
    issues: list[dict[str, Any]] = []

    if not nodes:
        return [
            _issue(
                target,
                "Dust/contact contract failed: no created or scoped nodes were found for the requested effect.",
            )
        ]

    dust_terms = ("dust", "emission", "emitter", "emit", "source", "particle", "pop", "spray")
    contact_terms = (
        "contact",
        "touch",
        "collision",
        "collide",
        "impact",
        "near_ground",
        "ground_contact",
        "floor_contact",
    )
    contact_types = (
        "attribwrangle",
        "pointwrangle",
        "groupcreate",
        "groupexpression",
        "group",
        "blast",
        "delete",
        "ray",
        "scatter",
        "attribute_transfer",
        "attribtransfer",
        "distancefromgeometry",
    )
    emission_types = (
        "attribwrangle",
        "pointwrangle",
        "scatter",
        "popnet",
        "popsource",
        "dopnet",
        "volumerasterizeattributes",
        "pyrosource",
    )

    bad_vopnets = [
        node
        for node in nodes
        if str(node.get("type", "") or "").lower() == "vopnet"
        and any(term in _node_text(node) for term in dust_terms)
    ]
    if bad_vopnets:
        issues.append(
            _issue(
                str(bad_vopnets[0].get("path", target)),
                "Dust/contact contract failed: an emission node resolved to vopnet, which is not a valid POP/dust emission setup. Repair with a resolved SOP/DOP/POP/VEX source workflow.",
            )
        )

    has_contact = _has_any(nodes, contact_terms) or _has_type(nodes, contact_types)
    has_emission = _has_any(nodes, dust_terms) or _has_type(nodes, emission_types)

    if not has_contact:
        issues.append(
            _issue(
                target,
                "Dust/contact contract failed: no contact-point extraction node was found. Create points/groups where the source geometry touches the ground before emitting dust.",
            )
        )

    if not has_emission:
        issues.append(
            _issue(
                target,
                "Dust/contact contract failed: no dust/particle source or emitter node chain was found.",
            )
        )

    output_nodes = {
        str(node.get("path")): node
        for node in after_snapshot.get("nodes", []) or []
        if node.get("path")
    }
    obj_outputs = [
        path
        for path in outputs
        if str((output_nodes.get(path) or {}).get("category", "") or "").lower() == "obj"
        or str((output_nodes.get(path) or {}).get("type", "") or "").lower() in {"geo", "subnet"}
    ]
    if not outputs:
        issues.append(
            _issue(
                target,
                "Dust/contact contract failed: no visible final output exists for the contact/emission result.",
            )
        )
    elif obj_outputs:
        issues.append(
            _issue(
                obj_outputs[0],
                "Dust/contact contract failed: the visible output is only an object container, not the cooked contact/emission result.",
            )
        )
    elif not _output_is_relevant(outputs, dust_terms + contact_terms):
        issues.append(
            _issue(
                outputs[0],
                "Dust/contact contract failed: the visible output does not appear to be the dust/contact emission result.",
            )
        )

    object_only = [
        node
        for node in nodes
        if str(node.get("category", "") or "").lower() == "obj"
        or str(node.get("type", "") or "").lower() in {"geo", "subnet"}
    ]
    substantive = [
        node
        for node in nodes
        if str(node.get("category", "") or "").lower() != "obj"
        and str(node.get("type", "") or "").lower() not in {"geo", "subnet", "object_merge", "null"}
    ]
    if object_only and not substantive:
        issues.append(
            _issue(
                target,
                "Dust/contact contract failed: only containers or pass-through nodes were created. Build the contact detector and emission source network.",
            )
        )

    return issues


def _verify_particle_emission(
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any],
    parent_paths: list[str],
    outputs: list[str],
) -> list[dict[str, Any]]:
    nodes = _contract_nodes(before_snapshot, after_snapshot, parent_paths)
    target = (parent_paths or outputs or ["/obj"])[0]
    if not nodes:
        return [_issue(target, "Particle emission contract failed: no build nodes were found.")]

    emit_terms = ("emission", "emitter", "emit", "source", "particle", "pop", "spray", "dust")
    emit_types = ("attribwrangle", "pointwrangle", "scatter", "popnet", "popsource", "dopnet")
    issues: list[dict[str, Any]] = []
    if not (_has_any(nodes, emit_terms) or _has_type(nodes, emit_types)):
        issues.append(
            _issue(target, "Particle emission contract failed: no source/emitter chain was found.")
        )
    if not outputs:
        issues.append(
            _issue(target, "Particle emission contract failed: no visible final output exists.")
        )
    return issues
