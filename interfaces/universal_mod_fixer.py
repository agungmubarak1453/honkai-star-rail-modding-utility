#!/usr/bin/env python3

import argparse
import urllib.request

BASE_URL = "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/"

def get_script(script_path):
    script_url = BASE_URL + script_path

    print(f"Fetching script: {script_url}")

    source = urllib.request.urlopen(script_url).read()
    code = compile(source, script_url, "exec")

    namespace = {}
    exec(code, namespace)

    return namespace

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