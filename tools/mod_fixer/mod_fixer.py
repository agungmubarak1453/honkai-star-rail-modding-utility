import urllib.request

BASE_URL = "https://raw.githubusercontent.com/agungmubarak1453/honkai-star-rail-modding-utility/main/tools/"

def get_script(script_path):
    script_url = BASE_URL + script_path

    print(f"Fetching script: {script_url}")

    source = urllib.request.urlopen(script_url).read()
    code = compile(source, script_url, "exec")

    namespace = {}
    exec(code, namespace)

    return namespace

def fix(mod_path=".", fix_code=None, is_dry_run=False):
    print("Fixing mod...")

    if fix_code is None:
        get_script("mod_fixer/hash_fixer.py")["fix"](mod_path, is_dry_run)
        get_script("mod_fixer/rabbitfx_fixer.py")["fix"](mod_path, is_dry_run)
    else:
        print(f"Fix Code: {fix_code}")