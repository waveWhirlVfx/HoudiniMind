# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import json
import os

base_path = os.path.dirname(os.path.abspath(__file__))
os.makedirs(base_path, exist_ok=True)

def update_json(filename, new_data):
    filepath = os.path.join(base_path, filename)
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = []
    
    # Simple deduplication
    if filename == 'sop_recipes.json':
        existing = {item.get('asset') for item in data}
        for item in new_data:
            if item.get('asset') not in existing:
                data.append(item)
    elif filename == 'sop_errors.json':
        existing = {item.get('error') for item in data}
        for item in new_data:
            if item.get('error') not in existing:
                data.append(item)
    elif filename == 'sop_workflows.json':
        existing = {item.get('workflow') for item in data}
        for item in new_data:
            if item.get('workflow') not in existing:
                data.append(item)
    elif filename == 'sop_decision_guides.json':
        existing = {item.get('topic') for item in data}
        for item in new_data:
            if item.get('topic') not in existing:
                data.append(item)
                
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

# ==========================================
# 1. SOP RECIPES (+20)
# ==========================================
new_recipes = [
    {
        "asset": "Suspension Bridge",
        "description": "Procedural suspension bridge with adjustable length, pillars, and cables.",
        "nodes": ["line", "resample", "box", "sweep", "curve", "merge"],
        "node_settings": [
            {"node": "line (Deck)", "action": "Horizontal line for the bridge length. Sweep a flat box profile for the deck."},
            {"node": "resample", "action": "Resample the line to define pillar spacing."},
            {"node": "box (Pillar)", "action": "Tall box copied to the pillar points."},
            {"node": "curve (Main Cable)", "action": "Draw a drooping parabolic curve between pillars."},
            {"node": "line (Suspenders)", "action": "Vertical lines connecting the main cable to the deck."}
        ],
        "expected_outcome": "A complete suspension bridge that scales proportionally."
    },
    {
        "asset": "Chain (interlocking)",
        "description": "Interlocking metal chain links following a path.",
        "nodes": ["torus", "transform", "curve", "path_deform", "copy"],
        "node_settings": [
            {"node": "torus", "action": "Create a single chain link. Scale Z to make it oval."},
            {"node": "transform", "action": "Duplicate the link and rotate it 90 degrees, translating it forward to interlock."},
            {"node": "copy", "action": "Copy this pair of links multiple times along the Z axis."},
            {"node": "curve", "action": "Draw the path the chain should follow."},
            {"node": "path_deform", "action": "Deform the straight chain along the drawn curve."}
        ],
        "expected_outcome": "A flexible, continuous chain."
    },
    {
        "asset": "Rope",
        "description": "Twisted multi-strand rope.",
        "nodes": ["line", "resample", "sweep", "twist", "copy"],
        "node_settings": [
            {"node": "line", "action": "Draw a straight line for the core."},
            {"node": "circle", "action": "Create a small circle profile."},
            {"node": "copy", "action": "Copy the circle 3 times, rotated 120 degrees around the center."},
            {"node": "sweep", "action": "Sweep the 3 circles along the line to create 3 parallel strands."},
            {"node": "twist", "action": "Apply a high twist value along the length of the strands to braid them together."}
        ],
        "expected_outcome": "A braided, twisted rope."
    },
    {
        "asset": "Book",
        "description": "A closed book with a hard cover and pages.",
        "nodes": ["box", "polybevel", "boolean", "color"],
        "node_settings": [
            {"node": "box (Pages)", "action": "Create a box for the paper block. Color it white."},
            {"node": "box (Cover)", "action": "Create a slightly larger box for the cover. Color it brown."},
            {"node": "polybevel", "action": "Bevel the spine edge of the cover for a rounded back."},
            {"node": "boolean", "action": "Subtract a tiny sliver to create the gap between the cover and the pages."}
        ],
        "expected_outcome": "A simple prop book."
    },
    {
        "asset": "Barrel",
        "description": "Wooden barrel with metal bands.",
        "nodes": ["tube", "mountain", "polyextrude", "sweep"],
        "node_settings": [
            {"node": "tube", "action": "Create a barrel shape by tapering the top and bottom of a tube."},
            {"node": "polyextrude (Planks)", "action": "Select vertical faces and extrude them individually slightly to create wooden planks."},
            {"node": "circle (Bands)", "action": "Create circles at specific heights for the metal bands."},
            {"node": "sweep", "action": "Sweep a flat profile along the circles to create the metal rings."}
        ],
        "expected_outcome": "A classic wooden barrel."
    },
    {
        "asset": "Potion Bottle",
        "description": "A classic fantasy potion bottle with a cork.",
        "nodes": ["curve", "revolve", "polyextrude", "tube"],
        "node_settings": [
            {"node": "curve", "action": "Draw the half-profile of a bulbous bottle and thin neck."},
            {"node": "revolve", "action": "Revolve 360 degrees to create the glass shell."},
            {"node": "polyextrude", "action": "Add thickness to the glass."},
            {"node": "tube (Cork)", "action": "Create a slightly tapered tube and place it in the neck opening."}
        ],
        "expected_outcome": "A glass potion flask."
    },
    {
        "asset": "Mug / Cup",
        "description": "A coffee mug with a handle.",
        "nodes": ["tube", "polyextrude", "curve", "sweep", "boolean"],
        "node_settings": [
            {"node": "tube", "action": "Create a cylinder for the main cup body."},
            {"node": "polyextrude", "action": "Extrude the top face inward, then down to hollow out the cup."},
            {"node": "curve", "action": "Draw a 'C' shaped curve on the side for the handle."},
            {"node": "sweep", "action": "Sweep a circle along the curve to give the handle thickness."},
            {"node": "boolean", "action": "Union the handle to the cup body."}
        ],
        "expected_outcome": "A standard coffee mug."
    },
    {
        "asset": "Sword",
        "description": "A basic medieval sword.",
        "nodes": ["box", "polyedit", "mirror", "merge"],
        "node_settings": [
            {"node": "box (Blade)", "action": "Long, flat box. Scale the top points together to form a tip."},
            {"node": "box (Crossguard)", "action": "Horizontal box placed below the blade."},
            {"node": "cylinder (Grip)", "action": "Vertical cylinder below the crossguard."},
            {"node": "sphere (Pommel)", "action": "Place at the bottom of the grip."}
        ],
        "expected_outcome": "A low-poly sword prop."
    },
    {
        "asset": "Shield",
        "description": "A round wooden shield with a metal rim.",
        "nodes": ["tube", "polybevel", "sphere", "boolean"],
        "node_settings": [
            {"node": "tube (Wood)", "action": "Flat, wide tube. Add a slight dome shape by moving the center points up."},
            {"node": "tube (Rim)", "action": "A slightly larger tube with a hole in the middle to act as the metal binding."},
            {"node": "sphere (Boss)", "action": "A flattened half-sphere placed in the exact center of the shield."}
        ],
        "expected_outcome": "A Viking-style round shield."
    },
    {
        "asset": "Bow",
        "description": "A wooden longbow with a string.",
        "nodes": ["curve", "sweep", "line", "merge"],
        "node_settings": [
            {"node": "curve (Wood)", "action": "Draw the bent shape of the bow limbs."},
            {"node": "sweep", "action": "Sweep a circular profile along the curve, tapering the ends."},
            {"node": "line (String)", "action": "Draw a straight line connecting the two extreme ends of the bow curve."}
        ],
        "expected_outcome": "A basic archery bow."
    },
    {
        "asset": "Arrow",
        "description": "An arrow with a shaft, arrowhead, and fletching.",
        "nodes": ["tube", "cone", "grid", "copy", "merge"],
        "node_settings": [
            {"node": "tube (Shaft)", "action": "Long, very thin cylinder."},
            {"node": "cone (Head)", "action": "Place at the front of the shaft."},
            {"node": "grid (Fletching)", "action": "Cut a grid into a feather shape."},
            {"node": "copy", "action": "Copy the fletching 3 times radially around the back of the shaft."}
        ],
        "expected_outcome": "A standard arrow."
    },
    {
        "asset": "Crown",
        "description": "A royal gold crown.",
        "nodes": ["tube", "polyextrude", "bend", "polybevel"],
        "node_settings": [
            {"node": "tube", "action": "Create a flat grid, subdivide it, and delete top alternating faces to make spikes."},
            {"node": "polyextrude", "action": "Add thickness to the flat spike pattern."},
            {"node": "bend", "action": "Bend the flat strip 360 degrees into a perfect circle."},
            {"node": "fuse", "action": "Fuse the seam where the ends meet."}
        ],
        "expected_outcome": "A spiked king's crown."
    },
    {
        "asset": "Procedural Ivy / Vine",
        "description": "Vines growing and wrapping around an object.",
        "nodes": ["scatter", "findshortestpath", "sweep", "copytopoints"],
        "node_settings": [
            {"node": "scatter", "action": "Scatter start and end points on a target mesh."},
            {"node": "findshortestpath", "action": "Generate wandering curves connecting the points across the mesh surface."},
            {"node": "sweep", "action": "Give the curves a small thickness for the main vine stems."},
            {"node": "copytopoints (Leaves)", "action": "Scatter new points on the stems and copy leaf geometry (a bent grid) onto them."}
        ],
        "expected_outcome": "Organic ivy wrapping around any input shape."
    },
    {
        "asset": "Procedural Clouds (VDB)",
        "description": "Fluffy, volumetric clouds generated from spheres.",
        "nodes": ["scatter", "copytopoints", "vdbfrompolygons", "vdbcombine", "vdbreshapesdf"],
        "node_settings": [
            {"node": "scatter", "action": "Scatter points inside a bounding box."},
            {"node": "copytopoints", "action": "Copy overlapping spheres of varying sizes onto the points."},
            {"node": "vdbfrompolygons", "action": "Convert the spheres into a single SDF volume."},
            {"node": "vdbreshapesdf", "action": "Use volume noise to distort the SDF, making the edges fluffy and organic."},
            {"node": "convertvdb", "action": "Convert from SDF to a Density/Fog VDB for rendering."}
        ],
        "expected_outcome": "A realistic volumetric cloud."
    },
    {
        "asset": "Procedural Crater",
        "description": "A moon-like impact crater on a terrain.",
        "nodes": ["heightfield", "heightfield_pattern", "heightfield_noise", "heightfield_maskbyfeature"],
        "node_settings": [
            {"node": "heightfield", "action": "Create a base flat terrain."},
            {"node": "heightfield_pattern", "action": "Use a radial ramp pattern. Map it to dig a bowl shape and raise a lip around the edge."},
            {"node": "heightfield_noise", "action": "Add high-frequency noise inside the bowl to simulate rough ground."},
            {"node": "heightfield_maskbyfeature", "action": "Mask the steep inner slopes to apply a different texture or rock scatter."}
        ],
        "expected_outcome": "A realistic asteroid/moon crater."
    },
    {
        "asset": "Procedural Asteroid",
        "description": "A pockmarked, irregular space rock.",
        "nodes": ["sphere", "mountain", "scatter", "boolean"],
        "node_settings": [
            {"node": "sphere", "action": "Start with a high-res polygon sphere."},
            {"node": "mountain", "action": "Apply massive, low-frequency noise to distort the overall shape into a potato."},
            {"node": "scatter & copy", "action": "Scatter points and copy small spheres to them."},
            {"node": "boolean", "action": "Subtract the small spheres from the main body to create craters."}
        ],
        "expected_outcome": "A highly detailed asteroid."
    },
    {
        "asset": "Procedural Planet",
        "description": "A planetary body with continents and oceans.",
        "nodes": ["sphere", "vopnet", "polyreduce", "color"],
        "node_settings": [
            {"node": "sphere", "action": "Create a very high-res sphere."},
            {"node": "vopnet (Displacement)", "action": "Use multiple layers of Curl Noise to push points out (continents) and leave others flat (oceans)."},
            {"node": "color", "action": "Map height to color: blue for low areas, green/brown for mid, white for peaks."}
        ],
        "expected_outcome": "A stylized planetary globe."
    },
    {
        "asset": "Stalagmite / Stalactite",
        "description": "Cave formations.",
        "nodes": ["cone", "mountain", "vdbfrompolygons", "vdbsmooth", "convertvdb"],
        "node_settings": [
            {"node": "cone", "action": "Tall, thin cone shape."},
            {"node": "mountain", "action": "Add heavy vertical noise to make it lumpy and uneven."},
            {"node": "vdb", "action": "Convert to VDB, smooth it heavily to get that melted wax/drip look, and convert back to polygons."}
        ],
        "expected_outcome": "Organic cave spikes."
    },
    {
        "asset": "Tire (Tread)",
        "description": "A car tire with complex tread patterns.",
        "nodes": ["grid", "polyextrude", "bend", "mirror"],
        "node_settings": [
            {"node": "grid", "action": "Create a small, flat square representing one tread block."},
            {"node": "polyextrude", "action": "Extrude it upward to give it depth."},
            {"node": "copy", "action": "Copy it in a line to form a long strip."},
            {"node": "bend", "action": "Bend the strip 360 degrees to form the circular tire."}
        ],
        "expected_outcome": "A detailed vehicle tire."
    },
    {
        "asset": "Traffic Cone",
        "description": "Orange street cone with a base.",
        "nodes": ["tube", "box", "color", "merge"],
        "node_settings": [
            {"node": "tube", "action": "Taper heavily into a cone shape. Color it orange."},
            {"node": "box", "action": "Flat square base. Color it orange."},
            {"node": "group", "action": "Select the middle faces of the cone and color them white for the reflective stripe."}
        ],
        "expected_outcome": "A standard traffic safety cone."
    }
]
update_json('sop_recipes.json', new_recipes)

