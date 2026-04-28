# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
import json
import logging
import os

logger = logging.getLogger("houdinimind.schema_extractor")
logger.setLevel(logging.INFO)

try:
    import hou
except ImportError:
    hou = None


def generate_full_houdini_schema(output_filepath: str) -> bool:
    """
    Extract active Houdini node types and their parameter names into JSON.
    Must run inside Houdini or hython.
    """
    if not hou:
        logger.error("generate_full_houdini_schema must be run within Houdini or hython.")
        return False

    schema = {}
    total_nodes = 0
    total_parms = 0

    try:
        for cat_name, category in hou.nodeTypeCategories().items():
            schema[cat_name] = {}
            for node_name, node_type in category.nodeTypes().items():
                if getattr(node_type, "isDeprecated", lambda: False)():
                    continue

                valid_parms = []
                try:
                    for pt in node_type.parmTemplates():
                        if isinstance(pt, hou.FolderParmTemplate):
                            valid_parms.extend(p.name() for p in pt.parmTemplates())
                        else:
                            valid_parms.append(pt.name())
                except Exception as exc:
                    logger.debug("Could not extract parms for %s: %s", node_name, exc)

                schema[cat_name][node_name] = {
                    "ui_name": node_type.description(),
                    "parameters": sorted(set(valid_parms)),
                }
                total_nodes += 1
                total_parms += len(valid_parms)

        output_dir = os.path.dirname(output_filepath)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_filepath, "w", encoding="utf-8") as handle:
            json.dump(schema, handle, indent=4)

        logger.info(
            "Exported %s nodes and %s parameters to %s",
            total_nodes,
            total_parms,
            output_filepath,
        )
        return True
    except Exception as exc:
        logger.error("Failed schema generation: %s", exc)
        return False


if __name__ == "__main__":
    if hou:
        target_file = os.path.join(os.path.expanduser("~"), "houdini_full_schema.json")
        generate_full_houdini_schema(target_file)
