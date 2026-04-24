# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import numpy as np
import math
import os
import tempfile
import hou

def find_displayed_geometry():
    """Find all displayed geometry nodes in the scene."""
    displayed_geo = []
    
    # Iterate through all objects in /obj
    for node in hou.node("/obj").children():
        # Check if the node is a geometry node and is displayed
        if node.type().name() in ["geo", "subnet"] and node.isDisplayFlagSet():
            displayed_geo.append(node)
            
        # Also check for geometry nodes inside subnets
        if node.type().name() == "subnet" or node.type().name() == "gltf_hierarchy":
            for child in node.allSubChildren():
                if child.type().category().name() == "Sop" and child.isDisplayFlagSet():
                    # Get the parent OBJ node
                    obj_parent = child.parent()
                    while obj_parent and obj_parent.type().category().name() != "Object":
                        obj_parent = obj_parent.parent()
                    
                    if obj_parent and obj_parent not in displayed_geo:
                        displayed_geo.append(obj_parent)
    
    return displayed_geo

def calculate_bounding_box(nodes):
    """Calculate the collective bounding box of all given nodes."""
    if not nodes:
        return None
    
    # Initialize with extreme values
    min_bounds = np.array([float('inf'), float('inf'), float('inf')])
    max_bounds = np.array([float('-inf'), float('-inf'), float('-inf')])
    
    for node in nodes:
        try:
            # Get the geometry
            display_node = node.displayNode()
            if display_node is None:
                continue
                
            geo = display_node.geometry()
            if geo is None:
                continue
            
            # Get the bounding box
            bbox = geo.boundingBox()
            if bbox is None:
                continue
            
            # Get node's transform
            transform = node.worldTransform()
            
            # Transform the bounding box corners
            for x in [bbox.minvec()[0], bbox.maxvec()[0]]:
                for y in [bbox.minvec()[1], bbox.maxvec()[1]]:
                    for z in [bbox.minvec()[2], bbox.maxvec()[2]]:
                        point = hou.Vector4(x, y, z, 1.0)
                        transformed_point = point * transform
                        
                        # Update min and max bounds
                        min_bounds[0] = min(min_bounds[0], transformed_point[0])
                        min_bounds[1] = min(min_bounds[1], transformed_point[1])
                        min_bounds[2] = min(min_bounds[2], transformed_point[2])
                        
                        max_bounds[0] = max(max_bounds[0], transformed_point[0])
                        max_bounds[1] = max(max_bounds[1], transformed_point[1])
                        max_bounds[2] = max(max_bounds[2], transformed_point[2])
        except Exception as e:
            print(f"Error processing node {node.name()}: {e}")
            continue
    
    if np.isinf(min_bounds).any() or np.isinf(max_bounds).any():
        return None
    
    center = [(min_bounds[0] + max_bounds[0]) / 2,
              (min_bounds[1] + max_bounds[1]) / 2,
              (min_bounds[2] + max_bounds[2]) / 2]
    
    return {
        'min': min_bounds.tolist(),
        'max': max_bounds.tolist(),
        'center': center
    }

def setup_camera_rig(bbox_center, orthographic=False):
    """
    Set up a null and camera rig at the given position.
    """
    null_name = "MCP_CAM_CENTER"
    cam_name = "MCP_CAMERA"
    
    existing_null = hou.node("/obj/" + null_name)
    if existing_null:
        existing_null.destroy()
        
    existing_camera = hou.node("/obj/" + cam_name)
    if existing_camera:
        existing_camera.destroy()
    
    null = hou.node("/obj").createNode("null", null_name)
    null.setPosition(hou.Vector2(0, 0))
    null.parmTuple("t").set(bbox_center)
    
    camera = hou.node("/obj").createNode("cam", cam_name)
    camera.setPosition(hou.Vector2(3, 0))
    camera.parmTuple("t").set([0, 0, 5])
    camera.parm("resx").set(512)
    camera.parm("resy").set(512)
    camera.parm("aspect").set(1.0)
    
    if orthographic:
        camera.parm("projection").set(1)  # 1 = Orthographic
    else:
        camera.parm("projection").set(0)  # 0 = Perspective
    
    camera.setFirstInput(null)
    return null

def rotate_camera_center(null_node, rotation=(0, 90, 0)):
    """Rotate the camera center null node."""
    if not null_node:
        return
        
    try:
        current_rotation = null_node.parmTuple("r").eval()
        new_rotation = [
            current_rotation[0] + rotation[0],
            current_rotation[1] + rotation[1],
            current_rotation[2] + rotation[2]
        ]
        null_node.parmTuple("r").set(new_rotation)
    except Exception as e:
        print(f"Error rotating camera center: {e}")

