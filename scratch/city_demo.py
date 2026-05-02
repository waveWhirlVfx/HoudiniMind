import hou


def build_city():
    try:
        hou.hipFile.clear(suppress_save_prompt=True)
        obj = hou.node("/obj")
        geo = obj.createNode("geo", "toy_city_on_hill")

        # 1. Terrain Branch
        grid = geo.createNode("grid", "terrain_base")
        grid.parm("rows").set(150)
        grid.parm("cols").set(150)
        grid.parm("sizex").set(50)
        grid.parm("sizey").set(50)

        hill_vex = geo.createNode("attribwrangle", "generate_hill")
        hill_vex.setInput(0, grid)
        hill_vex.parm("snippet").set("""
float dist = length(@P * {1,0,1});
float h = 15.0 * exp(-0.02 * dist * dist);
@P.y = h;
@P.y += noise(@P * 0.3) * 3.0;
""")

        # Compute Normals
        normals = geo.createNode("normal", "compute_normals")
        normals.setInput(0, hill_vex)
        normals.parm("type").set(0)  # Point normals

        # 2. Road Branch
        road_path = geo.createNode("line", "road_base")
        road_path.parm("points").set(200)
        road_path.parm("dist").set(30)

        road_shape = geo.createNode("attribwrangle", "spiral_shape")
        road_shape.setInput(0, road_path)
        road_shape.parm("snippet").set("""
float t = (float)@ptnum / (@numpt-1);
float angle = t * 6.0 * PI;
float r = 5.0 + t * 18.0;
@P.x = r * cos(angle);
@P.z = r * sin(angle);
@P.y = 30;
""")

        road_ray = geo.createNode("ray", "project_road")
        road_ray.setInput(0, road_shape)
        road_ray.setInput(1, normals)
        road_ray.parm("method").set(0)  # Project Rays
        road_ray.parm("dirmethod").set(1)  # Down (Vector)
        road_ray.parm("diry").set(-1)

        road_resample = geo.createNode("resample", "smooth_road")
        road_resample.setInput(0, road_ray)
        road_resample.parm("length").set(0.5)

        road_math = geo.createNode("attribwrangle", "road_math")
        road_math.setInput(0, road_resample)
        road_math.parm("snippet").set("""
vector tangent;
if (@ptnum < @numpt - 1)
    tangent = normalize(point(0, "P", @ptnum + 1) - @P);
else
    tangent = normalize(@P - point(0, "P", @ptnum - 1));

vector up = {0,1,0};
vector side = normalize(cross(up, tangent));
up = normalize(cross(tangent, side));
@orient = quaternion(maketransform(tangent, up));
""")

        # 3. Buildings Branch
        scatter = geo.createNode("scatter", "building_locations")
        scatter.setInput(0, normals)
        scatter.parm("npts").set(800)

        # Attribute Transfer from Road
        attr_transfer = geo.createNode("attribtransfer", "get_road_proximity")
        attr_transfer.setInput(0, scatter)
        attr_transfer.setInput(1, road_math)
        attr_transfer.parm("pointattriblist").set("P")
        attr_transfer.parm("thresholddist").set(2.0)

        building_logic = geo.createNode("attribwrangle", "urban_planning")
        building_logic.setInput(0, attr_transfer)
        building_logic.setInput(1, road_math)
        building_logic.parm("snippet").set("""
int near_pts[] = pcfind(1, "P", @P, 5.0, 1);
if (len(near_pts) > 0) {
    vector road_pos = point(1, "P", near_pts[0]);
    float dist = distance(@P, road_pos);
    if (dist < 2.0) removepoint(0, @ptnum);
    else {
        float slope = 1.0 - abs(dot(@N, {0,1,0}));
        if (slope > 0.4) removepoint(0, @ptnum);
        else {
            @pscale = fit(dist, 2.0, 8.0, 0.4, 2.0) * rand(@ptnum);
            @height = fit(@P.y, 0, 15, 1.0, 8.0) * (1.0 - slope);
            
            vector up = {0,1,0};
            vector forward = normalize(cross(up, @N));
            up = normalize(cross(forward, @N));
            @orient = quaternion(maketransform(forward, up));
        }
    }
}
""")

        # 4. Influence Branch (Data Exchange)
        influence = geo.createNode("sphere", "hot_spot")
        influence.parm("tx").set(10)
        influence.parm("ty").set(10)
        influence.parm("tz").set(10)
        influence.parm("radx").set(15)

        inf_tag = geo.createNode("attribwrangle", "tag_influence")
        inf_tag.setInput(0, influence)
        inf_tag.parm("snippet").set("f@intensity = 1.0;")

        # Transfer to buildings
        inf_transfer = geo.createNode("attribtransfer", "apply_influence")
        inf_transfer.setInput(0, building_logic)
        inf_transfer.setInput(1, inf_tag)
        inf_transfer.parm("pointattriblist").set("intensity")
        inf_transfer.parm("thresholddist").set(15.0)

        inf_color = geo.createNode("attribwrangle", "influence_styling")
        inf_color.setInput(0, inf_transfer)
        inf_color.parm("snippet").set("""
@Cd = set(0.2, 0.4, 0.8);
@Cd = lerp(@Cd, {0.9, 0.2, 0.1}, @intensity);
@scale = set(1, @height, 1);
""")

        # 5. Geometry
        building_geo = geo.createNode("box", "building_mesh")
        copy_buildings = geo.createNode("copytopoints", "place_buildings")
        copy_buildings.setInput(0, building_geo)
        copy_buildings.setInput(1, inf_color)

        # 6. Assembly
        merge = geo.createNode("merge", "CITY_MERGE")
        merge.setInput(0, normals)
        merge.setInput(1, copy_buildings)

        road_sweep = geo.createNode("sweep", "road_surface")
        road_sweep.setInput(0, road_resample)
        road_sweep.parm("surfaceshape").set(3)  # Ribbon
        road_sweep.parm("width").set(1.5)

        lamp_mesh = geo.createNode("box", "lamp_mesh")
        lamp_mesh.parm("sizex").set(0.1)
        lamp_mesh.parm("sizey").set(3.0)
        lamp_mesh.parm("sizez").set(0.1)
        lamp_mesh.parm("ty").set(1.5)

        lamp_pts = geo.createNode("blast", "lamp_points")
        lamp_pts.setInput(0, road_math)
        lamp_pts.parm("group").set("@ptnum%15!=0")

        copy_lamps = geo.createNode("copytopoints", "place_lamps")
        copy_lamps.setInput(0, lamp_mesh)
        copy_lamps.setInput(1, lamp_pts)

        merge.setInput(2, road_sweep)
        merge.setInput(3, copy_lamps)

        merge.setDisplayFlag(True)
        geo.layoutChildren()

        # Validation
        merge.cook()
        print(f"Build successful. Points in merge: {len(merge.geometry().points())}")

        hou.hipFile.save("toy_city_on_hill.hip")
        print("SAVED: toy_city_on_hill.hip")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    build_city()
