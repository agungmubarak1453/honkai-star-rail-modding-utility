#!/usr/bin/env python3

# MARK: Script Helpers

import os
import urllib.request

from pathlib import Path

LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/") 
LOCAL_DIR = os.getenv("LOCAL_DIR")

def get_script(script_path, namespace={}):
    workspace_dir = ""
    
    if LOCAL_MODE:
        script_file = os.path.join(LOCAL_DIR + workspace_dir, script_path)

        print(f"Loading local script: {script_file}")

        with open(script_file, "rb") as f:
            source = f.read()

        filename = script_file
    else:
        script_url = BASE_URL + workspace_dir + script_path

        print(f"Fetching script: {script_url}")

        source = urllib.request.urlopen(script_url).read()
        filename = script_url

    code = compile(source, filename, "exec")

    exec(code, namespace)

    return namespace

# MARK: Body

import argparse

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "mod_path",
        nargs="?",
        default=".",
        help="Path to the mod folder (default: current directory)",
    )

    parser.add_argument(
        "--fix-code",
        default=None,
        help="Fix code",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without making changes",
    )

    args = parser.parse_args()

    mod_fixer = get_script("tools/mod_fixer/mod_fixer.py")

    mod_fixer["fix"](args.mod_path, args.fix_code, args.dry_run)

if __name__ == "__main__":
    main()