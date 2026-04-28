# HoudiniMind Agent Showcase Video Prompts

These prompts are designed to demonstrate the agent's core capabilities in a compelling way for video content. Each should take 30-90 seconds of agent work (not counting vision capture or final review).

## Category 1: Goal Memory & Persistence
*Demonstrates the agent's ability to maintain focus on the original task through multiple tool rounds.*

### Prompt 1.1: Multi-Step Glass Shattering
```
Create a glass sphere, break it into fragments with RBD, 
add a constraint that holds the pieces together initially, 
then remove the constraint so the pieces fall apart. 
Show me a viewport capture of the shattered pieces mid-fall.
```
**Why it works:**
- Tests goal anchoring through 4+ tool calls (create sphere, fracture, add RBD with constraint, remove constraint)
- Agent must remember "glass sphere" throughout the workflow
- Vision capture shows the final result clearly
- Visually satisfying for video (shattering effect)

### Prompt 1.2: Sculpted Object with Simulation
```
Create an abstract sculpted shape with organic geometry. 
Then set it up as a dynamic object that can be affected by forces. 
Attach it to a constraint so it swings like a pendulum. 
Simulate and show me a frame where it's in motion.
```
**Why it works:**
- Tests multi-round memory (organic shape → simulation setup → constraint → capture)
- Shows agent creativity in modeling
- Demonstrates constraint mastery
- Results in interesting motion capture

---

## Category 2: Vision-Based Feedback & Iteration
*Demonstrates agent's ability to use vision feedback to refine work.*

### Prompt 2.1: Chair Design with Vision Feedback
```
Create a simple chair with a seat, backrest, and four legs. 
Attach an image of a real chair to show the design I want. 
Based on the reference image, adjust the chair proportions and add details. 
Show me a final viewport capture of your design.
```
**Why it works:**
- Uses the improved image routing (vision always enabled)
- Agent sees reference and adapts work accordingly
- Multiple iterations based on visual feedback
- Clear before/after comparison possible

### Prompt 2.2: Scene Layout with Feedback
```
Create 5 random objects: a table, chairs, a lamp, a book, and a plant. 
Arrange them in a living room-like setup. 
Show me a screenshot. Then based on the layout, 
adjust the positions so it looks more natural and balanced.
```
**Why it works:**
- Tests vision-based spatial reasoning
- Multiple iterations with visual feedback
- Demonstrates agent's ability to critique and improve its own work

---

## Category 3: RBD Simulation & Dynamics
*Showcases the improved RBD simulation tool (no wrangle issues, proper constraint setup).*

### Prompt 3.1: Domino Chain Reaction
```
Create a series of 10 domino tiles arranged in a line. 
Set them up with RBD so they're interactive. 
Place a ball at the start of the line, then simulate. 
Capture a frame showing the dominoes falling.
```
**Why it works:**
- Clean demonstration of RBD setup
- Chain reaction effect is visually compelling
- Shows agent's ability to arrange objects procedurally
- Tests the fixed RBD tool (no wrangle artifacts)

### Prompt 3.2: Destructible Structure
```
Build a tower made of stacked boxes. 
Make it destructible with RBD. 
Add a dynamic sphere that falls and crashes through the tower. 
Show me the moment of impact with pieces exploding.
```
**Why it works:**
- Complex setup: modeling → RBD → dynamic interaction → capture
- Visually impressive destruction
- Tests agent's spatial reasoning and simulation knowledge

### Prompt 3.3: Fluid-Affected Rigid Bodies
```
Create a water surface as a deforming plane. 
Place floating wooden crates on top using RBD. 
Add a wave deformation to the water. 
Simulate and show the crates bobbing on the water.
```
**Why it works:**
- Tests integration of multiple systems (deformation + RBD)
- Realistic, recognizable scenario
- Good for demonstrating agent's tool chain knowledge

---

## Category 4: Modeling & Creativity
*Shows the agent's ability to create and refine geometry.*

### Prompt 4.1: Parametric Spiral Staircase
```
Create a spiral staircase with parametric controls. 
Make it 2 stories tall, with 24 steps. 
The staircase should have handrails. 
Show me a view from above and a view from the side.
```
**Why it works:**
- Tests procedural modeling knowledge
- Demonstrates agent's parametric thinking
- Two viewport captures show different perspectives
- Architectural complexity is impressive