# ==========================================
# 2. SOP WORKFLOWS (+10)
# ==========================================
new_workflows = [
    {
        "workflow": "Vellum Cloth Setup (Basic)",
        "description": "Turn standard geometry into falling/colliding cloth.",
        "prerequisites": ["A high-res polygon mesh (e.g. a grid)"],
        "context": "Vellum is Houdini's standard solver for cloth, hair, and soft bodies. It operates incredibly fast on the GPU.",
        "steps": [
            "1. Create your cloth geometry (e.g. a Grid, 100x100 rows).",
            "2. Append a 'Vellum Configure Cloth' node. This generates the internal constraints (stretch, bend).",
            "3. Append a 'Vellum Solver' node.",
            "4. Press Play on the timeline. The cloth will fall to infinity.",
            "5. Inside the Vellum Solver, double-click to dive inside, and add a 'Ground Plane' node to the DOPS network to give it something to hit."
        ],
        "tips": ["If the cloth passes through itself, increase 'Substeps' on the Vellum Solver parameter interface."]
    },
    {
        "workflow": "Vellum Softbody Setup (Basic)",
        "description": "Create squishy, jello-like objects.",
        "prerequisites": ["A solid, watertight mesh (e.g. a rubber toy or sphere)"],
        "context": "Unlike cloth, softbodies need to maintain their internal volume.",
        "steps": [
            "1. Append a 'Remesh' SOP to your geometry to ensure uniform triangle sizes.",
            "2. Append a 'Vellum Configure Strut Softbody' node.",
            "3. Adjust 'Strut Length' to determine how rigid the interior is.",
            "4. Append a 'Vellum Solver' and press Play."
        ],
        "tips": ["Tetrahedral softbodies are more accurate but slower. Strut softbodies are great for fast, squishy effects."]
    },
    {
        "workflow": "Vellum Hair Setup (Basic)",
        "description": "Simulate hair, strings, or ropes.",
        "prerequisites": ["Lines or curves (not polygon tubes)"],
        "context": "Vellum hair only simulates points connected by lines. You add thickness *after* the simulation.",
        "steps": [
            "1. Generate multiple curves (e.g. using 'Hair Generate' or scattering lines on a scalp).",
            "2. Append a 'Vellum Configure Hair' node.",
            "3. To pin the roots to the head, enable 'Pin to Animation' and specify the root points (usually `@curveu==0`).",
            "4. Append a 'Vellum Solver' and press Play.",
            "5. After the solver, append a 'Sweep' SOP to give the simulated curves actual renderable thickness."
        ],
        "tips": ["Always simulate raw curves first, mesh them second. Never simulate the meshed tubes."]
    },
    {
        "workflow": "RBD Fracture and Simulate",
        "description": "Break an object and make it collapse physically.",
        "prerequisites": ["A solid mesh"],
        "context": "Rigid Body Dynamics (RBD) using Bullet is the core of destruction FX.",
        "steps": [
            "1. Append an 'RBD Material Fracture' node to your mesh. Set Material Type to Concrete or Glass.",
            "2. The node will fracture the mesh into packed pieces and create proxy collision geometry.",
            "3. Append an 'RBD Bullet Solver' node to the output of the fracture node.",
            "4. Enable 'Ground Plane' on the solver's Collision tab.",
            "5. Press Play. The pieces will fall and scatter."
        ],
        "tips": ["Use 'RBD Exploded View' between the fracture and the solver to visualize how the pieces are cut before simulating."]
    },
    {
        "workflow": "Pyro Smoke Setup (SOPs)",
        "description": "Emit rising smoke from geometry.",
        "prerequisites": ["A source mesh (e.g. a torus or sphere)"],
        "context": "Modern Houdini does most basic Pyro setups directly in SOPs using Sparse Solvers.",
        "steps": [
            "1. Append a 'Pyro Source' SOP to your mesh. Set 'Initialize' to 'Source Smoke'. This creates density and temperature points.",
            "2. Append a 'Volume Rasterize Attributes' SOP. Select 'density' and 'temperature'. This converts the points into VDB volumes.",
            "3. Append a 'Pyro Solver' SOP.",
            "4. Press Play. The heat will cause the density to rise as smoke."
        ],
        "tips": ["Lower the 'Voxel Size' in the Volume Rasterize and Pyro Solver nodes to increase resolution, but beware of slower sim times."]
    },
    {
        "workflow": "Flip Fluid Setup (Basic SOPs)",
        "description": "Create a splashing pool of water.",
        "prerequisites": ["A box or shape defining the initial water volume"],
        "context": "FLIP (Fluid Implicit Particle) is Houdini's liquid solver.",
        "steps": [
            "1. Append a 'FLIP Fluid from Object' shelf tool, or manually create a 'FLIP Source' SOP.",
            "2. In SOPs, use the 'FLIP Solver' node.",
            "3. Connect your source particles to the first input.",
            "4. Setup a collision object (like a bowl) and connect it to the fourth input (Collision Volume).",
            "5. Press play. After simulation, use 'Particle Fluid Surface' to convert the fluid points into a renderable liquid mesh."
        ],
        "tips": ["FLIP is heavily dependent on 'Particle Separation'. Smaller values mean vastly more particles and memory usage."]
    },
    {
        "workflow": "Path Deform (Animating along a curve)",
        "description": "Make a snake, train, or arrow slither along a complex path.",
        "prerequisites": ["A model (train/snake) pointing down the Z-axis", "A drawn curve"],
        "context": "Bends geometry to conform to a spline.",
        "steps": [
            "1. Ensure your model is aligned along the positive Z-axis.",
            "2. Append a 'Path Deform' SOP to the model.",
            "3. Connect the drawn curve into the second input of the Path Deform.",
            "4. Animate the 'Position' parameter from 0 to 1 to move the object along the path."
        ],
        "tips": ["If the object twists wildly, enable 'Compute Up Vector' on the curve, or use an Attribute Wrangle to define stable `@up` vectors along the curve points."]
    },
    {
        "workflow": "Procedural Noise Displacement",
        "description": "Create highly detailed, jagged rocks or terrain.",
        "prerequisites": ["A high-res base mesh"],
        "context": "Standard mountain SOPs only push points. VDB displacement alters the actual volume for overhangs and complex boolean-like detail.",
        "steps": [
            "1. Convert the mesh using 'VDB from Polygons'.",
            "2. Append a 'Volume VOP'. Dive inside.",
            "3. Add an 'Anti-Aliased Noise' node. Connect global `P` to the noise position.",
            "4. Multiply the noise output by a float parameter (Intensity).",
            "5. Add the result to the global `density` or `surface` output.",
            "6. Use 'Convert VDB' to turn it back to polygons."
        ],
        "tips": ["This technique guarantees no intersecting polygons, unlike heavy Mountain SOP displacement."]
    },
    {
        "workflow": "Instancing with Random Colors",
        "description": "Scatter identical objects but give them unique colors at render time.",
        "prerequisites": ["Target points, Instance geometry"],
        "context": "Essential for crowds, forests, or scattered debris.",
        "steps": [
            "1. On your scatter points, append an 'Attribute Randomize'. Set name to `Cd` (Color).",
            "2. Pack your instance geometry using a 'Pack' SOP.",
            "3. Append a 'Copy to Points' SOP. Connect the packed geo to Input 1, the colored points to Input 2.",
            "4. In the Copy to Points, ensure 'Pack and Instance' is ON.",
            "5. In the viewport, they may look grey. In Karma/Mantra, they will read the point `Cd` attribute and render multicolored."
        ],
        "tips": ["If you need the color in the viewport, you must type 'Cd' in the 'Transfer Attributes' box of the Copy to Points node."]
    },
    {
        "workflow": "Time Shifting / Freezing Simulation",
        "description": "Take one perfect frame of a simulation and freeze it as a static model.",
        "prerequisites": ["A cached simulation or animated sequence"],
        "context": "Used to extract a specific explosion shape, or a perfectly draped cloth, to use as a static prop.",
        "steps": [
            "1. Scrub the timeline until you find the exact frame you like (e.g. frame 45).",
            "2. Append a 'TimeShift' SOP after the simulation.",
            "3. Right-click the 'Frame' parameter and select 'Delete Channels' (this removes the `$F` expression).",
            "4. Type '45' into the Frame parameter.",
            "5. The geometry is now frozen at frame 45, regardless of where the timeline is."
        ],
        "tips": ["You can also use expressions in TimeShift, like `$F * 0.5` to artificially slow down geometry caches (though it requires sub-frame data to look smooth)."]
    }
]
update_json('sop_workflows.json', new_workflows)

