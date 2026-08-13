import json
import urllib.request

def load_json_data(path):
    data = None

    if path.startswith(("http://", "https://")):
        with urllib.request.urlopen(path) as response:
            data = json.load(response)
    else:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

    return data