def adjust_camera_to_fit_bbox(camera, bbox, padding_factor=1.1):
    """Adjust camera to fit bounding box."""
    if not camera or not bbox:
        return
    
    try:
        is_ortho = camera.parm("projection").eval() == 1
        bbox_width = bbox['max'][0] - bbox['min'][0]
        bbox_height = bbox['max'][1] - bbox['min'][1]
        bbox_depth = bbox['max'][2] - bbox['min'][2]
        
        bbox_diagonal = math.sqrt(bbox_width**2 + bbox_height**2 + bbox_depth**2)
        bbox_view_diagonal = math.sqrt(bbox_width**2 + bbox_height**2)
        
        null_node = hou.node("/obj/MCP_CAM_CENTER")
        
        if null_node:
            null_r = hou.Vector3(null_node.parmTuple("r").eval())
            has_significant_rotation = any(abs(r % 360) > 5 for r in null_r)
            
            if has_significant_rotation:
                controlling_dimension = bbox_view_diagonal * 1.2
                depth_for_clipping = bbox_diagonal / 2
            else:
                controlling_dimension = max(bbox_width, bbox_height)
                depth_for_clipping = bbox_depth
            
            fov_parm = camera.parm("aperture")
            if not fov_parm:
                resx = camera.parm("resx").eval()
                resy = camera.parm("resy").eval()
                aspect_ratio = float(resx) / float(resy)
                fov = 36.0
            else:
                fov = fov_parm.eval()
                aspect_ratio = camera.parm("aspect").eval()
            
            focal_parm = camera.parm("focal")
            focal_length = focal_parm.eval() if focal_parm else 30.0
            horizontal_fov = 2 * math.atan((fov/2) / focal_length)
            vertical_fov = 2 * math.atan(math.tan(horizontal_fov/2) / aspect_ratio)
            min_fov = min(horizontal_fov, vertical_fov)
            
            required_distance = (controlling_dimension * padding_factor / 2) / math.tan(min_fov / 2)
            required_distance += depth_for_clipping
            required_distance = max(5.0, required_distance)
            
            camera.parmTuple("t").set([0, 0, required_distance])
            
            if is_ortho:
                camera.parm("orthowidth").set(controlling_dimension * padding_factor)
        else:
            controlling_dimension = bbox_view_diagonal
            fov_parm = camera.parm("aperture")
            if not fov_parm:
                resx = camera.parm("resx").eval()
                resy = camera.parm("resy").eval()
                aspect_ratio = float(resx) / float(resy)
                fov = 36.0
            else:
                fov = fov_parm.eval()
                aspect_ratio = camera.parm("aspect").eval()
            
            focal_parm = camera.parm("focal")
            focal_length = focal_parm.eval() if focal_parm else 50.0
            horizontal_fov = 2 * math.atan((fov/2) / focal_length)
            vertical_fov = 2 * math.atan(math.tan(horizontal_fov/2) / aspect_ratio)
            min_fov = min(horizontal_fov, vertical_fov)
            
            required_distance = (controlling_dimension * padding_factor / 2) / math.tan(min_fov / 2)
            required_distance += bbox_depth
            required_distance = max(5.0, required_distance)
            camera.parmTuple("t").set([0, 0, required_distance])
            
            if is_ortho:
                camera.parm("orthowidth").set(controlling_dimension * padding_factor)
            
    except Exception as e:
        print(f"Error adjusting camera: {e}")