# ==========================================
# 3. SOP ERRORS (+8)
# ==========================================
new_errors = [
    {
        "error": "Vellum cloth exploding on frame 1",
        "symptoms": ["Cloth instantly shoots outward in a spiky mess", "Simulation disappears completely"],
        "cause": "The input geometry has intersecting polygons or points that are impossibly close together, causing the Vellum solver to apply infinite repulsive force to separate them.",
        "detailed_solution": "1. Ensure the cloth mesh is clean (no self-intersections). 2. In the Vellum Solver, go to the 'Advanced' tab and increase 'Collision Passes'. 3. On the Vellum Configure node, slightly lower 'Thickness' so collision radii don't overlap at the start.",
        "prevention": "Never simulate cloth that has already been extruded or has self-intersecting folds."
    },
    {
        "error": "RBD pieces intersecting at start",
        "symptoms": ["Fractured pieces slowly push apart before they even hit the ground", "Bullet solver is jittery"],
        "cause": "The collision padding (shrink wrap) around the packed primitives overlaps. This usually happens if you fracture an object, then scale it down, or if the fracture created microscopic slivers.",
        "detailed_solution": "Append an 'RBD Pack' node before the solver, or dive into the 'RBD Bullet Solver' properties and slightly increase the 'Collision Padding' or use 'Shrink Collision Geometry' to create a tiny gap between pieces.",
        "prevention": "Ensure the object is at world-scale (1 unit = 1 meter) before fracturing."
    },
    {
        "error": "Pyro volume disappearing instantly",
        "symptoms": ["Smoke emits for 1 frame and vanishes", "Density field shows 0 in spreadsheet"],
        "cause": "The source points lack the required attributes (density, temperature), or the bounding box of the Pyro Solver is not resizing to encompass the smoke.",
        "detailed_solution": "1. Check the 'Pyro Source' node to ensure it is outputting 'density'. 2. Check the 'Volume Rasterize Attributes' node to ensure 'density' is in the attributes list. 3. In the Pyro Solver, ensure 'Closed Boundaries' is turned off on the Y axis, and 'Max Size' on the bounding box allows expansion.",
        "prevention": "Always verify source volume data via middle-mouse click before diving into the solver."
    },
    {
        "error": "PolyExtrude outputting flipped normals",
        "symptoms": ["The extruded faces look black/dark in the viewport", "Render engines treat the geometry as inside-out"],
        "cause": "Extruding an open curve, or extruding a flat plane with a negative distance value.",
        "detailed_solution": "Check the 'Reverse Normals' option in the PolyExtrude node, or append a 'Reverse' SOP to flip the winding order of the polygons.",
        "prevention": "Ensure base normals are pointing outward before extruding."
    },
    {
        "error": "Sweep SOP twisting unexpectedly",
        "symptoms": ["The swept tube pinches, flattens, or spins wildly along the curve"],
        "cause": "The curve lacks consistent 'up' vectors. As the curve bends, Houdini's default parallel transport algorithm gets confused about which way is 'up'.",
        "detailed_solution": "1. On the curve, append a 'PolyFrame' SOP. Set 'Tangent Name' to `N` and 'Bitangent Name' to `up`. 2. Alternatively, in the Sweep SOP, change 'Roll/Twist' settings or check 'Compute Up Vector'.",
        "prevention": "Always define `@up` and `@N` attributes on complex 3D paths before sweeping."
    },
    {
        "error": "CopyToPoints instances not rotating correctly",
        "symptoms": ["All copied objects face the exact same direction, ignoring the surface normals"],
        "cause": "The template points lack `@N` (Normal) and `@up` (Up Vector) attributes, or you have an `@orient` quaternion attribute overriding everything else.",
        "detailed_solution": "Append a 'Normal' SOP to your target points. If instances spin on their axis, append an Attribute Wrangle and type `v@up = set(0,1,0);` to lock their vertical rotation.",
        "prevention": "Understand the Copy to Points alignment hierarchy: `@orient` > `@N` and `@up` > `v@v`."
    },
    {
        "error": "Boolean SOP extremely slow / hangs",
        "symptoms": ["Houdini freezes at 99% cooking the Boolean node"],
        "cause": "Inputs have massively dense topology (e.g. millions of polygons), or inputs are heavily non-manifold/messy, causing the exact-math solver to fail.",
        "detailed_solution": "1. Use 'PolyReduce' on the cutter object. 2. If it's a proxy/background object, use the 'VDB Boolean' workflow instead, which is resolution-independent and never hangs.",
        "prevention": "Do not boolean raw photogrammetry or ZBrush sculpts. Remesh or VDB them first."
    },
    {
        "error": "VDB from Polygons has holes or artifacts",
        "symptoms": ["The volume looks like Swiss cheese", "Certain parts of the mesh refuse to voxelize"],
        "cause": "The polygon mesh is open (not watertight), has reversed normals, or the Voxel Size is too large to capture thin walls.",
        "detailed_solution": "1. Lower the Voxel Size. 2. Append a 'PolyFill' SOP to close open holes. 3. Append a 'Clean' SOP to fix normal directions. If it's a 2D plane, change the VDB type to 'Unsigned Distance Field'.",
        "prevention": "Volumes require closed spaces. If you pour water into a mesh and it leaks, it will not convert to a solid VDB well."
    }
]
update_json('sop_errors.json', new_errors)

