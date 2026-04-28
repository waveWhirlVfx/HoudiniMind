# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Built-in Houdini Knowledge Base
Injected into the RAG system at startup.

Format: list of dicts with keys:
  title     : short name
  category  : workflow | recipe | best_practice | errors | vex | nodes | sim | usd
  tags      : list of search keywords
  content   : the actual knowledge text
"""

HOUDINI_KNOWLEDGE = [

    # ══════════════════════════════════════════════════════════════════
    #  NODE TYPE STRINGS — The #1 source of agent failures
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Critical Node Type String Reference",
        "category": "nodes",
        "tags": ["node type", "create_node", "type string", "internal name"],
        "content": """
CRITICAL: UI label != internal type string. Always verify with verify_node_type() before create_node.

SOP NODES (inside geo nodes):
  Box             → box
  Sphere          → sphere
  Grid            → grid
  Tube            → tube
  Torus           → torus
  Line            → line
  Circle          → circle
  Platonic Solid  → platonic
  Curve           → curve
  Merge           → merge
  Switch          → switch
  Transform       → xform
  Copy to Points  → copytopoints
  Copy and Transform → copy
  Attribute Wrangle → attribwrangle
  Attribute Create → attribcreate
  Attribute Transfer → attribtransfer
  Attribute Promote → attribpromote
  Attribute Cast  → attribcast
  Delete          → delete
  Blast           → blast
  Group           → groupcreate  (NOT 'group')
  Group Promote   → grouppromote
  Group from Bounding Box → groupbbox
  Scatter         → scatter
  Resample        → resample
  Fuse            → fuse
  Clean           → clean
  Normal          → normal
  Smooth          → smooth
  Subdivide       → subdivide
  Remesh          → remesh
  Boolean         → boolean
  PolyBevel       → polybevel   (NOT polybevel2 — the '2' is the UI version label)
  PolyExtrude     → polyextrude (NOT polyextrude2)
  PolyFrame       → polyframe
  PolySplit       → polysplit
  PolyReduce      → polyreduce
  Divide          → divide
  Convert         → convert
  Carve           → carve
  Clip            → clip
  Measure         → measure
  Color           → color
  UV Project      → uvproject
  UV Unwrap       → uvunwrap
  UV Layout       → uvlayout
  UV Flatten      → uvflatten
  Voronoi Fracture → voronoifracture
  Voronoi Fracture Points → voronoifracturepoints
  Pack            → pack
  Unpack          → unpack
  Instance        → instance
  Point Deform    → pointdeform
  Lattice         → lattice
  Magnet          → magnet
  Bend            → bend
  Mountain        → mountain
  Noise (VOP)     → Use attribwrangle with VEX noise functions
  For-Each Begin  → block_begin
  For-Each End    → block_end
  Null            → null
  Output          → output
  Object Merge    → object_merge
  File Cache      → filecache
  File SOP        → file
  Point Generate  → add  (NOT 'pointgenerate')
  Add             → add
  Foreach         → block_begin / block_end pair
  Ray             → ray
  Trace           → trace
  Intersect       → intersect
  IsoOffset       → isooffset
  VDB from Polygons → vdbfrompolygons
  VDB from Particles → vdbfromparticles
  Convert VDB     → convertvdb
  VDB Smooth      → vdbsmooth
  VDB Reshape     → vdbresize
  VDB Combine     → vdbcombine

OBJ LEVEL NODES:
  Geometry        → geo
  DOP Network     → dopnet
  Camera          → cam
  Light           → hlight  (or envlight, arealight)
  Bone            → bone
  Muscle          → muscle
  Null            → null
  Subnet          → subnet

DOP NODES (inside DOP Network):
  RBD Object      → rbdobject
  RBD Packed Object → rbdpackedobject
  Static Object   → staticobject
  Ground Plane    → groundplane
  FLIP Object     → flipobject
  Pyro Object     → pyrosolver (pyro source is a SOP)
  Vellum Object   → vellumobject
  Vellum Solver   → vellumsolver
  Bullet Solver   → bulletrbdsolver
  RBD Solver      → rbdsolver
  FLIP Solver     → flipsolver
  Pyro Solver     → pyrosolver
  Gravity         → gravity
  Drag            → drag
  Wind            → fan  (NOT 'wind')
  Merge DOP       → merge

