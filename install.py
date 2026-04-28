# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Install Script
Run this once from a terminal (not inside Houdini):

    python install.py

It will:
  1. Detect your Houdini 21 installation
  2. Write a Houdini package file so HoudiniMind loads automatically
  3. Create the data/db directory
  4. Build the retrievable knowledge base JSON
  5. Print next steps
"""

import glob
import json
import os
import platform
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ══════════════════════════════════════════════════════════════════════
#  Detect Houdini (cross-platform)
# ══════════════════════════════════════════════════════════════════════


def find_houdini_user_dir() -> str:
    """Find the Houdini user preferences directory on any OS."""
    system = platform.system()
    home = os.path.expanduser("~")
    candidates = []

    if system == "Darwin":
        # macOS: ~/Library/Preferences/houdini*
        prefs = os.path.join(home, "Library", "Preferences")
        if os.path.exists(prefs):
            for name in os.listdir(prefs):
                if name.lower().startswith("houdini") and os.path.isdir(os.path.join(prefs, name)):
                    candidates.append(os.path.join(prefs, name))
        fallback = os.path.join(prefs, "houdini21.0")
    elif system == "Linux":
        # Linux: ~/houdini*
        for name in os.listdir(home):
            if name.lower().startswith("houdini") and os.path.isdir(os.path.join(home, name)):
                candidates.append(os.path.join(home, name))
        fallback = os.path.join(home, "houdini21.0")
    else:
        # Windows: ~/Documents/houdini*
        docs = os.path.join(home, "Documents")
        if os.path.exists(docs):
            for name in os.listdir(docs):
                if name.lower().startswith("houdini") and os.path.isdir(os.path.join(docs, name)):
                    candidates.append(os.path.join(docs, name))
        fallback = os.path.join(docs, "houdini21.0")

    # Prefer 21.x
    for c in sorted(candidates, reverse=True):
        if "21" in c:
            return c
    return candidates[0] if candidates else fallback


def find_houdini_install() -> str:
    """Find Houdini program directory (cross-platform)."""
    system = platform.system()

    if system == "Windows":
        # Try Windows registry first
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Side Effects Software\Houdini"
            )
            path, _ = winreg.QueryValueEx(key, "InstallDir")
            return path
        except Exception:
            pass
        # Fall back to common Windows paths
        for drive in ["C:", "D:"]:
            for base in [
                r"\Program Files\Side Effects Software",
                r"\Program Files (x86)\Side Effects Software",
            ]:
                p = drive + base
                if os.path.exists(p):
                    entries = sorted(os.listdir(p), reverse=True)
                    for e in entries:
                        if e.startswith("Houdini") and "21" in e:
                            return os.path.join(p, e)
        return r"C:\Program Files\Side Effects Software\Houdini 21.0"

    elif system == "Darwin":
        # macOS: /Applications/Houdini/Houdini*/Frameworks
        app_base = "/Applications/Houdini"
        if os.path.exists(app_base):
            entries = sorted(os.listdir(app_base), reverse=True)
            for e in entries:
                fw = os.path.join(app_base, e, "Frameworks")
                if e.startswith("Houdini") and "21" in e and os.path.isdir(fw):
                    return os.path.join(app_base, e)
            for e in entries:
                if e.startswith("Houdini") and os.path.isdir(os.path.join(app_base, e)):
                    return os.path.join(app_base, e)
        # Also check ~/Library/Preferences/houdini*
        prefs = os.path.join(os.path.expanduser("~"), "Library", "Preferences")
        matches = sorted(glob.glob(os.path.join(prefs, "houdini*")), reverse=True)
        for m in matches:
            if "21" in m and os.path.isdir(m):
                return m
        return os.path.join(app_base, "Houdini 21.0")

    else:
        # Linux: /opt/hfs*
        opt_matches = sorted(glob.glob("/opt/hfs*"), reverse=True)
        for m in opt_matches:
            if "21" in m and os.path.isdir(m):
                return m
        if opt_matches:
            return opt_matches[0]
        # Check ~/houdini*
        home_matches = sorted(
            glob.glob(os.path.join(os.path.expanduser("~"), "houdini*")), reverse=True
        )
        for m in home_matches:
            if "21" in m and os.path.isdir(m):
                return m
        return "/opt/hfs21.0"


# ══════════════════════════════════════════════════════════════════════
#  Write Houdini package file
# ══════════════════════════════════════════════════════════════════════


def write_package(houdini_user_dir: str):
    """
    Write a .json package file so Houdini picks up HoudiniMind on startup.
    """
    packages_dir = os.path.join(houdini_user_dir, "packages")
    os.makedirs(packages_dir, exist_ok=True)

    package = {
        "env": [
            {"HOUDINIMIND_ROOT": SCRIPT_DIR},
            {"PYTHONPATH": {"value": SCRIPT_DIR, "method": "prepend"}},
        ],
        "path": SCRIPT_DIR,
    }

    pkg_path = os.path.join(packages_dir, "houdinimind.json")
    with open(pkg_path, "w") as f:
        json.dump(package, f, indent=2)
    return pkg_path


# ══════════════════════════════════════════════════════════════════════
#  Update config
# ══════════════════════════════════════════════════════════════════════


def update_config(data_dir: str):
    # deprecated — data_dir is now determined at runtime relative to the package
    pass


def build_knowledge_base(data_dir: str):
    kb_path = os.path.join(data_dir, "knowledge", "knowledge_base.json")
    try:
        from houdinimind.rag.kb_builder import build_kb

        build_kb(output_path=kb_path, verbose=False)
        return kb_path, None
    except Exception as e:
        return kb_path, str(e)


# ══════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════


def _install_pip_packages():
    """Install optional but recommended Python packages."""
    try:
        import subprocess

        pkgs = ["tiktoken", "httpx", "faster-whisper", "sounddevice"]
        for pkg in pkgs:
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--quiet", pkg],
                    capture_output=True,
                    timeout=60,
                )
                print(f"  ✓ {pkg} installed")
            except Exception:
                print(f"  ⚠ {pkg} not installed (optional — will use fallback)")
    except Exception:
        pass


def main():
    print("=" * 60)
    print("  Houdini Agent Installer")
    print("=" * 60)

    houdini_user_dir = find_houdini_user_dir()
    print(f"\n✓ Houdini user directory: {houdini_user_dir}")

    data_dir = os.path.join(SCRIPT_DIR, "data")
    db_dir = os.path.join(data_dir, "db")
    os.makedirs(db_dir, exist_ok=True)
    print(f"✓ Data directory ready: {data_dir}")

    print("\nInstalling optional Python packages (tiktoken, httpx)...")
    _install_pip_packages()

    pkg_path = write_package(houdini_user_dir)
    print(f"✓ Package file written: {pkg_path}")

    learned_path = os.path.join(data_dir, "system_prompt_learned.txt")
    if not os.path.exists(learned_path):
        with open(learned_path, "w") as f:
            f.write("# Learned knowledge\n(No patterns learned yet.)\n")
    print("✓ Learned prompt file initialised")

    kb_path, kb_error = build_knowledge_base(data_dir)
    if kb_error:
        print(f"⚠ Knowledge base build skipped: {kb_error}")
    else:
        print(f"✓ Knowledge base ready: {kb_path}")

    print("\n" + "=" * 60)
    print("  NEXT STEPS")
    print("=" * 60)
    print("""
 1. Make sure Ollama is installed and running:
    https://ollama.com/download
    Then in a terminal: ollama serve

 2. Pull the required models:
    ollama pull qwen3.5:397b-cloud   (main chat model)
    ollama pull nomic-embed-text     (required for knowledge search)

 3. Open Houdini 21 — HoudiniMind loads automatically via the
    package file written above.

 4. Add the panel in Houdini:
    - Click any pane's type icon (top-left corner of the pane)
    - Select "Python Panel"
    - In the Python Panel toolbar open the panel dropdown
    - Select "HoudiniMind" (it appears automatically)

 5. Wait for "Ready" in the status bar (~5-15 s on first launch),
    then select qwen3.5:397b-cloud from the model dropdown.

 6. Start chatting!

 Need help? See the Troubleshooting section in README.md
 """)


if __name__ == "__main__":
    main()
