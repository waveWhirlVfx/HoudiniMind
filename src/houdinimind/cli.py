"""HoudiniMind CLI — entry point for `houdinimind` command."""

from __future__ import annotations

import sys


def main() -> None:
    print("HoudiniMind — Agentic AI for SideFX Houdini")
    print()
    print("This tool runs inside Houdini as a Python Panel.")
    print("To install, run:  python install.py")
    print()
    print("For more information see README.md or https://github.com/anshulvashist/HoudiniMind")
    sys.exit(0)


if __name__ == "__main__":
    main()