def setup_render_node(render_engine="opengl", karma_engine="cpu", render_path=None, camera_path="/obj/MCP_CAMERA", view_name=None, rotation=None, is_ortho=False):
    """Create a render node."""
    try:
        if not render_path:
            render_path = os.path.join(tempfile.gettempdir(), "houdini_renders")
        
        if not os.path.exists(render_path):
            os.makedirs(render_path)
        
        if render_engine.lower() == "karma":
            render_node_name = f"MCP_{karma_engine.upper()}_KARMA"
            node_type = "karma"
        elif render_engine.lower() == "mantra":
            render_node_name = "MCP_MANTRA"
            node_type = "ifd"
        else:
            render_node_name = "MCP_OGL_RENDER"
            node_type = "opengl"
        
        proj_type = "ortho" if is_ortho else "persp"
        if view_name:
            filename = f"{render_node_name}_{view_name}_{proj_type}.jpg"
        elif rotation:
            rot_str = f"rot_{int(rotation[0])}_{int(rotation[1])}_{int(rotation[2])}"
            filename = f"{render_node_name}_{proj_type}_{rot_str}.jpg"
        else:
            filename = f"{render_node_name}_{proj_type}.jpg"
            
        filepath = os.path.join(render_path, filename).replace("\\", "/")
        
        render_node = hou.node("/out/" + render_node_name)
        if render_node:
            render_node.destroy()
        
        render_node = hou.node("/out").createNode(node_type, render_node_name)
        if not render_node:
            return None, None
        
        camera = hou.node(camera_path)
        if not camera:
            return render_node, filepath
            
        resx = camera.parm("resx").eval()
        resy = camera.parm("resy").eval()
            
        if render_engine.lower() == "opengl":
            if render_node.parm("camera"): render_node.parm("camera").set(camera_path)
            if render_node.parm("tres"):
                render_node.parm("tres").set(True)
                render_node.parm("res1").set(resx)
                render_node.parm("res2").set(resy)
            if render_node.parm("picture"): render_node.parm("picture").set(filepath)
            
        elif render_engine.lower() == "karma":
            if render_node.parm("camera"): render_node.parm("camera").set(camera_path)
            if render_node.parm("engine"):
                render_node.parm("engine").set("xpu" if karma_engine.lower() == "gpu" else "cpu")
            if render_node.parm("resolution1"):
                render_node.parm("resolution1").set(resx)
                render_node.parm("resolution2").set(resy)
            if render_node.parm("picture"): render_node.parm("picture").set(filepath)
            
        elif render_engine.lower() == "mantra":
            if render_node.parm("camera"): render_node.parm("camera").set(camera_path)
            if render_node.parm("override_camerares"):
                render_node.parm("override_camerares").set(True)
                render_node.parm("res_fraction").set("specific")
                if render_node.parm("res_overridex"):
                    render_node.parm("res_overridex").set(resx)
                    render_node.parm("res_overridey").set(resy)
            if render_node.parm("vm_picture"): render_node.parm("vm_picture").set(filepath)
        
        if render_node.parm("trange"):
            render_node.parm("trange").set(0)
        
        return render_node, filepath
    except Exception as e:
        print(f"Error setting up render node: {e}")
        return None, None

def render_single_view(orthographic=False, rotation=(0, 90, 0), render_path=None, render_engine="opengl", karma_engine="cpu"):
    """Render a single view."""
    displayed_geo = find_displayed_geometry()
    if not displayed_geo: return None
    
    bbox = calculate_bounding_box(displayed_geo)
    if not bbox: return None
    
    null = setup_camera_rig(bbox['center'], orthographic)
    rotate_camera_center(null, rotation)
    
    camera = hou.node("/obj/MCP_CAMERA")
    if camera:
        adjust_camera_to_fit_bbox(camera, bbox)
    else:
        return None
    
    render_node, filepath = setup_render_node(
        render_engine=render_engine,
        karma_engine=karma_engine,
        render_path=render_path,
        camera_path="/obj/MCP_CAMERA",
        rotation=rotation,
        is_ortho=orthographic
    )
    
    if not render_node: return None
    render_node.render()
    return filepath

def render_quad_view(orthographic=True, render_path=None, render_engine="opengl", karma_engine="cpu"):
    """Render four views."""
    rendered_files = []
    views = [
        {"name": "Front", "rotation": (0, 0, 0), "ortho": orthographic},
        {"name": "Left", "rotation": (0, -90, 0), "ortho": orthographic},
        {"name": "Top", "rotation": (-90, 0, 0), "ortho": orthographic},
        {"name": "Perspective", "rotation": (-45, -45, 0), "ortho": orthographic}
    ]
    
    displayed_geo = find_displayed_geometry()
    if not displayed_geo: return rendered_files
    
    bbox = calculate_bounding_box(displayed_geo)
    if not bbox: return rendered_files
    
    for view in views:
        null = setup_camera_rig(bbox['center'], view['ortho'])
        rotate_camera_center(null, view['rotation'])
        camera = hou.node("/obj/MCP_CAMERA")
        if camera:
            adjust_camera_to_fit_bbox(camera, bbox)
        else:
            continue
        
        view_name = view['name'].lower()
        render_node, filepath = setup_render_node(
            render_engine=render_engine,
            karma_engine=karma_engine,
            render_path=render_path,
            camera_path="/obj/MCP_CAMERA",
            view_name=view_name,
            is_ortho=view['ortho']
        )
        
        if render_node:
            render_node.render()
            if filepath: rendered_files.append(filepath)
    
    return rendered_files

def render_specific_camera(camera_path, render_path=None, render_engine="opengl", karma_engine="cpu"):
    """Render using a specific camera."""
    try:
        camera = hou.node(camera_path)
        if not camera or camera.type().name() != "cam":
            return None
            
        is_ortho = camera.parm("projection").eval() == 1
        view_name = camera.name()
        
        render_node, filepath = setup_render_node(
            render_engine=render_engine,
            karma_engine=karma_engine,
            render_path=render_path,
            camera_path=camera_path,
            view_name=view_name,
            is_ortho=is_ortho
        )
        
        if not render_node: return None
        render_node.render()
        return filepath
    except Exception as e:
        print(f"Error rendering specific camera: {e}")
        return None
