#!/usr/bin/env python3

# MARK: Script Helpers

import os
import urllib.request

from pathlib import Path

LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/") 
LOCAL_DIR = os.getenv("LOCAL_DIR")

def get_script(script_path, namespace={}):
    workspace_dir = "tools/mod_fixer/"
    
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

def fix(mod_path=".", fix_code=None, is_dry_run=False):
    print("Fixing mod...")

    if fix_code is None:
        get_script("hash_fixer.py")["fix"](mod_path, is_dry_run)
        get_script("rabbitfx_fixer.py")["fix"](mod_path, is_dry_run)
    else:
        print(f"Fix Code: {fix_code}")

        match fix_code:
            case "experimental":
                get_script("hash_fixer.py")["fix"](mod_path, is_dry_run)
                get_script("rabbitfx_fixer.py")["fix"](mod_path, is_dry_run)
                get_script("experimental_hash_fixer.py")["fix"](mod_path, is_dry_run)