### Prompt 4.2: Organic Plant Growth
```
Create a stylized plant with a main stem, branches, and leaves. 
Use Houdini's native tools to make it look procedurally grown. 
Vary the leaf shapes and sizes naturally. 
Show me the final plant in a nice viewport angle.
```
**Why it works:**
- Showcases procedural/organic capabilities
- Visually beautiful result
- Tests agent's knowledge of procedural patterns

---

## Category 5: Material & Rendering Setup
*Demonstrates agent's ability to work beyond just geometry.*

### Prompt 5.1: Material Variations
```
Create 3 spheres in a row. 
Apply different materials to them: 
- one metallic and shiny
- one matte plastic
- one translucent glass
Show them in a nice lighting setup.
```
**Why it works:**
- Tests shader/material knowledge
- Visual difference is clear and impressive
- Good for demonstrating agent's breadth

---

## Category 6: Complex Multi-Step Workflows
*Demonstrates end-to-end capabilities.*

### Prompt 6.1: Destruction Sequence (Full Workflow)
```
Create a brick wall using modular brick pieces. 
Fracture it at multiple levels. 
Add RBD dynamics to make it destructible. 
Drop a wrecking ball into it from above. 
Show me two frames: one before impact and one during/after destruction.
```
**Why it works:**
- Long, complex workflow testing goal memory throughout
- Visually spectacular (destruction)
- Tests multiple tool categories
- Shows agent's ability to plan multi-step sequences

### Prompt 6.2: Scene Assembly with Lighting
```
Build a simple bedroom scene with:
- A bed frame with mattress and pillows
- A nightstand with a lamp
- A window frame
- Wall geometry
Then add lighting to make it look warm and inviting. 
Show me the lit scene.
```
**Why it works:**
- Large scope tests memory persistence
- Tests modeling, scene composition, and lighting
- Recognizable scene is easy for viewers to evaluate
- Final result is polished and impressive

---

## Category 7: Quick Wins (30 seconds)
*Shorter prompts that show specific capabilities quickly.*

### Prompt 7.1: Instant Garden
```
Create a garden with 10 randomly placed plants of varying heights and styles. 
Add a simple wooden fence around it. 
Show the scene.
```

### Prompt 7.2: Bouncing Ball Rig
```
Create a ball and set it up to bounce realistically. 
Let it bounce 5 times with decreasing height. 
Show a frame mid-bounce.
```

### Prompt 7.3: Mirrored Sculpture
```
Create an interesting 3D shape and mirror it 3 times around to make a symmetrical sculpture. 
Apply a metallic material. 
Show the result.
```

---

## Recommended Video Sequence

For a 5-minute showcase video, use this order:
1. **Prompt 1.1** (Goal Memory) - Shows persistence, visually cool
2. **Prompt 3.1** (Dominoes) - Quick, satisfying payoff
3. **Prompt 2.1** (Chair with Vision) - Shows unique vision capability
4. **Prompt 3.2** (Tower Destruction) - Dramatic impact
5. **Prompt 6.1** (Wrecking Ball) - Complex workflow
6. **Prompt 4.1** (Spiral Staircase) - Architectural sophistication

**Alternate 3-minute version:**
1. Prompt 1.1 (Goal Memory)
2. Prompt 3.1 (Dominoes)
3. Prompt 6.1 (Wrecking Ball)

---

## Tips for Video Capture

### Before Running Prompts:
- Start with fresh Houdini session for each prompt
- Set viewport to 1920x1080 or 1280x720 for clean captures
- Use consistent lighting (HoudiniMind defaults or custom if needed)

### During Execution:
- Record agent work in real-time with screen capture tool
- Pause/speed up verbose output sections if needed
- Capture final viewport result with `0` key for full UI hide

### After Results:
- Use final viewport capture images for thumbnail frames
- Collect any interesting mid-work frames (domino falling, debris flying, etc.)
- Create split-screen comparisons for vision feedback prompts (reference → result)

### Key Moments to Capture:
- Agent's initial thought process (planning)
- Major tool execution (simulation, fracture, constraint)
- Final viewport frame with object(s) visible
- Any motion/dynamics in action if simulation runs