OUT / ROP NODES:
  Mantra          → ifd
  Karma           → karma
  OpenGL          → opengl
  Geometry ROP    → geometry
  Alembic ROP     → alembic
  USD Export      → usdexport
  Composite       → comp
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  VEX SNIPPETS
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "VEX — Common Attribute Wrangle Patterns",
        "category": "vex",
        "tags": ["vex", "wrangle", "attribwrangle", "attribute", "snippet", "code"],
        "content": """
All snippets go in an Attribute Wrangle SOP. Run over: Points (default).

RANDOM SCALE (pscale):
  @pscale = rand(@ptnum) * 0.5 + 0.5;

RANDOM COLOR:
  @Cd = set(rand(@ptnum), rand(@ptnum+1), rand(@ptnum+2));

RANDOM COLOR FROM PALETTE (3 colours):
  float r = rand(@ptnum);
  vector cols[] = {set(1,0,0), set(0,1,0), set(0,0,1)};
  @Cd = cols[int(r * 3) % 3];

NOISE-BASED DISPLACEMENT:
  vector pos = @P * chf("freq");
  @P += set(0, noise(pos) * chf("amp"), 0);

CURL NOISE VELOCITY:
  vector vel = curlnoise(@P * chf("freq") + @Time * chf("speed"));
  @v = vel * chf("strength");

DISTANCE TO CENTRE GRADIENT:
  float d = length(@P);
  @Cd = set(d, 0, 1-d);

DELETE POINTS BELOW Y=0:
  if (@P.y < 0) removepoint(0, @ptnum);

DELETE BY GROUP:
  if (inpointgroup(0, "mygroup", @ptnum)) removepoint(0, @ptnum);

SET POSITION ON CURVE (t along length):
  float t = float(@ptnum) / (npoints(0) - 1);
  @P = primuv(1, "P", 0, t);   // second input is the curve

COPY ATTRIBUTE FROM SECOND INPUT:
  int nearpt = nearpoint(1, @P);
  @Cd = point(1, "Cd", nearpt);

ROTATE POINTS AROUND Y AXIS:
  float angle = radians(chf("deg"));
  matrix3 m = ident();
  rotate(m, angle, {0,1,0});
  @P *= m;

SCATTER ON SURFACE (inside attribwrangle on prims):
  // Run over Primitives
  int pt = addpoint(0, primuv(0, "P", @primnum, set(rand(@primnum), rand(@primnum+7), 0)));
  setpointattrib(0, "N", pt, prim_normal(0, @primnum, {0,0,0}));

VORONOI / CELL NOISE:
  vector cell;
  float f1 = wnoise(@P * chf("freq"), 0, cell);
  @Cd = set(cell);

SMOOTH STEP REMAP:
  float t = fit(@Cd.r, 0, 1, 0, 1);
  t = smoothstep(0, 1, t);
  @Cd = set(t, t, t);

MAKE UV ATTRIBUTE FROM POSITION:
  @uv = set(fit(@P.x, -1, 1, 0, 1),
            fit(@P.y, -1, 1, 0, 1), 0);

POINT CLOUD LOOKUP:
  int handle = pcopen(1, "P", @P, chf("radius"), chi("maxpts"));
  while (pciterate(handle)) {
      int nearpt;
      pcimport(handle, "point.number", nearpt);
      @Cd += point(1, "Cd", nearpt);
  }
  pcclose(handle);
"""
    },

    {
        "title": "VEX — Common Functions Reference",
        "category": "vex",
        "tags": ["vex", "functions", "built-in", "reference", "sin", "cos", "noise", "rand"],
        "content": """
MATH:
  abs(x)          clamp(x, min, max)    fit(x, srcmin, srcmax, dstmin, dstmax)
  fit01(x, a, b)  smooth(a, b, x)       smoothstep(a, b, x)
  lerp(a, b, t)   pow(base, exp)        sqrt(x)   log(x)   exp(x)
  floor(x)        ceil(x)               round(x)  frac(x)  sign(x)
  min(a,b)        max(a,b)              mod(a,b)

TRIG:
  sin(x)  cos(x)  tan(x)  asin(x)  acos(x)  atan2(y,x)  radians(deg)  degrees(rad)

VECTOR:
  length(v)          normalize(v)          dot(a,b)          cross(a,b)
  distance(a,b)      set(x,y,z)            getcomp(v,i)      setcomp(v,i,val)
  ptransform(v,m)    vdot(a,b)

NOISE:
  noise(pos)         — Perlin noise, returns float
  vnoise(pos)        — Perlin noise, returns vector
  wnoise(pos,0,cell) — Worley / cellular noise, returns float, fills cell vec
  curlnoise(pos)     — Curl noise (divergence-free), returns vector
  onoise(pos)        — Original Perlin
  snoise(pos)        — Signed noise [-1,1]

RANDOM:
  rand(seed)         — float [0,1]
  random(seed)       — same as rand
  nrandom(seed)      — normal distribution

GEOMETRY READ:
  npoints(input)          nprims(input)           nvtx(input)
  point(input, attr, ptnum)  prim(input, attr, primnum)  vertex(input, attr, vtxnum)
  nearpoint(input, P)     nearpoints(input, P, maxdist, maxpts)
  primuv(input, attr, primnum, uvw)
  prim_normal(input, primnum, uvw)
  getbbox(input, min, max)

GEOMETRY WRITE:
  addpoint(geo, pos)      addprim(geo, type, pt0, pt1...)
  removepoint(geo, ptnum)  removeprim(geo, primnum, andpts)
  setpointattrib(geo, attr, ptnum, val)
  setprimattrib(geo, attr, primnum, val)
  setvertexattrib(geo, attr, linear_vtx, val)

ATTRIBUTE:
  hasattrib(input, class, attr)   attribsize(input, class, attr)
  inpointgroup(input, grp, ptnum) inprimgroup(input, grp, primnum)

STRING:
  sprintf(fmt, ...)    itoa(i)    atoi(s)    atof(s)
  strlen(s)            substr(s, start, len)
  re_match(pattern, s)

MATRIX:
  ident()              rotate(m, angle, axis)    scale(m, sv)
  translate(m, tv)     invert(m)                 transpose(m)
  dihedral(a, b)       maketransform(...)
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  SIMULATION RECIPES
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "FLIP Fluid Simulation — Full Setup Recipe",
        "category": "recipe",
        "tags": ["flip", "fluid", "water", "liquid", "simulation", "flipsolver", "recipe"],
        "content": """
FLIP fluid full setup in Houdini:

1. CREATE SOURCE GEOMETRY
   - Create geo node /obj/fluid_source
   - Inside: box or sphere SOP as fluid container area
   - Add VDB from Polygons SOP → converts to VDB
   - Or use ParticleFluids shelf tool (faster)

2. CREATE DOP NETWORK
   - At /obj level: create dopnet node
   - Go inside dopnet

3. INSIDE DOP NETWORK
   a. FLIP Object node (type: flipobject)
      - SOP Path: point to /obj/fluid_source/vdbfrompolygons1
      - Particle Separation: 0.05–0.1 (smaller = more detail, slower)
      - Initial Velocity: set if needed

   b. FLIP Solver node (type: flipsolver)
      - Connect FLIP Object output → FLIP Solver input
      - Substeps: 2–4 for fast motion
      - Enable Viscosity if needed
      - Surface Tension: 0.01–0.05 for water

   c. Static Object (type: staticobject) for collision geometry
      - SOP Path: point to your collision mesh
      - Check "Invert Sign" if geometry is inside-out

   d. Merge DOP → merge FLIP Solver + Static Object outputs

   e. Ground Plane DOP (type: groundplane) for infinite ground

4. SURFACE THE PARTICLES (back in /obj)
   - Create new geo node /obj/fluid_surface
   - Inside: DOP Import Fields or Particle Fluid Surface SOP
   - Connect to dopnet, surface using VDB Smooth + Convert VDB

5. COMMON ISSUES
   - "Missing gridscale attribute": FLIP Object particle separation too large
   - Sim exploding: reduce substeps, lower surface tension, check colliders
   - Particles leaking: increase collision padding on Static Object
   - Slow bake: reduce particle separation or use FLIP Sparse solver

KEY PARAMETERS:
  Particle Separation: /obj/dopnet/flipobject1  parm: particlesep
  Substeps:            /obj/dopnet/flipsolver1  parm: substeps
  Surface Tension:     /obj/dopnet/flipsolver1  parm: surfacetension
  Viscosity:           /obj/dopnet/flipsolver1  parm: viscosity
"""
    },

    {
        "title": "Pyro Simulation — Smoke and Fire Recipe",
        "category": "recipe",
        "tags": ["pyro", "smoke", "fire", "combustion", "pyrosolver", "simulation", "recipe"],
        "content": """
PYRO full setup (Houdini 19+):

PREFERRED HOUDINI 21 SOP-LEVEL WORKFLOW:
   Use a geo/SOP chain, not a DOP network, for ordinary agent-created Pyro FX:
   emitter geometry -> source points -> attribwrangle setting v/temperature/density/fuel
   -> pyrosource -> pyrosolver -> pyropostprocess -> null OUT.
   The setup_pyro_sim tool creates this SOP-level chain and returns mode="sop".
   Source rule before pyrosource:
   - Mesh/polygon emitter: use Scatter SOP first.
   - Volume/VDB emitter: use Points From Volume SOP first.
   - Existing point emitter: keep the points if desired.
   Always guarantee density and temperature attributes before pyrosource.

1. CREATE SOURCE
   - Geometry node with a sphere or any emitter shape
   - Add Pyro Source SOP (shelf: Pyro > Source)
   - Or manually: attribute wrangle to set "temperature", "fuel" attributes

2. SOP PYRO NETWORK
   a. Convert source to points: scatter for mesh, pointsfromvolume for volume, keep points for point source
   b. Add/verify v, temperature, density, and fuel attributes on those points
   c. Use Pyro Source SOP (type: pyrosource)
   d. Use Pyro Solver SOP (type: pyrosolver) wired directly after pyrosource
   e. Use Pyro Post Process SOP (type: pyropostprocess) after the solver
   f. End with a display/render Null such as pyro_out
   g. Voxel size: 0.025-0.05 for tests; coarser values are faster

4. PYRO SOLVER KEY SETTINGS:
   - Combustion > Enable Combustion: for fire
   - Temperature > Buoyancy: controls how fast smoke rises
   - Dissipation: how quickly smoke disappears
   - Turbulence > Scale: adds noise/detail
   - Wind: apply constant velocity to drift smoke

5. PYRO SOURCE ATTRIBUTES:
   - temperature: controls fire/heat  (use 1.0 for strong fire)
   - fuel:        combustible material (0–1)
   - density:     smoke density override
   - vel:         initial emission velocity

6. RENDERING PYRO:
   - Add Volume (Mantra) or Karma Volume shader
   - Density channel: density
   - Emission channels: temperature or Cd

7. COMMON ISSUES:
   - Sim too thin/wispy: increase Division Size, add turbulence
   - Fire doesn't show: check combustion enabled, temperature > 0
   - Smoke disappears too fast: reduce Dissipation value
   - Too slow: increase Division Size (coarser voxels), reduce container

KEY PARAMETER PATHS:
  Solver:       /obj/geo1/pyrosolver1
  Output:       /obj/geo1/pyro_out
  Legacy DOP:   only use /obj/dopnet paths when repairing an existing DOP scene
"""
    },

    {
        "title": "RBD Destruction — Voronoi Fracture + Bullet Recipe",
        "category": "recipe",
        "tags": ["rbd", "fracture", "voronoi", "destruction", "bullet", "rigid body", "recipe", "shatter"],
        "content": """
RBD Destruction full setup:

1. PREPARE GEOMETRY (SOP level inside geo node)
   a. Start with your object geometry
   b. Add Voronoi Fracture SOP (type: voronoifracture)
      - Scatter points inside the mesh first (Scatter SOP)
      - Plug: geometry → input 0, scattered points → input 1
      - Interior Detail: add inside surface detail
   c. Add Pack SOP (type: pack) — pack each fragment as a primitive
   d. (Optional) Assemble SOP for better constraint connectivity

2. DOP NETWORK SETUP
   a. RBD Packed Object (type: rbdpackedobject)
      - SOP Path: your packed geometry
      - Active: 1 for moving pieces, 0 for static initial state
   b. Bullet Solver (type: bulletrbdsolver) — faster than RBD Solver for many pieces
      - Substeps: 2–5 for fast collisions
   c. Static Object (type: staticobject) for floor/colliders
   d. Gravity (type: gravity) — default -9.8 Y
   e. Merge DOP to combine all

3. CONSTRAINT NETWORK (Glue)
   - Add Constraint Network DOP
   - Create constraint geometry: use SOP Solver to build glue constraints
   - Connect to rbdpackedobject
   - Glue strength: set per-constraint "strength" attribute

4. TRIGGER ACTIVATION
   - Use SOP Solver inside DOP to switch pieces from inactive to active
   - Or use Impact data from collision to trigger breakage

5. COMMON ISSUES:
   - Pieces tunnelling through each other: increase substeps
   - Too slow: reduce fragment count, use convex hull collision shapes
   - Pieces don't break: increase impact force, reduce glue strength
   - Floating pieces: check initial overlap detection

KEY PARMS:
  Fragment count:   scatter1/npts (how many Voronoi pieces)
  Glue strength:    constraint_network/strength
  Substeps:         bulletrbdsolver/substeps
  Bounce:           rbdpackedobject/bounce
  Friction:         rbdpackedobject/friction
"""
    },

    {
        "title": "Vellum Simulation — Cloth, Hair, Soft Body Recipe",
        "category": "recipe",
        "tags": ["vellum", "cloth", "hair", "soft body", "simulation", "constraint", "recipe"],
        "content": """
Vellum simulation types and setup:

1. CLOTH SETUP
   a. Grid SOP (medium resolution, e.g. 20x20)
   b. Vellum Configure Cloth SOP (type: vellumconstraints, preset: cloth)
      - Bend Stiffness: 0.01–1.0 (lower = more floppy)
      - Stretch Stiffness: 1.0 (1 = inextensible)
   c. Vellum Solver SOP (type: vellumsolver)
      - Substeps: 5–20 for stable cloth
      - Gravity: -9.8 default

2. HAIR / STRANDS SETUP
   a. Curve SOP or use curve_groom
   b. Vellum Configure Hair (type: vellumconstraints, preset: hair)
      - Stretch Stiffness: high (>10000) for stiff hair
      - Bend Stiffness: controls curliness

3. SOFT BODY
   a. Any mesh geometry
   b. Vellum Configure Tetrahedral Softbody
      - Tet-based (slower but accurate volume preservation)
      - Or use distance constraints for faster stretch

4. PINNING / CONSTRAINTS
   - Group points to pin (e.g. top edge = "pin_group")
   - In Vellum Configure: set Pin to Animation on that group
   - Or use Vellum Attach Constraints SOP for dynamic pinning

5. COLLISION OBJECTS
   - Add Vellum Configure Collider SOP to collision mesh
   - Include in same Vellum Solver as cloth

6. COMMON ISSUES:
   - Cloth explodes: reduce substeps, check self-collision thickness
   - Too stiff/slow: reduce constraint iterations, increase substeps
   - Pinned points drift: enable "Stiff" on pin constraints
   - Hair won't collide: enable hair-cloth collision in solver

KEY PARMS:
  Substeps:           vellumsolver/substeps  (default 5, use 10–20 for cloth)
  Bend stiffness:     vellumconstraints/bendstiffness
  Stretch stiffness:  vellumconstraints/stretchstiffness
  Gravity:            vellumsolver/gravity
  Thickness:          vellumsolver/thickness  (self-collision distance)
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  COMMON WORKFLOWS
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Copy to Points — Scatter Objects on Surface",
        "category": "workflow",
        "tags": ["copy to points", "copytopoints", "scatter", "instancing", "workflow"],
        "content": """
Standard Copy to Points workflow for scattering objects on a surface:

NETWORK SETUP:
  Input 0 → Copy to Points → Output
  Input 1 ↗

Input 0: the template geometry (what gets copied — e.g. tree, rock, blade of grass)
Input 1: the points to copy onto (from Scatter SOP on your surface)

STEP BY STEP:
1. Create your surface geometry (Grid, Terrain, etc.)
2. Add Scatter SOP → generates random points on surface
   - Relax Iterations: 5–10 for more even distribution
   - Force Total Count: set exact point count
3. Add Attribute Wrangle (run over Points of Scatter output):
   @pscale = rand(@ptnum) * 0.5 + 0.8;  // random scale
   @orient = quaternion(radians(rand(@ptnum)*360), {0,1,0});  // random Y rotation
4. Create template geometry in separate branch (e.g. tree geo node)
5. Connect: scatter output → CopyToPoints input 1
            template geo → CopyToPoints input 0
6. CopyToPoints settings:
   - Transform using Point Orientations: ON (uses @orient attribute)
   - Pack and Instance: ON for large counts (uses hardware instancing)

INSTANCING vs COPY:
  Pack and Instance = ON  : GPU instancing, fast, but geometry is identical
  Pack and Instance = OFF : Full geometry copies, slow for large counts, but each can differ

VARYING GEOMETRY:
  - Use For-Each loop or Copy SOP with multiple geometry inputs
  - Add "variant" integer attribute on points, use it to pick geometry branch
"""
    },

    {
        "title": "Procedural Modelling Best Practices",
        "category": "best_practice",
        "tags": ["procedural", "best practice", "workflow", "modelling", "params", "hda"],
        "content": """
CORE PRINCIPLES:
1. Never manually place objects — always use Copy to Points, For-Each, or procedural math
2. Use channel references (ch("parmname")) instead of hardcoded values
3. Group geometry early, reference groups later — never blast by position
4. Lock network topology; change only parameters
5. Work non-destructively: use layers of transforms, not Edit SOP permanent edits

NODE NETWORK ORGANISATION:
- Colour-code by function: Orange=input, Green=deform, Blue=procedural, Red=debug
- Use Null nodes as named outputs: OUT_geo, OUT_collision, OUT_render
- Comment key nodes with what they do
- Group related nodes in network boxes with labels
- Layout network regularly (L key or layout_network tool)

PARAMETER MANAGEMENT:
- Expose important params to OBJ level with Promote Parameter
- Use expression references: ch("../control_null/freq")
- Create a Control Null object at /obj with all scene-level sliders
- Use Take system for shot-specific overrides

PERFORMANCE:
- Freeze time-independent sops with File Cache (type: filecache)
- Pack heavy geometry before copying (Pack SOP first)
- Use VDB for volumes instead of polygonal meshes
- Profile with profile_network before optimising
- Avoid Fuse + Clean on every frame — do it once, cache it

HDA BEST PRACTICES:
- One HDA = one reusable function
- Expose only artist-facing parameters
- Add sensible defaults and parameter ranges
- Write help text for every parameter
- Version bump on breaking changes
"""
    },

    {
        "title": "For-Each Loop — Building Repetitive Structures",
        "category": "workflow",
        "tags": ["for-each", "loop", "block_begin", "block_end", "repetitive", "workflow"],
        "content": """
For-Each loop in Houdini SOPs:

BASIC STRUCTURE:
  For-Each Begin (type: block_begin)  ← defines loop variable
       ↓  (your SOP operations here)
  For-Each End (type: block_end)      ← merges results

LOOP TYPES (set on block_begin):
  Primitives   — iterates over each primitive separately
  Points       — iterates over each point separately
  Pieces       — iterates by "piece" attribute value
  Metadata     — loop N times without geometry
  Feedback     — output of each iteration becomes next iteration's input

PROCEDURAL STAIRS EXAMPLE (Feedback mode):
  1. block_begin: Method = Fetch Feedback, Max Iterations = 10
  2. attribwrangle (run over Detail):
     int n = detail(0, "iteration");
     // step dimensions from channel refs
     float step_w = chf("width");
     float step_h = chf("height");
     float step_d = chf("depth");
  3. box SOP: size = (step_w, step_h, step_d)
     tx = 0, ty = n*step_h, tz = n*step_d
  4. Merge SOP: merge box + block_begin output
  5. block_end: Feedback Each Iteration = ON

FENCE EXAMPLE (Pieces mode):
  1. Curve SOP: draw fence path
  2. Resample SOP: evenly space posts
  3. block_begin: Method = Primitives (or Points)
  4. Single fence post geometry
  5. Transform: use point position from iteration
  6. block_end: Merge all posts

ACCESSING ITERATION INFO:
  int n = detail(0, "iteration");       // current iteration number (0-based)
  int total = detail(0, "numiterations"); // total iterations

IMPORTANT: Always use Create Feedback = ON if modifying geometry across iterations.
Use Compile Block Begin/End SOP pair for performance-critical loops.
"""
    },

    {
        "title": "VDB Workflow — Volumes and Level Sets",
        "category": "workflow",
        "tags": ["vdb", "volume", "level set", "isooffset", "vdbfrompolygons", "sdf"],
        "content": """
VDB workflow for volumes and level sets:

CREATING VDB:
  Polygon mesh → VDB from Polygons (type: vdbfrompolygons)
    - Surface Width: 3–5 voxels
    - Voxel Size: 0.01–0.1 (smaller = more detail, more memory)
    - Output: signed distance field (SDF) + fog volume (density)

  Particles → VDB from Particles (type: vdbfromparticles)
    - Particle Radius Scale: 1.5–3.0
    - Min Radius: 1.0

  Explicit volume: Volume SOP or procedural VEX noise

COMMON VDB OPERATIONS:
  VDB Smooth (type: vdbsmooth)       — smooth/blur the VDB
  VDB Combine (type: vdbcombine)     — union/intersect/subtract two VDBs
  VDB Reshape (type: vdbresize)      — dilate/erode/close/open
  Convert VDB (type: convertvdb)     — VDB → polygons (for rendering/collision)
  VDB Morph (type: vdbmorph)         — blend between two VDB shapes

POLYGON MESHING (VDB → surface):
  Convert VDB SOP:
    - Convert: to Polygons
    - Adaptivity: 0 = uniform, 1 = adaptive (fewer polys, good for collision)
    - Smoothing: ON for clean surface

BOOLEAN OPERATIONS (VDB method — cleaner than polygon boolean):
  1. VDB from Polygons on mesh A → sdf_A
  2. VDB from Polygons on mesh B → sdf_B
  3. VDB Combine:
     - SDF Union     → min(A, B)
     - SDF Intersect → max(A, B)
     - SDF Subtract  → max(A, -B)

VOLUME RENDERING:
  - Fog volume (density channel): direct volume rendering
  - SDF: convert to mesh first, or use VDB Volume shader
  - In Karma/Mantra: assign Volume shader, set density/heat channels

PERFORMANCE TIPS:
  - Keep voxel count under 50M for interactive work
  - Use VDB Activate to limit computation region
  - Cache VDB sequences to disk with File Cache SOP
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  COMMON ERRORS AND FIXES
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Common Houdini Errors and Fixes",
        "category": "errors",
        "tags": ["error", "warning", "fix", "debug", "troubleshoot", "broken"],
        "content": """
ERROR: "Invalid node type"
FIX: The internal type string is wrong. Call verify_node_type() or list_node_types().
     Common traps: 'polybevel2'→'polybevel', 'polyextrude2'→'polyextrude', 'group'→'groupcreate'

ERROR: "Parameter not found" / "No such parameter"
FIX: Use safe_set_parameter() — it returns the full parameter list when the name is wrong.
     Call get_node_parameters() to see all valid parm names.

ERROR: "Unable to find point X" / "Points are missing"
FIX: Point numbers changed upstream. Use attribute-based selection (groups) instead of point numbers.

ERROR: "Cook failed" on VDB from Polygons
FIX: Input mesh has holes, non-manifold edges, or inverted normals.
     Fix: add Clean SOP before VDB from Polygons.
     Enable Watertight option if mesh has holes.

ERROR: FLIP sim "missing gridscale attribute"
FIX: FLIP Object particle separation is too large relative to container.
     Reduce particlesep or enlarge the container geometry.
     Alternatively check SOP path is pointing to valid VDB geometry.

ERROR: "Vellum constraint not found"
FIX: Vellum Configure SOP must be connected BEFORE the Vellum Solver.
     Ensure the "rest" geometry has matching point count.

ERROR: RBD pieces "sleeping" or not activating
FIX: Check Active value on RBD Packed Object = 1 (or use SOP Solver to activate per-piece).
     Ensure objects overlap or have initial velocity.

ERROR: Pyro sim not showing fire/smoke
FIX: Check DOP node SOP path is correct. Verify temperature/fuel attributes exist on source.
     In viewport: View > Display > Smoke (D key shortcut to see volumes).

ERROR: "Cannot find SOP /obj/geo1/..."
FIX: Node path is wrong. Use get_scene_summary to verify actual node paths. Never guess names.

ERROR: Render black / nothing visible
FIX: Check display/render flags on the geometry. Check camera path in ROP. Check light exists.
     In Karma: check Scene Import settings.

WARNING: "Geometry is time-dependent"
CAUSE: Geometry changes every frame (normal for animated/sim output).
FIX: If static geo is flagged, check for Time expression in parameters.

WARNING: Large memory usage
FIX: Pack geometry before copying. Use VDB instead of polygons for volumes.
     Cache sims to disk with File Cache SOP.

ERROR: Constraint "out of range" or particles leaking through collider
FIX: Increase collision substeps. Enable Continuous Collision Detection (CCD).
     Reduce particle radius or increase padding on Static Object.
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  MATERIALS AND SHADING
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Material Workflow — Principled Shader and MaterialX",
        "category": "workflow",
        "tags": ["material", "shader", "principledshader", "materialx", "karma", "mantra", "pbr"],
        "content": """
CREATING MATERIALS:

Houdini 19.5+ (Solaris/MaterialX preferred):
  1. Go to /mat or use Material Library LOP in Solaris
  2. Create Principled Shader (type: principledshader)
     OR
  3. Create MaterialX Standard Surface for Karma

Principled Shader (works in both Mantra and Karma):
  Key parameters:
    Base Color (basecolor):     diffuse color, RGB
    Roughness (rough):          0=mirror, 1=fully rough
    Metallic (metallic):        0=dielectric, 1=metal
    IOR (ior):                  1.5 for glass/plastic, 1.0 for air
    Opacity (opac):             transparency (set to < 1 for glass)
    Coat (coat):                clearcoat amount
    Emission (emit):            self-illumination
    Normal Map (baseBumpAndNormal_enable): for bump/normal mapping

ASSIGNING MATERIALS:
  SOP level: Material SOP (type: material)
    - Set shop_materialpath parameter to /mat/your_material
  OBJ level: Material parameter on the Geo node
  Solaris: Assign Material LOP

TEXTURE MAPS:
  1. In shader network editor at /mat
  2. Create Texture VOP (type: texture) or file node
  3. Connect to appropriate input of Principled Shader
  4. Typical map connections:
     - Diffuse texture → basecolor input
     - Roughness map  → rough input (use monotexture)
     - Normal map     → use Normal Map VOP between file and shader
     - Displacement   → use Displace Along Normal VOP

MATERIALX (Karma-native, Houdini 19+):
  Use Standard Surface mtlx node for best Karma results.
  Build in /stage or /mat using LOPs.
  Supports full USD-native workflow.

COMMON MATERIALS:
  Glass:   rough=0, metallic=0, ior=1.5, opac=0.0, coat=1.0
  Metal:   rough=0.2, metallic=1.0, ior=2.5
  Plastic: rough=0.4, metallic=0, ior=1.5
  Skin:    rough=0.6, metallic=0, subsurface=0.3
  Emissive: emit=1.0, emitcolor=(r,g,b)
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  USD / SOLARIS
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Solaris / USD Workflow Basics",
        "category": "usd",
        "tags": ["usd", "solaris", "lop", "stage", "karma", "render", "prims"],
        "content": """
SOLARIS OVERVIEW:
  Solaris = Houdini's USD-native context.
  Lives at /stage (LOP network).
  Outputs to Karma renderer or exports USD files.

KEY LOP NODES:
  Scene Import (type: sceneimport)    → brings /obj geometry into USD stage
  Merge (type: merge)                 → combine multiple USD streams
  Material Library (type: materiallibrary) → create/store materials
  Assign Material (type: assignmaterial)   → assign material to prims
  Camera (type: camera)               → USD camera
  Light (type: light)                 → USD lights (dome, rect, sphere, disk)
  Environment Light (type: envlight)  → HDRI dome light
  USD Render ROP (type: karma)        → render with Karma
  USD Export (type: usdexport)        → write USD to disk

SCENE IMPORT (bringing SOP geo into Solaris):
  1. Scene Import LOP: automatically imports /obj hierarchy
  2. SOP Import LOP: import a specific SOP path as a USD prim
     - SOP Path: /obj/geo1/OUT_render (point to Null output)
     - Prim Path: /World/geo1

MATERIAL ASSIGNMENT IN SOLARIS:
  1. Material Library LOP: create material subnet
  2. Assign Material LOP:
     - Primitives Pattern: /World/geo1 (path to geo prim)
     - Material Path: /materials/my_shader

KARMA RENDER SETUP:
  1. Camera LOP: set focal length, aperture, DOF
  2. Dome Light LOP: set HDRI map
  3. Karma CPU or XPU ROP LOP
     - Resolution: 1920x1080
     - Samples per pixel: 256+
     - Denoising: ON for speed

USD PRIM HIERARCHY:
  /World          ← top-level default prim
  /World/geo1     ← imported geometry
  /World/lights   ← light collection
  /materials      ← material library
  /cameras        ← camera collection

COMMON ISSUES:
  - Geo not appearing: check Scene Import node, check prim visibility
  - Materials not showing: check Assign Material prim pattern is correct
  - Karma crash: update GPU drivers, switch to CPU mode
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  HOUDINI-SPECIFIC PARAMETER NAMES
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Common SOP Parameter Names Reference",
        "category": "nodes",
        "tags": ["parameters", "parms", "names", "reference", "safe_set_parameter"],
        "content": """
BOX SOP (type: box):
  sizex, sizey, sizez   — dimensions
  tx, ty, tz            — position
  rx, ry, rz            — rotation (degrees)
  divx, divy, divz      — divisions per axis
  center                — toggle (0=corner at origin, 1=centered)

SPHERE SOP (type: sphere):
  radx, rady, radz      — radius per axis
  tx, ty, tz            — center position
  rows, cols            — polygon divisions
  type                  — 0=polygon, 1=NURBS, 2=mesh, 5=primitive

GRID SOP (type: grid):
  sizex, sizez          — grid dimensions
  rows, cols            — divisions
  tx, ty, tz            — position

TUBE SOP (type: tube):
  rad1                  — bottom radius (NOT 'radx', NOT 'radius')
  rad2                  — top radius (NOT 'rady'; set to 0 for a cone)
  height                — height along the axis
  rows, cols            — polygon divisions
  cap                   — cap ends (0=open, 1=closed)
  tx, ty, tz            — position
  orient                — axis orientation (0=X, 1=Y, 2=Z)
  ⚠ COMMON MISTAKE: LLMs often use 'radx'/'rady' — these DO NOT EXIST.
    The correct names are 'rad1' (bottom) and 'rad2' (top).

SCATTER SOP (type: scatter):
  npts                  — point count
  relaxtype             — 0=none, 1=element size, 2=element count
  relaxiters            — relaxation iterations
  seed                  — random seed

COPY TO POINTS SOP (type: copytopoints):
  pack                  — pack and instance (0=full copy, 1=packed)
  viewportlod           — viewport display
  useattributes         — use @orient, @scale, @pscale

TRANSFORM SOP (type: xform):
  tx, ty, tz            — translate
  rx, ry, rz            — rotate (degrees)
  sx, sy, sz            — scale
  px, py, pz            — pivot point

ATTRIBUTE WRANGLE (type: attribwrangle):
  snippet               — VEX code string
  class                 — 0=points, 1=vertices, 2=prims, 3=detail
  group                 — optional group to process

VORONOI FRACTURE (type: voronoifracture):
  usepts                — 1=use second input points
  innerdensity          — interior surface detail
  inradius              — interior surface roughness

FILE CACHE (type: filecache):
  file                  — output path, use $F4 for frame padding
  loadfromdisk          — 0=write, 1=read, 2=auto
  trange                — time range mode

CAMERA (type: cam, at /obj level):
  focal                 — focal length (mm)
  aperture              — film aperture width (mm)
  resx, resy            — resolution
  near, far             — clipping planes
  fstop                 — f-stop for DOF
  focus                 — focus distance

NULL SOP / OBJ:
  Any parameter set with set_parameter works as a control slider.
  Useful for building control interfaces.

MATERIAL SOP (type: material):
  shop_materialpath     — path to shader, e.g. /mat/principledshader1

OBJ-LEVEL GEOMETRY NODE:
  shop_materialpath     — material assignment at object level
  vm_rendervisibility   — render visibility flag
  tdisplay              — custom display colour (r/g/b parms)
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  PERFORMANCE AND CACHING
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Performance Optimisation and Caching",
        "category": "best_practice",
        "tags": ["performance", "optimise", "cache", "slow", "cook time", "speed", "filecache"],
        "content": """
PROFILING:
  1. Call profile_network(parent_path) to find slowest nodes
  2. Call measure_cook_time(node_path) for a specific node
  3. In Houdini: Alt+Shift+T to see cook times in network editor
  4. Look for red/orange clock icons on nodes

CACHING WITH FILE CACHE SOP:
  - Place after expensive operations (sim output, VDB, heavy deformation)
  - Set file path: $HIP/cache/$OS.$F4.bgeo.sc  (bgeo.sc = compressed)
  - Load from Disk = Write first frame, then set to Read
  - Use bgeo.sc (compressed) not bgeo for smaller files

INSTANCING (Large Object Counts):
  - Use Pack SOP before Copy to Points
  - Enable "Pack and Instance" on Copy to Points SOP
  - For 10,000+ instances this is MANDATORY for viewport performance
  - At render time, Mantra/Karma will use procedural instancing

GEOMETRY REDUCTION:
  - Use Poly Reduce SOP for render-time geo (reduce by 50–90% is often fine)
  - Use Divide SOP with "Remove Shared Edges" for triangle soup cleanup
  - Use Convert VDB → Convert VDB for adaptive meshing from volumes

VDB PERFORMANCE:
  - Activate VDB region: VDB Activate SOP limits computation to live voxels
  - Background value: background should be max distance for SDF
  - Clip VDB to bounding box: reduces memory footprint

SIMULATION CACHING:
  - Never re-simulate if you can cache to disk
  - For FLIP: File Cache SOP after DOP Import
  - Use bgeo.sc or vdb for volume data
  - Checkpoint caching: enable in DOP solver to resume from mid-sim

VIEWPORT OPTIMIZATION:
  - Set display flag on a Null OUT node, not on intermediate SOPs
  - Use LOD (Level of Detail) display in viewport settings
  - Hide non-essential geometry in template display mode
  - Use Packed Primitives — they display as bounding boxes in viewport

PYTHON / TOOL SPEED:
  - Use hou.setUpdateMode(hou.updateMode.Manual) during batch operations
  - Batch parameter sets with batch_set_parameters() (one cook vs many)
  - Use create_node_chain() instead of individual create_node calls
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  ANIMATION
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Animation and Keyframing",
        "category": "workflow",
        "tags": ["animation", "keyframe", "channel", "expression", "chop", "timeline"],
        "content": """
KEYFRAMING VIA PYTHON:
  # Using set_keyframe tool:
  set_keyframe(node_path="/obj/geo1/xform1", parm_name="tx", value=0.0, frame=1)
  set_keyframe(node_path="/obj/geo1/xform1", parm_name="tx", value=10.0, frame=24)

EXPRESSION LANGUAGE:
  $F        — current frame number
  $T        — current time in seconds
  $FPS      — frames per second
  $FSTART   — start frame
  $FEND     — end frame
  $SF       — simulation frame (for DOPs)

COMMON EXPRESSIONS:
  sin($F * 0.1) * 5          — oscillate position
  fit($F, 1, 24, 0, 1)       — ramp from 0 to 1 over 24 frames
  ch("../null1/speed") * $T  — drive by another node's parameter
  if($F < 12, 0, 1)          — binary switch at frame 12

CHOP (Channel Operators) FOR ANIMATION:
  CHOPs process animation curves. Useful for:
    - Spring dynamics (lag, bounce)
    - Noise overlay on keyframes
    - Motion capture retargeting
    - Audio-driven animation

  Workflow:
  1. Go to /ch network (CHOP context)
  2. Channel CHOP: import existing parm channels
  3. Spring CHOP: add dynamic lag/bounce
  4. Export CHOP: write back to parameters
  
CONSTRAINTS (OBJ level):
  - Path Constraint: follow a curve
  - Look At Constraint: always face a target
  - Blend Constraint: interpolate between multiple targets
  Access via: Object's Parameters > Misc tab > Constraints

TIMELINE:
  set_frame_range(start=1, end=240, fps=24)
  go_to_frame(frame=100)
"""
    },

    # ══════════════════════════════════════════════════════════════════
    #  HOUDINI PYTHON API
    # ══════════════════════════════════════════════════════════════════
    {
        "title": "Houdini Python API — hou Module Essentials",
        "category": "workflow",
        "tags": ["python", "hou", "api", "scripting", "automation"],
        "content": """
ESSENTIAL hou.* CALLS:

NODE ACCESS:
  node = hou.node("/obj/geo1")         — get node by path
  children = node.children()           — list child nodes
  parent = node.parent()               — get parent node
  hou.selectedNodes()                  — currently selected nodes

NODE CREATION:
  new_node = parent.createNode("box", "mybox")   — create node
  new_node.setPosition(hou.Vector2(0, 0))         — set network position
  parent.layoutChildren()                          — auto-layout

PARAMETERS:
  parm = node.parm("tx")               — get parameter by name
  parm.set(5.0)                         — set value
  parm.setExpression("$T * 2")          — set expression
  parm.eval()                           — evaluate current value
  node.parmTuple("t").set((1, 2, 3))   — set vector parm

CONNECTIONS:
  node.setInput(0, other_node)          — connect: other_node → node input 0
  node.setInput(0, None)                — disconnect input 0
  node.inputs()                         — list input nodes
  node.outputs()                        — list output nodes

FLAGS:
  node.setDisplayFlag(True)
  node.setRenderFlag(True)
  node.setBypass(False)

GEOMETRY READING:
  geo = node.geometry()                    — get SOP geometry
  points = geo.points()                    — all points
  prims = geo.prims()                      — all primitives
  pt.attribValue("P")                      — get position
  pt.attribValue("Cd")                     — get color

HIP FILE:
  hou.hipFile.save()                       — save current file
  hou.hipFile.saveAs("/path/to/file.hip")
  hou.hipFile.load("/path/to/file.hip")
  hou.hipFile.path()                       — current file path

TIME:
  hou.frame()                              — current frame
  hou.setFrame(24)                         — set frame
  hou.fps()                                — current FPS
  hou.time()                               — current time (seconds)

MAIN THREAD SAFETY:
  ALWAYS use hdefereval for hou.* calls from background threads:
  import hdefereval
  result = hdefereval.executeInMainThreadWithResult(hou.node, "/obj/geo1")
  
  NEVER: threading.Thread(target=lambda: hou.node(...)).start()
  This causes crashes. No exceptions.
"""
    },

]


def get_all_entries() -> list:
    """Return all knowledge entries ready for kb_builder to ingest."""
    return HOUDINI_KNOWLEDGE
