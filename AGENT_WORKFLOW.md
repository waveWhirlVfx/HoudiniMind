# HoudiniMind Agent Workflow

This document provides a comprehensive technical breakdown of what happens when you send a message to the HoudiniMind AI Agent. It details the internal pipeline from the initial message receipt to the final scene mutation and verification.

## High-Level Architecture
The HoudiniMind agent follows a **Plan → Act → Observe → Verify** loop, optimized for the high-precision requirements of 3D procedural workflows in SideFX Houdini.

```mermaid
graph TD
    A[User Message] --> B[Intent Classification]
    B --> C[RAG & Knowledge Retrieval]
    C --> D[Hierarchical Planning]
    D --> E[Execution Loop (Tool Calling)]
    E --> F{Internal Validation}
    F -- Fail --> G[Auto-Repair Pass]
    G --> E
    F -- Pass --> H[Auto-Finalize Network]
    H --> I[Post-Build Verification]
    I --> J[Vision Feedback Loop]
    J -- Fail --> K[VLM Guided Correction]
    K --> E
    J -- Pass --> L[Semantic Scoring]
    L --> M[Final Response]
```

---

## 1. Initial Processing & Grounding
### Intent Classification
The `AgentLoop` first classifies the request into one of four modes:
- **BUILD**: Creating or modifying geometry networks.
- **DEBUG**: Investigating and fixing scene errors.
- **ADVICE/RESEARCH**: Pure knowledge retrieval or workflow strategy.
- **RESEARCH (Options)**: Generating multiple alternative approaches for the user to choose from.

### RAG (Retrieval-Augmented Generation)
The agent performs a background pre-fetch from the local Houdini Knowledge Base:
- **Recipes**: Semantic retrieval of successful past node-chains for specific objects (e.g., "table legs", "pyro setup").
- **Documentation**: Technical details on VEX functions or node parameters.
- **Project Rules**: Local coding standards and "Memories" learned from previous sessions.

---

## 2. The Planning Phase
Before a single node is created, the **Planner Agent** decomposes the high-level goal into a hierarchical JSON plan.
- **Stage-based Breakdown**: e.g., "Stage 1: Base Geometry, Stage 2: Boolean Operations, Stage 3: Detailing".
- **Prototype Measurements**: The planner calculates relative scales and positions (e.g., "Place legs at Y=0.75") to prevent spatial hallucinations.
- **Dependency Tracking**: Ensuring parent containers exist before child SOPs are requested.

---

## 3. The Execution Loop (`_run_loop`)
The agent enters a multi-round tool-calling loop (up to 25 rounds).

### Context Optimization
To prevent context-window overflow, HoudiniMind uses **Dynamic Tool Selection**. Out of 60+ available tools, it only sends the top ~20 most relevant tool schemas based on the current plan.

### Main-Thread Marshalling
All Houdini interactions (`hou.*`) are marshalled to the **Houdini Main Thread** via `hdefereval`. This ensures the UI remains responsive and prevents multi-threaded crashes.

### Safety & Guardrails
- **Repetition Guard**: Detects if the agent is stuck in a loop (e.g., resizing the same node repeatedly) and injects a corrective warning.
- **Stagnation Detection**: Terminates the loop if the same error repeats 3+ times without progress.
- **Main-Thread Timeout**: Prevents the agent from hanging if a Houdini cook takes too long.

---

## 4. Verification & Self-Correction
Once the execution loop finishes, the agent performs multiple layers of QA.

### Structural QA (Validator Agent)
The scene is scanned for:
- **Cook Errors**: Any red nodes or failed expressions.
- **Disconnected Branches**: "Orphan" nodes that are not wired into the display output.
- **Empty Geometry**: Nodes that exist but produced zero points/voxels.

### Vision Feedback Loop (VLM)
If the build is complex, the agent triggers a **Visual Self-Check**:
1. It captures a viewport screenshot.
2. It sends the screenshot to a **Vision Language Model (VLM)** along with the original goal.
3. **Visual Verdict**: If the VLM says "The table has no legs," the agent generates a targeted repair pass to fix the visual discrepancy.

### Semantic Scoring
For high-quality assets, the agent performs a "Multiview Render" (Front, Side, Perspective) and scores the result against:
- **Identity**: Does it look like the requested object?
- **Proportion**: Are the scales physically plausible?
- **Support**: Do parts correctly sit on top of each other?

---

## 5. Finalization
- **Auto-Finalize**: The agent automatically adds `OUT` nulls, merges loose branches, and flags the correct display node.
- **Scene Diff**: A summary of all created nodes and modified parameters is generated.
- **Task Anchor**: The original user goal is re-injected as a reminder in every round to prevent "goal drift" during long sessions.

---

## Summary of Specialized Agents
| Agent | Role |
| :--- | :--- |
| **Planner** | Strategic breakdown and spatial math. |
| **Builder** | Tool execution and Houdini network wiring. |
| **Critic** | Error diagnosis and root-cause analysis. |
| **Validator** | Structural QA (Errors, Wiring, Geometry counts). |
| **Vision/VLM** | Visual quality control and silhouette verification. |
