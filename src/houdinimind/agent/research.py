# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
﻿import time
import json
import os
import traceback
from typing import List, Dict, Any

try:
    import hou
    HOU_AVAILABLE = True
except ImportError:
    HOU_AVAILABLE = False

class ResearchManager:
    """
    Manages autonomous Houdini experiments.
    Inspired by Karpathy's autoresearch.
    """
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.experiments_file = os.path.join(data_dir, "experiments.tsv")
        self._init_log()

    def _init_db(self):
        if not os.path.exists(self.experiments_file):
            with open(self.experiments_file, "w", encoding="utf-8") as f:
                f.write("ts\tnode\tmetric\tvalue\tstatus\tdescription\n")

    def _init_log(self):
        self._init_db()

    def log_result(self, node: str, metric: str, value: float, status: str, desc: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.experiments_file, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{node}\t{metric}\t{value}\t{status}\t{desc}\n")

    def run_single_experiment(self, node_path: str, parms: Dict[str, Any], metric_type: str = "cook_time") -> Dict:
        """
        1. Backup parms
        2. Set new parms
        3. Cook & measure
        4. Return comparison
        """
        if not HOU_AVAILABLE: return {"status": "error", "message": "No Houdini"}
        node = hou.node(node_path)
        if not node: return {"status": "error", "message": "Node not found"}

        # Backup
        backups = {}
        for p_name in parms:
            p = node.parm(p_name)
            if p: backups[p_name] = p.eval()

        try:
            # Set
            for p_name, val in parms.items():
                node.parm(p_name).set(val)

            # Measure
            t0 = time.time()
            node.cook(force=True)
            t1 = time.time()
            val = t1 - t0 if metric_type == "cook_time" else 0.0
            
            return {
                "status": "ok",
                "value": val,
                "backups": backups
            }
        except Exception as e:
            # Revert on crash
            for p_name, old_val in backups.items():
                node.parm(p_name).set(old_val)
            return {"status": "error", "message": str(e)}

    def get_history(self, limit: int = 20) -> List[Dict]:
        if not os.path.exists(self.experiments_file): return []
        results = []
        with open(self.experiments_file, "r", encoding="utf-8") as f:
            lines = f.readlines()[1:] # skip header
            for line in lines[-limit:]:
                parts = line.strip().split("\t")
                if len(parts) >= 6:
                    results.append({
                        "ts": parts[0], "node": parts[1], "metric": parts[2],
                        "value": parts[3], "status": parts[4], "desc": parts[5]
                    })
        return results
