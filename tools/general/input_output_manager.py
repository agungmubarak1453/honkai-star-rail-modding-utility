import json
import urllib.request
import shutil

from pathlib import Path
from datetime import datetime

INACTIVE_STRING = "DISABLED"

def handle_backup(path):
    file = Path(path)

    # Create backup if the file already exists
    if file.exists():
        timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
        backup_path = file.with_name(
            f"{INACTIVE_STRING}_{file.stem}_BACKUP_{timestamp}{file.suffix}"
        )

    shutil.copy2(file, backup_path)

def load_json_data(path):
    data = None

    if path.startswith(("http://", "https://")):
        with urllib.request.urlopen(path) as response:
            data = json.load(response)
    else:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

    return data

def load_text(path):
    Path(path).read_text(encoding="utf-8")

def write_text(path, text_string):
    file = Path(path)

    handle_backup(file)

    # Write the new content
    file.write_text(text_string, encoding="utf-8")

def get_all_files_with_extension(searched_dir_path, extension, is_recursive=False) -> List[Path]:
    files = []

    extension_pattern = "*." + extension 

    if is_recursive:
        files = Path(searched_dir_path).rglob(extension_pattern)
    else:
        files = Path(searched_dir_path).glob(extension_pattern)

    filtered_files = []

    for file in files:
        if INACTIVE_STRING not in file.name:
            filtered_files.append(file)

    return filtered_files