#!/usr/bin/env python3

# MARK: Script Helpers

import os
import urllib.request

from pathlib import Path

LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/") 
LOCAL_DIR = os.getenv("LOCAL_DIR")

def get_script(script_path, namespace={}):
    WORKSPACE_DIR = ""
    
    if LOCAL_MODE:
        script_file = os.path.join(LOCAL_DIR + WORKSPACE_DIR, script_path)

        print(f"Loading local script: {script_file}")

        with open(script_file, "rb") as f:
            source = f.read()

        filename = script_file
    else:
        script_url = BASE_URL + WORKSPACE_DIR + script_path

        print(f"Fetching script: {script_url}")

        source = urllib.request.urlopen(script_url).read()
        filename = script_url

    code = compile(source, filename, "exec")

    exec(code, namespace)

    return namespace

# MARK: Body

input_output_manager_script = get_script("tools/general/input_output_manager.py")
ini_file_script = get_script("tools/general/ini_file.py")

def fix(mod_path=".", is_dry_run=False):
    print("Fixing mod with experimental hash fixer...")

    files = input_output_manager_script["get_all_files_with_extension"](mod_path, "ini")
    ini_files = [ini_file_script["IniFile"](file) for file in files]

    replacing_hashes_path = "datas/replacing_hashes.json"

    replacing_hashes = input_output_manager_script["load_json_data"](replacing_hashes_path)

    modified_ini_files = []

    for ini_file in ini_files:
        is_modified = False

        for key, value in replacing_hashes.items():
            if ini_file.is_found(key):
                old_hash = key

                if is_dry_run:
                    print(f"{ini_file} -> will change hash {old_hash}")
                else:
                    new_hash = replacing_hashes[old_hash]

                    while replacing_hashes.get(new_hash, None) is not None:
                        new_hash = replacing_hashes[new_hash]

                    ini_file.replace(old_hash, new_hash)

                    is_modified = True
        
        if is_modified:
            modified_ini_files.append(ini_file)
    
    # Apply the change
    for ini_file in modified_ini_files:
        ini_file.write_file()