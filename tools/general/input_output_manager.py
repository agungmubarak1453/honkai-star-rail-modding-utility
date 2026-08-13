import json
import urllib.request

def load_json_data(url):
    with urllib.request.urlopen(url) as response:
        data = json.load(response)

    return data