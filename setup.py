#!/usr/bin/env python3
"""
graph-wiki setup — configure a source checkout from the cloned repo.

Usage: python3 setup.py [--knowledge-pack NAME]

This installer is a thin shim over the packaged CLI. It runs
``graph-wiki setup --agent all`` from this checkout, so source and pip/uv
installs share one implementation. Skills are installed project-locally only;
nothing is written into global agent directories.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def run_owiki(*args):
    """Run graph-wiki CLI from this checkout via PYTHONPATH."""
    if shutil.which("python3"):
        result = subprocess.run(
            [sys.executable, "-m", "graph_wiki.cli", *args],
            cwd=str(SCRIPT_DIR),
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        return result.returncode == 0
    elif shutil.which("graph-wiki"):
        result = subprocess.run(["graph-wiki", *args])
        return result.returncode == 0
    else:
        print(
            "⚠️  Skipping setup — neither 'python3' nor 'graph-wiki' found on PATH.",
            file=sys.stderr,
        )
        return False


def prompt_vault_path():
    """Ask for the vault path; an empty answer means project-local skills only."""
    print()
    try:
        return input(
            "  Where is your Obsidian vault? (absolute path, Enter to skip): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def main():
    parser = argparse.ArgumentParser(description="graph-wiki setup")
    parser.add_argument("--knowledge-pack", metavar="NAME", help="use a Knowledge Pack")
    parser.add_argument(
        "--list-knowledge-packs",
        action="store_true",
        help="list available Knowledge Packs and exit",
    )
    args = parser.parse_args()

    if args.list_knowledge_packs:
        return 0 if run_owiki("setup", "--list-knowledge-packs") else 1

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║         graph-wiki — Agent Setup              ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    vault_path = prompt_vault_path()

    if vault_path:
        argv = ["setup", "--vault", vault_path, "--agent", "all"]
        if args.knowledge_pack:
            argv += ["--knowledge-pack", args.knowledge_pack]
    elif args.knowledge_pack:
        argv = ["setup", "--knowledge-pack", args.knowledge_pack, "--agent", "all"]
    else:
        # No vault: install the project-local mirrors without touching config.
        argv = ["setup", "--skills-only", "--agent", "all"]

    return 0 if run_owiki(*argv) else 1


if __name__ == "__main__":
    sys.exit(main())