# ==========================================
# 4. SOP DECISION GUIDES (+5)
# ==========================================
new_decisions = [
    {
        "topic": "Vellum vs RBD vs FEM",
        "scenario": "You need to simulate physics.",
        "comparison": {
            "Vellum": "Position-based dynamics. Best for cloth, hair, strings, grains, and squishy soft bodies. Fast on GPU.",
            "RBD (Bullet)": "Rigid body dynamics. Best for breaking glass, crumbling concrete, rigid metal collisions. Does not bend.",
            "FEM": "Finite Element Method. Extremely slow, highly accurate. Used for hyper-realistic muscle/tissue simulations in creature FX."
        },
        "recommendation": "Use RBD for destruction. Use Vellum for almost everything else (cloth, squishy things). Ignore FEM unless doing advanced character FX."
    },
    {
        "topic": "VDB vs Polygon Modeling",
        "scenario": "You are building a complex procedural asset (like a cavern or a spaceship hull).",
        "comparison": {
            "VDB (Volumes)": "Pros: Never fails booleans, smooths intersections beautifully, completely procedural. Cons: High memory, loses sharp edges, destroys UVs.",
            "Polygon (Standard)": "Pros: Fast for simple shapes, keeps UVs, perfect sharp edges. Cons: Booleans fail easily, topology gets messy."
        },
        "recommendation": "Use Polygons for hard surface/mechanical assets where sharp edges and UVs matter. Use VDB for organic assets (rocks, terrain, fluid meshes) where topology just needs to be contiguous."
    },
    {
        "topic": "Pack vs Pack and Instance",
        "scenario": "You are duplicating an object thousands of times using Copy to Points.",
        "comparison": {
            "Pack": "Creates a packed primitive in memory. You still 'copy' that packed pointer. Good for standard scenes.",
            "Pack and Instance": "Tells the renderer (Mantra/Karma) to only load the geometry once and draw it X times dynamically. Viewport only shows points or bounding boxes."
        },
        "recommendation": "Always enable 'Pack and Instance' on the CopyToPoints SOP if you have more than 10,000 copies, or if the source geometry is extremely dense."
    },
    {
        "topic": "Point vs Primitive attributes for Shading",
        "scenario": "You want to assign a color (@Cd) to your geometry.",
        "comparison": {
            "Point Attributes": "Stored on the vertices. Creates a smooth gradient between points. (e.g. Red point next to Blue point creates a purple gradient face).",
            "Primitive Attributes": "Stored on the face. Gives the entire polygon one solid, flat color. No gradients."
        },
        "recommendation": "Use Point attributes for organic, smooth color blending. Use Primitive attributes for hard, low-poly, or distinct material assignments."
    },
    {
        "topic": "Heightfield vs Polygon Grid for Terrain",
        "scenario": "You need to build a mountain range.",
        "comparison": {
            "Heightfield (2D Volume)": "Incredibly fast. Includes dedicated erosion, terracing, and noise nodes. Used by game engines directly.",
            "Polygon Grid + Mountain": "Slow. Real 3D geometry. Can have overhangs and caves (Heightfields cannot)."
        },
        "recommendation": "Always use Heightfields for large-scale landscapes and terrain generation. Only convert to Polygons at the very end if needed for rendering or specific collisions."
    }
]
update_json('sop_decision_guides.json', new_decisions)

print("Massive dataset expansion complete.")