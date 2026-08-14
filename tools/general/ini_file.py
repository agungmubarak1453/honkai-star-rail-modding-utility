#!/usr/bin/env python3

# MARK: Script Helpers

import os
import urllib.request

from pathlib import Path

LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/") 
LOCAL_DIR = os.getenv("LOCAL_DIR")
WORKSPACE_DIR = "tools/general/"

def get_script(script_path, namespace={}):
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

import re

from dataclasses import dataclass, field
from typing import Optional

input_output_manager_script = get_script("input_output_manager.py")

# Regex patterns
RE_SECTION   = re.compile(r"^\[([^\]]+)\]$")
RE_COMMENT   = re.compile(r"^\s*;")

class IniFile:
    def __init__(self, path: str):
        self.path = path
        self.text_string = input_output_manager_script["load_text"](path)

    def is_found(self, searched_string):
        if searched_string in self.text_string:
            return True
        else:
            return False

    def replace(self, old_string, new_string):
        self.text_string = self.text_string.replace(old_string, new_string)

    def write_file(self, new_path=None):
        writing_path = self.path

        if new_path != None:
            writing_path = new_path

        input_output_manager_script["write_text"](writing_path, self.text_string)

    def __str__(self):
        return self.path